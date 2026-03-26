from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bleak import BleakError, BleakScanner
from flask import Flask, Response, jsonify

APP_VERSION = "0.2.0"
DEFAULT_CONFIG_PATH = "config.json"
LOGGER = logging.getLogger("thexporter")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


@dataclass(slots=True, frozen=True)
class SensorConfig:
    address: str
    name: str
    decoder: str = "auto"


@dataclass(slots=True)
class Config:
    bind_host: str = "0.0.0.0"
    port: int = 8000
    sensors: dict[str, SensorConfig] = field(default_factory=dict)
    metric_ttl_seconds: int = 180
    scan_mode: str = "passive"
    log_level: str = "INFO"
    default_decoder: str = "auto"
    default_sensor_name: str = "ble_sensor"
    config_path: str = DEFAULT_CONFIG_PATH

    @classmethod
    def from_env(cls) -> "Config":
        file_config, config_path = _load_file_config()
        config = cls(
            bind_host=_env_or_config("THX_BIND_HOST", file_config, "bind_host", "0.0.0.0"),
            port=_env_or_config_int("THX_PORT", file_config, "port", 8000),
            metric_ttl_seconds=_env_or_config_int("THX_METRIC_TTL_SECONDS", file_config, "metric_ttl_seconds", 180),
            scan_mode=_env_or_config("THX_SCAN_MODE", file_config, "scan_mode", "passive").strip().lower(),
            log_level=_env_or_config("THX_LOG_LEVEL", file_config, "log_level", "INFO").strip().upper(),
            default_decoder=_env_or_config("THX_DECODER", file_config, "default_decoder", "auto").strip().lower(),
            default_sensor_name=_env_or_config("THX_SENSOR_NAME", file_config, "default_sensor_name", "ble_sensor"),
            config_path=config_path,
        )
        config.sensors = _load_sensor_configs(
            config.default_sensor_name,
            config.default_decoder,
            file_config.get("sensors"),
        )
        return config


@dataclass(slots=True)
class SensorReading:
    address: str
    name: str
    decoder: str
    temperature_celsius: float | None = None
    humidity_percent: float | None = None
    battery_percent: float | None = None
    battery_voltage_volts: float | None = None
    rssi: int | None = None
    packet_counter: int | None = None
    last_seen_timestamp: float = field(default_factory=time.time)

    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.last_seen_timestamp)


class SensorCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._readings: dict[str, SensorReading] = {}

    def update(self, reading: SensorReading) -> None:
        with self._lock:
            self._readings[reading.address] = reading

    def snapshot(self) -> dict[str, SensorReading]:
        with self._lock:
            return dict(self._readings)


class BleTemperatureScanner:
    def __init__(self, config: Config, cache: SensorCache) -> None:
        self._config = config
        self._cache = cache
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="ble-scanner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._scan_forever())
        finally:
            self._loop.close()

    async def _scan_forever(self) -> None:
        while not self._stop_event.is_set():
            scanner: BleakScanner | None = None
            try:
                scanner = BleakScanner(
                    detection_callback=self._detection_callback,
                    scanning_mode=self._config.scan_mode,
                )
                LOGGER.info("Starting BLE scan with mode=%s", self._config.scan_mode)
                await scanner.start()
                while not self._stop_event.is_set():
                    await asyncio.sleep(1)
            except BleakError as exc:
                LOGGER.warning("BLE scan failed: %s", exc)
                if self._config.scan_mode == "passive":
                    LOGGER.warning("Falling back from passive scan to active scan")
                    self._config.scan_mode = "active"
                await asyncio.sleep(5)
            except Exception:
                LOGGER.exception("Unexpected error in BLE scan loop")
                await asyncio.sleep(5)
            finally:
                if scanner is not None:
                    try:
                        await scanner.stop()
                    except Exception:
                        LOGGER.debug("Ignoring scanner stop failure", exc_info=True)

    def _detection_callback(self, device: Any, advertisement_data: Any) -> None:
        address = _normalize_mac(getattr(device, "address", None))
        if not address:
            return

        sensor = self._resolve_sensor(address)
        if sensor is None:
            return

        decoded = decode_advertisement(sensor.decoder, advertisement_data)
        if decoded is None:
            return

        reading = SensorReading(
            address=address,
            name=sensor.name,
            decoder=decoded["decoder"],
            temperature_celsius=decoded.get("temperature_celsius"),
            humidity_percent=decoded.get("humidity_percent"),
            battery_percent=decoded.get("battery_percent"),
            battery_voltage_volts=decoded.get("battery_voltage_volts"),
            packet_counter=decoded.get("packet_counter"),
            rssi=getattr(advertisement_data, "rssi", None),
            last_seen_timestamp=time.time(),
        )
        self._cache.update(reading)
        LOGGER.debug("Updated sensor reading: %s", reading)

    def _resolve_sensor(self, address: str) -> SensorConfig | None:
        if self._config.sensors:
            return self._config.sensors.get(address)

        return SensorConfig(
            address=address,
            name=f"{self._config.default_sensor_name}_{address.replace(':', '').lower()}",
            decoder=self._config.default_decoder,
        )


def _load_file_config() -> tuple[dict[str, Any], str]:
    config_path = os.getenv("THX_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    path = Path(config_path)
    if not path.exists():
        return {}, config_path

    with path.open(encoding="utf-8") as fp:
        raw_config = json.load(fp)
    if not isinstance(raw_config, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    return raw_config, config_path


def _env_or_config(name: str, file_config: dict[str, Any], config_key: str, default: str) -> str:
    value = os.getenv(name)
    if value is not None:
        return value

    config_value = file_config.get(config_key)
    if config_value is None:
        return default
    return str(config_value)


def _env_or_config_int(name: str, file_config: dict[str, Any], config_key: str, default: int) -> int:
    value = os.getenv(name)
    if value is not None:
        return int(value)

    config_value = file_config.get(config_key)
    if config_value is None:
        return default
    return int(config_value)


def _load_sensor_configs(
    default_name: str,
    default_decoder: str,
    file_sensors: Any = None,
) -> dict[str, SensorConfig]:
    sensors_json = os.getenv("THX_SENSORS")
    if sensors_json:
        return _parse_sensor_configs(json.loads(sensors_json), default_name, default_decoder, "THX_SENSORS")

    if file_sensors is not None:
        return _parse_sensor_configs(file_sensors, default_name, default_decoder, "config.json sensors")

    single_mac = _normalize_mac(os.getenv("THX_SENSOR_MAC"))
    if not single_mac:
        return {}

    sensor = SensorConfig(address=single_mac, name=default_name, decoder=default_decoder)
    return {single_mac: sensor}


def _parse_sensor_configs(
    raw_items: Any,
    default_name: str,
    default_decoder: str,
    source_name: str,
) -> dict[str, SensorConfig]:
    if not isinstance(raw_items, list):
        raise ValueError(f"{source_name} must be a JSON array")

    sensors: dict[str, SensorConfig] = {}
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Each {source_name} item must be a JSON object")
        address = _normalize_mac(item.get("mac") or item.get("address"))
        if not address:
            raise ValueError(f"{source_name} item #{index} is missing mac/address")
        name = str(item.get("name") or f"{default_name}_{index}")
        decoder = str(item.get("decoder") or default_decoder).strip().lower()
        sensors[address] = SensorConfig(address=address, name=name, decoder=decoder)
    return sensors


def decode_advertisement(decoder: str, advertisement_data: Any) -> dict[str, float | int | str] | None:
    if decoder in {"auto", "bthome"}:
        decoded = decode_bthome_v2(advertisement_data)
        if decoded is not None or decoder == "bthome":
            return decoded

    if decoder in {"auto", "pvvx_custom"}:
        decoded = decode_pvvx_custom(advertisement_data)
        if decoded is not None or decoder == "pvvx_custom":
            return decoded

    return None


def decode_bthome_v2(advertisement_data: Any) -> dict[str, float | int | str] | None:
    payload = _get_service_payload(advertisement_data, "fcd2")
    if not payload or len(payload) < 2:
        return None

    device_info = payload[0]
    encrypted = bool(device_info & 0x01)
    if encrypted:
        LOGGER.debug("Encrypted BTHome advertisement is not supported")
        return None

    cursor = 1
    result: dict[str, float | int | str] = {"decoder": "bthome"}

    while cursor < len(payload):
        object_id = payload[cursor]
        cursor += 1

        if object_id == 0x01 and cursor + 1 <= len(payload):
            result["battery_percent"] = float(payload[cursor])
            cursor += 1
        elif object_id == 0x02 and cursor + 2 <= len(payload):
            result["temperature_celsius"] = int.from_bytes(payload[cursor:cursor + 2], "little", signed=True) / 100.0
            cursor += 2
        elif object_id == 0x03 and cursor + 2 <= len(payload):
            result["humidity_percent"] = int.from_bytes(payload[cursor:cursor + 2], "little") / 100.0
            cursor += 2
        elif object_id == 0x2E and cursor + 1 <= len(payload):
            result["humidity_percent"] = float(payload[cursor])
            cursor += 1
        elif object_id == 0x0C and cursor + 2 <= len(payload):
            result["voltage_volts"] = int.from_bytes(payload[cursor:cursor + 2], "little") / 1000.0
            cursor += 2
        else:
            length = _bthome_length(object_id)
            if length is None or cursor + length > len(payload):
                LOGGER.debug("Stopping BTHome parse at unknown object_id=0x%02x", object_id)
                break
            cursor += length

    if "voltage_volts" in result and "battery_voltage_volts" not in result:
        result["battery_voltage_volts"] = float(result.pop("voltage_volts"))

    if not any(key in result for key in ("temperature_celsius", "humidity_percent", "battery_percent")):
        return None
    return result


def decode_pvvx_custom(advertisement_data: Any) -> dict[str, float | int | str] | None:
    payload = _get_service_payload(advertisement_data, "181a")
    if not payload or len(payload) < 15:
        return None

    return {
        "decoder": "pvvx_custom",
        "temperature_celsius": int.from_bytes(payload[6:8], "little", signed=True) / 100.0,
        "humidity_percent": int.from_bytes(payload[8:10], "little") / 100.0,
        "battery_voltage_volts": int.from_bytes(payload[10:12], "little") / 1000.0,
        "battery_percent": float(payload[12]),
        "packet_counter": int(payload[13]),
        "flags": int(payload[14]),
    }


def _bthome_length(object_id: int) -> int | None:
    lengths = {
        0x00: 1,
        0x01: 1,
        0x02: 2,
        0x03: 2,
        0x0C: 2,
        0x2E: 1,
    }
    return lengths.get(object_id)


def _get_service_payload(advertisement_data: Any, uuid_suffix: str) -> bytes | None:
    for key, value in getattr(advertisement_data, "service_data", {}).items():
        normalized_key = key.replace("-", "").lower()
        if normalized_key.endswith(uuid_suffix):
            return bytes(value)
    return None


def _normalize_mac(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().replace("-", ":").upper()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 6:
        return raw
    return ":".join(part.zfill(2) for part in parts)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_line(name: str, labels: dict[str, str], value: float | int) -> str:
    label_text = ",".join(f'{key}="{_escape_label(val)}"' for key, val in labels.items())
    return f"{name}{{{label_text}}} {value}"


def build_metrics(cache: SensorCache, config: Config) -> str:
    readings = cache.snapshot()
    lines = [
        "# HELP ble_temp_humidity_exporter_info Static information about this exporter.",
        "# TYPE ble_temp_humidity_exporter_info gauge",
        _metric_line(
            "ble_temp_humidity_exporter_info",
            {
                "version": APP_VERSION,
                "scan_mode": config.scan_mode,
                "config_path": config.config_path,
                "configured_sensor_count": str(len(config.sensors)),
            },
            1,
        ),
        "# HELP ble_temp_humidity_exporter_scrape_success 1 if the exporter has at least one reading to expose.",
        "# TYPE ble_temp_humidity_exporter_scrape_success gauge",
        f"ble_temp_humidity_exporter_scrape_success {1 if readings else 0}",
    ]

    sensors = config.sensors or {
        address: SensorConfig(address=reading.address, name=reading.name, decoder=reading.decoder)
        for address, reading in readings.items()
    }

    if not sensors and not readings:
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "# HELP ble_temp_humidity_configured_sensor_info Static information for each configured or discovered sensor.",
            "# TYPE ble_temp_humidity_configured_sensor_info gauge",
        ]
    )
    for sensor in sensors.values():
        lines.append(
            _metric_line(
                "ble_temp_humidity_configured_sensor_info",
                {"address": sensor.address, "sensor_name": sensor.name, "configured_decoder": sensor.decoder},
                1,
            )
        )

    for sensor in sensors.values():
        reading = readings.get(sensor.address)
        labels = {
            "address": sensor.address,
            "sensor_name": sensor.name,
            "decoder": reading.decoder if reading else sensor.decoder,
        }
        age_seconds = reading.age_seconds() if reading else float(config.metric_ttl_seconds + 1)
        sensor_up = 1 if reading and age_seconds <= config.metric_ttl_seconds else 0
        last_seen = reading.last_seen_timestamp if reading else 0

        lines.extend(
            [
                "# HELP ble_temp_humidity_sensor_up 1 if a fresh advertisement has been seen within THX_METRIC_TTL_SECONDS.",
                "# TYPE ble_temp_humidity_sensor_up gauge",
                _metric_line("ble_temp_humidity_sensor_up", labels, sensor_up),
                "# HELP ble_temp_humidity_last_seen_timestamp_seconds UNIX timestamp of the latest received advertisement.",
                "# TYPE ble_temp_humidity_last_seen_timestamp_seconds gauge",
                _metric_line("ble_temp_humidity_last_seen_timestamp_seconds", labels, last_seen),
                "# HELP ble_temp_humidity_advertisement_age_seconds Seconds since the latest received advertisement.",
                "# TYPE ble_temp_humidity_advertisement_age_seconds gauge",
                _metric_line("ble_temp_humidity_advertisement_age_seconds", labels, age_seconds),
            ]
        )

        if reading is None:
            continue

        optional_metrics: list[tuple[str, str, float | int | None]] = [
            (
                "ble_temp_humidity_temperature_celsius",
                "Latest temperature reported by the BLE thermometer in Celsius.",
                reading.temperature_celsius,
            ),
            (
                "ble_temp_humidity_relative_humidity_percent",
                "Latest relative humidity reported by the BLE thermometer in percent.",
                reading.humidity_percent,
            ),
            (
                "ble_temp_humidity_battery_percent",
                "Latest battery charge reported by the BLE thermometer in percent.",
                reading.battery_percent,
            ),
            (
                "ble_temp_humidity_battery_voltage_volts",
                "Latest battery voltage reported by the BLE thermometer in volts.",
                reading.battery_voltage_volts,
            ),
            (
                "ble_temp_humidity_rssi_dbm",
                "RSSI of the latest BLE advertisement in dBm.",
                reading.rssi,
            ),
            (
                "ble_temp_humidity_packet_counter",
                "Packet counter extracted from the BLE advertisement when available.",
                reading.packet_counter,
            ),
        ]

        for metric_name, help_text, value in optional_metrics:
            if value is None:
                continue
            lines.append(f"# HELP {metric_name} {help_text}")
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(_metric_line(metric_name, labels, value))

    return "\n".join(lines) + "\n"


def create_app(config: Config, cache: SensorCache) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> Response:
        return jsonify(
            {
                "name": "temp-humidity-exporter",
                "version": APP_VERSION,
                "metrics_path": "/metrics",
                "scan_mode": config.scan_mode,
                "config_path": config.config_path,
                "sensors": [
                    {"address": sensor.address, "name": sensor.name, "decoder": sensor.decoder}
                    for sensor in config.sensors.values()
                ],
                "sensor_count": len(config.sensors),
            }
        )

    @app.get("/healthz")
    def healthz() -> Response:
        readings = cache.snapshot()
        if config.sensors:
            healthy = all(
                (reading := readings.get(sensor.address)) is not None
                and reading.age_seconds() <= config.metric_ttl_seconds
                for sensor in config.sensors.values()
            )
        else:
            healthy = any(reading.age_seconds() <= config.metric_ttl_seconds for reading in readings.values())
        status = 200 if healthy else 503
        return jsonify({"ok": healthy, "reading_count": len(readings)}), status

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(build_metrics(cache, config), mimetype="text/plain; version=0.0.4; charset=utf-8")

    return app


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)

    cache = SensorCache()
    scanner = BleTemperatureScanner(config, cache)
    app = create_app(config, cache)

    def _shutdown(*_: Any) -> None:
        LOGGER.info("Stopping BLE scanner")
        scanner.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    scanner.start()
    LOGGER.info(
        "Starting exporter on %s:%s scan_mode=%s configured_sensors=%s",
        config.bind_host,
        config.port,
        config.scan_mode,
        len(config.sensors),
    )
    app.run(host=config.bind_host, port=config.port)


if __name__ == "__main__":
    main()

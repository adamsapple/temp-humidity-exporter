from __future__ import annotations

from .config import Config, SensorConfig
from .constants import APP_VERSION
from .models import SensorCache


def build_metrics(cache: SensorCache, config: Config) -> str:
    readings = cache.snapshot()
    lines = [
        "# HELP ble_temp_humidity_exporter_info Static information about this exporter.",
        "# TYPE ble_temp_humidity_exporter_info gauge",
        _metric_line(
            "ble_temp_humidity_exporter_info",
            {
                "version": APP_VERSION,
                "scanner_backend": config.scanner_backend,
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


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_line(name: str, labels: dict[str, str], value: float | int) -> str:
    label_text = ",".join(f'{key}="{_escape_label(val)}"' for key, val in labels.items())
    return f"{name}{{{label_text}}} {value}"

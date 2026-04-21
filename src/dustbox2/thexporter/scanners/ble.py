from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

from bleak import BleakError, BleakScanner

try:
    from bleak.backends.bluezdbus.advertisement_monitor import AdvertisementDataType, OrPattern
except ImportError:  # pragma: no cover - only available on Linux/BlueZ
    AdvertisementDataType = None
    OrPattern = None

from ..config import Config, SensorConfig, normalize_mac
from ..constants import LOGGER_NAME
from ..decoders import decode_advertisement
from ..models import SensorCache, SensorReading

LOGGER = logging.getLogger(LOGGER_NAME)


class BleTemperatureScanner:
    def __init__(self, config: Config, cache: SensorCache) -> None:
        self._config = config
        self._cache = cache
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dbus_unavailable_logged = False
        self._permission_denied_logged = False

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
                    bluez=_build_bluez_args(self._config),
                )
                LOGGER.info("Starting BLE scan with mode=%s", self._config.scan_mode)
                await scanner.start()
                self._dbus_unavailable_logged = False
                self._permission_denied_logged = False
                while not self._stop_event.is_set():
                    await asyncio.sleep(1)
            except BleakError as exc:
                permission_denied = _is_permission_denied_error(exc)
                if permission_denied:
                    self._log_permission_denied(exc)
                else:
                    LOGGER.warning("BLE scan failed: %s", exc)
                if self._config.scan_mode == "passive" and not permission_denied:
                    LOGGER.warning("Falling back from passive scan to active scan")
                    self._config.scan_mode = "active"
                await asyncio.sleep(5)
            except FileNotFoundError as exc:
                self._log_missing_system_bus(exc)
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
        address = normalize_mac(getattr(device, "address", None))
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

    def _log_missing_system_bus(self, exc: FileNotFoundError) -> None:
        if self._dbus_unavailable_logged:
            LOGGER.debug("System D-Bus socket is still unavailable: %s", exc)
            return

        bus_address = os.getenv("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=/run/dbus/system_bus_socket")
        missing_path = exc.filename or "/run/dbus/system_bus_socket"
        LOGGER.error(
            "System D-Bus is unavailable for BLE scanning (missing %s). "
            "Real BLE scanning requires host BlueZ and access to the system bus at %s. "
            "The HTTP endpoints will stay up, but BLE readings will not arrive until the environment is fixed. "
            "For dev-container verification, set THX_SCANNER_BACKEND=mock.",
            missing_path,
            bus_address,
        )
        self._dbus_unavailable_logged = True

    def _log_permission_denied(self, exc: BleakError) -> None:
        if self._permission_denied_logged:
            LOGGER.debug("BLE scan is still blocked by permissions: %s", exc)
            return

        LOGGER.error(
            "BLE scan permission denied: %s. "
            "The process can reach BlueZ but cannot enable LE discovery on the host adapter. "
            "If running in Docker, keep `network_mode: host`, mount `/run/dbus`, add `NET_ADMIN` and `NET_RAW`, "
            "and if the host still rejects discovery enable `privileged: true`. "
            "If running directly on Linux, run as root or grant `cap_net_raw,cap_net_admin` to the Python interpreter. "
            "The HTTP endpoints will stay up, but BLE readings will not arrive until permissions are fixed. "
            "For dev-container verification, set THX_SCANNER_BACKEND=mock.",
            exc,
        )
        self._permission_denied_logged = True


def _build_bluez_args(config: Config) -> dict[str, Any]:
    if config.scan_mode != "passive":
        return {}

    patterns = _build_passive_or_patterns(config)
    if not patterns:
        LOGGER.warning("No BlueZ passive scan patterns available; passive scan may fail")
        return {}

    return {"or_patterns": patterns}


def _build_passive_or_patterns(config: Config) -> list[Any]:
    if AdvertisementDataType is None or OrPattern is None:
        LOGGER.warning("BlueZ advertisement monitor helpers are unavailable in this Bleak build")
        return []

    requested_decoders = (
        {sensor.decoder for sensor in config.sensors.values()} if config.sensors else {config.default_decoder}
    )

    normalized_decoders: set[str] = set()
    for decoder in requested_decoders:
        if decoder == "auto":
            normalized_decoders.update({"bthome", "pvvx_custom"})
        elif decoder in {"bthome", "pvvx_custom"}:
            normalized_decoders.add(decoder)

    patterns: list[Any] = []

    if "bthome" in normalized_decoders:
        patterns.append(OrPattern(0, AdvertisementDataType.SERVICE_DATA_UUID16, bytes.fromhex("d2fc")))
    if "pvvx_custom" in normalized_decoders:
        patterns.append(OrPattern(0, AdvertisementDataType.SERVICE_DATA_UUID16, bytes.fromhex("1a18")))
    return patterns


def _is_permission_denied_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "permission denied",
            "operation not permitted",
            "not authorized",
            "access denied",
            "org.freedesktop.dbus.error.accessdenied",
        )
    )

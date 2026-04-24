from __future__ import annotations

from ..config import Config, SensorConfig
from ..constants import APP_VERSION
from ..scandata import ScanDataStore
from ..scanthread import ScanThread


def build_status_payload(config: Config, store: ScanDataStore, scanner: ScanThread) -> dict[str, object]:
    """Build the JSON payload returned by the root status endpoint."""
    readings = store.snapshot()
    discovered_devices = store.device_snapshot()
    status = store.status_snapshot()
    sensors = dict(config.sensors)
    if not sensors:
        sensors = {
            address: SensorConfig(
                address=reading.address,
                decoder=reading.decoder,
            )
            for address, reading in readings.items()
        }

    devices = []
    for address in sorted(set(sensors) | set(discovered_devices) | set(readings)):
        sensor = sensors.get(address)
        reading = readings.get(address)
        discovered = discovered_devices.get(address)
        resolved_name = _resolve_status_name(sensor, discovered, reading)
        last_reading = reading.to_dict() if reading else None
        if last_reading is not None and resolved_name:
            last_reading["name"] = resolved_name
        devices.append(
            {
                "address": address,
                "name": resolved_name,
                "configured_name": None if sensor is None else sensor.name,
                "device_name": None if discovered is None else discovered.device_name,
                "target_state": "unknown" if discovered is None else discovered.is_target,
                "address_type": None if discovered is None else discovered.address_type,
                "configured_decoder": None if sensor is None else sensor.decoder,
                "last_gatt_name_attempt_timestamp": None if discovered is None else discovered.last_gatt_name_attempt_timestamp,
                "last_gatt_name_error": None if discovered is None else discovered.last_gatt_name_error,
                "first_seen_timestamp": None if discovered is None else discovered.first_seen_timestamp,
                "last_seen_timestamp": None if discovered is None else discovered.last_seen_timestamp,
                "last_reading": last_reading,
                "healthy": bool(reading and reading.age_seconds() <= config.metric_ttl_seconds),
            }
        )

    return {
        "name": "thexporter",
        "version": APP_VERSION,
        "scanner_running": scanner.is_running() and status.running,
        "bind": {"host": config.bind_host, "port": config.port},
        "config_path": config.config_path,
        "scan_seconds": config.scan_seconds,
        "metric_ttl_seconds": config.metric_ttl_seconds,
        "last_error": status.last_error,
        "status": status.to_dict(),
        "device_count": len(devices),
        "devices": devices,
    }


def _resolve_status_name(
    sensor: SensorConfig | None,
    discovered: object,
    reading: object,
) -> str | None:
    """Resolve the best name to expose in the status response."""
    configured_name = None if sensor is None else sensor.name
    device_name = None if discovered is None else getattr(discovered, "device_name", None)
    reading_name = None if reading is None else getattr(reading, "name", None)
    return configured_name or device_name or reading_name

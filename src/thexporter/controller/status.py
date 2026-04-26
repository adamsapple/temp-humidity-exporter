from __future__ import annotations

from ..config import Config, SensorConfig
from ..constants import APP_VERSION
from ..scandata import ScanDataStore
from ..scanthread import ScanThread


def build_status_payload(config: Config, store: ScanDataStore, scanner: ScanThread) -> dict[str, object]:
    """Build the JSON payload returned by the root status endpoint."""
    readings = store.snapshot()
    status = store.status_snapshot()
    sensors = config.sensors or {
        address: SensorConfig(
            address=reading.address,
            decoder=reading.decoder,
        )
        for address, reading in readings.items()
    }

    devices = []
    for sensor in sensors.values():
        reading = readings.get(sensor.address)
        devices.append(
            {
                "address": sensor.address,
                "configured_decoder": sensor.decoder,
                "last_reading": reading.to_dict() if reading else None,
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

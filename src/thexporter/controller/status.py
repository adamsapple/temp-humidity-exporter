from __future__ import annotations

from ..config import Config
from ..constants import APP_VERSION
from ..device_registry import DeviceRegistry
from ..scandata import ScanDataStore
from ..scanthread import ScanThread


def build_status_payload(
    config: Config,
    store: ScanDataStore,
    scanner: ScanThread,
    registry: DeviceRegistry,
) -> dict[str, object]:
    """Build the JSON payload returned by the root status endpoint."""
    readings = store.snapshot()
    status = store.status_snapshot()
    devices_by_address = registry.snapshot_known_devices()
    monitored_devices = registry.snapshot_monitored_devices()
    expected_devices = registry.snapshot_expected_devices()

    devices = []
    for device in devices_by_address.values():
        reading = readings.get(device.address)
        devices.append(
            {
                "address": device.address,
                "name": device.name,
                "device_name": device.device_name,
                "name_alias": device.name_alias,
                "decoder": device.decoder,
                "configured_decoder": device.configured_decoder,
                "source": device.source,
                "target": device.target,
                "material": device.material,
                "color": device.color,
                "monitored": device.address in monitored_devices,
                "required_for_health": device.address in expected_devices,
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
        "discovered_devices_path": config.discovered_devices_path,
        "scan_seconds": config.scan_seconds,
        "metric_ttl_seconds": config.metric_ttl_seconds,
        "negative_cache_seconds": config.negative_cache_seconds,
        "last_error": status.last_error,
        "status": status.to_dict(),
        "device_count": len(devices),
        "monitored_device_count": len(monitored_devices),
        "required_device_count": len(expected_devices),
        "ignored_non_target_devices": list(registry.runtime_ignored_addresses()),
        "devices": devices,
    }

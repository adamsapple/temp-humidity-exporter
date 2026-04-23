from __future__ import annotations

from ..config import Config
from ..device_registry import DeviceRegistry
from ..scandata import ScanDataStore
from ..scanthread import ScanThread


def render_health(
    config: Config,
    store: ScanDataStore,
    scanner: ScanThread,
    registry: DeviceRegistry,
) -> tuple[str, int]:
    """Return a minimal health body and HTTP status for external monitoring."""
    readings = store.snapshot()
    status = store.status_snapshot()
    expected_devices = registry.snapshot_expected_devices()

    if expected_devices:
        # Configured devices and explicitly included discovered devices are strict health targets.
        healthy = all(
            (reading := readings.get(device.address)) is not None
            and reading.age_seconds() <= config.metric_ttl_seconds
            for device in expected_devices.values()
        )
    else:
        # Undefined discovered devices are collected, but they do not become mandatory for health.
        healthy = any(
            (reading := readings.get(device.address)) is not None
            and reading.age_seconds() <= config.metric_ttl_seconds
            for device in registry.snapshot_monitored_devices().values()
        )

    healthy = healthy and scanner.is_running() and status.last_error is None
    return ("200\n" if healthy else "503\n", 200 if healthy else 503)

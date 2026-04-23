from __future__ import annotations

from ..config import Config
from ..device_registry import DeviceRegistry
from ..metric_builder import build_metrics
from ..scandata import ScanDataStore


def render_metrics(config: Config, store: ScanDataStore, registry: DeviceRegistry) -> str:
    """Return the Prometheus text body for the /metrics endpoint."""
    return build_metrics(store, config, registry)

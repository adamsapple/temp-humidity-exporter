from __future__ import annotations

from .ble import BleTemperatureScanner
from .mock import MockTemperatureScanner
from ..config import Config
from ..models import SensorCache


def create_scanner(config: Config, cache: SensorCache) -> BleTemperatureScanner | MockTemperatureScanner:
    if config.scanner_backend == "mock":
        return MockTemperatureScanner(config, cache)
    return BleTemperatureScanner(config, cache)

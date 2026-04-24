from __future__ import annotations

import logging

from ..config import Config
from ..constants import LOGGER_NAME
from ..scandata import ScanDataStore
from ..scanthread import ScanThread

LOGGER = logging.getLogger(LOGGER_NAME)

def render_health(config: Config, store: ScanDataStore, scanner: ScanThread) -> tuple[str, int]:
    """Return a minimal health body and HTTP status for external monitoring."""
    readings = store.snapshot()
    status = store.status_snapshot()

    if config.sensors:
        # In configured mode every listed sensor must have a fresh reading.
        healthy = all(
            (reading := readings.get(sensor.address)) is not None
            and reading.age_seconds() <= config.metric_ttl_seconds
            for sensor in config.sensors.values()
        )
    else:
        # In auto-discovery mode a single fresh reading is enough to consider the exporter alive.
        healthy = any(reading.age_seconds() <= config.metric_ttl_seconds for reading in readings.values())

    healthy = healthy and scanner.is_running() and status.last_error is None
    #return ("1\n" if healthy else "0\n", 200 if healthy else 503)
    return ("200\n" if healthy else "503\n", 200 if healthy else 503)

from __future__ import annotations

import logging
import signal
import sys
from typing import Any

from .config import Config
from .constants import LOGGER_NAME
from .scandata import ScanDataStore
from .scanthread import ScanThread
from .web import create_app

LOGGER = logging.getLogger(LOGGER_NAME)


def configure_logging(level: str) -> None:
    """Configure the root logger used by both Flask and the scanner thread."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    """Load configuration, start the BLE scanner, and serve the Flask app."""
    config = Config.from_env()
    configure_logging(config.log_level)

    store = ScanDataStore()
    scanner = ScanThread(config, store)
    app = create_app(config, store, scanner)

    def _shutdown(*_: Any) -> None:
        """Convert SIGTERM into the same shutdown path as Ctrl+C."""
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    scanner.start()

    LOGGER.info(
        "Starting exporter on %s:%s scan_seconds=%s configured_sensors=%s",
        config.bind_host,
        config.port,
        config.scan_seconds,
        len(config.sensors),
    )

    try:
        app.run(host=config.bind_host, port=config.port, use_reloader=False)
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user")
    finally:
        LOGGER.info("Stopping scanner thread")
        scanner.stop()

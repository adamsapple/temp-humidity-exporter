from __future__ import annotations

import logging
import signal
from typing import Any

from .config import Config
from .constants import LOGGER_NAME
from .models import SensorCache
from .scanners import create_scanner
from .web import create_app

LOGGER = logging.getLogger(LOGGER_NAME)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)

    cache = SensorCache()
    scanner = create_scanner(config, cache)
    app = create_app(config, cache)

    def _shutdown(*_: Any) -> None:
        raise SystemExit(0)

    scanner.start()
    LOGGER.info(
        "Starting exporter on %s:%s scanner_backend=%s scan_mode=%s configured_sensors=%s",
        config.bind_host,
        config.port,
        config.scanner_backend,
        config.scan_mode,
        len(config.sensors),
    )
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        app.run(host=config.bind_host, port=config.port, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        LOGGER.info("Stopping scanner backend")
        scanner.stop()

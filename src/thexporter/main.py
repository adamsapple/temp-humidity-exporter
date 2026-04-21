from __future__ import annotations
from typing import Any

import logging
import signal
import sys
import argparse
from pathlib import Path

from .config import Config
from .constants import LOGGER_NAME, DEFAULT_CONFIG_PATH
from .logger import configure_logging, logger_initialize_config
from .scandata import ScanDataStore
from .scanthread import ScanThread
from .web import create_app

#logger_initialize_config("INFO")
LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.setLevel(logging.INFO)
# configure_logging(LOGGER,logging.INFO)
# def configure_logging(level: str) -> None:
#     """Configure the root logger used by both Flask and the scanner thread."""
#     logging.basicConfig(
#         level=getattr(logging, level.upper(), logging.INFO),
#         format="%(asctime)s %(levelname)s %(name)s: %(message)s",
#         stream=sys.stdout,
#     )


def main() -> None:
    """Load configuration, start the BLE scanner, and serve the Flask app."""

    parser = argparse.ArgumentParser(description='thexporter: command line options.')
    parser.add_argument('-c', '--config', type=str,      # 値を取るオプション
                        help='path to the configuration file (default: {})'.format(DEFAULT_CONFIG_PATH))
    
    args = parser.parse_args()
    config_path = args.config or DEFAULT_CONFIG_PATH
    LOGGER.info("Using configuration file: %s", config_path)
    
    if not Path(config_path).exists():
        LOGGER.error("Configuration file not found: %s", config_path)
        sys.exit(1)

    config  = Config.from_file(config_path)
    configure_logging(LOGGER, config.log_level)

    store   = ScanDataStore()
    scanner = ScanThread(config, store)
    app     = create_app(config, store, scanner)

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

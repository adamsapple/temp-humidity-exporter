from __future__ import annotations
from logging import Logger

APP_VERSION = "0.2.0"
DEFAULT_CONFIG_PATH = "config.json"
LOGGER_NAME     = "thexporter"
FLASK_NAME      = "thexporter_web"
SCAN_SECONDS    = 3.0
CAP_NET_ADMIN   = 12
CAP_NET_RAW     = 13
LOGGER : Logger | None = None

from __future__ import annotations
from .logger import Logger

APP_VERSION = "0.2.0"
DEFAULT_CONFIG_PATH = "config.json"
LOGGER_NAME     = "thexporter"
FLASK_NAME      = "thexporter_web"
SCAN_SECONDS    = 3.0
CAP_NET_ADMIN   = 12
CAP_NET_RAW     = 13
static_logger: Logger = None

def initLogger() -> None:
    global static_logger
    static_logger = Logger(LOGGER_NAME)

def getLogger() -> Logger:
    global static_logger
    if static_logger is None:
        initLogger()
    
    return static_logger
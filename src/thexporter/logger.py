from __future__ import annotations

import logging


class Logger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def debug(self, message: str) -> None:
        self.logger.debug(message)

    def info(self, message: str) -> None:
        self.logger.info(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str) -> None:
        self.logger.error(message)

    def trace(self, message: str) -> None:
        self.logger.debug(message)

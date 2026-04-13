from __future__ import annotations
from dataclasses import dataclass
from typing import Any

import logging
import inspect
import os
import sys

class Logger:
    """
    ログ出力用クラス
    """
    logger: logging.Logger

    def __init__(self, name: str):
        # self.logger = logging.basicConfig(level=logging.DEBUG, format="[%(asctime)s] [%(process)d] [%(name)s] [%(levelname)s] %(message)s")
        logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                stream=sys.stdout
            )
        self.logger = logging.getLogger(name)
    
    def debug(self, message: str ) -> None:
        self.logger.debug(message)

    def info(self, message: str) -> None:
        self.logger.info(message)

    def warning(self, message: str) -> None:
        self.logger.warning(message)

    def error(self, message: str) -> None:
        self.logger.error(message)
    
    def trace(self, message: str) -> None:
        frame = inspect.currentframe().f_back
        location = "{}:{} {}".format(os.path.basename(frame.f_code.co_filename), frame.f_lineno, frame.f_code.co_name)
        l = logging.getLogger(location)
        l.info(location, message)

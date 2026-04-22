from __future__ import annotations

import sys
import logging

def logger_initialize_config(level: str) -> None:
    logging.basicConfig(
         level=getattr(logging, level.upper(), logging.INFO),
         format="%(asctime)s %(levelname)s %(name)s: %(message)s",
         stream=sys.stdout,
    )

def configure_logging(logger: logging.Logger, level: str) -> None:
    """Configure the root logger used by both Flask and the scanner thread."""
    # logging.basicConfig(
    #     level=getattr(logging, level.upper(), logging.INFO),
    #     format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    #     stream=sys.stdout,
    # )

    # logger = logging.getLogger(name)

    if logger.hasHandlers() is False:
        handler = logging.StreamHandler(sys.stdout)
        # handler.setLevel(level)
        #handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    for h in logger.handlers:
        h.setLevel(level)

    logger.setLevel(level)
    # print("handles(",logger.name, "): ", len(logger.handlers))

# class Logger:
#     def __init__(self, name: str):
#         self.logger = logging.getLogger(name)

#     def debug(self, message: str) -> None:
#         self.logger.debug(message)

#     def info(self, message: str) -> None:
#         self.logger.info(message)

#     def warning(self, message: str) -> None:
#         self.logger.warning(message)

#     def error(self, message: str) -> None:
#         self.logger.error(message)

#     def trace(self, message: str) -> None:
#         self.logger.debug(message)

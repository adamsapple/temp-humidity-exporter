#!/usr/bin/env -S python3 -u
#-u to unbuffer output. Otherwise when calling with nohup or redirecting output things are printed very lately or would even mixup

from __future__ import annotations

import logging
import sys
import signal
from typing import Any

import argparse
import os
import re
from dataclasses import dataclass
from collections import deque
import threading
import time

from bluepy import btle

LOGGER_NAME="test"

def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout
    )

# def show_logs():
#     "(possibly) show logs."
#     print('-' * 10)
#     debug('DEBUG level log')
#     print('-' * 10)
#     info('INFO level log')
#     print('-' * 10)
#     warning('WARNING level log')
#     print('-' * 10)
#     error('ERROR level log')
#     print('-' * 10)
#     try:
#         raise Exception('foo bar.')
#     except:
#         exception('EXCEPTION level log')
#     print('-' * 10)
#     critical('CRITICAL level log')
#     print('-' * 10)

def main() -> None:
    print("main")
    LOGGER.info("main2")
    #show_logs()


if __name__ == "__main__":
    configure_logging("INFO")
    LOGGER = logging.getLogger(LOGGER_NAME)
    main()
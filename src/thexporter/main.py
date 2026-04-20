#!/usr/bin/env -S python3 -u
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

import os
import sys
import signal
from bluepy.btle import BTLEException, DefaultDelegate, Scanner
import binascii
from colorama import Fore, Back, Style, init

from .constants import SCAN_SECONDS, LOGGER_NAME, CAP_NET_ADMIN, CAP_NET_RAW, getLogger

# from .config import Config
# from .constants import LOGGER_NAME
# from .models import SensorCache
# from .scanners import create_scanner
# from .web import create_app

LOGGER = getLogger()

# def configure_logging(level: str) -> None:
#     logging.basicConfig(
#         level=getattr(logging, level, logging.INFO),
#         format="%(asctime)s %(levelname)s %(name)s: %(message)s",
#         stream=sys.stdout
#     )

@dataclass(slots=True)
class Pvvx:
    address: str
    name: str | None = 'unknown'
    decoder: str | None = None
    temperature_celsius: float | None = None
    humidity_percent: float | None = None
    battery_percent: float | None = None
    battery_voltage_volts: float | None = None
    #__DECODER: str = 'pvvx_custom'
    
    def __init__(self, address: str):
        self.address = address
    
    def __str__(self):
        return f'''\
{Fore.WHITE}address: {Fore.RED}{self.address} \
{Fore.WHITE}name: {Fore.LIGHTBLACK_EX}{self.name} \
{Fore.WHITE}decoder: {Fore.LIGHTBLACK_EX}{self.decoder} \
{Fore.WHITE}temperature_celsius: {Fore.BLUE}{self.temperature_celsius} \
{Fore.WHITE}humidity_percent: {Fore.LIGHTBLUE_EX}{self.humidity_percent} \
{Fore.WHITE}battery_percent: {Fore.LIGHTGREEN_EX}{self.battery_percent} \
{Fore.WHITE}battery_voltage_volts: {Fore.GREEN}{self.battery_voltage_volts}\
{Fore.RESET}\
'''
    
class ScanDelegate(DefaultDelegate):
    def __init__(self) -> None:
        super().__init__()


    def handleDiscovery(self, device, isNewDev, isNewData) -> None:
        if isNewDev or isNewData:
            if device.addr != "A4:C1:38:18:32:D9".lower():
                return

            LOGGER.info(f"detected: {device.addr}")       
            # for (adTypeCode, description, valueText) in device.getScanData():
            #    #print(f'- {description}：{valueText}')
            #    LOGGER.info(f"{adTypeCode}: {description}: {valueText}")
            payload = self._get_service_payload(device, 0x181a)
            if payload is None:
                return
            # print(f"Raw Data: {payload.hex()}") 
            pvvx    = self._decode_pvvx_custom(payload)
            if pvvx is None:
                return
            pvvx.name = device.getValueText(9) # Type 9 is "Complete Local Name"
            if pvvx.name is None:
                pvvx.name = "unknown"
            
            # LOGGER.info(f"name(7): {device.getValueText(7)}, name(8): {device.getValueText(8)}, name(9): {device.getValueText(9)}")
            LOGGER.info(f"value: {pvvx}")


    def _get_service_payload(self, device: Any, uuid_suffix: int) -> bytes | None:
        for (adTypeCode, description, valueText) in device.getScanData():
            #LOGGER.info(f"adTypeCode: {adTypeCode}, description: {description}")
            byteData = binascii.unhexlify(valueText)
            if len(byteData) != 15:
                continue

            sig = int.from_bytes(byteData[0:2], "little", signed=True)
            
            if sig != uuid_suffix:
                continue

            return byteData
        
        return None
    

    def _decode_pvvx_custom(self, payload: bytes) -> Pvvx | None: # dict[str, float | int | str] | None:
        if not payload or len(payload) < 15:
            return None
        mac = payload[2:8].hex()
        mac_coloned = (':'.join([mac[i:i+2] for i in range(0,len(mac), 2)])).lower()
        pvvx: Pvvx = Pvvx(mac_coloned)
        pvvx.decoder               = 'pvvx_custom' # Pvvx.__DECODER
        pvvx.temperature_celsius   = int.from_bytes(payload[8:10], "big", signed=True) * 0.1
        pvvx.humidity_percent      = int.from_bytes(payload[10:11], "big") * 0.01
        pvvx.battery_percent       = float(payload[11]) * 0.01
        pvvx.battery_voltage_volts = int.from_bytes(payload[12:14], "big") * 0.001

        return pvvx
    
        # return {
        #     "decoder": "pvvx_custom",
        #     "mac":payload[2:8].hex(),
        #     "temperature_celsius": int.from_bytes(payload[8:10], "little", signed=True) / 10.0,
        #     "humidity_percent": int.from_bytes(payload[10:11], "little") / 100.0,
        #     "battery_voltage_volts": int.from_bytes(payload[11:13], "little") / 1000.0,
        #     "battery_percent": float(payload[13]),
        #     "flags": int(payload[14]),
        # }

def _read_effective_capabilities() -> int | None:
    status_path = "/proc/self/status"
    if not os.path.exists(status_path):
        return None

    try:
        with open(status_path, encoding="utf-8") as fp:
            for line in fp:
                if line.startswith("CapEff:"):
                    return int(line.split(":", 1)[1].strip(), 16)
    except OSError:
        return None

    return None


def _has_capability(capabilities: int | None, cap_number: int) -> bool:
    if capabilities is None:
        return False
    return bool(capabilities & (1 << cap_number))


def _has_scan_permissions() -> bool:
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() == 0:
        return True

    capabilities = _read_effective_capabilities()
    return _has_capability(capabilities, CAP_NET_ADMIN) and _has_capability(capabilities, CAP_NET_RAW)


def _is_permission_denied_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "permission denied",
            "operation not permitted",
            "not authorized",
            "access denied",
            "failed to execute management command 'le on'",
        )
    )


def _print_permission_guidance(prefix: str) -> None:
    python_path = os.path.realpath(sys.executable)
    LOGGER.warning(f"{prefix}: BLE scan requires root or Linux capabilities cap_net_raw,cap_net_admin.")
    LOGGER.warning("Host Linux example:")
    LOGGER.warning(f"  sudo setcap 'cap_net_raw,cap_net_admin+eip' {python_path}")
    LOGGER.warning("  Then restart the shell or re-activate the virtual environment before retrying.")
    LOGGER.warning("Docker example:")
    LOGGER.warning("  Add `cap_add: [NET_ADMIN, NET_RAW]`, mount `/run/dbus`, use `network_mode: host`.")
    LOGGER.warning("  If it still fails against the host adapter, try `privileged: true`.")


def _warn_if_permissions_look_missing() -> None:
    if os.name != "posix":
        return
    if _has_scan_permissions():
        return
    _print_permission_guidance("Preflight warning")


def _shutdown(*_: Any) -> None:
    raise SystemExit(0)


def main() -> None:
    LOGGER.info("start.")

    _warn_if_permissions_look_missing()
    scanner = Scanner().withDelegate(ScanDelegate())
    signal.signal(signal.SIGTERM, _shutdown)

    LOGGER.info("BLE scan started. Press Ctrl+C to stop.")

    try:
        while True:
            scanner.scan(SCAN_SECONDS, passive=True)
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user.")
    except BTLEException as exc:
        LOGGER.error(f"BLE scan error: {exc}")
        if _is_permission_denied_error(exc):
            _print_permission_guidance("Permission error")
    finally:
        LOGGER.info("Stopping scanner backend")
        scanner.stop()
    return

#     config = Config.from_env()
#     configure_logging(config.log_level)

#     cache = SensorCache()
#     scanner = create_scanner(config, cache)
#     app = create_app(config, cache)

#     def _shutdown(*_: Any) -> None:
#         raise SystemExit(0)

#     scanner.start()
#     LOGGER.info(
#         "Starting exporter on %s:%s scanner_backend=%s scan_mode=%s configured_sensors=%s",
#         config.bind_host,
#         config.port,
#         config.scanner_backend,
#         config.scan_mode,
#         len(config.sensors),
#     )
#     signal.signal(signal.SIGTERM, _shutdown)

#     try:
#         app.run(host=config.bind_host, port=config.port, use_reloader=False)
#     except KeyboardInterrupt:
#         pass
#     finally:
#         LOGGER.info("Stopping scanner backend")
#         scanner.stop()
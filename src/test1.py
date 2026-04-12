#!/usr/bin/env -S python3 -u
import logging
import os
import sys
from bluepy.btle import BTLEException, DefaultDelegate, Scanner

LOGGER_NAME="test"
CAP_NET_ADMIN = 12
CAP_NET_RAW = 13

def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout
    )




class ScanDelegate(DefaultDelegate):
    def __init__(self) -> None:
        super().__init__()

    def handleDiscovery(self, dev, isNewDev, isNewData) -> None:
        if isNewDev or isNewData:
            LOGGER.info(f"detected: {dev.addr}")


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


def main() -> None:
    LOGGER.info("main")
    _warn_if_permissions_look_missing()
    scanner = Scanner().withDelegate(ScanDelegate())

    LOGGER.info("BLE scan started. Press Ctrl+C to stop.")

    try:
        while True:
            scanner.scan(3.0, passive=True)
    except KeyboardInterrupt:
        LOGGER.info("\nStopped by user.")
    except BTLEException as exc:
        LOGGER.error(f"BLE scan error: {exc}")
        if _is_permission_denied_error(exc):
            _print_permission_guidance("Permission error")


if __name__ == "__main__":
    configure_logging("INFO")
    LOGGER = logging.getLogger(LOGGER_NAME)
    main()

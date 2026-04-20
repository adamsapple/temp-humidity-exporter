from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any

try:
    from bluepy.btle import BTLEException, DefaultDelegate, Scanner
    BLUEPY_IMPORT_ERROR: Exception | None = None
except ModuleNotFoundError as exc:  # pragma: no cover - depends on runtime environment
    BTLEException = Exception

    class DefaultDelegate:  # type: ignore[no-redef]
        """Fallback base class used only to keep module importable without bluepy."""

        def __init__(self, *_: Any, **__: Any) -> None:
            pass

    Scanner = None  # type: ignore[assignment]
    BLUEPY_IMPORT_ERROR = exc

from .config import Config, SensorConfig, normalize_mac
from .constants import CAP_NET_ADMIN, CAP_NET_RAW, LOGGER_NAME
from .devices.pvvx import decode_pvvx_service_data, extract_pvvx_service_data
from .scandata import ScanDataStore, SensorReading

LOGGER = logging.getLogger(LOGGER_NAME)


class ScanThread:
    """Run bluepy scanning in a dedicated daemon thread."""

    def __init__(self, config: Config, store: ScanDataStore) -> None:
        """Bind runtime configuration and the shared reading store."""
        self._config = config
        self._store = store
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the scanner thread if it is not already running."""
        _require_bluepy()
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="ble-scan-thread", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the scanner thread to stop and wait briefly for it to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=max(5.0, self._config.scan_seconds + 1.0))

    def is_running(self) -> bool:
        """Return whether the scanner thread is currently alive."""
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        """Continuously execute bluepy scan cycles until shutdown is requested."""
        self._store.mark_running(True)
        if not has_scan_permissions():
            _print_permission_guidance("Preflight warning")
        scanner = Scanner().withDelegate(_ScanDelegate(self._config, self._store))

        try:
            while not self._stop_event.is_set():
                self._store.mark_scan_started()
                try:
                    scanner.scan(self._config.scan_seconds, passive=True)
                    self._store.mark_scan_completed()
                except BTLEException as exc:
                    LOGGER.error("BLE scan error: %s", exc)
                    self._store.mark_error(str(exc))
                    if _is_permission_denied_error(exc):
                        _print_permission_guidance("Permission error")
                except Exception as exc:
                    LOGGER.exception("Unexpected scan loop error")
                    self._store.mark_error(str(exc))
        finally:
            self._store.mark_running(False)
            try:
                scanner.stop()
            except Exception:
                LOGGER.debug("Ignoring scanner stop failure", exc_info=True)


class _ScanDelegate(DefaultDelegate):
    """Receive bluepy discovery callbacks and translate them into SensorReading objects."""

    def __init__(self, config: Config, store: ScanDataStore) -> None:
        """Remember configuration and shared store used by discovery callbacks."""
        super().__init__()
        self._config = config
        self._store = store

    def handleDiscovery(self, device: Any, isNewDev: bool, isNewData: bool) -> None:
        """Decode supported advertisements and push fresh values into the store."""
        if not (isNewDev or isNewData):
            return

        payload = extract_pvvx_service_data(device)
        if payload is None:
            return

        decoded = decode_pvvx_service_data(payload)
        if decoded is None:
            return

        device_address = normalize_mac(getattr(device, "addr", None))
        payload_address = normalize_mac(decoded.get("address"))
        sensor = self._resolve_sensor(device_address, payload_address)
        if sensor is None:
            return

        # When sensors are configured, use the configured address as the canonical label key.
        address = sensor.address if self._config.sensors else (payload_address or device_address or sensor.address)
        configured_name = None if not self._config.sensors else sensor.name
        # Prefer the configured display name, otherwise try the BLE local name, then fall back to a synthetic name.
        name = configured_name or _device_name(device) or self._fallback_name(address)
        reading = SensorReading(
            address=address,
            name=name,
            decoder=str(decoded["decoder"]),
            temperature_celsius=_as_float(decoded.get("temperature_celsius")),
            humidity_percent=_as_float(decoded.get("humidity_percent")),
            battery_percent=_as_float(decoded.get("battery_percent")),
            battery_voltage_volts=_as_float(decoded.get("battery_voltage_volts")),
            packet_counter=_as_int(decoded.get("packet_counter")),
            flags=_as_int(decoded.get("flags")),
            rssi=_as_int(getattr(device, "rssi", None)),
        )
        self._store.update(reading)
        LOGGER.debug("Updated reading for %s: %s", address, reading.to_dict())

    def _resolve_sensor(self, *addresses: str | None) -> SensorConfig | None:
        """Match an observed device to configured sensors or synthesize one in auto-discovery mode."""
        normalized_addresses = [address for address in addresses if address]

        if self._config.sensors:
            for address in normalized_addresses:
                sensor = self._config.sensors.get(address)
                if sensor is not None:
                    return sensor
            return None

        address = next((value for value in normalized_addresses if value), None)
        if address is None:
            return None
        return SensorConfig(
            address=address,
            name=self._fallback_name(address),
            decoder=self._config.default_decoder,
        )

    def _fallback_name(self, address: str) -> str:
        """Build a stable synthetic name when the device has no configured or advertised name."""
        suffix = address.replace(":", "").lower()[-6:]
        return f"{self._config.default_sensor_name}_{suffix}"


def _require_bluepy() -> None:
    """Raise a user-friendly error when bluepy is unavailable in the current environment."""
    if BLUEPY_IMPORT_ERROR is None:
        return
    raise RuntimeError(
        "bluepy is not installed in the current Python environment. "
        "Install dependencies with `pip install -r requirements.txt` or `pip install bluepy`."
    ) from BLUEPY_IMPORT_ERROR


def _device_name(device: Any) -> str | None:
    """Return the advertised complete or shortened local name when present."""
    for ad_type in (9, 8):
        value = device.getValueText(ad_type)
        if value:
            return str(value)
    return None


def _as_float(value: Any) -> float | None:
    """Convert optional numeric values into float while preserving None."""
    if value is None:
        return None
    return float(value)


def _as_int(value: Any) -> int | None:
    """Convert optional numeric values into int while preserving None."""
    if value is None:
        return None
    return int(value)


def _read_effective_capabilities() -> int | None:
    """Read the Linux effective capability bitmask from /proc/self/status."""
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
    """Check whether a Linux capability bit is present in the bitmask."""
    if capabilities is None:
        return False
    return bool(capabilities & (1 << cap_number))


def has_scan_permissions() -> bool:
    """Determine whether the current process can likely start BLE scanning."""
    geteuid = getattr(os, "geteuid", None)
    if callable(geteuid) and geteuid() == 0:
        return True

    capabilities = _read_effective_capabilities()
    return _has_capability(capabilities, CAP_NET_ADMIN) and _has_capability(capabilities, CAP_NET_RAW)


def _is_permission_denied_error(exc: BaseException) -> bool:
    """Classify bluepy errors that usually mean missing BLE permissions."""
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
    """Log practical guidance for enabling BLE scan permissions on Linux and Docker."""
    python_path = os.path.realpath(sys.executable)
    LOGGER.warning("%s: BLE scan requires root or Linux capabilities cap_net_raw,cap_net_admin.", prefix)
    LOGGER.warning("Host Linux example:")
    LOGGER.warning("  sudo setcap 'cap_net_raw,cap_net_admin+eip' %s", python_path)
    LOGGER.warning("Docker example:")
    LOGGER.warning("  Add cap_add: [NET_ADMIN, NET_RAW], mount /run/dbus, and use network_mode: host.")

from __future__ import annotations
from dataclasses import asdict, dataclass, field

import threading
import datetime
import time
from typing import Literal


@dataclass(slots=True)
class SensorReading:
    """Latest observed values for a single sensor advertisement stream."""

    address: str
    name: str
    decoder: str
    temperature_celsius: float | None = None
    humidity_percent: float | None = None
    battery_percent: float | None = None
    battery_voltage_volts: float | None = None
    rssi: int | None = None
    packet_counter: int | None = None
    flags: int | None = None
    last_seen_timestamp: float = field(default_factory=time.time)

    def age_seconds(self) -> float:
        """Return how many seconds have passed since the latest advertisement."""
        return max(0.0, time.time() - self.last_seen_timestamp)

    def to_dict(self) -> dict[str, object]:
        """Serialize the reading for JSON status output."""
        data = asdict(self)
        data["age_seconds"] = round(self.age_seconds(), 3)
        return data


@dataclass(slots=True)
class DiscoveredDevice:
    """Observed BLE device state that may exist before a sensor reading is decoded."""

    address: str
    address_type: str | None = None
    device_name: str | None = None
    is_target: Literal["unknown", "include", "exclude"] = "unknown"
    first_seen_timestamp: float = field(default_factory=time.time)
    last_seen_timestamp: float = field(default_factory=time.time)
    last_gatt_name_attempt_timestamp: float | None = None
    last_gatt_name_error: str | None = None

    def age_seconds(self) -> float:
        """Return how many seconds have passed since the latest advertisement."""
        return max(0.0, time.time() - self.last_seen_timestamp)

    def to_dict(self) -> dict[str, object]:
        """Serialize the device state for JSON status output."""
        data = asdict(self)
        data["age_seconds"] = round(self.age_seconds(), 3)
        return data


@dataclass(slots=True)
class ScanStatus:
    """Mutable scanner state shared with HTTP handlers."""

    running: bool = False
    last_error: str | None = None
    last_error_timestamp: float | None = None
    last_scan_started_at: str | None = None
    last_scan_completed_at: str | None = None
    last_update_at: str | None = None
    scan_cycles: int = 0
    started_at: str | None = field(default_factory=str)

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f')

    def to_dict(self) -> dict[str, object]:
        """Serialize status for JSON status output."""
        return asdict(self)


class ScanDataStore:
    """Thread-safe storage for the scanner thread and Flask request handlers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: dict[str, DiscoveredDevice] = {}
        self._readings: dict[str, SensorReading] = {}
        self._status = ScanStatus()

    def snapshot(self) -> dict[str, SensorReading]:
        """Return a shallow copy of all currently cached readings."""
        with self._lock:
            return dict(self._readings)

    def device_snapshot(self) -> dict[str, DiscoveredDevice]:
        """Return a shallow copy of discovered device states."""
        with self._lock:
            return dict(self._devices)

    def status_snapshot(self) -> ScanStatus:
        """Return a copy of the current scanner status."""
        with self._lock:
            return ScanStatus(**self._status.to_dict())

    def mark_running(self, running: bool) -> None:
        """Update whether the background scanner thread is active."""
        with self._lock:
            self._status.running = running
            if running:
                self._status.last_error = None

    def mark_scan_started(self) -> None:
        """Record the start time of a scan cycle."""
        with self._lock:
            self._status.last_scan_started_at = ScanDataStore._getTimeStr()

    def mark_scan_completed(self) -> None:
        """Record a successful scan cycle and clear stale error state."""
        # now = time.time()
        with self._lock:
            self._status.last_scan_completed_at = ScanDataStore._getTimeStr()
            self._status.scan_cycles += 1
            self._status.last_error = None

    def mark_error(self, message: str) -> None:
        """Record the latest scanner error for / and /health output."""
        now = time.time()
        with self._lock:
            self._status.last_error = message
            self._status.last_error_timestamp = now

    def observe_device(
        self,
        address: str,
        *,
        address_type: str | None = None,
        device_name: str | None = None,
    ) -> None:
        """Create or refresh a discovered device entry from an advertisement."""
        now = time.time()
        with self._lock:
            device = self._devices.get(address)
            if device is None:
                device = DiscoveredDevice(address=address)
                self._devices[address] = device
            device.last_seen_timestamp = now
            if address_type:
                device.address_type = address_type
            if device_name:
                device.device_name = device_name
                device.last_gatt_name_error = None
                if address in self._readings:
                    self._readings[address].name = device_name

    def merge_device(self, source_address: str, target_address: str) -> None:
        """Merge aliases that refer to the same physical device under one address key."""
        if source_address == target_address:
            return

        with self._lock:
            source = self._devices.pop(source_address, None)
            target = self._devices.get(target_address)
            if target is None:
                target = DiscoveredDevice(address=target_address)
                self._devices[target_address] = target

            if source is not None:
                target.first_seen_timestamp = min(target.first_seen_timestamp, source.first_seen_timestamp)
                target.last_seen_timestamp = max(target.last_seen_timestamp, source.last_seen_timestamp)
                if not target.address_type and source.address_type:
                    target.address_type = source.address_type
                if not target.device_name and source.device_name:
                    target.device_name = source.device_name
                target.is_target = _merge_target_state(target.is_target, source.is_target)

                source_attempt = source.last_gatt_name_attempt_timestamp or float("-inf")
                target_attempt = target.last_gatt_name_attempt_timestamp or float("-inf")
                if source_attempt > target_attempt:
                    target.last_gatt_name_attempt_timestamp = source.last_gatt_name_attempt_timestamp
                    target.last_gatt_name_error = source.last_gatt_name_error

            reading = self._readings.pop(source_address, None)
            if reading is not None and target_address not in self._readings:
                reading.address = target_address
                if target.device_name:
                    reading.name = target.device_name
                self._readings[target_address] = reading

    def set_target_state(self, address: str, state: Literal["unknown", "include", "exclude"]) -> None:
        """Record whether a discovered device has been identified as a target sensor."""
        now = time.time()
        with self._lock:
            device = self._devices.get(address)
            if device is None:
                device = DiscoveredDevice(address=address)
                self._devices[address] = device
            device.last_seen_timestamp = now
            device.is_target = _merge_target_state(device.is_target, state)

    def get_device_name(self, address: str) -> str | None:
        """Return the best device-provided name known for the address."""
        with self._lock:
            device = self._devices.get(address)
            return None if device is None else device.device_name

    def device_name_lookup_candidates(self, retry_seconds: int) -> list[tuple[str, str | None]]:
        """Return target devices whose names are still unknown and due for a GATT retry."""
        now = time.time()
        with self._lock:
            candidates: list[tuple[str, str | None]] = []
            for address, device in self._devices.items():
                if device.is_target != "include" or device.device_name:
                    continue
                if now - device.first_seen_timestamp < retry_seconds:
                    continue
                if (
                    device.last_gatt_name_attempt_timestamp is not None
                    and now - device.last_gatt_name_attempt_timestamp < retry_seconds
                ):
                    continue
                candidates.append((address, device.address_type))
            return candidates

    def mark_gatt_name_attempt(self, address: str) -> None:
        """Record when a GATT device-name lookup starts."""
        now = time.time()
        with self._lock:
            device = self._devices.get(address)
            if device is None:
                device = DiscoveredDevice(address=address)
                self._devices[address] = device
            device.last_gatt_name_attempt_timestamp = now

    def mark_gatt_name_failure(self, address: str, error: str) -> None:
        """Store the latest GATT name lookup failure for diagnostics."""
        with self._lock:
            device = self._devices.get(address)
            if device is None:
                device = DiscoveredDevice(address=address)
                self._devices[address] = device
            device.last_gatt_name_error = error

    def mark_gatt_name_success(self, address: str, device_name: str) -> None:
        """Store a GATT-resolved device name and clear the latest error."""
        with self._lock:
            device = self._devices.get(address)
            if device is None:
                device = DiscoveredDevice(address=address)
                self._devices[address] = device
            device.device_name = device_name
            device.last_gatt_name_error = None
            if address in self._readings:
                self._readings[address].name = device_name

    def update(self, reading: SensorReading) -> None:
        """Replace the latest reading for a sensor and update timestamps."""
        now = time.time()
        dt_str = ScanDataStore._getTimeStr()
        reading.last_seen_timestamp = now
        with self._lock:
            self._readings[reading.address] = reading
            self._status.last_update_at = dt_str

    def _getTimeStr() -> str:
        return datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f')


def _merge_target_state(
    left: Literal["unknown", "include", "exclude"],
    right: Literal["unknown", "include", "exclude"],
) -> Literal["unknown", "include", "exclude"]:
    """Combine target states while preserving an include match once discovered."""
    if "include" in (left, right):
        return "include"
    if "exclude" in (left, right):
        return "exclude"
    return "unknown"

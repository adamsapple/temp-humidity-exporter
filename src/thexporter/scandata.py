from __future__ import annotations

import threading
import datetime
import time
from dataclasses import asdict, dataclass, field


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
        self.started_at = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f')

    def to_dict(self) -> dict[str, object]:
        """Serialize status for JSON status output."""
        return asdict(self)


class ScanDataStore:
    """Thread-safe storage for the scanner thread and Flask request handlers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._readings: dict[str, SensorReading] = {}
        self._status = ScanStatus()

    def snapshot(self) -> dict[str, SensorReading]:
        """Return a shallow copy of all currently cached readings."""
        with self._lock:
            return dict(self._readings)

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

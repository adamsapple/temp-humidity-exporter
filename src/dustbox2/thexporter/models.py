from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class SensorReading:
    address: str
    name: str
    decoder: str
    temperature_celsius: float | None = None
    humidity_percent: float | None = None
    battery_percent: float | None = None
    battery_voltage_volts: float | None = None
    rssi: int | None = None
    packet_counter: int | None = None
    last_seen_timestamp: float = field(default_factory=time.time)

    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.last_seen_timestamp)


class SensorCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._readings: dict[str, SensorReading] = {}

    def update(self, reading: SensorReading) -> None:
        with self._lock:
            self._readings[reading.address] = reading

    def snapshot(self) -> dict[str, SensorReading]:
        with self._lock:
            return dict(self._readings)

from __future__ import annotations

import logging
import threading
import time

from ..config import Config, SensorConfig
from ..constants import LOGGER_NAME
from ..models import SensorCache, SensorReading

LOGGER = logging.getLogger(LOGGER_NAME)


class MockTemperatureScanner:
    def __init__(self, config: Config, cache: SensorCache) -> None:
        self._config = config
        self._cache = cache
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._sensors = _mock_sensor_configs(config)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="mock-scanner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        LOGGER.info("Starting mock sensor backend with %s sensor(s)", len(self._sensors))
        tick = 0
        while not self._stop_event.is_set():
            now = time.time()
            for index, sensor in enumerate(self._sensors.values(), start=1):
                self._cache.update(self._build_reading(sensor, index, tick, now))
            tick += 1
            self._stop_event.wait(2)

    def _build_reading(self, sensor: SensorConfig, index: int, tick: int, now: float) -> SensorReading:
        phase = (tick + index) % 12
        return SensorReading(
            address=sensor.address,
            name=sensor.name,
            decoder=sensor.decoder,
            temperature_celsius=20.0 + index + (phase * 0.2),
            humidity_percent=45.0 + index + (phase * 0.5),
            battery_percent=float(max(10, 98 - ((tick + index) % 25))),
            battery_voltage_volts=3.0 + ((phase % 5) * 0.01),
            rssi=-40 - index - (phase % 6),
            packet_counter=tick,
            last_seen_timestamp=now,
        )


def _mock_sensor_configs(config: Config) -> dict[str, SensorConfig]:
    if config.sensors:
        return config.sensors

    address = "00:00:00:00:00:01"
    return {
        address: SensorConfig(
            address=address,
            name=f"{config.default_sensor_name}_mock",
            decoder=config.default_decoder,
        )
    }

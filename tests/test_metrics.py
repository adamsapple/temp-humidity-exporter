from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from thexporter.config import Config
from thexporter.metric_builder import build_metrics
from thexporter.scandata import ScanDataStore, SensorReading


class MetricBuilderTest(unittest.TestCase):
    def test_measurement_metrics_use_address_and_sensor_info_carries_name(self) -> None:
        store = ScanDataStore()
        address = "AA:BB:CC:DD:EE:FF"
        store.observe_device(address, address_type="public", device_name="Living Room")
        store.set_target_state(address, "include")
        store.update(
            SensorReading(
                address=address,
                name="Living Room",
                decoder="pvvx_custom",
                temperature_celsius=23.4,
                humidity_percent=56.0,
            )
        )

        metrics = build_metrics(store, Config())

        temperature_line = next(
            line for line in metrics.splitlines()
            if line.startswith("thexporter_temperature_celsius{")
        )
        self.assertIn('address="AA:BB:CC:DD:EE:FF"', temperature_line)
        self.assertNotIn('sensor_name="', temperature_line)
        self.assertIn(
            'thexporter_sensor_info{address="AA:BB:CC:DD:EE:FF",sensor_name="Living Room"} 1',
            metrics,
        )

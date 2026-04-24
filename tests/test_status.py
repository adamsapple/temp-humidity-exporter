from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from thexporter.config import Config
from thexporter.controller.status import build_status_payload
from thexporter.scandata import ScanDataStore, SensorReading


class StatusPayloadTest(unittest.TestCase):
    def test_status_includes_device_name_and_target_state(self) -> None:
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
            )
        )

        payload = build_status_payload(Config(), store, _ScannerStub())

        self.assertEqual(payload["device_count"], 1)
        device = payload["devices"][0]
        self.assertEqual(device["device_name"], "Living Room")
        self.assertEqual(device["target_state"], "include")
        self.assertEqual(device["last_reading"]["name"], "Living Room")


class _ScannerStub:
    def is_running(self) -> bool:
        return True

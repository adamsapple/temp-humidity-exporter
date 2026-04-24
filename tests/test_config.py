from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from thexporter.config import Config


class ConfigTest(unittest.TestCase):
    def test_missing_sensors_defaults_to_empty_mapping(self) -> None:
        path = _write_config({"bind_host": "127.0.0.1"})
        self.addCleanup(lambda: os.unlink(path))

        config = Config.from_file(path)

        self.assertEqual(config.bind_host, "127.0.0.1")
        self.assertEqual(config.sensors, {})
        self.assertEqual(config.device_name_retry_seconds, 30)

    def test_sensor_name_is_optional_override(self) -> None:
        path = _write_config(
            {
                "device_name_retry_seconds": 45,
                "sensors": [
                    {"mac": "AA:BB:CC:DD:EE:01", "decoder": "auto"},
                    {"mac": "AA:BB:CC:DD:EE:02", "name": "greenhouse_south", "decoder": "pvvx_custom"},
                ],
            }
        )
        self.addCleanup(lambda: os.unlink(path))

        config = Config.from_file(path)

        self.assertEqual(config.device_name_retry_seconds, 45)
        self.assertIsNone(config.sensors["AA:BB:CC:DD:EE:01"].name)
        self.assertEqual(config.sensors["AA:BB:CC:DD:EE:02"].name, "greenhouse_south")


def _write_config(data: dict[str, object]) -> str:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fp:
        json.dump(data, fp)
        return fp.name

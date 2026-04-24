from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from thexporter.config import Config
from thexporter.scandata import ScanDataStore
from thexporter.scanthread import _ScanDelegate


class ScanDelegateTest(unittest.TestCase):
    def test_name_only_advertisement_is_cached_before_sensor_payload(self) -> None:
        store = ScanDataStore()
        delegate = _ScanDelegate(Config(), store)
        device = FakeDevice(
            addr="AA:BB:CC:DD:EE:FF",
            addr_type="public",
            local_name="Desk Sensor",
            scan_data=[],
        )

        delegate.handleDiscovery(device, True, False)

        discovered = store.device_snapshot()["AA:BB:CC:DD:EE:FF"]
        self.assertEqual(discovered.device_name, "Desk Sensor")
        self.assertEqual(discovered.is_target, "unknown")
        self.assertEqual(store.snapshot(), {})

    def test_sensor_payload_marks_target_and_uses_advertised_name(self) -> None:
        store = ScanDataStore()
        delegate = _ScanDelegate(Config(), store)
        address = "AA:BB:CC:DD:EE:FF"
        device = FakeDevice(
            addr=address,
            addr_type="public",
            local_name="Living Room",
            scan_data=[(22, "16b Service Data", _custom_payload_hex(address))],
        )

        delegate.handleDiscovery(device, True, False)

        discovered = store.device_snapshot()[address]
        reading = store.snapshot()[address]
        self.assertEqual(discovered.is_target, "include")
        self.assertEqual(discovered.device_name, "Living Room")
        self.assertEqual(reading.name, "Living Room")
        self.assertEqual(reading.decoder, "pvvx_custom")


class FakeDevice:
    def __init__(
        self,
        *,
        addr: str,
        addr_type: str,
        local_name: str | None,
        scan_data: list[tuple[int, str, str]],
    ) -> None:
        self.addr = addr
        self.addrType = addr_type
        self.rssi = -55
        self._local_name = local_name
        self._scan_data = scan_data

    def getValueText(self, ad_type: int) -> str | None:
        if ad_type in (8, 9):
            return self._local_name
        return None

    def getScanData(self) -> list[tuple[int, str, str]]:
        return list(self._scan_data)


def _custom_payload_hex(address: str) -> str:
    mac_bytes = bytes.fromhex(address.replace(":", ""))
    payload = (
        bytes.fromhex("1A18")
        + mac_bytes
        + int(234).to_bytes(2, "big", signed=True)
        + int(5600).to_bytes(2, "big")
        + int(3000).to_bytes(2, "big")
        + bytes([85, 1, 2])
    )
    return payload.hex()

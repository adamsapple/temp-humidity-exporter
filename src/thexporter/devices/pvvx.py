from __future__ import annotations

import binascii
from typing import Any

from ..config import normalize_mac
from ..constants import PVVX_ENVIRONMENTAL_SENSING_UUID


def extract_pvvx_service_data(device: Any) -> bytes | None:
    """Extract the raw Environmental Sensing service data from a BLE advertisement."""
    for ad_type_code, _description, value_text in device.getScanData():
        # AD type 22 means 16-bit Service Data in the format used by PVVX firmware.
        if ad_type_code != 22:
            continue

        try:
            raw = binascii.unhexlify(value_text)
        except (binascii.Error, ValueError):
            continue

        if len(raw) < 15:
            continue
        if int.from_bytes(raw[0:2], "little") != PVVX_ENVIRONMENTAL_SENSING_UUID:
            continue
        return raw

    return None


def decode_pvvx_service_data(payload: bytes) -> dict[str, float | int | str] | None:
    """Decode either the short ATC format or the custom extended PVVX format."""
    if len(payload) == 15:
        return _decode_atc1441(payload)
    if len(payload) >= 17:
        # Some stacks may append extra bytes, so only the known leading layout is decoded.
        return _decode_custom(payload[:17])
    return None


def _decode_atc1441(payload: bytes) -> dict[str, float | int | str]:
    """Decode the compact ATC1441-compatible PVVX advertisement."""
    return {
        "decoder": "pvvx_atc1441",
        "address": _mac_from_payload(payload[2:8]),
        "temperature_celsius":   int.from_bytes(payload[8:10], "big", signed=True) * 0.1,
        "humidity_percent":      float(payload[10]),
        "battery_percent":       float(payload[11]),
        "battery_voltage_volts": int.from_bytes(payload[12:14], "big") * 0.001,
        "packet_counter":        int(payload[14]),
    }


def _decode_custom(payload: bytes) -> dict[str, float | int | str]:
    """Decode the extended PVVX custom advertisement format."""
    return {
        "decoder": "pvvx_custom",
        "address": _mac_from_payload(payload[2:8]),
        "temperature_celsius":   int.from_bytes(payload[8:10], "big", signed=True) * 0.01,
        "humidity_percent":      int.from_bytes(payload[10:12], "big") * 0.01,
        "battery_voltage_volts": int.from_bytes(payload[12:14], "big") * 0.001,
        "battery_percent":       float(payload[14]),
        "packet_counter":        int(payload[15]),
        "flags":                 int(payload[16]),
    }


def _mac_from_payload(raw_mac: bytes) -> str:
    """Convert the MAC bytes embedded in the payload into canonical string form."""
    return normalize_mac(":".join(f"{byte:02X}" for byte in raw_mac)) or ""

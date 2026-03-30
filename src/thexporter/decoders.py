from __future__ import annotations

import logging
from typing import Any

from .constants import LOGGER_NAME

LOGGER = logging.getLogger(LOGGER_NAME)


def decode_advertisement(decoder: str, advertisement_data: Any) -> dict[str, float | int | str] | None:
    if decoder in {"auto", "bthome"}:
        decoded = decode_bthome_v2(advertisement_data)
        if decoded is not None or decoder == "bthome":
            return decoded

    if decoder in {"auto", "pvvx_custom"}:
        decoded = decode_pvvx_custom(advertisement_data)
        if decoded is not None or decoder == "pvvx_custom":
            return decoded

    return None


def decode_bthome_v2(advertisement_data: Any) -> dict[str, float | int | str] | None:
    payload = _get_service_payload(advertisement_data, "fcd2")
    if not payload or len(payload) < 2:
        return None

    device_info = payload[0]
    encrypted = bool(device_info & 0x01)
    if encrypted:
        LOGGER.debug("Encrypted BTHome advertisement is not supported")
        return None

    cursor = 1
    result: dict[str, float | int | str] = {"decoder": "bthome"}

    while cursor < len(payload):
        object_id = payload[cursor]
        cursor += 1

        if object_id == 0x01 and cursor + 1 <= len(payload):
            result["battery_percent"] = float(payload[cursor])
            cursor += 1
        elif object_id == 0x02 and cursor + 2 <= len(payload):
            result["temperature_celsius"] = int.from_bytes(
                payload[cursor : cursor + 2], "little", signed=True
            ) / 100.0
            cursor += 2
        elif object_id == 0x03 and cursor + 2 <= len(payload):
            result["humidity_percent"] = int.from_bytes(payload[cursor : cursor + 2], "little") / 100.0
            cursor += 2
        elif object_id == 0x2E and cursor + 1 <= len(payload):
            result["humidity_percent"] = float(payload[cursor])
            cursor += 1
        elif object_id == 0x0C and cursor + 2 <= len(payload):
            result["voltage_volts"] = int.from_bytes(payload[cursor : cursor + 2], "little") / 1000.0
            cursor += 2
        else:
            length = _bthome_length(object_id)
            if length is None or cursor + length > len(payload):
                LOGGER.debug("Stopping BTHome parse at unknown object_id=0x%02x", object_id)
                break
            cursor += length

    if "voltage_volts" in result and "battery_voltage_volts" not in result:
        result["battery_voltage_volts"] = float(result.pop("voltage_volts"))

    if not any(key in result for key in ("temperature_celsius", "humidity_percent", "battery_percent")):
        return None
    return result


def decode_pvvx_custom(advertisement_data: Any) -> dict[str, float | int | str] | None:
    payload = _get_service_payload(advertisement_data, "181a")
    if not payload or len(payload) < 15:
        return None

    return {
        "decoder": "pvvx_custom",
        "temperature_celsius": int.from_bytes(payload[6:8], "little", signed=True) / 100.0,
        "humidity_percent": int.from_bytes(payload[8:10], "little") / 100.0,
        "battery_voltage_volts": int.from_bytes(payload[10:12], "little") / 1000.0,
        "battery_percent": float(payload[12]),
        "packet_counter": int(payload[13]),
        "flags": int(payload[14]),
    }


def _bthome_length(object_id: int) -> int | None:
    lengths = {
        0x00: 1,
        0x01: 1,
        0x02: 2,
        0x03: 2,
        0x0C: 2,
        0x2E: 1,
    }
    return lengths.get(object_id)


def _get_service_payload(advertisement_data: Any, uuid_suffix: str) -> bytes | None:
    for key, value in getattr(advertisement_data, "service_data", {}).items():
        normalized_key = key.replace("-", "").lower()
        if normalized_key.endswith(uuid_suffix):
            return bytes(value)
    return None

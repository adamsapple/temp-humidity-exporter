from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

import json
import pyyaml
import os
from pathlib import Path

from .constants import DEFAULT_CONFIG_PATH


@dataclass(slots=True, frozen=True)
class SensorConfig:
    address: str
    name: str
    decoder: str = "auto"


@dataclass(slots=True)
class Config:
    bind_host: str = "0.0.0.0"
    port: int = 8000
    sensors: dict[str, SensorConfig] = field(default_factory=dict)
    metric_ttl_seconds: int = 180
    scanner_backend: str = "ble"
    scan_mode: str = "passive"
    log_level: str = "INFO"
    default_decoder: str = "auto"
    default_sensor_name: str = "ble_sensor"
    config_path: str = DEFAULT_CONFIG_PATH

    @classmethod
    def from_env(cls) -> "Config":
        file_config, config_path = _load_file_config()
        config = cls(
            bind_host=_env_or_config("THX_BIND_HOST", file_config, "bind_host", "0.0.0.0"),
            port=_env_or_config_int("THX_PORT", file_config, "port", 8000),
            metric_ttl_seconds=_env_or_config_int(
                "THX_METRIC_TTL_SECONDS", file_config, "metric_ttl_seconds", 180
            ),
            scanner_backend=_env_or_config(
                "THX_SCANNER_BACKEND", file_config, "scanner_backend", "ble"
            ).strip().lower(),
            scan_mode=_env_or_config("THX_SCAN_MODE", file_config, "scan_mode", "passive").strip().lower(),
            log_level=_env_or_config("THX_LOG_LEVEL", file_config, "log_level", "INFO").strip().upper(),
            default_decoder=_env_or_config("THX_DECODER", file_config, "default_decoder", "auto").strip().lower(),
            default_sensor_name=_env_or_config(
                "THX_SENSOR_NAME", file_config, "default_sensor_name", "ble_sensor"
            ),
            config_path=config_path,
        )
        config.sensors = _load_sensor_configs(
            config.default_sensor_name,
            config.default_decoder,
            file_config.get("sensors"),
        )
        if config.scanner_backend not in {"ble", "mock"}:
            raise ValueError("THX_SCANNER_BACKEND must be 'ble' or 'mock'")
        return config


def normalize_mac(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().replace("-", ":").upper()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 6:
        return raw
    return ":".join(part.zfill(2) for part in parts)


def _load_file_config() -> tuple[dict[str, Any], str]:
    config_path = os.getenv("THX_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    path = Path(config_path)
    if not path.exists():
        return {}, config_path

    with path.open(encoding="utf-8") as fp:
        raw_config = json.load(fp)
    if not isinstance(raw_config, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    return raw_config, config_path


def _env_or_config(name: str, file_config: dict[str, Any], config_key: str, default: str) -> str:
    value = os.getenv(name)
    if value is not None:
        return value

    config_value = file_config.get(config_key)
    if config_value is None:
        return default
    return str(config_value)


def _env_or_config_int(name: str, file_config: dict[str, Any], config_key: str, default: int) -> int:
    value = os.getenv(name)
    if value is not None:
        return int(value)

    config_value = file_config.get(config_key)
    if config_value is None:
        return default
    return int(config_value)


def _load_sensor_configs(
    default_name: str,
    default_decoder: str,
    file_sensors: Any = None,
) -> dict[str, SensorConfig]:
    sensors_json = os.getenv("THX_SENSORS")
    if sensors_json:
        return _parse_sensor_configs(json.loads(sensors_json), default_name, default_decoder, "THX_SENSORS")

    if file_sensors is not None:
        return _parse_sensor_configs(file_sensors, default_name, default_decoder, "config.json sensors")

    single_mac = normalize_mac(os.getenv("THX_SENSOR_MAC"))
    if not single_mac:
        return {}

    sensor = SensorConfig(address=single_mac, name=default_name, decoder=default_decoder)
    return {single_mac: sensor}


def _parse_sensor_configs(
    raw_items: Any,
    default_name: str,
    default_decoder: str,
    source_name: str,
) -> dict[str, SensorConfig]:
    if not isinstance(raw_items, list):
        raise ValueError(f"{source_name} must be a JSON array")

    sensors: dict[str, SensorConfig] = {}
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Each {source_name} item must be a JSON object")
        address = normalize_mac(item.get("mac") or item.get("address"))
        if not address:
            raise ValueError(f"{source_name} item #{index} is missing mac/address")
        name = str(item.get("name") or f"{default_name}_{index}")
        decoder = str(item.get("decoder") or default_decoder).strip().lower()
        sensors[address] = SensorConfig(address=address, name=name, decoder=decoder)
    return sensors

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import DEFAULT_CONFIG_PATH, DEFAULT_SCAN_SECONDS


@dataclass(slots=True, frozen=True)
class SensorConfig:
    """Static configuration for a single BLE thermometer."""

    address: str
    name: str
    decoder: str = "auto"
    material: str = "unknown"
    color: str = "#FFFFFF"


@dataclass(slots=True)
class Config:
    """Runtime configuration loaded from config.json and environment variables."""

    bind_host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    scan_seconds: float = DEFAULT_SCAN_SECONDS
    metric_ttl_seconds: int = 180
    active_scan_ttl_seconds: int = 30
    default_decoder: str = "auto"
    default_sensor_name: str = "pvvx"
    default_material: str = "unknown"
    default_color: str = "unknown"
    config_path: str = DEFAULT_CONFIG_PATH
    sensors: dict[str, SensorConfig] = field(default_factory=dict)

    @classmethod
    def from_file(cls, filepath: str | None) -> "Config":
        """Build configuration using environment variables over file values."""
        config_path = filepath or DEFAULT_CONFIG_PATH
        file_config, config_path = _load_file_config(config_path)
        config = cls(
            bind_host   = _config_or_default("bind_host", file_config, "0.0.0.0"),
            port        = _config_or_default_int("port", file_config, 8000),
            log_level   = _config_or_default("log_level", file_config, "INFO").upper(),
            scan_seconds= _config_or_default_float("scan_seconds", file_config, DEFAULT_SCAN_SECONDS),
            metric_ttl_seconds  = _config_or_default_int("metric_ttl_seconds", file_config, 180),
            active_scan_ttl_seconds = _config_or_default_int("active_scan_ttl_seconds", file_config, 30),
            default_decoder     = _normalize_decoder(
                                    _config_or_default("default_decoder", file_config, "auto")
                                  ),
            default_sensor_name =_config_or_default("default_sensor_name", file_config, "pvvx"),
            config_path = config_path,
        )
        config.sensors = _load_sensor_configs(
            file_config.get("sensors"),
            config.default_sensor_name,
            config.default_decoder,
            config.default_material,
            config.default_color
        )
        return config


def normalize_mac(value: str | None) -> str | None:
    """Normalize MAC addresses to upper-case colon-separated form."""
    if value is None:
        return None
    raw = str(value).strip().replace("-", ":").upper()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 6:
        return raw
    return ":".join(part.zfill(2) for part in parts)


def _normalize_decoder(value: Any) -> str:
    """Normalize decoder aliases accepted by this exporter."""
    decoder = str(value).strip().lower()
    if decoder in {"", "auto"}:
        return "auto"
    if decoder in {"pvvx", "pvvx_atc1441", "pvvx_custom", "bthome"}:
        return decoder
    raise ValueError("decoder must be one of auto, pvvx, pvvx_atc1441, pvvx_custom, bthome")


def _load_file_config(config_path: str) -> tuple[dict[str, Any], str]:
    """Load the JSON config file when present, otherwise return defaults."""
    
    path = Path(config_path)
    if not path.exists():
        return {}, config_path

    with path.open(encoding="utf-8") as fp:
        raw_config = json.load(fp)
    if not isinstance(raw_config, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    return raw_config, config_path


def _load_sensor_configs(
    file_sensors: Any,
    default_name: str,
    default_decoder: str,
    default_material: str,
    default_color: str,
) -> dict[str, SensorConfig]:
    """Resolve sensor definitions from env, config file, or legacy single-MAC settings."""
    
    if file_sensors is not None:
        return _parse_sensor_configs(file_sensors, default_name, default_decoder, default_material, default_color, "config.json sensors")


def _parse_sensor_configs(
    raw_items: Any,
    default_name: str,
    default_decoder: str,
    default_material: str,
    default_color: str,
    source_name: str,
) -> dict[str, SensorConfig]:
    """Validate and normalize a sensor list from JSON-compatible data."""
    if not isinstance(raw_items, list):
        raise ValueError(f"{source_name} must be a JSON array")

    sensors: dict[str, SensorConfig] = {}
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Each {source_name} item must be a JSON object")

        address = normalize_mac(item.get("mac") or item.get("address"))
        if not address:
            raise ValueError(f"{source_name} item #{index} is missing mac/address")

        name     = str(item.get("name") or f"{default_name}_{index}")
        decoder  = _normalize_decoder(item.get("decoder") or default_decoder)
        material = str(item.get("material") or default_material)
        color    = str(item.get("color") or default_color)
        sensors[address] = SensorConfig(address=address, name=name, decoder=decoder, material=material, color=color)
    return sensors


def _config_or_default(name: str, file_config: dict[str, Any], default: str) -> str:
    value = file_config.get(name)
    return value if value else default

def _config_or_default_int(name: str, file_config: dict[str, Any], default: int) -> int:
    value = file_config.get(name)
    return int(value) if value else default

def _config_or_default_float(name: str, file_config: dict[str, Any], default: float) -> float:
    value = file_config.get(name)
    return float(value) if value else default

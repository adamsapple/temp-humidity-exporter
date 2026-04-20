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


@dataclass(slots=True)
class Config:
    """Runtime configuration loaded from config.json and environment variables."""

    bind_host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    scan_seconds: float = DEFAULT_SCAN_SECONDS
    metric_ttl_seconds: int = 180
    default_decoder: str = "auto"
    default_sensor_name: str = "pvvx"
    config_path: str = DEFAULT_CONFIG_PATH
    sensors: dict[str, SensorConfig] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        """Build configuration using environment variables over file values."""
        file_config, config_path = _load_file_config()
        config = cls(
            bind_host=_env_or_config("THX_BIND_HOST", file_config, "bind_host", "0.0.0.0"),
            port=_env_or_config_int("THX_PORT", file_config, "port", 8000),
            log_level=_env_or_config("THX_LOG_LEVEL", file_config, "log_level", "INFO").upper(),
            scan_seconds=_env_or_config_float(
                "THX_SCAN_SECONDS",
                file_config,
                "scan_seconds",
                DEFAULT_SCAN_SECONDS,
            ),
            metric_ttl_seconds=_env_or_config_int(
                "THX_METRIC_TTL_SECONDS",
                file_config,
                "metric_ttl_seconds",
                180,
            ),
            default_decoder=_normalize_decoder(
                _env_or_config("THX_DECODER", file_config, "default_decoder", "auto")
            ),
            default_sensor_name=_env_or_config(
                "THX_SENSOR_NAME",
                file_config,
                "default_sensor_name",
                "pvvx",
            ),
            config_path=config_path,
        )
        config.sensors = _load_sensor_configs(
            file_config.get("sensors"),
            config.default_sensor_name,
            config.default_decoder,
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


def _load_file_config() -> tuple[dict[str, Any], str]:
    """Load the JSON config file when present, otherwise return defaults."""
    config_path = os.getenv("THX_CONFIG_PATH", DEFAULT_CONFIG_PATH)
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
) -> dict[str, SensorConfig]:
    """Resolve sensor definitions from env, config file, or legacy single-MAC settings."""
    sensors_json = os.getenv("THX_SENSORS")
    if sensors_json:
        return _parse_sensor_configs(json.loads(sensors_json), default_name, default_decoder, "THX_SENSORS")

    if file_sensors is not None:
        return _parse_sensor_configs(file_sensors, default_name, default_decoder, "config.json sensors")

    single_mac = normalize_mac(os.getenv("THX_SENSOR_MAC"))
    if not single_mac:
        return {}

    return {
        single_mac: SensorConfig(
            address=single_mac,
            name=default_name,
            decoder=default_decoder,
        )
    }


def _parse_sensor_configs(
    raw_items: Any,
    default_name: str,
    default_decoder: str,
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

        name = str(item.get("name") or f"{default_name}_{index}")
        decoder = _normalize_decoder(item.get("decoder") or default_decoder)
        sensors[address] = SensorConfig(address=address, name=name, decoder=decoder)
    return sensors


def _normalize_decoder(value: Any) -> str:
    """Normalize decoder aliases accepted by this exporter."""
    decoder = str(value).strip().lower()
    if decoder in {"", "auto"}:
        return "auto"
    if decoder in {"pvvx", "pvvx_atc1441", "pvvx_custom", "bthome"}:
        return decoder
    raise ValueError("decoder must be one of auto, pvvx, pvvx_atc1441, pvvx_custom, bthome")


def _env_or_config(name: str, file_config: dict[str, Any], config_key: str, default: str) -> str:
    """Return a string value with env taking precedence over file and default."""
    value = os.getenv(name)
    if value is not None:
        return value

    config_value = file_config.get(config_key)
    if config_value is None:
        return default
    return str(config_value)


def _env_or_config_int(name: str, file_config: dict[str, Any], config_key: str, default: int) -> int:
    """Return an integer value with env taking precedence over file and default."""
    value = os.getenv(name)
    if value is not None:
        return int(value)

    config_value = file_config.get(config_key)
    if config_value is None:
        return default
    return int(config_value)


def _env_or_config_float(name: str, file_config: dict[str, Any], config_key: str, default: float) -> float:
    """Return a float value with env taking precedence over file and default."""
    value = os.getenv(name)
    if value is not None:
        return float(value)

    config_value = file_config.get(config_key)
    if config_value is None:
        return default
    return float(config_value)

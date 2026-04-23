from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from pathlib import Path
import threading
import time
from typing import Any

import yaml

from .config import Config, normalize_decoder, normalize_mac
from .constants import LOGGER_NAME

DEVICE_TARGET_UNDEFINED = "undefined"
DEVICE_TARGET_INCLUDE = "include"
DEVICE_TARGET_IGNORE = "ignore"
VALID_DEVICE_TARGETS = {
    DEVICE_TARGET_UNDEFINED,
    DEVICE_TARGET_INCLUDE,
    DEVICE_TARGET_IGNORE,
}

LOGGER = logging.getLogger(LOGGER_NAME)


@dataclass(slots=True, frozen=True)
class DiscoveredDevice:
    """Persisted metadata for a BLE device seen during scanning."""

    address: str
    name: str | None = None
    decoder: str = "auto"
    target: str = DEVICE_TARGET_UNDEFINED


@dataclass(slots=True, frozen=True)
class ManagedDevice:
    """Merged view of configured and discovered metadata used by the exporter."""

    address: str
    name: str
    device_name: str | None
    name_alias: str | None
    decoder: str
    configured_decoder: str | None
    material: str
    color: str
    target: str
    source: str


class DeviceRegistry:
    """Manage configured devices, discovered devices, and runtime ignore hints."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._configured = dict(config.sensors)
        self._discovered_path = Path(config.discovered_devices_path)
        self._discovered = _load_discovered_devices(self._discovered_path, config.default_decoder)
        self._runtime_ignored_addresses: dict[str, float] = {}

        LOGGER.info(
            "Loaded device registry: configured=%s discovered=%s path=%s negative_cache_seconds=%s",
            len(self._configured),
            len(self._discovered),
            self._discovered_path,
            config.negative_cache_seconds,
        )

    def mark_runtime_ignored(self, address: str | None) -> None:
        """Remember addresses that have only shown non-target advertisements so far."""
        if not address:
            return

        with self._lock:
            now = time.monotonic()
            self._prune_expired_runtime_ignored_unlocked(now)
            if self._config.negative_cache_seconds <= 0:
                return
            if address in self._configured or address in self._discovered:
                return
            self._runtime_ignored_addresses[address] = now + self._config.negative_cache_seconds

    def should_skip_due_to_negative_cache(self, address: str | None) -> bool:
        """Return whether the address is still inside the temporary negative-cache window."""
        if not address:
            return False

        with self._lock:
            now = time.monotonic()
            self._prune_expired_runtime_ignored_unlocked(now)
            if self._config.negative_cache_seconds <= 0:
                return False
            if address in self._configured or address in self._discovered:
                return False
            expires_at = self._runtime_ignored_addresses.get(address)
            return expires_at is not None and expires_at > now

    def runtime_ignored_addresses(self) -> tuple[str, ...]:
        """Return addresses that were seen without the target service data."""
        with self._lock:
            self._prune_expired_runtime_ignored_unlocked(time.monotonic())
            return tuple(sorted(self._runtime_ignored_addresses))

    def observe_supported_device(
        self,
        device_address: str | None,
        payload_address: str | None,
        device_name: str | None,
        decoder: str,
    ) -> ManagedDevice | None:
        """Upsert a supported device and return its effective metadata when collectible."""
        normalized_addresses = [address for address in (payload_address, device_address) if address]
        if not normalized_addresses:
            return None

        dirty = False
        decoder_name = normalize_decoder(decoder)
        discovered_name = _optional_string(device_name)

        with self._lock:
            for address in normalized_addresses:
                self._runtime_ignored_addresses.pop(address, None)

            address = self._canonical_address_unlocked(normalized_addresses)
            if address is None:
                return None

            current = self._discovered.get(address)
            if current is None:
                self._discovered[address] = DiscoveredDevice(
                    address=address,
                    name=discovered_name,
                    decoder=decoder_name,
                    target=DEVICE_TARGET_UNDEFINED,
                )
                dirty = True
            else:
                updated = current
                if discovered_name and discovered_name != current.name:
                    updated = replace(updated, name=discovered_name)
                if decoder_name != current.decoder:
                    updated = replace(updated, decoder=decoder_name)
                if updated != current:
                    self._discovered[address] = updated
                    dirty = True

            if dirty:
                self._save_discovered_devices_unlocked()

            managed = self._build_managed_device_unlocked(address)
            if managed.source != "config" and managed.target == DEVICE_TARGET_IGNORE:
                return None
            return managed

    def snapshot_known_devices(self) -> dict[str, ManagedDevice]:
        """Return every configured or discovered device, including ignored ones."""
        with self._lock:
            return {
                address: self._build_managed_device_unlocked(address)
                for address in self._known_addresses_unlocked()
            }

    def snapshot_monitored_devices(self) -> dict[str, ManagedDevice]:
        """Return devices that should appear in status and metrics output."""
        devices = self.snapshot_known_devices()
        return {
            address: device
            for address, device in devices.items()
            if device.source == "config" or device.target != DEVICE_TARGET_IGNORE
        }

    def snapshot_expected_devices(self) -> dict[str, ManagedDevice]:
        """Return devices that should be considered mandatory for health checks."""
        devices = self.snapshot_known_devices()
        return {
            address: device
            for address, device in devices.items()
            if device.source == "config" or device.target == DEVICE_TARGET_INCLUDE
        }

    def _known_addresses_unlocked(self) -> list[str]:
        """Return every known address in a stable order."""
        return sorted(set(self._configured) | set(self._discovered))

    def _prune_expired_runtime_ignored_unlocked(self, now: float) -> None:
        """Drop temporary negative-cache entries whose ignore window has expired."""
        expired_addresses = [
            address
            for address, expires_at in self._runtime_ignored_addresses.items()
            if expires_at <= now
        ]
        for address in expired_addresses:
            self._runtime_ignored_addresses.pop(address, None)

    def _canonical_address_unlocked(self, addresses: list[str]) -> str | None:
        """Resolve an observation to its canonical address."""
        for address in addresses:
            if address in self._configured:
                return address
        for address in addresses:
            if address in self._discovered:
                return address
        return next((address for address in addresses if address), None)

    def _build_managed_device_unlocked(self, address: str) -> ManagedDevice:
        """Merge static and discovered metadata into one exporter-facing device view."""
        configured = self._configured.get(address)
        discovered = self._discovered.get(address)
        device_name = discovered.name if discovered else None
        name_alias = configured.name_alias if configured else None
        target = DEVICE_TARGET_INCLUDE if configured else (discovered.target if discovered else DEVICE_TARGET_UNDEFINED)
        decoder = (
            discovered.decoder
            if discovered and discovered.decoder
            else (configured.decoder if configured else self._config.default_decoder)
        )

        return ManagedDevice(
            address=address,
            name=name_alias or device_name or _fallback_name(self._config.default_sensor_name, address),
            device_name=device_name,
            name_alias=name_alias,
            decoder=decoder,
            configured_decoder=configured.decoder if configured else None,
            material=configured.material if configured else self._config.default_material,
            color=configured.color if configured else self._config.default_color,
            target=target,
            source="config" if configured else "discovered",
        )

    def _save_discovered_devices_unlocked(self) -> None:
        """Persist discovered devices as YAML using an atomic replace."""
        self._discovered_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "devices": [
                {
                    "mac": device.address,
                    "name": device.name,
                    "decoder": device.decoder,
                    "target": device.target,
                }
                for device in sorted(self._discovered.values(), key=lambda item: item.address)
            ]
        }
        temporary_path = self._discovered_path.with_name(f".{self._discovered_path.name}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as fp:
                yaml.safe_dump(payload, fp, sort_keys=False, allow_unicode=True)
            temporary_path.replace(self._discovered_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink(missing_ok=True)


def _load_discovered_devices(path: Path, default_decoder: str) -> dict[str, DiscoveredDevice]:
    """Read the persisted discovered device YAML file when it exists."""
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}

    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("devices") or []
    else:
        raise ValueError(f"{path} must contain a YAML list or a YAML object with a devices array")

    if not isinstance(items, list):
        raise ValueError(f"{path} devices must be a YAML array")

    discovered: dict[str, DiscoveredDevice] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path} devices[{index}] must be a YAML object")

        address = normalize_mac(item.get("mac") or item.get("address"))
        if not address:
            raise ValueError(f"{path} devices[{index}] is missing mac/address")

        discovered[address] = DiscoveredDevice(
            address=address,
            name=_optional_string(item.get("name")),
            decoder=normalize_decoder(item.get("decoder") or default_decoder),
            target=_normalize_target(item.get("target") or DEVICE_TARGET_UNDEFINED),
        )

    return discovered


def _normalize_target(value: Any) -> str:
    """Normalize the include/ignore state used by discovered device entries."""
    target = str(value).strip().lower()
    if target not in VALID_DEVICE_TARGETS:
        raise ValueError("target must be one of undefined, include, ignore")
    return target


def _optional_string(value: Any) -> str | None:
    """Collapse empty strings into None for persisted YAML values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _fallback_name(prefix: str, address: str) -> str:
    """Build a stable fallback display name when no alias or BLE name is available."""
    suffix = address.replace(":", "").lower()[-6:]
    return f"{prefix}_{suffix}"

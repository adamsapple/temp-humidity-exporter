from __future__ import annotations

from .config import Config, SensorConfig
from .constants import APP_VERSION
from .scandata import ScanDataStore


def build_metrics(store: ScanDataStore, config: Config) -> str:
    """Render the latest cached readings in Prometheus text exposition format."""
    readings = store.snapshot()
    status = store.status_snapshot()
    lines = [
        "# HELP thexporter_info Static information about this exporter.",
        "# TYPE thexporter_info gauge",
        _metric_line(
            "thexporter_info",
            {
                "version": APP_VERSION,
                "config_path": config.config_path,
            },
            1,
        ),
        "# HELP thexporter_scanner_running 1 if the BLE scanner thread is running.",
        "# TYPE thexporter_scanner_running gauge",
        f"thexporter_scanner_running {1 if status.running else 0}",
        "# HELP thexporter_scrape_success 1 if at least one device reading is cached.",
        "# TYPE thexporter_scrape_success gauge",
        f"thexporter_scrape_success {1 if readings else 0}",
    ]

    sensors = config.sensors or {
        address: SensorConfig(
            address=reading.address,
            name=reading.name,
            decoder=reading.decoder,
        )
        for address, reading in readings.items()
    }

    if not sensors:
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "# HELP thexporter_sensor_up 1 if a fresh advertisement has been received within the TTL.",
            "# TYPE thexporter_sensor_up gauge",
            "# HELP thexporter_last_seen_timestamp_seconds UNIX timestamp of the latest reading.",
            "# TYPE thexporter_last_seen_timestamp_seconds gauge",
            "# HELP thexporter_advertisement_age_seconds Seconds since the latest reading.",
            "# TYPE thexporter_advertisement_age_seconds gauge",
            "# HELP thexporter_temperature_celsius Latest measured temperature in Celsius.",
            "# TYPE thexporter_temperature_celsius gauge",
            "# HELP thexporter_humidity_percent Latest measured humidity in percent.",
            "# TYPE thexporter_humidity_percent gauge",
            "# HELP thexporter_battery_percent Latest battery level in percent.",
            "# TYPE thexporter_battery_percent gauge",
            "# HELP thexporter_battery_voltage_volts Latest battery voltage in volts.",
            "# TYPE thexporter_battery_voltage_volts gauge",
            "# HELP thexporter_rssi_dbm RSSI of the latest BLE advertisement in dBm.",
            "# TYPE thexporter_rssi_dbm gauge",
            "# HELP thexporter_packet_counter Packet counter from the latest advertisement.",
            "# TYPE thexporter_packet_counter gauge",
            "# HELP thexporter_flags Flags value from the latest advertisement when present.",
            "# TYPE thexporter_flags gauge",
        ]
    )

    for sensor in sensors.values():
        reading = readings.get(sensor.address)
        labels = {
            "address": sensor.address,
            "sensor_name": sensor.name,
            "decoder": reading.decoder if reading else sensor.decoder,
            "material": sensor.material,
            "color": sensor.color,
        }
        age_seconds = reading.age_seconds() if reading else float(config.metric_ttl_seconds + 1)
        up = 1 if reading and age_seconds <= config.metric_ttl_seconds else 0

        lines.append(_metric_line("thexporter_sensor_up", labels, up))
        lines.append(
            _metric_line(
                "thexporter_last_seen_timestamp_seconds",
                labels,
                reading.last_seen_timestamp if reading else 0,
            )
        )
        lines.append(_metric_line("thexporter_advertisement_age_seconds", labels, age_seconds))

        if reading is None:
            continue

        # Only expose measurements that were actually present in the last decoded packet.
        optional_metrics: list[tuple[str, float | int | None]] = [
            ("thexporter_temperature_celsius", reading.temperature_celsius),
            ("thexporter_humidity_percent", reading.humidity_percent),
            ("thexporter_battery_percent", reading.battery_percent),
            ("thexporter_battery_voltage_volts", reading.battery_voltage_volts),
            ("thexporter_rssi_dbm", reading.rssi),
            ("thexporter_packet_counter", reading.packet_counter),
            ("thexporter_flags", reading.flags),
        ]
        for metric_name, value in optional_metrics:
            if value is None:
                continue
            lines.append(_metric_line(metric_name, labels, value))

    return "\n".join(lines) + "\n"


def _metric_line(name: str, labels: dict[str, str], value: float | int) -> str:
    """Render one Prometheus sample line with escaped labels."""
    label_text = ",".join(f'{key}="{_escape_label(val)}"' for key, val in labels.items())
    return f"{name}{{{label_text}}} {value}"


def _escape_label(value: str) -> str:
    """Escape label values according to the Prometheus text format."""
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

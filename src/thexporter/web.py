from __future__ import annotations

from flask import Flask, Response, jsonify

from .config import Config, SensorConfig
from .constants import APP_VERSION
from .metrics import build_metrics
from .models import SensorCache


def create_app(config: Config, cache: SensorCache) -> Flask:
    app = Flask("thexporter")

    @app.get("/")
    def index() -> Response:
        readings = cache.snapshot()
        visible_sensors = config.sensors or {
            address: SensorConfig(address=reading.address, name=reading.name, decoder=reading.decoder)
            for address, reading in readings.items()
        }
        return jsonify(
            {
                "name": "temp-humidity-exporter",
                "version": APP_VERSION,
                "metrics_path": "/metrics",
                "scanner_backend": config.scanner_backend,
                "scan_mode": config.scan_mode,
                "config_path": config.config_path,
                "sensors": [
                    {"address": sensor.address, "name": sensor.name, "decoder": sensor.decoder}
                    for sensor in visible_sensors.values()
                ],
                "sensor_count": len(visible_sensors),
            }
        )

    @app.get("/healthz")
    def healthz() -> Response:
        readings = cache.snapshot()
        if config.sensors:
            healthy = all(
                (reading := readings.get(sensor.address)) is not None
                and reading.age_seconds() <= config.metric_ttl_seconds
                for sensor in config.sensors.values()
            )
        else:
            healthy = any(reading.age_seconds() <= config.metric_ttl_seconds for reading in readings.values())
        status = 200 if healthy else 503
        return jsonify({"ok": healthy, "reading_count": len(readings)}), status

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(build_metrics(cache, config), mimetype="text/plain; version=0.0.4; charset=utf-8")

    return app

from __future__ import annotations

from flask import Flask, Response, jsonify

from .helper.logger import configure_logging
from .config import Config
from .constants import FLASK_NAME
from .controller.health import render_health
from .controller.metrics import render_metrics
from .controller.status import build_status_payload
from .device_registry import DeviceRegistry
from .scandata import ScanDataStore
from .scanthread import ScanThread


def create_app(config: Config, store: ScanDataStore, scanner: ScanThread, registry: DeviceRegistry) -> Flask:
    """Create the Flask application that exposes status, health, and metrics."""
    
    app = Flask(FLASK_NAME)
    configure_logging(app.logger, config.log_level)

    @app.get("/")
    def index() -> Response:
        """Return a JSON snapshot of exporter state and discovered devices."""
        return jsonify(build_status_payload(config, store, scanner, registry))

    @app.get("/health")
    @app.get("/healthz")
    def health() -> Response:
        """Expose a minimal health response expected by external monitors."""
        body, status = render_health(config, store, scanner, registry)
        return Response(body, status=status, mimetype="text/plain; charset=utf-8")

    @app.get("/metrics")
    def metrics() -> Response:
        """Expose cached sensor readings in Prometheus text format."""
        return Response(
            render_metrics(config, store, registry),
            mimetype="text/plain; version=0.0.4; charset=utf-8",
        )

    return app

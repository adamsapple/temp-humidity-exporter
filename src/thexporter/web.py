from __future__ import annotations

import logging

from flask import Flask, Response, jsonify

from .config import Config
from .constants import FLASK_NAME, LOGGER_NAME
from .controller.health import render_health
from .controller.metrics import render_metrics
from .controller.status import build_status_payload
from .scandata import ScanDataStore
from .scanthread import ScanThread

from .logger import configure_logging

def create_app(config: Config, store: ScanDataStore, scanner: ScanThread) -> Flask:
    """Create the Flask application that exposes status, health, and metrics."""
    
    app = Flask(FLASK_NAME)
    configure_logging(app.logger, config.log_level)

    @app.get("/")
    def index() -> Response:
        """Return a JSON snapshot of exporter state and discovered devices."""
        return jsonify(build_status_payload(config, store, scanner))

    @app.get("/health")
    def health() -> Response:
        """Expose a minimal health response expected by external monitors."""
        body, status = render_health(config, store, scanner)
        return Response(body, status=status, mimetype="text/plain; charset=utf-8")

    @app.get("/metrics")
    def metrics() -> Response:
        """Expose cached sensor readings in Prometheus text format."""
        return Response(
            render_metrics(config, store),
            mimetype="text/plain; version=0.0.4; charset=utf-8",
        )

    return app

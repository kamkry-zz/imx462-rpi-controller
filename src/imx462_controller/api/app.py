"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..camera.service import CameraManager
from ..config import AppConfig, Secrets
from ..mqtt.client import MqttPublisher
from ..otel.setup import setup_telemetry
from .routes import router
from .streaming import ConnectionManager, status_broadcaster

logger = logging.getLogger(__name__)


def create_app(
    config: AppConfig,
    secrets: Secrets,
    picam2_factory=None,
    encoder_factory=None,
) -> FastAPI:
    """Build the FastAPI app wired to the camera manager, MQTT, and OTel."""
    camera_manager = CameraManager(
        config,
        picam2_factory=picam2_factory,
        encoder_factory=encoder_factory,
    )
    mqtt = MqttPublisher(config.mqtt, secrets)
    connections = ConnectionManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        mqtt.start()
        mqtt.start_heartbeat(config.mqtt.heartbeat_interval_seconds, camera_manager.status)
        status_fn = lambda: {**camera_manager.status(), "clients": connections.clients()}
        broadcaster = asyncio.create_task(status_broadcaster(connections, status_fn, interval=2.0))
        logger.info("Application started")
        try:
            yield
        finally:
            broadcaster.cancel()
            mqtt.stop()
            camera_manager.close()
            logger.info("Application stopped")

    app = FastAPI(title="IMX462 RPi Camera Controller", lifespan=lifespan)
    app.state.camera_manager = camera_manager
    app.state.mqtt = mqtt
    app.state.connections = connections
    app.state.config = config

    @app.middleware("http")
    async def _no_cache_static(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith((".js", ".css", ".html")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response

    setup_telemetry(config.otel, secrets, app=app)

    app.include_router(router)

    static_dir = Path(__file__).parent.parent / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app

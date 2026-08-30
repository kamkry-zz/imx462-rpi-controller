"""Configuration loading and validation.

Non-secret values come from ``config.yaml``; secrets come from a local ``.env``.
Both are validated into typed models so the rest of the app never reads raw dicts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class DefaultMode(BaseModel):
    width: int = 1920
    height: int = 1080
    bit_depth: int | None = None  # RAW10/RAW12 (imx290); None for sensors without a selector
    framerate: int = 60


class CameraConfig(BaseModel):
    id: int
    name: str
    overlay: str = "imx290"  # device-tree overlay driving this sensor (imx290/imx708/...)
    overlay_params: str = ""  # extra dtoverlay parameters (e.g. clock-frequency=74250000)
    default_mode: DefaultMode | None = None  # per-camera mode override (falls back to global)


class CaptureConfig(BaseModel):
    output_dir: str = "/var/lib/imx462-controller/media"
    photo_format: str = "jpg"
    video_format: str = "mp4"


class MqttTopicsConfig(BaseModel):
    events: str = "imx462/events"
    status: str = "imx462/status"
    metrics: str = "imx462/metrics"


class MqttConfig(BaseModel):
    topics: MqttTopicsConfig = MqttTopicsConfig()
    heartbeat_interval_seconds: int = 30


class OtelConfig(BaseModel):
    endpoint: str = ""
    service_name: str = "imx462-rpi-controller"
    metric_export_interval_ms: int = 30000


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    cameras: list[CameraConfig] = []
    default_mode: DefaultMode = DefaultMode()
    capture: CaptureConfig = CaptureConfig()
    mqtt: MqttConfig = MqttConfig()
    otel: OtelConfig = OtelConfig()
    logging: LoggingConfig = LoggingConfig()


class Secrets(BaseModel):
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    otel_headers: str = ""


def load_config(path: str | Path) -> AppConfig:
    """Load and validate ``config.yaml``. Raises ``ConfigError`` on any problem."""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        raw: Any = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Invalid configuration in {config_path}: expected a mapping")

    try:
        return AppConfig.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError
        raise ConfigError(f"Invalid configuration in {config_path}: {exc}") from exc


def load_secrets(path: str | Path = ".env") -> Secrets:
    """Load secrets from a local ``.env`` file (missing file is tolerated)."""
    load_dotenv(path, override=False)
    try:
        port = int(os.getenv("MQTT_PORT", "1883"))
    except ValueError:
        port = 1883
    return Secrets(
        mqtt_host=os.getenv("MQTT_HOST", ""),
        mqtt_port=port,
        mqtt_username=os.getenv("MQTT_USERNAME", ""),
        mqtt_password=os.getenv("MQTT_PASSWORD", ""),
        otel_headers=os.getenv("OTEL_EXPORTER_OTLP_HEADERS", ""),
    )

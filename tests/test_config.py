from __future__ import annotations

import pytest

from imx462_controller.config import (
    AppConfig,
    Secrets,
    load_config,
)


@pytest.fixture
def sample_config_dict() -> dict:
    return {
        "server": {"host": "127.0.0.1", "port": 9000},
        "cameras": [{"id": 0, "name": "cam0"}, {"id": 1, "name": "cam1"}],
        "default_mode": {"width": 1920, "height": 1080, "bit_depth": 12, "framerate": 60},
        "capture": {"output_dir": "/tmp/media", "photo_format": "jpg", "video_format": "mp4"},
        "mqtt": {
            "topics": {"events": "e", "status": "s", "metrics": "m"},
            "heartbeat_interval_seconds": 10,
        },
        "otel": {"endpoint": "http://localhost:4318", "service_name": "test"},
        "logging": {"level": "INFO"},
    }


def test_load_config_valid(tmp_path, sample_config_dict):
    import yaml

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(sample_config_dict))
    config = load_config(path)
    assert isinstance(config, AppConfig)
    assert len(config.cameras) == 2
    assert config.default_mode.bit_depth == 12
    assert config.capture.output_dir == "/tmp/media"


def test_load_config_missing_file(tmp_path):
    from imx462_controller.config import ConfigError

    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_load_config_invalid_yaml(tmp_path):
    from imx462_controller.config import ConfigError

    path = tmp_path / "config.yaml"
    path.write_text("cameras: [unclosed")
    with pytest.raises(ConfigError):
        load_config(path)


def test_load_config_invalid_schema(tmp_path):
    from imx462_controller.config import ConfigError

    path = tmp_path / "config.yaml"
    path.write_text("cameras:\n  - id: not_an_int\n    name: cam0\n")
    with pytest.raises(ConfigError):
        load_config(path)


def test_load_config_defaults_for_empty_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("")
    config = load_config(path)
    assert config.server.port == 8000
    assert config.cameras == []


def test_load_secrets_defaults():
    secrets = Secrets()
    assert secrets.mqtt_port == 1883
    assert secrets.mqtt_host == ""

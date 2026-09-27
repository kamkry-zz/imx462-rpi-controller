from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from imx462_controller.api.app import create_app
from imx462_controller.config import AppConfig, CameraConfig, CaptureConfig, Secrets


class FakePicamera2:
    def __init__(self, camera_num=None):
        self.camera_num = camera_num
        self.started = False
        self.config = None
        self.captured = []

    def create_video_configuration(
        self, main=None, lores=None, sensor=None, controls=None, transform=None, raw=None
    ):
        return {
            "main": main,
            "lores": lores,
            "raw": raw,
            "sensor": sensor,
            "controls": controls,
            "transform": transform,
        }

    def configure(self, config):
        self.config = config
        size = config.get("main", {}).get("size", (1920, 1080))
        self.main_size = (size[0], size[1])

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def capture_file(self, path):
        Path(path).write_bytes(b"\xff\xd8fakejpeg")
        self.captured.append(path)

    def capture_metadata(self):
        return {"AnalogueGain": 1.0, "ExposureTime": 33333, "SensorTimestamp": 0}

    def capture_arrays(self, names):
        import numpy as np

        w, h = getattr(self, "main_size", (1920, 1080))
        arr = np.zeros((h * 3 // 2, w), dtype=np.uint8)
        return [arr], {"ExposureTime": 33333, "SensorTimestamp": 1_000_000_000}

    def set_controls(self, controls):
        pass

    def start_encoder(self, encoder, output, name=None):
        pass

    def stop_encoder(self, encoder=None):
        pass


class AutofocusPicamera2(FakePicamera2):
    """Fake reporting Camera Module 3 (imx708) autofocus controls."""

    def __init__(self, camera_num=None):
        super().__init__(camera_num)
        self.camera_controls = {
            "ExposureTime": (16666, 115686258, 33333),
            "AnalogueGain": (1.0, 31.6, 1.0),
            "AfMode": (0, 2, 1),
            "AfTrigger": (0, 1, 0),
            "LensPosition": (0.0, 15.25, 0.0),
        }
        self.metadata = {
            "AnalogueGain": 1.0,
            "ExposureTime": 33333,
            "AfState": 2,
            "LensPosition": 0.0,
        }

    def capture_metadata(self):
        return {**self.metadata, "SensorTimestamp": 0}


@pytest.fixture
def focus_client(tmp_path):
    config = AppConfig(
        cameras=[CameraConfig(id=0, name="cam0")],
        capture=CaptureConfig(output_dir=str(tmp_path / "media"), video_format="h264"),
    )
    app = create_app(
        config,
        Secrets(),
        picam2_factory=AutofocusPicamera2,
        encoder_factory=lambda path: (object(), str(path)),
    )
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(tmp_path):
    config = AppConfig(
        cameras=[CameraConfig(id=0, name="cam0")],
        capture=CaptureConfig(output_dir=str(tmp_path / "media"), video_format="h264"),
    )
    secrets = Secrets()  # no MQTT host -> MQTT disabled; no otel endpoint -> disabled
    app = create_app(
        config,
        secrets,
        picam2_factory=FakePicamera2,
        encoder_factory=lambda path: (object(), str(path)),
    )
    with TestClient(app) as c:
        yield c


def test_list_cameras(client):
    res = client.get("/api/cameras")
    assert res.status_code == 200
    data = res.json()
    assert len(data["cameras"]) == 1
    assert data["cameras"][0]["name"] == "cam0"


def test_set_mode(client):
    res = client.put(
        "/api/cameras/0/mode",
        json={"width": 1920, "height": 1080, "bit_depth": 12, "framerate": 60},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_set_mode_accepts_null_bit_depth(client):
    # Sensors without a bit-depth selector (e.g. imx708) report bit_depth: null;
    # the mode API must accept it instead of rejecting with 422.
    res = client.put(
        "/api/cameras/0/mode",
        json={"width": 2304, "height": 1296, "bit_depth": None, "framerate": 30},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_capture_photo(client):
    client.put(
        "/api/cameras/0/mode",
        json={"width": 1920, "height": 1080, "bit_depth": 12, "framerate": 60},
    )
    res = client.post("/api/cameras/0/photo")
    assert res.status_code == 200
    assert res.json()["path"].endswith(".jpg")


def test_recording_start_stop(client):
    client.put(
        "/api/cameras/0/mode",
        json={"width": 1920, "height": 1080, "bit_depth": 12, "framerate": 60},
    )
    start = client.post("/api/cameras/0/recording/start")
    assert start.status_code == 200
    assert start.json()["recording"] is True

    stop = client.post("/api/cameras/0/recording/stop")
    assert stop.status_code == 200
    assert stop.json()["recording"] is False
    assert stop.json()["path"].endswith(".h264")


def test_unknown_camera_returns_404(client):
    assert client.post("/api/cameras/99/photo").status_code == 404


def test_camera_settings(client):
    client.put(
        "/api/cameras/0/mode",
        json={"width": 1920, "height": 1080, "bit_depth": 12, "framerate": 60},
    )
    # Settings are read by a background metadata thread; wait for the first read.
    res = client.get("/api/cameras/0/settings")
    for _ in range(50):
        if res.json().get("analogue_gain") is not None:
            break
        time.sleep(0.1)
        res = client.get("/api/cameras/0/settings")
    assert res.status_code == 200
    assert "analogue_gain" in res.json()
    assert "exposure_time" in res.json()


def test_unknown_camera_settings_returns_404(client):
    assert client.get("/api/cameras/99/settings").status_code == 404


def test_config_endpoint(client):
    res = client.get("/api/config")
    assert res.status_code == 200
    assert res.json()["cameras"][0]["id"] == 0


def test_static_frontend_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "IMX462" in res.text


def test_websocket_initial_status(client):
    with client.websocket_connect("/api/ws") as ws:
        data = ws.receive_json()
        assert "cameras" in data
        assert data["cameras"][0]["id"] == 0
        assert "clients" in data


def test_set_controls(client):
    res = client.put(
        "/api/cameras/0/controls",
        json={"controls": {"Brightness": 0.2, "ColourGains": [1.5, 1.2]}},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_set_flip(client):
    res = client.put("/api/cameras/0/flip", json={"hflip": True, "vflip": False})
    assert res.status_code == 200
    assert res.json()["hflip"] is True


def test_assets_list_download_delete(client):
    client.put(
        "/api/cameras/0/mode",
        json={"width": 1920, "height": 1080, "bit_depth": 12, "framerate": 60},
    )
    photo = client.post("/api/cameras/0/photo").json()
    assert photo["url"].startswith("/api/assets/")
    filename = photo["path"].split("/")[-1]

    assets = client.get("/api/assets").json()["assets"]
    assert any(a["filename"] == filename for a in assets)

    download = client.get(photo["url"])
    assert download.status_code == 200
    assert download.content == b"\xff\xd8fakejpeg"
    assert "attachment" in download.headers["content-disposition"]

    deleted = client.delete(f"/api/assets/{filename}")
    assert deleted.status_code == 200
    assert client.get(photo["url"]).status_code == 404


def test_assets_traversal_blocked(client):
    assert client.get("/api/assets/..%2Fconfig.yaml").status_code >= 400
    assert client.delete("/api/assets/..%2Fetc%2Fpasswd").status_code >= 400


def test_list_cameras_includes_default_mode(client):
    data = client.get("/api/cameras").json()
    assert data["default_mode"]["width"] == 1920
    assert "bit_depth" in data["default_mode"]


def test_list_cameras_includes_capabilities(client):
    data = client.get("/api/cameras").json()
    assert data["cameras"][0]["capabilities"]["exposure_max_us"] > 0


def test_capabilities_endpoint(client):
    res = client.get("/api/cameras/0/capabilities")
    assert res.status_code == 200
    caps = res.json()
    assert caps["exposure_max_us"] > 0
    assert caps["gain_min"] > 0
    assert caps["min_frame_duration_us"] > 0


def test_capabilities_unknown_camera_returns_404(client):
    assert client.get("/api/cameras/99/capabilities").status_code == 404


def test_set_stream_mode(client):
    res = client.put("/api/cameras/0/stream-mode", json={"mode": "single"})
    assert res.status_code == 200
    assert res.json()["mode"] == "single"
    res = client.put("/api/cameras/0/stream-mode", json={"mode": "continuous"})
    assert res.status_code == 200
    assert res.json()["mode"] == "continuous"


def test_snapshot_native(client):
    client.put(
        "/api/cameras/0/mode",
        json={"width": 1920, "height": 1080, "bit_depth": 12, "framerate": 60},
    )
    res = client.post("/api/cameras/0/snapshot", json={"exposure_us": 2000000, "gain": 1.0})
    assert res.status_code == 200
    assert res.json()["path"].endswith(".jpg")


def test_snapshot_rejects_nonpositive_exposure(client):
    assert (
        client.post("/api/cameras/0/snapshot", json={"exposure_us": 0, "gain": 1.0}).status_code
        == 422
    )
    assert (
        client.post("/api/cameras/0/snapshot", json={"exposure_us": -5, "gain": 1.0}).status_code
        == 422
    )
    assert (
        client.post("/api/cameras/0/snapshot", json={"exposure_us": 1000, "gain": -1.0}).status_code
        == 422
    )


def test_stream_unknown_camera_returns_404(client):
    assert client.get("/api/cameras/99/stream").status_code == 404


def test_focus_get(focus_client):
    res = focus_client.get("/api/cameras/0/focus")
    assert res.status_code == 200
    assert "focus_mode" in res.json()


def test_focus_trigger(focus_client):
    res = focus_client.post("/api/cameras/0/focus/trigger", json={})
    assert res.status_code == 200
    assert res.json()["focus_mode"] == "auto"


def test_focus_set_manual(focus_client):
    res = focus_client.put(
        "/api/cameras/0/focus", json={"mode": "manual", "lens_position": 1.0}
    )
    assert res.status_code == 200
    assert res.json()["focus_mode"] == "manual"
    assert res.json()["lens_position"] == 1.0


def test_focus_periodic_interval(focus_client):
    res = focus_client.put(
        "/api/cameras/0/focus", json={"mode": "auto", "refocus_interval_seconds": 30}
    )
    assert res.status_code == 200
    assert res.json()["refocus_interval_seconds"] == 30


def test_focus_invalid_mode_rejected(focus_client):
    assert focus_client.put("/api/cameras/0/focus", json={"mode": "bogus"}).status_code == 422


def test_focus_trigger_bad_timeout_rejected(focus_client):
    res = focus_client.post(
        "/api/cameras/0/focus/trigger", json={"wait": True, "timeout_ms": 0}
    )
    assert res.status_code == 422


def test_focus_unsupported_camera(client):
    assert client.get("/api/cameras/0/focus").status_code == 409
    assert client.post("/api/cameras/0/focus/trigger", json={}).status_code == 409
    assert client.put("/api/cameras/0/focus", json={"mode": "auto"}).status_code == 409


def test_focus_unknown_camera_returns_404(focus_client):
    assert focus_client.get("/api/cameras/99/focus").status_code == 404


def _set_long_exposure(client):
    return client.put(
        "/api/cameras/0/controls",
        json={
            "controls": {
                "AeEnable": False,
                "ExposureTime": 2000000,
                "AnalogueGain": 1.0,
                "FrameDurationLimits": [2000000, 2000000],
            }
        },
    )


def test_focus_stale_in_long_exposure(focus_client):
    _set_long_exposure(focus_client)
    body = focus_client.get("/api/cameras/0/focus").json()
    assert body["focus_stale"] is True
    assert body["af_state"] is None


def test_focus_trigger_assists_in_long_exposure(focus_client):
    _set_long_exposure(focus_client)
    res = focus_client.post(
        "/api/cameras/0/focus/trigger", json={"wait": True, "timeout_ms": 1500}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["assisted"] is True
    assert body["focus_mode"] == "manual"  # locked at the achieved position


def test_focus_trigger_assist_disabled_returns_409(focus_client):
    _set_long_exposure(focus_client)
    res = focus_client.post("/api/cameras/0/focus/trigger", json={"assist": False})
    assert res.status_code == 409


def test_focus_trigger_in_manual_preserves_mode(focus_client):
    focus_client.put("/api/cameras/0/focus", json={"mode": "manual", "lens_position": 4.0})
    res = focus_client.post(
        "/api/cameras/0/focus/trigger", json={"wait": True, "timeout_ms": 1500}
    )
    assert res.status_code == 200
    assert res.json()["focus_mode"] == "manual"  # focus now must not drop the manual lock

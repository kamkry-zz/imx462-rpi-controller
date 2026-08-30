from __future__ import annotations

import pytest

from imx462_controller.camera.service import (
    CameraManager,
    CameraMode,
    CameraWorker,
    _StreamingOutput,
)
from imx462_controller.config import AppConfig, CameraConfig, CaptureConfig


class FakePicamera2:
    def __init__(self, camera_num=None):
        self.camera_num = camera_num
        self.started = False
        self.config = None
        self.controls = None
        self.captured = []
        self.encoders = []
        self.encoder_stopped = []
        self.frames = [b"\xff\xd8fakejpeg"]
        self.metadata = {"AnalogueGain": 2.0, "ExposureTime": 33333, "SensorTimestamp": 0}

    def create_video_configuration(
        self, main=None, lores=None, sensor=None, controls=None, transform=None
    ):
        return {
            "main": main,
            "lores": lores,
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
        self.captured.append(path)

    def capture_array(self, name):
        import numpy as np

        w, h = getattr(self, "main_size", (1920, 1080))
        return np.zeros((h * 3 // 2, w), dtype=np.uint8)

    def capture_arrays(self, names):
        import numpy as np

        w, h = getattr(self, "main_size", (1920, 1080))
        arr = np.zeros((h * 3 // 2, w), dtype=np.uint8)
        return [arr], {"ExposureTime": 33333, "SensorTimestamp": 1_000_000_000}

    def capture_metadata(self):
        return self.metadata

    def set_controls(self, controls):
        self.controls = controls

    def start_encoder(self, encoder, output, name=None):
        self.encoders.append((encoder, output, name))

    def stop_encoder(self, encoder=None):
        self.encoder_stopped.append(encoder)


@pytest.fixture
def capture_config(tmp_path):
    return CaptureConfig(output_dir=str(tmp_path / "media"), video_format="h264")


@pytest.fixture
def app_config():
    return AppConfig(
        cameras=[CameraConfig(id=0, name="cam0"), CameraConfig(id=1, name="cam1")],
        capture=CaptureConfig(output_dir="/tmp/imx462-media"),
    )


def test_configure_mode_uses_raw12_for_12bit(capture_config):
    fake = FakePicamera2()
    worker = CameraWorker(0, "cam0", fake, capture_config)
    worker.configure_mode(CameraMode(width=1920, height=1080, bit_depth=12, framerate=60))
    assert fake.started is True
    assert fake.config["sensor"]["bit_depth"] == 12


def test_configure_mode_uses_raw10_for_10bit(capture_config):
    fake = FakePicamera2()
    worker = CameraWorker(0, "cam0", fake, capture_config)
    worker.configure_mode(CameraMode(width=1280, height=720, bit_depth=10, framerate=60))
    assert fake.config["sensor"]["bit_depth"] == 10


def test_capture_photo_requires_start(capture_config):
    fake = FakePicamera2()
    worker = CameraWorker(0, "cam0", fake, capture_config)
    with pytest.raises(RuntimeError):
        worker.capture_photo()


def test_capture_photo_writes_file(capture_config, tmp_path):
    fake = FakePicamera2()
    worker = CameraWorker(0, "cam0", fake, capture_config)
    worker.configure_mode(CameraMode(width=1920, height=1080, bit_depth=12, framerate=60))
    path = worker.capture_photo()
    assert path.suffix == ".jpg"
    assert str(path).startswith(str(tmp_path / "media"))
    assert len(fake.captured) == 1


def test_recording_state_transitions(capture_config):
    fake = FakePicamera2()
    worker = CameraWorker(
        0,
        "cam0",
        fake,
        capture_config,
        encoder_factory=lambda path: (object(), str(path)),
    )
    worker.configure_mode(CameraMode(width=1920, height=1080, bit_depth=12, framerate=60))

    worker.start_recording()
    assert worker.recording is True
    assert len(fake.encoders) == 1

    path = worker.stop_recording()
    assert worker.recording is False
    assert path is not None
    assert path.suffix == ".h264"
    assert len(fake.encoder_stopped) == 1


def test_stop_recording_when_idle_returns_none(capture_config):
    fake = FakePicamera2()
    worker = CameraWorker(0, "cam0", fake, capture_config)
    assert worker.stop_recording() is None


def test_manager_list_cameras_without_hardware(app_config):
    manager = CameraManager(app_config)
    cameras = manager.list_cameras()
    assert [c.id for c in cameras] == [0, 1]
    assert all(c.modes for c in cameras)


def test_manager_unknown_camera_raises(app_config):
    manager = CameraManager(app_config)
    with pytest.raises(KeyError):
        manager.get_worker(99)


def test_recording_uses_main_stream(capture_config):
    fake = FakePicamera2()
    worker = CameraWorker(
        0,
        "cam0",
        fake,
        capture_config,
        encoder_factory=lambda path: (object(), str(path)),
    )
    worker.configure_mode(CameraMode(width=1920, height=1080, bit_depth=12, framerate=60))
    worker.start_recording()
    assert fake.encoders[0][2] == "main"


def test_stream_subscribe_uses_lores_stream(capture_config):
    fake = FakePicamera2()
    worker = CameraWorker(
        0,
        "cam0",
        fake,
        capture_config,
        mjpeg_encoder_factory=lambda output: (object(), output),
    )
    worker.configure_mode(CameraMode(width=1920, height=1080, bit_depth=12, framerate=60))
    q = worker.subscribe()
    assert len(fake.encoders) == 1
    assert fake.encoders[0][2] == "lores"
    assert worker._stream_output is not None
    assert q in worker._subscribers

    worker.unsubscribe(q)
    assert q not in worker._subscribers


def test_auto_configure_on_capture(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    assert worker.started is False
    worker.capture_photo()
    assert worker.started is True
    assert fake.config["sensor"]["bit_depth"] == 12


def test_set_controls_runtime_for_non_timing(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    fake.controls = None
    worker.set_controls({"ColourGains": [1.5, 1.2], "Brightness": 0.1})
    assert fake.controls["ColourGains"] == (1.5, 1.2)
    assert fake.controls["Brightness"] == 0.1


def test_set_controls_applies_long_exposure_via_reconfigure(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    fake.controls = None
    worker.set_controls(
        {"AeEnable": False, "ExposureTime": 10000000, "FrameDurationLimits": [10000000, 10000000]}
    )
    # Long exposures must be baked via reconfigure so the change does not stall
    # behind ~10 in-flight frames (minutes at a 10s frame rate).
    assert fake.controls is None
    assert fake.config["controls"]["ExposureTime"] == 10000000
    assert fake.config["controls"]["FrameDurationLimits"] == (10000000, 10000000)


def test_configure_mode_sets_framerate_by_default(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    assert fake.config["controls"]["FrameRate"] == 60


def test_configure_mode_omits_framerate_with_manual_frame_duration(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker._controls = {
        "AeEnable": False,
        "FrameDurationLimits": (50000, 50000),
        "ExposureTime": 50000,
    }
    worker.configure_mode(default)
    assert "FrameRate" not in fake.config["controls"]
    assert fake.config["controls"]["FrameDurationLimits"] == (50000, 50000)


def test_set_flip_applies_transform(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.set_flip(hflip=True, vflip=False)
    assert fake.config["transform"] == (True, False)


def test_streaming_output_frame_roundtrip():
    so = _StreamingOutput()
    assert so.next_frame(timeout=0.05) is None
    so.write(b"\xff\xd8jpeg-frame")
    assert so.next_frame(timeout=0.05) == b"\xff\xd8jpeg-frame"
    assert so.next_frame(timeout=0.05) is None


def test_finalize_video_mp4(monkeypatch, tmp_path):
    from imx462_controller.camera.service import _finalize_video

    raw = tmp_path / "clip.h264"
    raw.write_bytes(b"\x00\x00\x00\x01fake")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        raw.with_suffix(".mp4").write_bytes(b"mp4data")

    monkeypatch.setattr("imx462_controller.camera.service.subprocess.run", fake_run)
    result = _finalize_video(raw, "mp4")
    assert result.suffix == ".mp4"
    assert not raw.exists()
    assert calls
    assert calls[0][0] == "ffmpeg"


def test_finalize_video_falls_back_without_ffmpeg(monkeypatch, tmp_path):
    from imx462_controller.camera.service import _finalize_video

    raw = tmp_path / "clip.h264"
    raw.write_bytes(b"x")

    def fake_run(cmd, **kwargs):
        raise OSError("ffmpeg missing")

    monkeypatch.setattr("imx462_controller.camera.service.subprocess.run", fake_run)
    result = _finalize_video(raw, "mp4")
    assert result == raw
    assert raw.exists()


def test_sanitize_controls_strips_none_and_nan():
    from imx462_controller.camera.service import _sanitize_controls

    result = _sanitize_controls(
        {
            "ExposureTime": None,
            "AnalogueGain": float("nan"),
            "Brightness": 0.1,
            "FrameDurationLimits": [None, 33333],
            "ColourGains": [1.5, float("nan")],
        }
    )
    assert "ExposureTime" not in result
    assert "AnalogueGain" not in result
    assert result["Brightness"] == 0.1
    assert result["FrameDurationLimits"] == (33333,)
    assert result["ColourGains"] == (1.5,)


def test_set_controls_ignores_null_values(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    fake.controls = None
    worker.set_controls({"ExposureTime": None, "FrameDurationLimits": [None, None]})
    assert fake.controls is None


def test_set_controls_passes_flicker_period(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    worker.set_controls({"AeFlickerPeriod": 10000})
    assert fake.controls["AeFlickerPeriod"] == 10000


def test_current_settings_reads_metadata(capture_config):
    import time

    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    settings = {}
    for _ in range(50):
        settings = worker.current_settings()
        if settings.get("analogue_gain"):
            break
        time.sleep(0.05)
    assert settings["analogue_gain"] == 2.0
    assert settings["exposure_time"] == 33333


def test_current_settings_empty_when_not_started(capture_config):
    fake = FakePicamera2()
    worker = CameraWorker(0, "cam0", fake, capture_config)
    assert worker.current_settings() == {}


def test_set_controls_with_frame_duration_reconfigures(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    worker.set_controls(
        {
            "AeEnable": False,
            "ExposureTime": 500000,
            "AnalogueGain": 2.0,
            "FrameDurationLimits": [500000, 500000],
        }
    )
    # A frame-duration change is baked via reconfigure, not runtime set_controls.
    assert fake.controls is None
    assert fake.config["controls"]["FrameDurationLimits"] == (500000, 500000)
    assert fake.config["controls"]["ExposureTime"] == 500000


def test_set_controls_without_frame_duration_uses_runtime(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    worker.set_controls({"AeFlickerPeriod": 10000})
    assert fake.controls == {"AeFlickerPeriod": 10000}


def test_current_settings_merges_manual_controls_when_metadata_paused(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    worker.set_controls(
        {
            "AeEnable": False,
            "ExposureTime": 500000,
            "AnalogueGain": 2.5,
            "FrameDurationLimits": [500000, 500000],
        }
    )
    # At >1s frame durations the metadata thread is paused; the applied manual
    # controls must be surfaced instead of stale metadata.
    settings = worker.current_settings()
    assert settings["exposure_time"] == 500000
    assert settings["analogue_gain"] == 2.5


def test_stream_mode_single_stops_encoder(capture_config):
    fake = FakePicamera2()
    default = CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)
    worker = CameraWorker(
        0,
        "cam0",
        fake,
        capture_config,
        default_mode=default,
        mjpeg_encoder_factory=lambda output: (object(), output),
    )
    worker.configure_mode(default)
    worker.subscribe()
    assert len(fake.encoders) == 1

    worker.set_stream_mode("single")
    assert worker.stream_mode == "single"
    assert len(fake.encoder_stopped) == 1

    worker.set_stream_mode("continuous")
    assert worker.stream_mode == "continuous"


def test_snapshot_native(capture_config, tmp_path):
    fake = FakePicamera2()
    default = CameraMode(width=320, height=240, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=default)
    worker.configure_mode(default)
    path = worker.capture_snapshot(exposure_us=2000000, gain=1.0)
    assert path.suffix == ".jpg"
    assert path.exists()
    assert len(fake.captured) == 0
    assert fake.controls["ExposureTime"] == 2000000


def test_snapshot_native_long_exposure(capture_config, tmp_path):
    fake = FakePicamera2()
    small = CameraMode(width=320, height=240, bit_depth=12, framerate=60)
    worker = CameraWorker(0, "cam0", fake, capture_config, default_mode=small)
    worker.configure_mode(small)
    path = worker.capture_snapshot(exposure_us=30000000, gain=1.0)
    assert path.suffix == ".jpg"
    assert path.exists()
    assert fake.controls["ExposureTime"] == 30000000

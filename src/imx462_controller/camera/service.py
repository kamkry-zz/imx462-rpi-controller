"""Camera enumeration, per-camera worker threads, and capture.

Picamera2/libcamera must stay in a single process, so each camera gets its own
worker thread; blocking capture releases the GIL. ``picamera2`` is imported
lazily so this module is importable (and testable) on machines without it.

Stream layout per camera:
- ``main`` (YUV420, full res) -> stills (``capture_file``) and H.264 recording.
- ``lores`` (YUV420, downscaled) -> always-on MJPEG live view (hardware encoder).
This keeps live view and recording/photo capture independent on the same camera.
"""

from __future__ import annotations

import io
import logging
import math
import queue
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import AppConfig, CaptureConfig, DefaultMode
from ..otel import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer("imx462_controller.camera")

# The IMX290/IMX462 exposes single-frame exposures up to ~115 s natively (24-bit
# VMAX plus adjustable HMAX), so no software stacking is required for the 1-30 s
# ladder offered by the UI.
MIN_FRAME_US = 16_666  # 1/60 s


def _sanitize_controls(controls: dict[str, Any]) -> dict[str, Any]:
    """Drop None/NaN values so a bad payload can never stall the sensor."""
    clean: dict[str, Any] = {}
    for key, value in controls.items():
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        if isinstance(value, (list, tuple)):
            filtered = [v for v in value if v is not None and not (isinstance(v, float) and math.isnan(v))]
            if not filtered:
                continue
            value = tuple(filtered)
        clean[key] = value
    return clean


def _yuv420_to_rgb_full(yuv: Any, width: int, height: int) -> Any:
    """Convert a planar YUV420 (I420) buffer to a full-resolution RGB array.

    Uses the same plane layout as ``picamera2.converters.YUV420_to_RGB`` (Y, then
    U, then V packed tightly), but upsamples chroma to full resolution instead of
    subsampling luma.
    """
    import numpy as np

    w, h = width, height
    w2, h2 = w // 2, h // 2
    n = w * h
    n2 = n // 2
    n4 = n // 4
    flat = np.ascontiguousarray(yuv).ravel()
    y_plane = flat[:n].reshape(h, w).astype(np.float32)
    u_plane = flat[n : n + n4].reshape(h2, w2).astype(np.float32) - 128.0
    v_plane = flat[n + n4 : n + n2].reshape(h2, w2).astype(np.float32) - 128.0

    u_full = np.repeat(np.repeat(u_plane, 2, axis=0), 2, axis=1)
    v_full = np.repeat(np.repeat(v_plane, 2, axis=0), 2, axis=1)

    r = y_plane + 1.402 * v_full
    g = y_plane - 0.344 * u_full - 0.714 * v_full
    b = y_plane + 1.772 * u_full
    return np.stack([r, g, b], axis=-1).clip(0, 255).astype(np.uint8)


@dataclass
class CameraMode:
    width: int
    height: int
    bit_depth: int
    framerate: int


@dataclass
class CameraInfo:
    id: int
    name: str
    model: str = ""
    modes: list[CameraMode] = field(default_factory=list)


class _StreamingOutput(io.BufferedIOBase):
    """Accumulates MJPEG encoder frames for consumption by an HTTP stream."""

    def __init__(self) -> None:
        self.frame: bytes | None = None
        self._condition = threading.Condition()
        self._seq = 0
        self._consumed_seq = 0

    def write(self, buf: Any) -> int:
        with self._condition:
            self.frame = buf
            self._seq += 1
            self._condition.notify_all()
        return len(buf)

    def next_frame(self, timeout: float = 5.0) -> bytes | None:
        """Return the next frame once, blocking until one arrives (or timeout)."""
        with self._condition:
            while self._seq == self._consumed_seq:
                self._condition.wait(timeout)
                if self._seq == self._consumed_seq:
                    return None
            self._consumed_seq = self._seq
            return self.frame


def _lores_size(width: int, height: int) -> tuple[int, int]:
    lw, lh = min(width, 1280), min(height, 720)
    if (lw, lh) == (width, height):
        lw, lh = width // 2, height // 2
    return lw, lh


def _transform(hflip: bool, vflip: bool) -> Any:
    """Build a libcamera transform (falls back to a tuple without libcamera)."""
    try:
        import libcamera

        return libcamera.Transform(hflip=hflip, vflip=vflip)
    except ImportError:
        return (hflip, vflip)


class CameraWorker:
    """Owns a single Picamera2 instance and serialises operations with a lock."""

    def __init__(
        self,
        camera_id: int,
        name: str,
        picam2: Any,
        capture: CaptureConfig,
        default_mode: CameraMode | None = None,
        encoder_factory: Any = None,
        mjpeg_encoder_factory: Any = None,
    ) -> None:
        self._id = camera_id
        self._name = name
        self._picam2 = picam2
        self._output_dir = Path(capture.output_dir)
        self._photo_format = capture.photo_format
        self._video_format = capture.video_format
        self._default_mode = default_mode
        self._encoder_factory = encoder_factory or _default_encoder_factory
        self._mjpeg_encoder_factory = mjpeg_encoder_factory or _default_mjpeg_encoder_factory
        self._lock = threading.RLock()
        self._started = False
        self._recording = False
        self._mode: CameraMode | None = None
        self._controls: dict[str, Any] = {}
        self._hflip = False
        self._vflip = False
        self._video_encoder: Any = None
        self._recording_raw_path: Path | None = None
        self._stream_output: _StreamingOutput | None = None
        self._mjpeg_encoder: Any = None
        self._subscribers: list[queue.Queue] = []
        self._feed_thread: threading.Thread | None = None
        self._feed_stop = threading.Event()
        self._stream_mode = "continuous"
        self._capturing = False
        self._metadata: dict[str, Any] = {}
        self._metadata_lock = threading.Lock()
        self._metadata_stop = threading.Event()
        self._metadata_thread = threading.Thread(
            target=self._metadata_loop, daemon=True, name=f"settings-{self._name}"
        )
        self._metadata_thread.start()

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def started(self) -> bool:
        return self._started

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    @property
    def stream_mode(self) -> str:
        return self._stream_mode

    def _ensure_output_dir(self) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_started(self) -> None:
        """Auto-configure the camera with the default mode if not yet started."""
        if not self._started:
            if self._default_mode is None:
                raise RuntimeError(f"Camera {self._name} has no default mode")
            self.configure_mode(self._default_mode)

    def configure_mode(self, mode: CameraMode) -> None:
        """(Re)configure the sensor and start the camera."""
        with self._lock, tracer.start_as_current_span("camera.configure_mode"):
            self._teardown_encoders()
            if self._started:
                self._picam2.stop()
            lw, lh = _lores_size(mode.width, mode.height)
            controls = dict(self._controls)
            if controls.get("AeEnable"):
                # Auto exposure controls the exposure/gain itself; a stale
                # ExposureTime (e.g. from a previous long single-frame snapshot)
                # would conflict with the frame duration in the config.
                controls.pop("ExposureTime", None)
                controls.pop("AnalogueGain", None)
            if "FrameDurationLimits" not in controls:
                controls["FrameRate"] = mode.framerate
            config = self._picam2.create_video_configuration(
                main={"size": (mode.width, mode.height), "format": "YUV420"},
                lores={"size": (lw, lh), "format": "YUV420"},
                sensor={"output_size": (mode.width, mode.height), "bit_depth": mode.bit_depth},
                controls=controls,
                transform=_transform(self._hflip, self._vflip),
            )
            self._picam2.configure(config)
            self._picam2.start()
            self._started = True
            self._mode = mode
            logger.info("Camera %s configured: %s", self._name, mode)
            if self._subscribers:
                self._ensure_stream_encoder()

    def set_flip(self, hflip: bool, vflip: bool) -> None:
        """Apply a horizontal/vertical flip and reconfigure the camera."""
        with self._lock, tracer.start_as_current_span("camera.set_flip"):
            if (hflip, vflip) == (self._hflip, self._vflip) and self._started:
                return
            self._hflip = hflip
            self._vflip = vflip
            if self._started and self._mode is not None:
                self.configure_mode(self._mode)
            else:
                self._ensure_started()

    def set_controls(self, controls: dict[str, Any]) -> None:
        """Apply libcamera controls at runtime without disturbing the stream.

        Controls are stored so a later mode change re-applies them, and applied
        immediately via ``set_controls`` (no reconfigure, so live view keeps
        flowing). Frame-duration changes are sent explicitly by the frontend.
        """
        with self._lock, tracer.start_as_current_span("camera.set_controls"):
            normalized = _sanitize_controls(controls)
            if not normalized:
                return
            self._controls.update(normalized)
            if not self._started:
                self._ensure_started()
            else:
                self._picam2.set_controls(normalized)
            logger.info("Camera %s controls set: %s", self._name, normalized)

    def current_settings(self) -> dict[str, Any]:
        """Return the latest gain/exposure read by the background metadata thread."""
        return dict(self._metadata)

    def _metadata_loop(self) -> None:
        """Continuously read current gain/exposure (never blocks callers).

        A single dedicated thread performs the blocking ``capture_metadata`` call
        so a stalled sensor or a long exposure can never stall the rest of the app
        (and never leaks a queued capture job).
        """
        while not self._metadata_stop.wait(0.2):
            limits = self._controls.get("FrameDurationLimits")
            frame_us = limits[0] if limits else MIN_FRAME_US
            if frame_us > 1_000_000:
                # Slow frame rate: a metadata read would block for the whole
                # frame duration and stall the next snapshot. Skip until the
                # camera is back to a fast frame rate.
                continue
            with self._metadata_lock:
                if self._capturing or not self._started or self._recording:
                    continue
                try:
                    md = self._picam2.capture_metadata()
                except Exception as exc:  # noqa: BLE001 - transient during reconfig/stall
                    logger.debug("Metadata read failed: %s", exc)
                    continue
                self._metadata = {
                    "analogue_gain": float(md.get("AnalogueGain", 0.0)),
                    "exposure_time": int(md.get("ExposureTime", 0)),
                }

    def _teardown_encoders(self) -> None:
        self._stop_stream_encoder()
        if self._video_encoder is not None:
            self._picam2.stop_encoder(self._video_encoder)
            self._video_encoder = None
        self._recording = False
        self._recording_raw_path = None

    def _new_filename(self, ext: str) -> Path:
        self._ensure_output_dir()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self._output_dir / f"{self._name}_{stamp}_{uuid.uuid4().hex[:8]}.{ext}"

    def capture_photo(self) -> Path:
        """Capture a still image and return its path."""
        with self._lock, tracer.start_as_current_span("camera.capture_photo"):
            self._ensure_started()
            path = self._new_filename(self._photo_format)
            self._picam2.capture_file(str(path))
            logger.info("Photo captured: %s", path)
            return path

    def set_stream_mode(self, mode: str) -> None:
        """Switch between continuous MJPEG live view and single-frame (at-rest) mode."""
        with self._lock, tracer.start_as_current_span("camera.set_stream_mode"):
            mode = "single" if mode == "single" else "continuous"
            if mode == self._stream_mode:
                return
            self._stream_mode = mode
            if mode == "single":
                self._stop_stream_encoder()
            elif self._started and self._mode is not None:
                # Reconfigure so any pending exposure change (e.g. leaving a
                # long single-frame exposure) applies immediately instead of
                # lagging ~10 in-flight frames. configure_mode re-bakes
                # self._controls and restarts the encoder for subscribers.
                self.configure_mode(self._mode)
            logger.info("Camera %s stream mode: %s", self._name, mode)

    def capture_snapshot(self, exposure_us: int, gain: float = 1.0) -> Path:
        """Capture a single still with the requested exposure and return its path.

        The exposure is applied by reconfiguring the camera rather than runtime
        ``set_controls``: libcamera applies runtime control changes only after
        several in-flight frames have completed, which at long exposures means
        minutes. A reconfigure bakes the exposure into the camera configuration,
        so the first frame captured is already at the requested exposure.
        """
        with self._lock, tracer.start_as_current_span("camera.capture_snapshot"):
            self._ensure_started()
            import numpy as np
            from PIL import Image

            with self._metadata_lock:
                self._capturing = True
                try:
                    self._apply_snapshot_exposure(exposure_us, gain)
                    if self._mode is not None:
                        self.configure_mode(self._mode)
                    frame = self._capture_fresh_frame(exposure_us)
                finally:
                    self._capturing = False

            width = self._mode.width if self._mode else 1920
            height = self._mode.height if self._mode else 1080
            rgb = _yuv420_to_rgb_full(frame.astype(np.float32), width, height)
            path = self._new_filename(self._photo_format)
            Image.fromarray(rgb).save(str(path), quality=95)
            logger.info("Snapshot captured (%d µs): %s", exposure_us, path)
            return path

    def _capture_fresh_frame(self, target_us: int) -> Any:
        """Return the first frame whose exposure matches the requested value.

        Frames buffered at the previous frame rate are discarded so the result
        reflects the requested exposure rather than a stale short exposure.
        """
        tolerance = max(target_us * 0.15, 1000)
        frames, md = self._picam2.capture_arrays(["main"])
        for _ in range(11):
            if abs(int(md.get("ExposureTime", 0)) - target_us) <= tolerance:
                return frames[0]
            frames, md = self._picam2.capture_arrays(["main"])
        return frames[0]

    def _apply_snapshot_exposure(self, exposure_us: int, gain: float) -> None:
        frame = max(exposure_us, MIN_FRAME_US)
        controls = {
            "AeEnable": False,
            "ExposureTime": exposure_us,
            "FrameDurationLimits": (frame, frame),
            "AnalogueGain": gain,
        }
        self._controls.update(controls)
        self._picam2.set_controls(controls)

    def start_recording(self) -> None:
        with self._lock, tracer.start_as_current_span("camera.start_recording"):
            if self._recording:
                return
            self._ensure_started()
            raw_path = self._new_filename("h264")
            encoder, output = self._encoder_factory(raw_path)
            self._picam2.start_encoder(encoder, output, name="main")
            self._video_encoder = encoder
            self._recording = True
            self._recording_raw_path = raw_path
            logger.info("Recording started: %s", raw_path)

    def stop_recording(self) -> Path | None:
        with self._lock, tracer.start_as_current_span("camera.stop_recording"):
            if not self._recording:
                return None
            self._picam2.stop_encoder(self._video_encoder)
            self._video_encoder = None
            self._recording = False
            raw_path = self._recording_raw_path
            self._recording_raw_path = None
            if raw_path is None:
                return None
            path = _finalize_video(raw_path, self._video_format)
            logger.info("Recording stopped: %s", path)
            return path

    def subscribe(self) -> queue.Queue:
        """Register a live-view client; returns a queue of MJPEG frames."""
        with self._lock:
            self._ensure_started()
            self._ensure_stream_encoder()
            q: queue.Queue = queue.Queue(maxsize=2)
            self._subscribers.append(q)
            return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """Remove a live-view client."""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _ensure_stream_encoder(self) -> None:
        if self._stream_mode != "continuous":
            return
        if self._mjpeg_encoder is not None:
            return
        self._stream_output = _StreamingOutput()
        encoder, output = self._mjpeg_encoder_factory(self._stream_output)
        self._picam2.start_encoder(encoder, output, name="lores")
        self._mjpeg_encoder = encoder
        self._feed_stop.clear()
        self._feed_thread = threading.Thread(
            target=self._feed_loop, daemon=True, name=f"mjpeg-feed-{self._name}"
        )
        self._feed_thread.start()

    def _feed_loop(self) -> None:
        while not self._feed_stop.is_set():
            output = self._stream_output
            if output is None:
                time.sleep(0.1)
                continue
            frame = output.next_frame(timeout=1.0)
            if frame is None:
                continue
            with self._lock:
                for q in list(self._subscribers):
                    try:
                        q.put_nowait(frame)
                    except queue.Full:
                        pass

    def _stop_stream_encoder(self) -> None:
        self._feed_stop.set()
        if self._mjpeg_encoder is not None:
            try:
                self._picam2.stop_encoder(self._mjpeg_encoder)
            except Exception as exc:  # noqa: BLE001 - encoder may already be stopped
                logger.warning("MJPEG encoder stop failed: %s", exc)
            self._mjpeg_encoder = None
        self._stream_output = None

    def close(self) -> None:
        self._metadata_stop.set()
        with self._lock:
            if self._started:
                self._teardown_encoders()
                self._picam2.stop()
                self._started = False


class CameraManager:
    """Discovers cameras and owns a worker thread per camera."""

    def __init__(
        self,
        config: AppConfig,
        picam2_factory: Any = None,
        encoder_factory: Any = None,
        mjpeg_encoder_factory: Any = None,
    ) -> None:
        self._config = config
        self._picam2_factory = picam2_factory or _default_picam2_factory
        self._encoder_factory = encoder_factory
        self._mjpeg_encoder_factory = mjpeg_encoder_factory
        self._workers: dict[int, CameraWorker] = {}
        self._executor = ThreadPoolExecutor(max_workers=max(1, len(config.cameras)))
        self._started_at = time.time()
        self._settings: dict[int, dict[str, Any]] = {}
        self._settings_stop = threading.Event()
        self._settings_thread = threading.Thread(
            target=self._settings_loop, daemon=True, name="camera-settings"
        )
        self._settings_thread.start()

    def _settings_loop(self) -> None:
        """Periodically read current gain/exposure for the status payload."""
        while not self._settings_stop.wait(2.0):
            for cam_id, worker in list(self._workers.items()):
                self._settings[cam_id] = worker.current_settings()

    def discover(self) -> list[CameraInfo]:
        """Enumerate connected cameras (cam0/cam1) and their supported modes."""
        infos: list[CameraInfo] = []
        try:
            from picamera2 import Picamera2

            global_info = Picamera2.global_camera_info()
        except Exception as exc:  # noqa: BLE001 - camera hardware may be absent
            logger.warning("Camera enumeration failed: %s", exc)
            global_info = []

        by_num = {entry.get("Num"): entry for entry in global_info if isinstance(entry, dict)}

        for cam in self._config.cameras:
            entry = by_num.get(cam.id, {})
            infos.append(
                CameraInfo(
                    id=cam.id,
                    name=cam.name,
                    model=entry.get("Model", ""),
                    modes=_default_modes(self._config.default_mode),
                )
            )
        return infos

    def list_cameras(self) -> list[CameraInfo]:
        return self.discover()

    def get_worker(self, camera_id: int) -> CameraWorker:
        """Return (creating if necessary) the worker for a configured camera."""
        cam = next((c for c in self._config.cameras if c.id == camera_id), None)
        if cam is None:
            raise KeyError(f"Camera {camera_id} is not configured")
        if camera_id not in self._workers:
            picam2 = self._picam2_factory(camera_id)
            default_mode = CameraMode(
                width=self._config.default_mode.width,
                height=self._config.default_mode.height,
                bit_depth=self._config.default_mode.bit_depth,
                framerate=self._config.default_mode.framerate,
            )
            worker = CameraWorker(
                camera_id,
                cam.name,
                picam2,
                self._config.capture,
                default_mode=default_mode,
                encoder_factory=self._encoder_factory,
                mjpeg_encoder_factory=self._mjpeg_encoder_factory,
            )
            self._workers[camera_id] = worker
        return self._workers[camera_id]

    def configure(self, camera_id: int, mode: CameraMode) -> None:
        worker = self.get_worker(camera_id)
        self._executor.submit(worker.configure_mode, mode).result()

    def set_controls(self, camera_id: int, controls: dict[str, Any]) -> None:
        worker = self.get_worker(camera_id)
        self._executor.submit(worker.set_controls, controls).result()

    def set_flip(self, camera_id: int, hflip: bool, vflip: bool) -> None:
        worker = self.get_worker(camera_id)
        self._executor.submit(worker.set_flip, hflip, vflip).result()

    def output_dir(self, camera_id: int) -> Path:
        return self.get_worker(camera_id).output_dir

    def capture_photo(self, camera_id: int) -> Path:
        worker = self.get_worker(camera_id)
        return self._executor.submit(worker.capture_photo).result()

    def set_stream_mode(self, camera_id: int, mode: str) -> None:
        worker = self.get_worker(camera_id)
        self._executor.submit(worker.set_stream_mode, mode).result()

    def capture_snapshot(self, camera_id: int, exposure_us: int, gain: float) -> Path:
        worker = self.get_worker(camera_id)
        return self._executor.submit(worker.capture_snapshot, exposure_us, gain).result()

    def start_recording(self, camera_id: int) -> None:
        worker = self.get_worker(camera_id)
        self._executor.submit(worker.start_recording).result()

    def stop_recording(self, camera_id: int) -> Path | None:
        worker = self.get_worker(camera_id)
        return self._executor.submit(worker.stop_recording).result()

    def status(self) -> dict[str, Any]:
        return {
            "uptime_seconds": round(time.time() - self._started_at, 1),
            "cameras": [
                {
                    "id": cam.id,
                    "name": cam.name,
                    "recording": (
                        self._workers[cam.id].recording if cam.id in self._workers else False
                    ),
                    "started": self._workers[cam.id].started if cam.id in self._workers else False,
                    "configured": cam.id in self._workers,
                }
                for cam in self._config.cameras
            ],
            "settings": {str(k): v for k, v in self._settings.items()},
        }

    def close(self) -> None:
        self._settings_stop.set()
        for worker in self._workers.values():
            worker.close()
        self._executor.shutdown(wait=False)


def _default_picam2_factory(camera_id: int) -> Any:
    from picamera2 import Picamera2

    return Picamera2(camera_num=camera_id)


def _finalize_video(raw_path: Path, video_format: str) -> Path:
    """Remux raw H.264 to a container format (mp4) when requested.

    Falls back to the raw ``.h264`` file if remuxing is unavailable.
    """
    if video_format != "mp4":
        return raw_path
    final_path = raw_path.with_suffix(".mp4")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(final_path),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("ffmpeg remux failed (%s); keeping raw H.264", exc)
        return raw_path
    raw_path.unlink(missing_ok=True)
    return final_path


def _default_encoder_factory(path: Path) -> tuple[Any, Any]:
    """Build an H.264 encoder and file output for recording."""
    from picamera2.encoders import H264Encoder
    from picamera2.outputs import FileOutput

    return H264Encoder(), FileOutput(str(path))


def _default_mjpeg_encoder_factory(output: Any) -> tuple[Any, Any]:
    """Build an MJPEG encoder and file output bound to the streaming buffer."""
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput

    return MJPEGEncoder(), FileOutput(output)


def _default_modes(mode: DefaultMode) -> list[CameraMode]:
    return [
        CameraMode(width=1280, height=720, bit_depth=10, framerate=60),
        CameraMode(width=1280, height=720, bit_depth=12, framerate=60),
        CameraMode(width=1920, height=1080, bit_depth=10, framerate=60),
        CameraMode(width=1920, height=1080, bit_depth=12, framerate=60),
    ]

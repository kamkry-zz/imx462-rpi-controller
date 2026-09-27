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

from ..config import AppConfig, CaptureConfig
from ..otel import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer("imx462_controller.camera")

# The IMX290/IMX462 exposes single-frame exposures up to ~115 s natively (24-bit
# VMAX plus adjustable HMAX), so no software stacking is required for the 1-30 s
# ladder offered by the UI.
MIN_FRAME_US = 16_666  # 1/60 s
IMX290_MAX_EXPOSURE_US = 115_686_258  # sensor max (~115.7 s), used as a fallback bound

# libcamera autofocus control values (enum ordinals), passed as integers so the
# service stays importable without libcamera — mirrors the transform fallback.
AF_MODE_MANUAL = 0
AF_MODE_AUTO = 1
AF_MODE_CONTINUOUS = 2
AF_TRIGGER_START = 0
AF_TRIGGER_CANCEL = 1
AF_MODE_VALUES = {
    "manual": AF_MODE_MANUAL,
    "auto": AF_MODE_AUTO,
    "continuous": AF_MODE_CONTINUOUS,
}
AF_RANGE_VALUES = {"normal": 0, "macro": 1, "full": 2}
AF_SPEED_VALUES = {"normal": 0, "fast": 1}
# libcamera AfState metadata ordinals -> stable API strings.
AF_STATE_NAMES = {0: "idle", 1: "scanning", 2: "focused", 3: "failed"}
AF_STATE_FOCUSED = 2
AF_STATE_FAILED = 3

# Frame durations above this (µs) are too slow for a practical autofocus sweep:
# an explicit trigger runs an "AF-assist" (temporarily switching to a fast,
# auto-exposure configuration) instead, and periodic refocus is skipped. 0.2 s
# ≈ 5 fps; an AF sweep of several coarse steps needs frames to converge.
AF_ASSIST_THRESHOLD_US = 200_000


def _min_frame_us(mode: CameraMode | None) -> int:
    """Minimum frame duration (us) for a mode, derived from its framerate.

    Fast sensors (imx290 @ 60 fps) floor at ~1/60 s; low-framerate sensors such
    as the imx415 (~15 fps full-array readout on 2-lane csi platforms) need a
    ~67 ms floor — a fixed 1/60 s assumption would request an out-of-range
    ``FrameDurationLimits`` from libcamera.
    """
    if mode is None or mode.framerate <= 0:
        return MIN_FRAME_US
    return math.ceil(1_000_000 / mode.framerate)

# Fixed bitrate for the always-on MJPEG live view. Pinned (instead of picamera2's
# framerate-scaled default) so low-framerate sensor modes (e.g. imx708 4K at
# ~14 fps) do not collapse the bitrate and cause macroblocking in the live feed.
MJPEG_BITRATE = 20_000_000


def _coerce_frame_duration_limits(value: Any) -> tuple[int, int] | None:
    """Validate a ``FrameDurationLimits`` payload as a pair of integer µs values.

    Returns ``None`` for anything malformed (scalar, wrong length, non-numeric)
    so a bad client payload can never crash control application or reconfigure.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        low, high = (float(entry) for entry in value)
    except (TypeError, ValueError):
        return None
    if math.isnan(low) or math.isnan(high):
        return None
    return int(low), int(high)


def _is_missing(value: Any) -> bool:
    """True for values that must never reach libcamera (``None``/NaN)."""
    return value is None or (isinstance(value, float) and math.isnan(value))


def _sanitize_control_value(key: str, value: Any) -> Any:
    """Return the sanitized value for one control, or ``None`` to drop it."""
    if key == "FrameDurationLimits":
        return _coerce_frame_duration_limits(value)
    if _is_missing(value):
        return None
    if isinstance(value, (list, tuple)):
        filtered = tuple(entry for entry in value if not _is_missing(entry))
        return filtered or None
    return value


def _sanitize_controls(controls: dict[str, Any]) -> dict[str, Any]:
    """Drop None/NaN values and malformed limits so a bad payload never crashes."""
    clean: dict[str, Any] = {}
    for key, value in controls.items():
        sanitized = _sanitize_control_value(key, value)
        if sanitized is not None:
            clean[key] = sanitized
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
    bit_depth: int | None = None
    framerate: int = 60


@dataclass
class CameraCapabilities:
    """Per-sensor capabilities surfaced to the UI and external clients."""

    modes: list[CameraMode] = field(default_factory=list)
    exposure_min_us: int = MIN_FRAME_US
    exposure_max_us: int = IMX290_MAX_EXPOSURE_US
    gain_min: float = 1.0
    gain_max: float = 31.6
    # Minimum frame duration (us) of the camera's configured default mode (or
    # of its fastest advertised mode when no default is known) — the safe floor
    # clients that never switch modes can request FrameDurationLimits at.
    # Low-framerate sensors (imx415, default 4K @ 15 fps) report ~66 667 µs;
    # 60 fps sensors report ~16 667 µs.
    min_frame_duration_us: int = MIN_FRAME_US
    supports_manual_exposure: bool = True
    supports_raw12: bool = True
    # Autofocus (actuator) support. False for sensors with no VCM (e.g. imx290);
    # True for the Camera Module 3 (imx708). ``lens_position`` bounds are in
    # dioptres (0 = infinity) and only meaningful when manual focus is supported.
    supports_autofocus: bool = False
    supports_manual_focus: bool = False
    lens_position_min: float | None = None
    lens_position_max: float | None = None
    lens_position_default: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "modes": [m.__dict__ for m in self.modes],
            "exposure_min_us": self.exposure_min_us,
            "exposure_max_us": self.exposure_max_us,
            "gain_min": self.gain_min,
            "gain_max": self.gain_max,
            "min_frame_duration_us": self.min_frame_duration_us,
            "supports_manual_exposure": self.supports_manual_exposure,
            "supports_raw12": self.supports_raw12,
            "supports_autofocus": self.supports_autofocus,
            "supports_manual_focus": self.supports_manual_focus,
            "lens_position_min": self.lens_position_min,
            "lens_position_max": self.lens_position_max,
            "lens_position_default": self.lens_position_default,
        }

    def copy(self) -> CameraCapabilities:
        """Return a copy with its own modes list, for per-read adjustments."""
        return CameraCapabilities(
            modes=list(self.modes),
            exposure_min_us=self.exposure_min_us,
            exposure_max_us=self.exposure_max_us,
            gain_min=self.gain_min,
            gain_max=self.gain_max,
            min_frame_duration_us=self.min_frame_duration_us,
            supports_manual_exposure=self.supports_manual_exposure,
            supports_raw12=self.supports_raw12,
            supports_autofocus=self.supports_autofocus,
            supports_manual_focus=self.supports_manual_focus,
            lens_position_min=self.lens_position_min,
            lens_position_max=self.lens_position_max,
            lens_position_default=self.lens_position_default,
        )


@dataclass
class CameraInfo:
    id: int
    name: str
    model: str = ""
    modes: list[CameraMode] = field(default_factory=list)
    default_mode: CameraMode | None = None
    capabilities: CameraCapabilities | None = None


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


# Static fallback catalogs keyed by libcamera sensor model. These are used only
# when libcamera is unavailable (no hardware, tests) or a camera has not yet
# been opened; the authoritative source is ``read_capabilities``, which reads
# ``Picamera2.sensor_modes`` / ``Picamera2.camera_controls`` at runtime.

_MODEL_MODES: dict[str, list[CameraMode]] = {
    "imx290": [  # IMX462 via the imx290 overlay
        CameraMode(width=1280, height=720, bit_depth=10, framerate=60),
        CameraMode(width=1280, height=720, bit_depth=12, framerate=60),
        CameraMode(width=1920, height=1080, bit_depth=10, framerate=60),
        CameraMode(width=1920, height=1080, bit_depth=12, framerate=60),
    ],
    "imx708": [  # Camera Module 3 / 3 Wide (10-bit only)
        CameraMode(width=1536, height=864, framerate=60),
        CameraMode(width=2304, height=1296, framerate=30),
        CameraMode(width=4608, height=2592, framerate=15),
    ],
    "imx219": [
        CameraMode(width=1920, height=1080, framerate=30),
        CameraMode(width=3280, height=2464, framerate=15),
    ],
    "imx477": [
        CameraMode(width=2028, height=1080, framerate=50),
        CameraMode(width=4056, height=3040, framerate=10),
    ],
    "ov5647": [
        CameraMode(width=1920, height=1080, framerate=30),
        CameraMode(width=2592, height=1944, framerate=15),
    ],
    "imx296": [CameraMode(width=1456, height=1088, framerate=60)],
    "imx415": [  # Inno Maker CAM-MIPI-IMX415 (RAW10 only)
        # Full-array 3864x2192 readout; 2-lane csi platforms (Pi 3/4, Zero 2 W)
        # are bandwidth-bound to ~15-17 fps at any output size, so the 30 fps
        # profile only reaches its rate on a 4-lane port (Pi 5 CAM1 with the
        # `4lane` overlay param); elsewhere libcamera clamps to the 2-lane
        # ceiling.
        CameraMode(width=3840, height=2160, framerate=15),
        CameraMode(width=3840, height=2160, framerate=30),
    ],
}

# (exposure_min_us, exposure_max_us, gain_min, gain_max) fallback bounds. These
# are approximations for sensors other than the IMX462; on real hardware the
# values are read from libcamera and override these.
_MODEL_BOUNDS: dict[str, tuple[int, int, float, float]] = {
    "imx290": (MIN_FRAME_US, IMX290_MAX_EXPOSURE_US, 1.0, 31.6),
    "imx708": (MIN_FRAME_US, 1_000_000, 1.0, 16.0),
    "imx219": (MIN_FRAME_US, 6_000_000, 1.0, 12.0),
    "imx477": (MIN_FRAME_US, 200_000_000, 1.0, 16.0),
    "ov5647": (MIN_FRAME_US, 6_000_000, 1.0, 8.0),
    "imx296": (MIN_FRAME_US, 100_000, 1.0, 16.0),
    # IMX415: 30 dB max gain (0.3 dB x 100 steps) ~= ISO 3160; the 30 s exposure
    # ceiling mirrors the UI ladder (20-bit VMAX permits much more; runtime
    # libcamera reads override these approximations anyway).
    "imx415": (MIN_FRAME_US, 30_000_000, 1.0, 31.6),
}

# (supports_autofocus, supports_manual_focus, lens_min, lens_max, lens_default)
# fallback focus capabilities keyed by sensor model. Only the Camera Module 3
# (imx708) carries a VCM actuator; every other supported sensor has none. On
# real hardware the runtime ``camera_controls`` read overrides these.
_MODEL_FOCUS: dict[str, tuple[bool, bool, float, float, float]] = {
    "imx708": (True, True, 0.0, 32.0, 1.0),
}


def _bit_depth_from_format(fmt: Any) -> int | None:
    """Extract 10/12 from a libcamera format string like ``SRGGB12_CSI2P``."""
    import re

    match = re.search(r"(\d+)", str(fmt))
    if not match:
        return None
    depth = int(match.group(1))
    return depth if depth in (10, 12) else None


def _fps_bounds(fps: Any) -> tuple[float, float]:
    if isinstance(fps, (tuple, list)) and len(fps) >= 2:
        return float(fps[0]), float(fps[1])
    if isinstance(fps, (int, float)):
        return float(fps), float(fps)
    return 0.0, 0.0


def _pick_framerate(fps: Any) -> int:
    _lo, hi = _fps_bounds(fps)
    for rate in (60, 30, 15):
        if rate <= hi:
            return rate
    return max(1, int(hi))


def _read_sensor_modes(picam2: Any) -> list[CameraMode]:
    """Read supported modes from ``Picamera2.sensor_modes``.

    ``bit_depth`` is only populated for sensors that expose a RAW10/RAW12
    selector (multiple bit depths); other sensors (e.g. IMX708) leave it
    ``None`` so ``configure_mode`` omits the field.
    """
    raw_modes = getattr(picam2, "sensor_modes", None) or []
    depths = {_bit_depth_from_format(m.get("format")) for m in raw_modes}
    depths.discard(None)
    multi_depth = len(depths) > 1
    modes: list[CameraMode] = []
    for m in raw_modes:
        size = m.get("size")
        if not size or len(size) < 2:
            continue
        width, height = int(size[0]), int(size[1])
        bit_depth = _bit_depth_from_format(m.get("format")) if multi_depth else None
        modes.append(
            CameraMode(width=width, height=height, bit_depth=bit_depth, framerate=_pick_framerate(m.get("fps")))
        )
    return modes


def _min_frame_across(modes: list[CameraMode]) -> int:
    """Smallest minimum frame duration (us) over the advertised modes."""
    if not modes:
        return MIN_FRAME_US
    return min(_min_frame_us(mode) for mode in modes)


def _min_frame_for(default_mode: CameraMode | None, modes: list[CameraMode]) -> int:
    """Frame-duration floor advertised in capabilities.

    Prefers the configured default mode (the one the camera runs unless a
    client changes it); falls back to the fastest advertised mode when no
    default is known. Clients that never switch modes (e.g. cat-watcher) can
    floor their ``FrameDurationLimits`` at this value safely.
    """
    if default_mode is not None:
        return _min_frame_us(default_mode)
    return _min_frame_across(modes)


def _apply_control_bounds(caps: CameraCapabilities, controls: dict[str, Any]) -> None:
    """Overwrite exposure/gain/focus bounds in ``caps`` from libcamera control info."""
    exposure = controls.get("ExposureTime")
    if isinstance(exposure, (tuple, list)) and len(exposure) >= 2:
        caps.exposure_min_us = int(exposure[0])
        caps.exposure_max_us = int(exposure[1])
    gain = controls.get("AnalogueGain")
    if isinstance(gain, (tuple, list)) and len(gain) >= 2:
        caps.gain_min = float(gain[0])
        caps.gain_max = float(gain[1])
    caps.supports_manual_exposure = "ExposureTime" in controls and "AnalogueGain" in controls
    # Focus support is only ever *added* here (never cleared), so the static
    # per-model fallback survives a runtime read whose control map is sparse.
    if "AfMode" in controls or "AfTrigger" in controls:
        caps.supports_autofocus = True
    lens = controls.get("LensPosition")
    if lens is not None:
        caps.supports_manual_focus = True
        if isinstance(lens, (tuple, list)) and len(lens) >= 2:
            caps.lens_position_min = float(lens[0])
            caps.lens_position_max = float(lens[1])
            if len(lens) >= 3:
                caps.lens_position_default = float(lens[2])


def read_capabilities(picam2: Any, default_mode: CameraMode | None = None) -> CameraCapabilities:
    """Read authoritative capabilities (modes + control bounds) from libcamera."""
    caps = CameraCapabilities(modes=_read_sensor_modes(picam2))
    controls = getattr(picam2, "camera_controls", None) or {}
    _apply_control_bounds(caps, controls)
    caps.min_frame_duration_us = _min_frame_for(default_mode, caps.modes)
    caps.supports_raw12 = any(m.bit_depth == 12 for m in caps.modes)
    return caps


def _modes_for_model(model: str, default_mode: CameraMode | None = None) -> list[CameraMode]:
    for key, modes in _MODEL_MODES.items():
        if model and key in model.lower():
            return list(modes)
    if default_mode is not None:
        return [default_mode]
    return [CameraMode(width=1920, height=1080, bit_depth=12, framerate=60)]


def _capabilities_for_model(model: str, default_mode: CameraMode | None = None) -> CameraCapabilities:
    bounds = None
    for key, value in _MODEL_BOUNDS.items():
        if model and key in model.lower():
            bounds = value
            break
    exposure_min, exposure_max, gain_min, gain_max = bounds or (
        MIN_FRAME_US,
        IMX290_MAX_EXPOSURE_US,
        1.0,
        31.6,
    )
    modes = _modes_for_model(model, default_mode)
    focus = next(
        (value for key, value in _MODEL_FOCUS.items() if model and key in model.lower()),
        None,
    )
    has_af, has_manual, lens_min, lens_max, lens_default = focus or (
        False,
        False,
        None,
        None,
        None,
    )
    return CameraCapabilities(
        modes=modes,
        exposure_min_us=exposure_min,
        exposure_max_us=exposure_max,
        gain_min=gain_min,
        gain_max=gain_max,
        min_frame_duration_us=_min_frame_for(default_mode, modes),
        supports_manual_exposure=True,
        supports_raw12="imx290" in model.lower(),
        supports_autofocus=has_af,
        supports_manual_focus=has_manual,
        lens_position_min=lens_min,
        lens_position_max=lens_max,
        lens_position_default=lens_default,
    )


def _mode_from_config(mode: Any) -> CameraMode:
    """Convert a config ``DefaultMode`` to a ``CameraMode``."""
    return CameraMode(
        width=mode.width,
        height=mode.height,
        bit_depth=mode.bit_depth,
        framerate=mode.framerate,
    )


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
        fallback_capabilities: CameraCapabilities | None = None,
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
        self._fallback_capabilities = fallback_capabilities
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
        self._capabilities: CameraCapabilities | None = None
        # Focus state. ``_focus_mode`` is None until configure decides (auto for
        # actuator cameras, None for the rest). ``AfTrigger`` is never stored.
        self._focus_mode: str | None = None
        self._lens_position: float | None = None
        self._focus_range: str | None = None
        self._focus_speed: str | None = None
        self._refocus_interval: float = 0.0
        self._refocus_due: float = 0.0
        self._metadata: dict[str, Any] = {}
        self._metadata_lock = threading.Lock()
        self._metadata_stop = threading.Event()
        self._metadata_thread = threading.Thread(
            target=self._metadata_loop, daemon=True, name=f"settings-{self._name}"
        )
        self._metadata_thread.start()
        # One persistent feed thread for the worker's lifetime: encoder teardown
        # on reconfigure only clears ``_stream_output``, so frames resume without
        # leaking a thread per reconfigure.
        self._feed_thread = threading.Thread(
            target=self._feed_loop, daemon=True, name=f"mjpeg-feed-{self._name}"
        )
        self._feed_thread.start()

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
        """(Re)configure the sensor and start the camera.

        Any active recording is stopped and finalized before the reconfigure:
        libcamera tears the encoder down on configure, so leaving it running
        would silently lose the file. Finalization starts before any operation
        that can raise, so even a failed reconfigure preserves the recording.
        The remux runs off the camera lock (and off the caller's thread) so live
        view and control operations are not stalled by ffmpeg.
        """
        with self._lock, tracer.start_as_current_span("camera.configure_mode"):
            raw_path = self._teardown_encoders()
            if raw_path is not None:
                _finalize_recording(raw_path, self._video_format, wait=False)
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
            limits = _coerce_frame_duration_limits(controls.get("FrameDurationLimits"))
            if limits is None:
                # No (valid) manual frame duration: drive the mode's framerate.
                controls.pop("FrameDurationLimits", None)
                controls["FrameRate"] = mode.framerate
            else:
                # Re-floor stored limits for the new mode: a limit carried over
                # from a faster mode is out of range for a slow sensor and would
                # be rejected at start.
                floor = _min_frame_us(mode)
                controls["FrameDurationLimits"] = tuple(max(value, floor) for value in limits)
            if self.supports_autofocus():
                if self._focus_mode is None:
                    # Actuator cameras default to single autofocus on start.
                    self._focus_mode = "auto"
                controls.update(self._persistent_focus_controls())
            sensor: dict[str, Any] = {"output_size": (mode.width, mode.height)}
            if mode.bit_depth is not None:
                sensor["bit_depth"] = mode.bit_depth
            config = self._picam2.create_video_configuration(
                main={"size": (mode.width, mode.height), "format": "YUV420"},
                lores={"size": (lw, lh), "format": "YUV420"},
                raw=None,
                sensor=sensor,
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
        """Apply libcamera controls, reconfiguring when the frame duration changes.

        Controls are stored so a later mode change re-applies them. Ordinary
        control changes go through runtime ``set_controls`` (no reconfigure, so
        live view keeps flowing). A frame-duration change, however, would stall
        behind ~10 in-flight frames — minutes at long exposures — so it is baked
        in via ``configure_mode`` instead (the same path the snapshot capture
        uses), making the change take effect on the next frame.

        ``FrameDurationLimits`` entries below the active mode's minimum frame
        time (1/framerate) are raised to that floor, so a client built around
        60 fps sensors (e.g. a hard-coded 1/60 s floor) cannot stall or fail a
        low-framerate sensor such as the imx415 at ~15 fps.
        """
        with self._lock, tracer.start_as_current_span("camera.set_controls"):
            normalized = _sanitize_controls(controls)
            if not normalized:
                return
            limits = normalized.get("FrameDurationLimits")
            if limits:
                floor = _min_frame_us(self._mode if self._mode is not None else self._default_mode)
                normalized["FrameDurationLimits"] = tuple(
                    max(value, floor) for value in limits
                )
            self._controls.update(normalized)
            if not self._started:
                self._ensure_started()
            elif "FrameDurationLimits" in normalized and self._mode is not None:
                self.configure_mode(self._mode)
            else:
                self._picam2.set_controls(normalized)
            logger.info("Camera %s controls set: %s", self._name, normalized)

    def supports_autofocus(self) -> bool:
        """True when the sensor exposes autofocus controls (static fallback or live)."""
        caps = self._capabilities or self._fallback_capabilities
        if caps is not None and caps.supports_autofocus:
            return True
        controls = getattr(self._picam2, "camera_controls", None) or {}
        return "AfMode" in controls or "AfTrigger" in controls

    def supports_manual_focus(self) -> bool:
        """True when the sensor exposes a manual lens-position control."""
        caps = self._capabilities or self._fallback_capabilities
        if caps is not None and caps.supports_manual_focus:
            return True
        controls = getattr(self._picam2, "camera_controls", None) or {}
        return "LensPosition" in controls

    def _lens_bounds(self) -> tuple[float, float, float]:
        """(min, max, default) lens position, preferring the live control range."""
        caps = self._capabilities or self._fallback_capabilities
        lo = caps.lens_position_min if caps and caps.lens_position_min is not None else 0.0
        hi = caps.lens_position_max if caps and caps.lens_position_max is not None else 32.0
        default = (
            caps.lens_position_default
            if caps and caps.lens_position_default is not None
            else lo
        )
        lens = (getattr(self._picam2, "camera_controls", None) or {}).get("LensPosition")
        if isinstance(lens, (tuple, list)) and len(lens) >= 2:
            lo, hi = float(lens[0]), float(lens[1])
            if len(lens) >= 3:
                default = float(lens[2])
        return float(lo), float(hi), float(default)

    def _clamp_lens_position(self, value: float) -> float:
        lo, hi, _ = self._lens_bounds()
        return max(lo, min(float(value), hi))

    @staticmethod
    def _validate_focus(value: Any, allowed: dict[str, int], name: str) -> str:
        key = str(value).lower()
        if key not in allowed:
            raise ValueError(f"Unsupported focus {name}: {value}")
        return key

    def _persistent_focus_controls(self) -> dict[str, Any]:
        """Focus controls re-applied on reconfigure. Never includes ``AfTrigger``."""
        if self._focus_mode is None:
            return {}
        controls: dict[str, Any] = {"AfMode": AF_MODE_VALUES[self._focus_mode]}
        if self._focus_range:
            controls["AfRange"] = AF_RANGE_VALUES[self._focus_range]
        if self._focus_speed:
            controls["AfSpeed"] = AF_SPEED_VALUES[self._focus_speed]
        if self._focus_mode == "manual":
            if self._lens_position is None:
                _, _, self._lens_position = self._lens_bounds()
            controls["LensPosition"] = self._lens_position
        return controls

    def _frame_us(self) -> int:
        """Best-known current frame duration (µs).

        Prefers the stored manual ``FrameDurationLimits`` (which drives
        ``configure_mode``), then the live exposure read by the metadata thread
        (AE can stretch the frame in a light-starved scene), then the mode floor.
        """
        limits = self._controls.get("FrameDurationLimits")
        if limits:
            return int(limits[0])
        exposure = self._metadata.get("exposure_time")
        if isinstance(exposure, (int, float)) and exposure > 0:
            return int(exposure)
        return _min_frame_us(self._mode)

    def _af_busy(self) -> bool:
        """True while a capture or recording is in flight (explicit AF is rejected)."""
        return self._capturing or self._recording

    def _af_slow_frame(self) -> bool:
        """True when the frame duration is too slow for a practical AF sweep."""
        return self._frame_us() > AF_ASSIST_THRESHOLD_US

    def _focus_state_stale(self) -> bool:
        """True when the metadata poll is paused, so AfState would be stale.

        Mirrors the poll's own pause condition (a *stored* frame duration above
        1 s). AE-driven slow frames do not pause the poll, so the state stays
        live there even when the exposure is long.
        """
        limits = self._controls.get("FrameDurationLimits")
        return bool(limits) and int(limits[0]) > 1_000_000

    def _af_blocked(self) -> bool:
        """True when a scheduled refocus must be skipped (busy or slow frames)."""
        return self._af_busy() or self._af_slow_frame()

    def _issue_af_trigger(self) -> None:
        """Start a single autofocus cycle.

        Cancel then Start guarantees a fresh cycle even if the trigger is already
        armed: some IPAs treat a repeated ``Start`` as a no-op.
        """
        self._picam2.set_controls({"AfTrigger": AF_TRIGGER_CANCEL})
        self._picam2.set_controls({"AfTrigger": AF_TRIGGER_START})

    def _clear_af_state(self) -> None:
        """Drop the last AfState so a wait observes only the new sweep's result."""
        with self._metadata_lock:
            self._metadata.pop("af_state", None)

    def _wait_for_focus(self, timeout_ms: int) -> None:
        """Block until a fresh focus result appears or the timeout elapses."""
        deadline = time.monotonic() + max(int(timeout_ms), 0) / 1000.0
        while time.monotonic() < deadline:
            if self._metadata.get("af_state") in ("focused", "failed"):
                return
            time.sleep(0.05)

    def _trigger_with_assist(self, timeout_ms: int) -> dict[str, Any]:
        """Focus via a temporary fast, auto-exposure configuration.

        Long-exposure/manual cameras cannot sweep focus at ~0.5 fps. The previous
        exposure controls are saved, the camera is reconfigured to auto exposure
        at the mode's frame rate for the sweep, focus is locked at the achieved
        lens position, and the original exposure is restored. Runs under the
        camera lock (an explicit, bounded, user-initiated action).
        """
        saved_controls = dict(self._controls)
        saved_focus_mode = self._focus_mode
        saved_lens = self._lens_position
        settled: str | None = None
        achieved: float | None = None
        self._controls.pop("ExposureTime", None)
        self._controls.pop("AnalogueGain", None)
        self._controls.pop("FrameDurationLimits", None)
        self._controls["AeEnable"] = True
        self._focus_mode = "auto"
        try:
            if self._mode is not None:
                self.configure_mode(self._mode)
            self._clear_af_state()
            self._issue_af_trigger()
            self._wait_for_focus(max(int(timeout_ms), 5000))
            # Capture the fresh result before restoring the slow exposure (which
            # would make focus_state() report it as stale).
            settled = self._metadata.get("af_state")
            achieved = self._metadata.get("lens_position")
        finally:
            if achieved is not None:
                # Lock focus at the achieved position so it holds for the long exposure.
                self._focus_mode = "manual"
                self._lens_position = self._clamp_lens_position(achieved)
            else:
                self._focus_mode = saved_focus_mode
                self._lens_position = saved_lens
            self._controls = saved_controls
            if self._mode is not None:
                self.configure_mode(self._mode)
        state = self.focus_state()
        # This response reflects a just-completed measurement, not stale data.
        state["af_state"] = settled
        state["focus_stale"] = False
        state["assisted"] = True
        return state

    def _apply_focus_mode(self, mode: str) -> None:
        """Re-apply a focus mode at runtime; manual locks the achieved lens."""
        with self._lock:
            self._focus_mode = mode
            if mode == "manual":
                achieved = self._metadata.get("lens_position")
                if achieved is not None:
                    self._lens_position = self._clamp_lens_position(achieved)
            self._picam2.set_controls(self._persistent_focus_controls())

    def trigger_autofocus(
        self,
        range: str | None = None,
        speed: str | None = None,
        wait: bool = False,
        timeout_ms: int = 2000,
        assist: bool = True,
    ) -> dict[str, Any]:
        """Run a single autofocus cycle on demand, optionally waiting for it.

        An explicit trigger always succeeds: if the camera is in a
        long-exposure/manual state too slow for a focus sweep it runs an
        AF-assist (see ``_trigger_with_assist``) unless ``assist`` is disabled.
        A capture or recording in progress is rejected instead.

        The pre-trigger focus mode is preserved: a one-shot from ``manual``
        re-locks focus at the achieved position, and a nudge from ``continuous``
        resumes continuous tracking rather than silently downgrading to single.
        """
        with self._lock, tracer.start_as_current_span("camera.trigger_autofocus"):
            if not self.supports_autofocus():
                raise RuntimeError(f"Camera {self._name} does not support autofocus")
            if self._af_busy():
                raise RuntimeError(
                    f"Camera {self._name} is capturing or recording; stop it before focusing"
                )
            self._ensure_started()
            if range is not None:
                self._focus_range = self._validate_focus(range, AF_RANGE_VALUES, "range")
            if speed is not None:
                self._focus_speed = self._validate_focus(speed, AF_SPEED_VALUES, "speed")
            previous_mode = self._focus_mode
            if self._af_slow_frame():
                if not assist:
                    raise RuntimeError(
                        "Camera is in long-exposure mode; autofocus needs assist or Auto Exposure"
                    )
                return self._trigger_with_assist(timeout_ms)
            self._focus_mode = "auto"
            self._picam2.set_controls(self._persistent_focus_controls())
            self._clear_af_state()
            self._issue_af_trigger()
        # Wait off-lock so the MJPEG feed thread is never stalled by focus polling.
        # A manual lock must wait to know where the sweep landed.
        if wait or previous_mode == "manual":
            self._wait_for_focus(timeout_ms)
        if previous_mode == "manual":
            # Focus now from a manual lock: sweep, then lock again at the result.
            settled = self._metadata.get("af_state")
            self._apply_focus_mode("manual")
            state = self.focus_state()
            state["af_state"] = settled
            state["focus_stale"] = False
        elif previous_mode == "continuous":
            # A one-shot nudge should not silently drop continuous tracking.
            self._apply_focus_mode("continuous")
            state = self.focus_state()
        else:
            state = self.focus_state()
        state["assisted"] = False
        return state

    def _set_refocus_interval(self, seconds: float | None, manual: bool) -> None:
        """Store the periodic-refocus interval; always disabled in manual mode."""
        if seconds is None:
            if manual:
                self._refocus_interval = 0.0
                self._refocus_due = 0.0
            return
        interval = float(seconds)
        if interval < 0:
            raise ValueError("refocus_interval_seconds must be >= 0")
        if manual:
            # A manual lock must never be overridden by scheduled AF.
            interval = 0.0
        self._refocus_interval = interval
        self._refocus_due = time.monotonic() + interval if interval > 0 else 0.0

    def set_focus(
        self,
        mode: str,
        lens_position: float | None = None,
        range: str | None = None,
        speed: str | None = None,
        refocus_interval_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Set focus mode, manual lens position, and/or the periodic refocus interval."""
        with self._lock, tracer.start_as_current_span("camera.set_focus"):
            if not self.supports_autofocus():
                raise RuntimeError(f"Camera {self._name} does not support autofocus")
            key = str(mode).lower()
            if key not in AF_MODE_VALUES:
                raise ValueError(f"Unsupported focus mode: {mode}")
            if key == "manual" and not self.supports_manual_focus():
                raise RuntimeError(f"Camera {self._name} does not support manual focus")
            self._focus_mode = key
            if range is not None:
                self._focus_range = self._validate_focus(range, AF_RANGE_VALUES, "range")
            if speed is not None:
                self._focus_speed = self._validate_focus(speed, AF_SPEED_VALUES, "speed")
            if lens_position is not None:
                self._lens_position = self._clamp_lens_position(lens_position)
            self._set_refocus_interval(refocus_interval_seconds, key == "manual")
            self._ensure_started()
            self._picam2.set_controls(self._persistent_focus_controls())
            if key == "auto":
                self._issue_af_trigger()
            logger.info(
                "Camera %s focus set: mode=%s lens=%s interval=%ss",
                self._name,
                self._focus_mode,
                self._lens_position,
                self._refocus_interval,
            )
            return self.focus_state()

    def focus_state(self) -> dict[str, Any]:
        """Snapshot the current focus mode, state, lens position, and interval."""
        # The stored position is authoritative only in manual mode; otherwise the
        # live metadata is where the autofocus algorithm actually left the lens.
        lens = (
            self._lens_position
            if self._focus_mode == "manual" and self._lens_position is not None
            else self._metadata.get("lens_position")
        )
        # When the poll is paused by a slow stored frame, report unknown rather
        # than a misleading previous AfState.
        stale = self._focus_state_stale()
        return {
            "focus_mode": self._focus_mode,
            "af_state": None if stale else self._metadata.get("af_state"),
            "focus_stale": stale,
            "lens_position": lens,
            "refocus_interval_seconds": self._refocus_interval,
            "range": self._focus_range,
            "speed": self._focus_speed,
        }

    def refocus_due(self, now: float) -> bool:
        """True when a scheduled periodic refocus should fire now."""
        if self._refocus_interval <= 0 or not self.supports_autofocus():
            return False
        if self._focus_mode in (None, "continuous", "manual"):
            # Continuous AF already tracks the scene, and a manual lock must not
            # be overridden; nothing to schedule.
            return False
        if now < self._refocus_due:
            return False
        self._refocus_due = now + self._refocus_interval
        return not self._af_blocked()

    def capabilities(self) -> CameraCapabilities | None:
        """Read authoritative capabilities, serialized with camera ops.

        ``Picamera2.sensor_modes`` internally reconfigures the camera and raises
        if it is already running, so the full read is only possible while
        stopped; its result is cached (sensor modes never change). While the
        camera is started, exposure/gain bounds are read from
        ``camera_controls`` (which stays valid at runtime) and merged onto the
        static per-model catalog, so clients still get the real per-sensor
        bounds instead of the approximations.
        """
        with self._lock:
            if self._capabilities is None:
                if self._started:
                    return self._runtime_capabilities()
                self._capabilities = read_capabilities(self._picam2, self._default_mode)
            return self._capabilities

    def _runtime_capabilities(self) -> CameraCapabilities | None:
        """Bounds from ``camera_controls`` while the camera is running."""
        if self._fallback_capabilities is None:
            return None
        caps = self._fallback_capabilities.copy()
        controls = getattr(self._picam2, "camera_controls", None) or {}
        _apply_control_bounds(caps, controls)
        if self._mode is not None:
            # The frame floor belongs to the mode actually running, which can
            # differ from the configured default after a client mode switch.
            caps.min_frame_duration_us = _min_frame_us(self._mode)
        return caps

    def current_settings(self) -> dict[str, Any]:
        """Return the latest gain/exposure read by the background metadata thread.

        When exposure is manual (``AeEnable`` off) and the frame duration
        exceeds 1 s the metadata thread is paused, so the raw metadata would go
        stale exactly when callers need it most. The last-applied manual
        controls are merged in instead; auto-exposure keeps using metadata.
        """
        settings = dict(self._metadata)
        controls = self._controls
        if controls.get("AeEnable") is False:
            if controls.get("ExposureTime") is not None:
                settings["exposure_time"] = int(controls["ExposureTime"])
            if controls.get("AnalogueGain") is not None:
                settings["analogue_gain"] = float(controls["AnalogueGain"])
        if self._focus_mode is not None:
            settings["focus_mode"] = self._focus_mode
            # Only in manual mode is the stored lens position authoritative; in
            # auto/continuous the live metadata reflects where the lens actually is.
            if self._focus_mode == "manual" and self._lens_position is not None:
                settings["lens_position"] = self._lens_position
            # When the poll is paused by a slow stored frame, surface the focus
            # state as unknown instead of a stale previous AfState.
            stale = self._focus_state_stale()
            settings["focus_stale"] = stale
            if stale:
                settings["af_state"] = None
        return settings

    def _metadata_loop(self) -> None:
        """Continuously read current gain/exposure (never blocks callers).

        A single dedicated thread performs the blocking ``capture_metadata`` call
        so a stalled sensor or a long exposure can never stall the rest of the app
        (and never leaks a queued capture job).
        """
        while not self._metadata_stop.wait(0.2):
            limits = self._controls.get("FrameDurationLimits")
            frame_us = limits[0] if limits else _min_frame_us(self._mode)
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
                settings: dict[str, Any] = {
                    "analogue_gain": float(md.get("AnalogueGain", 0.0)),
                    "exposure_time": int(md.get("ExposureTime", 0)),
                }
                if "AfState" in md:
                    settings["af_state"] = AF_STATE_NAMES.get(
                        int(md["AfState"]), str(md["AfState"])
                    )
                if "LensPosition" in md:
                    settings["lens_position"] = float(md["LensPosition"])
                self._metadata = settings

    def _teardown_encoders(self) -> Path | None:
        """Stop all encoders; return the raw recording path for finalization."""
        self._stop_stream_encoder()
        return self._stop_video_encoder()

    def _stop_video_encoder(self) -> Path | None:
        """Stop the H.264 encoder and hand back the raw file to finalize."""
        encoder = self._video_encoder
        self._video_encoder = None
        self._recording = False
        raw_path = self._recording_raw_path
        self._recording_raw_path = None
        if encoder is not None:
            self._picam2.stop_encoder(encoder)
        return raw_path

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

            exposure_us, gain = self._clamp_snapshot(exposure_us, gain)
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
        frame = max(exposure_us, _min_frame_us(self._mode))
        controls = {
            "AeEnable": False,
            "ExposureTime": exposure_us,
            "FrameDurationLimits": (frame, frame),
            "AnalogueGain": gain,
        }
        self._controls.update(controls)
        self._picam2.set_controls(controls)

    def _clamp_snapshot(self, exposure_us: int, gain: float) -> tuple[int, float]:
        """Clamp a snapshot request to the sensor's known bounds (if read)."""
        caps = self._capabilities
        if caps is None:
            return exposure_us, gain
        exposure_us = max(caps.exposure_min_us, min(exposure_us, caps.exposure_max_us))
        gain = max(caps.gain_min, min(gain, caps.gain_max))
        return exposure_us, gain

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
            raw_path = self._stop_video_encoder()
        if raw_path is None:
            return None
        # Remux outside the camera lock: ffmpeg can take a while and the feed
        # thread (and every control op) needs the lock to keep live view alive.
        path = _finalize_recording(raw_path, self._video_format, wait=True)
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

    def _feed_loop(self) -> None:
        # Persistent thread for the worker's lifetime; encoder teardown simply
        # clears ``_stream_output`` until the next encoder is started.
        while not self._feed_stop.is_set():
            output = self._stream_output
            if output is None:
                self._feed_stop.wait(0.1)
                continue
            frame = output.next_frame(timeout=1.0)
            if frame is None:
                continue
            with self._lock:
                for q in self._subscribers:
                    try:
                        q.put_nowait(frame)
                    except queue.Full:
                        pass

    def _stop_stream_encoder(self) -> None:
        if self._mjpeg_encoder is not None:
            try:
                self._picam2.stop_encoder(self._mjpeg_encoder)
            except Exception as exc:  # noqa: BLE001 - encoder may already be stopped
                logger.warning("MJPEG encoder stop failed: %s", exc)
            self._mjpeg_encoder = None
        self._stream_output = None

    def close(self) -> None:
        self._metadata_stop.set()
        self._feed_stop.set()
        raw_path: Path | None = None
        with self._lock:
            if self._started:
                raw_path = self._teardown_encoders()
                self._picam2.stop()
                self._started = False
        if self._feed_thread is not None and self._feed_thread.is_alive():
            self._feed_thread.join(timeout=2.0)
        if raw_path is not None:
            path = _finalize_recording(raw_path, self._video_format, wait=True)
            logger.info("Recording finalized on shutdown: %s", path)


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
        self._workers_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max(1, len(config.cameras)))
        self._started_at = time.time()
        self._settings_stop = threading.Event()
        self._settings_thread = threading.Thread(
            target=self._settings_loop, daemon=True, name="camera-settings"
        )
        self._settings_thread.start()

    def _settings_loop(self) -> None:
        """Periodically fire due periodic refocus (status is read live elsewhere)."""
        while not self._settings_stop.wait(2.0):
            now = time.monotonic()
            for cam_id, worker in list(self._workers.items()):
                try:
                    if worker.refocus_due(now):
                        self._executor.submit(worker.trigger_autofocus)
                except Exception as exc:  # noqa: BLE001 - never kill the loop
                    logger.debug("Periodic refocus failed for %s: %s", cam_id, exc)

    def _default_mode_for(self, cam: Any) -> CameraMode:
        """Return the per-camera default mode, falling back to the global one."""
        configured = cam.default_mode or self._config.default_mode
        return _mode_from_config(configured)

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
            model = entry.get("Model", "")
            default_mode = self._default_mode_for(cam)
            infos.append(
                CameraInfo(
                    id=cam.id,
                    name=cam.name,
                    model=model,
                    modes=_modes_for_model(model, default_mode),
                    default_mode=default_mode,
                    capabilities=_capabilities_for_model(model, default_mode),
                )
            )
        return infos

    def list_cameras(self) -> list[CameraInfo]:
        return self.discover()

    def capabilities(self, camera_id: int) -> CameraCapabilities:
        """Read authoritative capabilities from libcamera (opening the camera).

        Falls back to the static per-model catalog if the camera cannot be
        opened or libcamera is unavailable.
        """
        cam = next((c for c in self._config.cameras if c.id == camera_id), None)
        if cam is None:
            raise KeyError(f"Camera {camera_id} is not configured")
        try:
            worker = self.get_worker(camera_id)
            # Run on the worker executor so sensor-mode reads are serialized
            # with configure/start/controls instead of racing them.
            caps = self._executor.submit(worker.capabilities).result()
            if caps and caps.modes:
                return caps
        except Exception as exc:  # noqa: BLE001 - camera may be absent/busy
            logger.warning("Capability read failed for %s: %s", cam.name, exc)
        return _capabilities_for_model(
            self._model_for(camera_id), self._default_mode_for(cam)
        )

    def _model_for(self, camera_id: int) -> str:
        for info in self.discover():
            if info.id == camera_id:
                return info.model
        return ""

    def get_worker(self, camera_id: int) -> CameraWorker:
        """Return (creating if necessary) the worker for a configured camera."""
        cam = next((c for c in self._config.cameras if c.id == camera_id), None)
        if cam is None:
            raise KeyError(f"Camera {camera_id} is not configured")
        with self._workers_lock:
            if camera_id not in self._workers:
                picam2 = self._picam2_factory(camera_id)
                default_mode = self._default_mode_for(cam)
                worker = CameraWorker(
                    camera_id,
                    cam.name,
                    picam2,
                    self._config.capture,
                    default_mode=default_mode,
                    encoder_factory=self._encoder_factory,
                    mjpeg_encoder_factory=self._mjpeg_encoder_factory,
                    fallback_capabilities=_capabilities_for_model(
                        self._model_for(camera_id), default_mode
                    ),
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

    def trigger_autofocus(
        self,
        camera_id: int,
        range: str | None = None,
        speed: str | None = None,
        wait: bool = False,
        timeout_ms: int = 2000,
        assist: bool = True,
    ) -> dict[str, Any]:
        worker = self.get_worker(camera_id)
        return self._executor.submit(
            worker.trigger_autofocus, range, speed, wait, timeout_ms, assist
        ).result()

    def set_focus(
        self,
        camera_id: int,
        mode: str,
        lens_position: float | None = None,
        range: str | None = None,
        speed: str | None = None,
        refocus_interval_seconds: float | None = None,
    ) -> dict[str, Any]:
        worker = self.get_worker(camera_id)
        return self._executor.submit(
            worker.set_focus,
            mode,
            lens_position,
            range,
            speed,
            refocus_interval_seconds,
        ).result()

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
            # Read live (not cached) so focus/exposure changes are reflected in
            # the next WebSocket/MQTT status broadcast without a lag window.
            "settings": {
                str(cam_id): worker.current_settings()
                for cam_id, worker in self._workers.items()
            },
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


_FINALIZE_LOCK = threading.Lock()


def _finalize_recording(raw_path: Path, video_format: str, *, wait: bool) -> Path | None:
    """Remux a stopped recording, serialized against other finalizations.

    ``wait=True`` blocks and returns the final path (used by ``stop_recording``
    and shutdown, which must report it). ``wait=False`` remuxes on a daemon
    thread so a reconfigure that auto-finalized a recording is never stalled by
    ffmpeg (the raw file is already safely closed either way).
    """
    if video_format != "mp4":
        return raw_path
    if wait:
        with _FINALIZE_LOCK:
            return _finalize_video(raw_path, video_format)

    def _run() -> None:
        with _FINALIZE_LOCK:
            path = _finalize_video(raw_path, video_format)
            logger.info("Recording finalized: %s", path)

    threading.Thread(target=_run, daemon=True, name="video-finalize").start()
    return None


def _default_encoder_factory(path: Path) -> tuple[Any, Any]:
    """Build an H.264 encoder and file output for recording."""
    from picamera2.encoders import H264Encoder
    from picamera2.outputs import FileOutput

    return H264Encoder(), FileOutput(str(path))


def _default_mjpeg_encoder_factory(output: Any) -> tuple[Any, Any]:
    """Build an MJPEG encoder and file output bound to the streaming buffer.

    The bitrate is pinned rather than left to picamera2's default, which scales
    with the encoder's nominal framerate: in low-framerate sensor modes (e.g.
    the 4K mode of the imx708 at ~14 fps) the default would halve the bitrate
    and produce visible macroblocking in the live view.
    """
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput

    return MJPEGEncoder(bitrate=MJPEG_BITRATE), FileOutput(output)

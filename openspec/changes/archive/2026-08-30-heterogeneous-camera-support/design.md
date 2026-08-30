## Context

The app enumerates cameras via `Picamera2.global_camera_info()` but hardcodes the
IMX462's four modes (`_default_modes()`) and its exposure/gain bounds. The sensor
config (`configure_mode`) always passes `bit_depth`, which is only valid for
multi-bit-depth RAW sensors (imx290 RAW10/RAW12). The Ansible role writes a fixed
`imx290` overlay for cam0 and cam1, and the frontend hardcodes shutter/ISO ladders.

## Goals / Non-Goals

**Goals:**
- Treat each camera as its own sensor: read modes + control bounds from libcamera.
- Support heterogeneous cameras (imx290 + imx708, and generically imx219/imx477/
  ov5647/imx296) with per-camera overlay and default mode.
- Keep the existing single-process, thread-per-camera, REST-first architecture.

**Non-Goals:**
- WebRTC, multi-process camera sharing, or the legacy Bullseye/picamera stack.
- A per-model tuning-file pipeline beyond the existing imx290 vendor file.

## Decisions

- **Authoritative capabilities from libcamera.** `read_capabilities(picam2)`
  reads `Picamera2.sensor_modes` and `camera_controls`; a static `_MODEL_MODES` /
  `_MODEL_BOUNDS` catalog keyed by sensor model is only a fallback when libcamera
  is unavailable or the camera cannot be opened (keeps `list_cameras()` and tests
  hardware-free).
- **`bit_depth` only for multi-depth sensors.** `_read_sensor_modes` sets
  `bit_depth` from the format string (`SRGGB10/12`) only when a sensor exposes
  more than one depth; `configure_mode` omits `bit_depth` when `None`. This avoids
  passing an invalid selector to single-depth sensors (imx708).
- **Per-camera config.** `CameraConfig` gains `overlay`, `overlay_params`, and an
  optional `default_mode`; the manager falls back to the global `default_mode`.
- **Capabilities endpoint.** `GET /api/cameras/{id}/capabilities` opens the camera
  lazily (worker construction, lock-guarded) and returns authoritative modes +
  bounds; `/api/cameras` returns static fallback capabilities without opening.
- **Frontend derives ladders.** The shutter/ISO ladders are filtered from fixed
  1/3-stop candidate lists against the selected camera's `exposure_min_us` /
  `exposure_max_us` / `gain_min` / `gain_max`.
- **Ansible per-camera overlay.** The `camera-overlay` role loops over configured
  cameras and replaces any existing `dtoverlay=...,camN` line (idempotent), and
  removes stale lines for unconfigured slots; the vendor imx290 tuning file is
  installed only when an imx290 camera is configured.

## Risks / Trade-offs

- Reading capabilities opens a Picamera2 instance; it is lightweight (no stream
  started) but adds a lazy worker. Worker creation is lock-guarded to avoid races.
- The static catalog's non-imx290 bounds are approximations; on real hardware
  libcamera overrides them. Exact imx708 bounds must be confirmed on-device.
- Renaming the deployment requirement was avoided to keep the delta merge simple;
  the existing "Camera overlay for one or two cameras" name is retained.

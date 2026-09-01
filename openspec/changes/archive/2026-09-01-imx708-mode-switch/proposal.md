## Why

Switching the Mode dropdown in the web UI does nothing on cameras whose modes
carry no bit depth (`bit_depth: null`), i.e. the Camera Module 3 (imx708):
the `ModeRequest` schema declares `bit_depth` as a required int, so the request
is rejected with 422 and the frontend swallows the error in the console. The
live feed keeps streaming its old configuration — mode switches silently no-op
on imx708 cameras (e.g. `raspberrypi-zero-2w-2` cam0, `raspberrypi-5-2` cam1).

## What Changes

- `ModeRequest.bit_depth` becomes optional (`int | None = None`), matching
  `CameraMode.bit_depth` and `configure_mode`'s existing handling of `None`
  (sensor config omits the field for 10-bit-only sensors).
- The web UI surfaces mode/controls/flip/stream-mode API failures as a toast
  instead of a console-only `console.error`, so silent failures are visible.
- Regression tests: API accepts `bit_depth: null` in mode requests; the camera
  service omits `bit_depth` from the sensor config when `None`.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `camera-control`: the "Configure sensor mode" requirement now states that the
  bit depth is optional (omitted/null) for sensors without a bit-depth selector,
  and mode changes must succeed for such sensors.

## Impact

- `src/imx462_controller/api/routes.py` (1 field change).
- `src/imx462_controller/static/app.js` (error handling in four async control
  handlers).
- `tests/test_api.py`, `tests/test_camera_service.py` (regression tests).
- No schema/config/DB changes; no breaking API change (existing int values
  still accepted).

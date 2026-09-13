## Why

Production use (multiple Pis feeding cat-watcher) exposed latent defects in the
camera runtime: any reconfigure silently destroyed an active recording, the
MJPEG stream endpoint could block the whole event loop, every reconfigure leaked
a feed thread, and MQTT telemetry died permanently when the broker was down at
startup. These are backfilled into one change so the specs match the code now
deployed, together with the remaining review findings.

## What Changes

- **Recording integrity**: any camera reconfigure (mode change, flip, controls
  update with `FrameDurationLimits`, return to continuous stream mode, snapshot)
  stops and finalizes an active recording instead of dropping it. The remux runs
  off the camera lock — asynchronously for reconfigures, synchronously for
  `stop_recording` and shutdown, which report the final path. A reconfigure that
  fails after the encoder is stopped still finalizes the raw file.
- **Live view stability**: one persistent MJPEG feed thread per camera worker
  (encoder teardown only clears its output), and stream subscribe/unsubscribe run
  off the asyncio event loop so a slow snapshot or remux cannot freeze every
  request and stream.
- **Control validation**: malformed `FrameDurationLimits` payloads are dropped
  instead of crashing control application, malformed control payloads return 422,
  and stored frame-duration limits are re-floored when the mode changes.
- **Capabilities at runtime**: while the camera is started, exposure/gain bounds
  are read from `camera_controls` and merged onto the static catalog;
  `min_frame_duration_us` reflects the mode actually running.
- **Snapshot bounds**: snapshot exposure/gain must be positive and are clamped to
  the sensor's reported bounds (server-side against cached capabilities,
  client-side in the UI).
- **Telemetry**: MQTT uses an asynchronous connect so a broker that is
  unreachable at startup is retried with backoff instead of disabling telemetry
  until restart.
- **Deployment**: the systemd unit gets a stop timeout long enough to finalize an
  active recording during shutdown.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `capture`: recording finalization on reconfiguration (including failed
  reconfigures and shutdown), and bounded, positive snapshot requests.
- `live-view`: persistent MJPEG feed path and non-blocking stream subscription.
- `camera-control`: runtime capability bounds while the camera is running, the
  running mode's frame-duration floor, control payload validation, and mode-change
  re-flooring of stored limits.
- `telemetry`: broker retry from startup, not only after a successful connect.
- `deployment`: systemd stop timeout accommodating recording finalization.

## Impact

- `src/imx462_controller/camera/service.py` — recording finalize choke point and
  off-lock remux (`_finalize_recording`, `_stop_video_encoder`), persistent feed
  thread, runtime capability bounds, frame-duration coercion/re-flooring,
  snapshot clamping.
- `src/imx462_controller/api/routes.py` — event-loop offload for stream
  subscribe/unsubscribe, snapshot field constraints, 422 for malformed controls.
- `src/imx462_controller/mqtt/client.py` — `connect_async()` + reconnect.
- `src/imx462_controller/static/app.js` — snapshot clamped to `capsBounds()`.
- `ansible/roles/app/templates/imx462-controller.service.j2` — `TimeoutStopSec`.
- Tests — `tests/test_camera_service.py`, `tests/test_api.py`,
  `tests/test_mqtt.py`.
- Docs — `AGENTS.md`, `docs/architecture.md`.
- No API shape changes for valid requests; cat-watcher (external client) keeps
  working without changes.

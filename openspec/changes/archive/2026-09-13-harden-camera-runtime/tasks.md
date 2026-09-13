## 1. Recording integrity

- [x] 1.1 Finalize an active recording at the `configure_mode` choke point: stop the H.264 encoder, capture the raw path, and remux to the configured container (`_finalize_recording`), with `wait=True` for `stop_recording`/shutdown and `wait=False` for reconfigures
- [x] 1.2 Start the finalize immediately after encoder teardown, before any operation that can raise, so a failed reconfigure still finalizes the recording (review finding)
- [x] 1.3 Finalize on shutdown (`close`) and log the final path
- [x] 1.4 Tests: reconfigure finalizes an active recording; `stop_recording` returns the finalized `.mp4`; failed reconfigure finalizes; shutdown finalizes

## 2. Live view and concurrency

- [x] 2.1 Replace the per-reconfigure feed thread with one persistent feed thread per worker; encoder teardown only clears the stream output, and `close` stops/joins the thread
- [x] 2.2 Run stream subscribe/unsubscribe off the asyncio event loop (`anyio.to_thread.run_sync`) and shield the unsubscribe so client disconnects still remove the subscriber
- [x] 2.3 Tests: a single feed thread survives repeated reconfigures; the thread stops on close

## 3. Controls, capabilities, and snapshots

- [x] 3.1 Validate `FrameDurationLimits` as a pair of finite numbers; drop malformed values so sibling controls still apply; return 422 for uninterpretable control payloads
- [x] 3.2 Re-floor stored `FrameDurationLimits` to the new mode's minimum in `configure_mode`
- [x] 3.3 Read exposure/gain bounds from `camera_controls` while the camera is running and merge them onto the static catalog; report the running mode's `min_frame_duration_us` (review finding)
- [x] 3.4 Require positive snapshot exposure/gain (`SnapshotRequest`) and clamp requests to the sensor's known bounds server-side; clamp in the UI against `capsBounds()`
- [x] 3.5 Tests: malformed limits dropped; re-floor on mode change; runtime bounds while started; snapshot clamping; API 422 for non-positive snapshot values

## 4. Telemetry

- [x] 4.1 Connect to MQTT asynchronously (`connect_async()` + `loop_start()`) so an unreachable broker at startup is retried; disconnect before stopping the loop
- [x] 4.2 Test: `start()` uses the async connect path and configures reconnect backoff

## 5. Deployment

- [x] 5.1 Add `TimeoutStopSec=180` to the systemd unit template so shutdown can finalize an active recording before the process is terminated (review finding)

## 6. Verification

- [x] 6.1 Run `pytest` and `ruff check .` — all pass
- [x] 6.2 Run `openspec validate harden-camera-runtime`
- [x] 6.3 Confirm the REST contract for valid requests is unchanged (cat-watcher: `/capabilities`, `/controls`, `/settings`, `/status`, `/photo`, `/flip`, `/stream` framing)

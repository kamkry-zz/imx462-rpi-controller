## Context

See proposal.md — Why. The controller runs one `CameraWorker` per camera with a
single `RLock` serializing all camera operations, a background metadata thread,
and (since this change) a persistent MJPEG feed thread. External clients
(cat-watcher) call `GET /capabilities`, `PUT /controls` with
`FrameDurationLimits`, `POST /photo`, and hold long-lived MJPEG connections; no
response shapes may change. The findings below were found in review after the
first implementation pass.

## Goals / Non-Goals

**Goals:**
- Never lose a recording because of a reconfigure, a failed reconfigure, or
  shutdown.
- Keep the event loop responsive while camera operations hold the worker lock.
- Keep telemetry alive across broker outages, including at startup.
- Return authoritative per-sensor bounds and the running mode's frame floor.
- Make bad control/snapshot payloads client errors, not crashes.

**Non-Goals:**
- Changing the REST contract for valid requests (cat-watcher compatibility).
- Rejecting reconfigures while recording (409): cat-watcher's exposure tuner
  updates controls periodically and would fail; auto-finalize is preferred.
- Pre-warming capability reads at startup (adds latency on first request and can
  exceed cat-watcher's 5 s timeout); runtime bounds from `camera_controls` give
  the same information without opening the camera early.
- Emitting OTel/MQTT metrics (still configured but unused; separate follow-up).

## Decisions

- **Finalize at the `configure_mode` choke point.** Every reconfigure path
  (mode, flip, `FrameDurationLimits` controls, return to continuous stream mode,
  snapshot) already funnels through `configure_mode`, so one hook covers them
  all. The encoder is stopped under the camera lock and the raw path is captured
  before any operation that can raise, so a failed reconfigure still finalizes
  (review finding 1). Alternative: reject reconfigures while recording — breaks
  cat-watcher's tuner; rejected.
- **Remux off the camera lock.** `_finalize_recording` serializes ffmpeg runs
  with a module lock; reconfigures use `wait=False` (daemon thread, caller never
  blocks), `stop_recording`/shutdown use `wait=True` (must report the final
  path). Before this, ffmpeg ran under the worker lock and froze live-view
  fan-out and every control op.
- **One persistent feed thread per worker.** Encoder teardown only clears the
  stream output; the thread waits and resumes when a new encoder starts.
  Alternative: recreate the thread per encoder — leaked one thread per control
  change (verified 1 → N). Rejected.
- **Offload stream subscribe/unsubscribe to the thread pool** with
  `anyio.to_thread.run_sync`, and shield the unsubscribe on client disconnect so
  the subscriber is always removed even when the generator is cancelled.
  Alternative: make the route synchronous — still leaves the cleanup running on
  the loop. Rejected.
- **Runtime bounds while started.** `Picamera2.sensor_modes` reconfigures the
  camera and raises while running, but `camera_controls` stays valid. The worker
  keeps a static fallback catalog and merges runtime bounds onto it;
  `min_frame_duration_us` is overridden with the running mode's floor (review
  finding 2).
- **Drop vs reject malformed controls.** `FrameDurationLimits` must be exactly
  two finite numbers; malformed values are dropped so valid sibling controls
  still apply, and uninterpretable payloads surface as 422. Alternative: reject
  the whole payload — harsher for a field that is easy to ignore.
- **Async MQTT connect.** `connect_async()` + `loop_start()` lets paho's network
  loop retry with the configured backoff; the previous synchronous `connect()`
  failed once and left telemetry disabled until restart. Alternative: a custom
  reconnect thread — paho already does this. Rejected.
- **Systemd stop timeout.** Keep the synchronous shutdown remux and raise
  `TimeoutStopSec` to 180 s (ffmpeg's own timeout is 120 s per file), so a long
  recording is not SIGKILLed mid-remux. Alternative: skip remux on shutdown
  (fast stop, raw `.h264` left) — loses the container conversion the user
  expects. Chosen: option (a), timeout bump.

## Risks / Trade-offs

- [A reconfigure now stops an active recording] → Documented behavior: the
  recording is finalized and preserved; the UI reflects `recording: false` via
  the WebSocket status. cat-watcher's tuner is unaffected (200 responses).
- [Async finalize thread is daemon] → If the process exits immediately after a
  reconfigure, the raw `.h264` remains (never lost, just not remuxed); shutdown
  finalizes synchronously when the recording is still marked active.
- [Runtime bounds come from the running mode] → `min_frame_duration_us` can
  differ from the configured default; all server paths re-floor requests, so
  clients cannot stall a slow sensor.
- [Snapshot clamp only uses an authoritative read] → If capabilities were never
  read, the server clamp is a no-op; the UI clamps against the static catalog and
  requests must be positive, so out-of-range values are still bounded in
  practice.
- [Shutdown can take up to ~120 s per active recording] → `TimeoutStopSec=180`
  bounds it; deployments with many cameras finalize sequentially.

## Migration Plan

1. Deploy the updated code and re-render the systemd unit (Ansible restarts the
   service).
2. `daemon-reload` is handled by the role; no config/schema change.
3. Rollback: redeploy the previous revision; recorded files are unaffected.

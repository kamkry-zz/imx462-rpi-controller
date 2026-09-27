## Why

The Raspberry Pi **Camera Module 3 (IMX708)** carries a VCM autofocus actuator
that libcamera already drives through standard controls (`AfMode`, `AfTrigger`,
`LensPosition`, and `AfState` metadata), but the controller has no first-class
support for it: no capability discovery, no on-demand focus trigger, no periodic
refocus, no manual focus, and no focus-state feedback. Clients can only fire
blind through the generic `/controls` endpoint, and the web UI cannot offer any
focus control at all. Autofocus-capable boards are already in the fleet, so this
is a gap users hit today.

## What Changes

- **Capability discovery**: detect autofocus support per camera at runtime from
  `camera_controls` (`AfMode`/`AfTrigger` → autofocus, `LensPosition` → manual
  focus) and advertise `supports_autofocus`, `supports_manual_focus`, and the
  lens-position min/max/default in `GET /api/cameras/{id}/capabilities`. The
  static per-model fallback marks `imx708` as autofocus-capable; non-actuator
  sensors (imx290/imx219/imx477/ov5647/imx296/imx415) report unsupported and are
  unaffected.
- **Single autofocus by default**: on start/reconfigure an autofocus camera runs
  `AfMode=Auto` and performs one focus cycle. The one-shot `AfTrigger` is a
  command, never a stored/re-baked control, so reconfigures do not re-trigger AF.
- **On-demand trigger**: `POST /api/cameras/{id}/focus/trigger` re-runs a single
  autofocus cycle at any time, optionally blocking (with a timeout) until focus
  settles, and optionally selecting the focus range/speed.
- **AF-assist for long exposures**: autofocus needs a fast frame rate, so an
  explicit trigger while the camera is in a long-exposure/manual state
  temporarily switches to auto exposure at the mode's frame rate, runs the sweep,
  locks focus at the achieved position, and restores the previous exposure. The
  trigger thus always works instead of silently failing; a capture/recording in
  progress is rejected, and the assist can be disabled (then a slow-frame trigger
  is rejected with a clear error). Periodic refocus is skipped for slow frames
  (it would toggle the exposure every interval).
- **Accurate focus state**: when the frame duration is too slow for the metadata
  poll to stay fresh, the focus state is reported as *unknown* with a stale flag
  instead of showing the last value as `failed`.
- **Periodic refocus**: `PUT /api/cameras/{id}/focus` accepts
  `refocus_interval_seconds`; when > 0 the controller re-issues a single
  autofocus at that interval in the background. The interval is runtime state
  (not written to `config.yaml`) and survives client disconnects; `0` disables it.
- **Manual focus**: `PUT /api/cameras/{id}/focus` with `mode: "manual"` and a
  `lens_position` (dioptres) sets a fixed lens position; the value is persisted
  across reconfigures like other stored controls.
- **Continuous autofocus**: `mode: "continuous"` selects libcamera's continuous
  AF as an additional runtime option.
- **Focus state reporting**: `GET /api/cameras/{id}/focus` and the WebSocket
  status/settings payload expose `focus_mode`, `af_state`
  (idle/scanning/focused/failed), and `lens_position`.
- **Web UI**: a Focus card (mode select, "Focus now", manual lens slider,
  refocus-interval selector, AF-state badge), shown only when the selected
  camera advertises autofocus support.
- **Capture safety**: a periodic/triggered AF is skipped while a long
  single-frame exposure is pending, so refocus never fights an in-flight
  snapshot.

## Capabilities

### New Capabilities

- `autofocus`: per-camera autofocus discovery and control — capability
  advertisement, on-demand single AF, continuous AF, periodic refocus, and manual
  lens position, plus focus-state reporting and safe interaction with
  reconfigures and long-exposure captures.

### Modified Capabilities

- none

## Impact

- `src/imx462_controller/camera/service.py` — focus capability fields, focus
  mode/lens state, `trigger_autofocus`/`set_focus`, AF-assist
  (`_trigger_with_assist` saving/restoring exposure), focus locking, stale-state
  reporting, `AfState`/`LensPosition` metadata reads, `configure_mode` AF re-bake
  (never `AfTrigger`), periodic refocus in `CameraManager._settings_loop`.
- `src/imx462_controller/api/routes.py` — `GET/PUT /focus` and
  `POST /focus/trigger` (with `assist` flag) endpoints and validation; focus
  fields in the status payload.
- `src/imx462_controller/static/{index.html,app.js,style.css}` — Focus card gated
  on `supports_autofocus`.
- Tests — `tests/test_camera_service.py` (trigger/re-arm, manual focus
  persistence, periodic scheduler, capability detection) and `tests/test_api.py`
  (get/trigger/put, 404/409/422 paths).
- Docs — `AGENTS.md`, `docs/architecture.md`, `openspec/project.md`.
- No new Python dependencies, no `config.yaml` schema change, no breaking API
  change; non-autofocus sensors behave exactly as before.

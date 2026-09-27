## 1. Camera service: capability detection and focus state

- [x] 1.1 Extend `CameraCapabilities` with `supports_autofocus`, `supports_manual_focus`, `lens_position_min`, `lens_position_max`, `lens_position_default` (default false/None), and include them in `to_dict()` and `copy()`.
- [x] 1.2 Populate the focus fields in `_apply_control_bounds` from `camera_controls` (`AfMode`/`AfTrigger` → autofocus, `LensPosition` → manual focus + bounds), so runtime reads stay authoritative.
- [x] 1.3 Add a static `imx708` focus entry (autofocus + manual, lens bounds) to the per-model fallback catalog; all other supported models report no focus support.
- [x] 1.4 Extend the background metadata read to record `AfState` and `LensPosition` (guarded by the metadata lock) when present, and expose them via `current_settings()` as `af_state`/`lens_position` plus the stored `focus_mode`.

## 2. Camera service: focus operations

- [x] 2.1 Add focus state to `CameraWorker` (`_focus_mode`, `_lens_position`, `_refocus_interval`, `_refocus_due`) initialised to single-autofocus when the sensor supports it, and re-applied by `configure_mode` (never `AfTrigger`).
- [x] 2.2 Implement `trigger_autofocus(range=None, speed=None, wait=False, timeout_ms=...)`: apply `AfMode=Auto` + range/speed, send `AfTrigger=Start` at runtime (with a Cancel→Start fallback if a repeat is a no-op), and optionally poll `capture_metadata()["AfState"]` until focused/failed or timeout.
- [x] 2.3 Implement `set_focus(mode, lens_position=None, range=None, speed=None, refocus_interval_seconds=None)`: persist mode/lens/range/speed, apply at runtime via `set_controls`, clamp `lens_position` to the sensor bounds, and schedule the next periodic refocus.
- [x] 2.4 Add `focus_state()` returning `{focus_mode, af_state, lens_position, refocus_interval_seconds, range, speed}` for the focus endpoint.
- [x] 2.5 Gate `trigger_autofocus` and periodic refocus while a long single-frame exposure is pending (`_capturing` and/or frame duration > 1 s) so refocus never interrupts a snapshot.
- [x] 2.6 Add `CameraManager` methods (`trigger_autofocus`, `set_focus`) dispatching through the executor, and drive periodic refocus from `_settings_loop` when a worker's interval is due.

## 3. API routes

- [x] 3.1 Add `GET /api/cameras/{camera_id}/focus` returning the focus state; 404 for an unknown camera and a 409/422 client error when focus is unsupported.
- [x] 3.2 Add `POST /api/cameras/{camera_id}/focus/trigger` with a validated request body (`wait`, `timeout_ms`, `range`, `speed`); reject non-positive/non-numeric timeouts and unsupported cameras.
- [x] 3.3 Add `PUT /api/cameras/{camera_id}/focus` with a validated body (`mode`, `lens_position`, `range`, `speed`, `refocus_interval_seconds`); reject unknown modes and unsupported cameras; publish an MQTT event for focus changes.
- [x] 3.4 Include `focus_mode`/`af_state`/`lens_position` in the status payload surfaced over the WebSocket, and ensure `/api/cameras` and `/capabilities` expose the new capability fields.

## 4. Web UI

- [x] 4.1 Add a Focus card to `index.html` (mode select, "Focus now" button, manual lens slider with min/max/default, refocus-interval selector, focus-state badge), hidden by default.
- [x] 4.2 Wire `app.js` to show the card only when `caps.supports_autofocus`, populate the lens range from capabilities, call the focus endpoints, and render `af_state`/`lens_position` from the status payload; style it in `style.css`.

## 5. Tests

- [x] 5.1 `tests/test_camera_service.py`: capability detection with and without focus controls; static `imx708` fallback reports autofocus, `imx290` does not.
- [x] 5.2 `tests/test_camera_service.py`: trigger issues `AfMode`/`AfTrigger` without reconfiguring; a reconfigure re-applies persistent focus settings but does not re-trigger AF.
- [x] 5.3 `tests/test_camera_service.py`: manual focus clamps to bounds and survives a mode change; periodic refocus triggers on schedule and is skipped during a long exposure.
- [x] 5.4 `tests/test_api.py`: focus get/trigger/put happy paths; 404 unknown camera; 409/422 for unsupported camera, invalid mode, and malformed timeout.

## 6. Docs and validation

- [x] 6.1 Document the new endpoints, defaults, and units (dioptres) in `docs/architecture.md`, and note the IMX708-only autofocus support in `AGENTS.md` and `openspec/project.md`.
- [x] 6.2 Run `pytest` and `ruff`; validate the change with `openspec validate add-autofocus-support --strict`.
- [x] 6.3 Validate trigger/wait/periodic/manual focus on the IMX708 hardware and record the observed `AfTrigger` re-arm and `AfState` behaviour. Done on `raspberrypi-zero-2w-2` / `raspberrypi-5-1` / `raspberrypi-5-2` (imx708_wide_noir, libcamera v0.7.2): see design.md "Hardware validation".

## 7. AF-assist and accurate focus state

- [x] 7.1 Split the old long-exposure gate into `_af_busy` (capture/recording) and `_af_slow_frame` (frame duration above the assist threshold); keep scheduled refocus skipped for both.
- [x] 7.2 Implement `_trigger_with_assist`: save exposure controls, reconfigure to fast auto exposure, sweep, lock focus at the achieved lens position, restore the previous exposure, and report `assisted`.
- [x] 7.3 Reject an explicit trigger with a client error while capturing/recording, and when assist is disabled in a slow-frame state.
- [x] 7.4 Report `focus_stale` and a null `af_state` when the metadata poll is paused by a slow frame (`focus_state`, `current_settings`, status/WS).
- [x] 7.5 API: `assist` flag on `POST /focus/trigger`; propagate `assisted`/`focus_stale`; map the new rejections to 409.
- [x] 7.6 UI: show `unknown` (not `failed`) for stale state, add a long-exposure hint, and run "Focus now" with assist and a longer timeout.
- [x] 7.7 Tests: assist enter/restore + lock, assist-disabled 409, busy 409, stale state, periodic skip on slow frames (service + API).
- [x] 7.8 Redeploy to the IMX708 hosts and validate: from a 2 s manual exposure, `Focus now` returns `focused` with `assisted: true` and locks focus; `GET /focus` reports `focus_stale` before the assist. Validated on `raspberrypi-zero-2w-2`: pre-trigger `focus_stale: true`, trigger `assisted: true`/`af_state: focused`/manual lock.

## 8. Manual-focus stability and UI state sync

- [x] 8.1 Preserve the pre-trigger focus mode in `trigger_autofocus`: manual re-locks at the achieved lens position, continuous resumes tracking, auto stays auto (`_apply_focus_mode`).
- [x] 8.2 Disable periodic refocus in manual mode: `refocus_due` returns false and `set_focus("manual")` zeroes the interval.
- [x] 8.3 `CameraManager.status()` reports live `current_settings()` (drop the cached `_settings` snapshot) so the 2 s WebSocket/MQTT broadcast is never stale.
- [x] 8.4 UI: background broadcasts only update the read-only `af_state` badge; mode/range/interval/lens sync only on initial `GET /focus` and explicit responses; disable the refocus selector in manual.
- [x] 8.5 Tests: manual trigger re-locks and preserves mode, continuous preserved, manual disables periodic, API manual trigger preserves mode.
- [x] 8.6 Redeploy and validate on `raspberrypi-zero-2w-2`: set manual and confirm the mode stays manual across broadcast cycles and the lens holds; "Focus now" briefly focuses and returns to manual; the refocus selector is disabled. Validated: manual 6.0 held over 6 s; manual trigger returned `focus_mode:"manual"`/`af_state:"focused"` locked at 1.54; setting manual cleared a 30 s interval to 0.

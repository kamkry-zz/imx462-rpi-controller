## Context

See `proposal.md` for motivation. The camera runtime already has the pieces this
change builds on:

- One `CameraWorker` per camera, serialising every operation behind an
  `RLock` and running on a `ThreadPoolExecutor` (`CameraManager`).
- Controls are stored in `_controls` and re-baked into the camera configuration
  by `configure_mode`; a `FrameDurationLimits` change forces a reconfigure while
  other controls apply at runtime via `set_controls`.
- Capabilities are read from libcamera (`sensor_modes` / `camera_controls`) with
  a static per-model fallback for no-hardware/test environments, and cached.
- A background metadata thread reads gain/exposure off the camera lock; a
  manager-level settings loop polls each worker every ~2 s for the status
  payload.

libcamera exposes the IMX708's VCM through standard controls: `AfMode`
(Manual/Auto/Continuous), `AfTrigger` (Start/Cancel), `AfRange`, `AfSpeed`,
`AfPause`, `LensPosition` (float dioptres, 0 = infinity), and reports `AfState`
(Idle/Scanning/Focused/Failed) plus `LensPosition` in capture metadata. Autofocus
is evaluated by the IPA per-frame, so it does not need a reconfigure and is not
subject to the ~10-in-flight-frame lag that affects timing controls.

## Goals / Non-Goals

**Goals:**

- First-class, discoverable autofocus control: capability advertisement,
  on-demand single AF, continuous AF, periodic refocus, manual lens position,
  and focus-state feedback.
- Zero impact on non-actuator sensors: IMX462/IMX290, IMX219, IMX477, OV5647,
  IMX296, IMX415 behave exactly as today.
- Correct interaction with the existing reconfigure/snapshot/recording paths and
  with the long-exposure single-frame mode.

**Non-Goals:**

- Persisting focus settings to `config.yaml` (per decision below; runtime only).
- Implementing any autofocus algorithm in software — focus is delegated to the
  libcamera IPA/VCM.
- Autofocus for sensors without an actuator.
- Freezing focus automatically before still capture (noted as a future option,
  not required here).

## Decisions

1. **Dedicated `/focus` REST endpoints instead of only the generic `/controls`.**
   The generic endpoint already forwards arbitrary controls, but it cannot express
   a one-shot trigger, wait-for-settlement, periodic scheduling, capability
   gating, or state readback. Dedicated endpoints make the behaviour a contract;
   the generic endpoint remains available and unchanged.
   Alternatives: document AF controls only (no discovery/state/scheduling);
   extend `/controls` with special-cased keys (leaky, no trigger semantics).

2. **Default focus mode is single autofocus (`AfMode=Auto`).**
   On start/reconfigure the worker applies the configured focus mode, defaulting
   to `Auto` when the sensor supports AF, so a fresh session is in focus without
   client action. Continuous autofocus is opt-in via the API.
   Alternatives: continuous by default (extra power/lens movement, and it can
   fight still captures); no default (operator must always trigger).

3. **`AfTrigger` is a transient command, never a stored/re-baked control.**
   Persistent focus state (`focus_mode`, `LensPosition`, `AfRange`, `AfSpeed`) is
   tracked separately and merged into `configure_mode`'s controls; `AfTrigger` is
   only ever sent as an explicit runtime `set_controls` call. This prevents a
   mode change, flip, snapshot reconfigure, or stream-mode switch from silently
   starting a new focus cycle.
   Alternatives: keep `AfTrigger` in `_controls` (re-triggers on every
   reconfigure — observed failure mode for long exposures); do not persist focus
   at all (manual lens position lost on each reconfigure).

4. **Periodic refocus driven by the manager settings loop, runtime-only.**
   `refocus_interval_seconds` is held in worker state; the existing
   `CameraManager._settings_loop` (2 s tick) checks each worker's due time and
   dispatches a single-AF trigger through the executor, so it is serialized with
   other camera ops and independent of client connections. The interval is not
   written to `config.yaml` (matches the requested "additional API option"),
   avoiding a config schema change.
   Alternatives: a new per-worker scheduler thread (more threads, no benefit);
   persisting to config (rejected by requirement).

5. **Detect support from `camera_controls`, fall back to a static IMX708 entry.**
   `supports_autofocus` = `"AfMode" in camera_controls` (or `AfTrigger`);
   `supports_manual_focus` = `"LensPosition" in camera_controls`, whose
   `(min, max, default)` tuple also yields the advertised bounds. This keeps the
   runtime read authoritative and mirrors the existing exposure/gain handling.
   The static catalog gains an `imx708` autofocus entry so the UI/tests work
   without hardware; other models stay unsupported.

6. **Focus state cached from the existing metadata read.**
   The metadata thread already calls `capture_metadata` off the camera lock. It
   additionally records `AfState` and `LensPosition` when present, so status reads
   never add a blocking camera call. When AF is unsupported these keys are absent
   and the focus fields are omitted/false.
   Alternatives: on-demand metadata read in the focus endpoint (blocks/stalls the
   feed, contradicts the hard-won rule that metadata reads stay off the hot path).

7. **Manual lens position is clamped to the sensor bounds and clamped-not-rejected.**
   Matches the snapshot-clamping convention: out-of-range values are saturated to
   the advertised min/max; only non-numeric/structurally invalid input is a 422.
   The applied position persists across reconfigures like other stored controls.

8. **An explicit trigger always works via AF-assist; periodic refocus is gated.**
   Autofocus needs many frames, so at a slow frame rate an explicit
   `POST /focus/trigger` temporarily reconfigures to auto exposure at the mode's
   frame rate, sweeps, locks focus at the achieved position, and restores the
   previous exposure. This avoids the original failure mode where a trigger in a
   long-exposure/manual state silently no-opped and returned a stale `failed`.
   Periodic refocus has no such assist (it would toggle the exposure every
   interval) and is skipped for slow frames. A capture/recording in progress is
   rejected with 409; the assist can be disabled per request.
   Alternatives: reject slow-frame triggers (simpler but leaves the user stuck);
   assist on periodic refocus too (repeated exposure flicker).

9. **Never report stale focus state as live.**
   When the metadata poll is paused by a slow frame, `focus_state()`/`current_settings()`
   report `af_state: null` with `focus_stale: true` instead of the last value, so
   the UI shows *unknown* rather than a misleading `failed`.
   Alternatives: keep the last value (observed to confuse operators); report a
   synthetic reason string (less structured for clients).

10. **An explicit trigger preserves the pre-trigger focus mode.**
    `POST /focus/trigger` sweeps in single-autofocus, then restores the prior
    mode: manual locks at the achieved lens position, continuous resumes tracking,
    auto stays auto. This makes "Focus now" a nudge rather than a mode switch, so
    a manual lock is not silently dropped (observed: users setting manual focus
    to defocus saw it revert to AF).
    Alternatives: always leave single autofocus (surprising mode change);
    special-case only manual (inconsistent for continuous).

11. **Manual mode disables periodic refocus.**
    `refocus_due()` returns false for manual and `set_focus("manual")` zeroes the
    interval, so a scheduled AF can never override a manual lock.
    Alternative: allow periodic AF in manual (defeats the purpose of a manual lock).

12. **The UI trusts explicit responses, not background broadcasts, for controls.**
    The 2 s status broadcast (`status_broadcaster`) updates only the read-only
    `af_state` badge; the focus mode/range/interval/lens controls sync from the
    initial `GET /focus` and from PUT/POST responses. The server's `status()`
    also reports live `current_settings()` instead of a cached snapshot. This
    removes the stale-broadcast race where the dropdown reverted to `auto` and
    the next interaction sent `mode: "auto"`.
    Alternatives: cache + client dirty flag (still racy); broadcast-less UI
    (loses live status).

## Risks / Trade-offs

- **`AfTrigger` re-arm semantics are unverified on hardware.** libcamera may treat
  a repeated `Start` as a no-op if the trigger is already armed. → Validate on the
  IMX708 board during apply; if needed, issue `AfTrigger=Cancel` before `Start`
  (encapsulated in one worker method so the change is localised).
- **Wait-for-settlement relies on `AfState` metadata.** If a build omits `AfState`,
  the wait path cannot detect completion. → Fall back to returning the last known
  state at timeout; never block indefinitely. Contained in the trigger method.
- **`LensPosition` is in dioptres, not a 0–100 scale.** A UI slider mapped
  directly would feel inverted to users. → Label the control as dioptres and
  present the sensor's advertised min/max; document the unit.
- **AF-assist changes exposure twice per explicit trigger** (fast during the
  sweep, original restored) and reconfigures the camera, briefly pausing live
  view. → Bounded (≤ timeout), only on an explicit user action, and the response
  reports `assisted: true`. Periodic refocus never assists.
- **A reconfigure during AF-assist auto-finalizes an active recording.** → A
  capture/recording in progress is rejected with 409 before the assist begins.
- **AE settle time during assist.** → The assist uses auto exposure so the IPA's
  own `skip_frames`/exposure settle before the sweep; focus is locked to the
  achieved `LensPosition` once `AfState` is terminal.
- **Status-broadcast vs user input race.** A 2 s broadcast carrying a stale
  `focus_mode` previously reverted the dropdown to `auto`, and the next edit then
  sent `mode: "auto"` (the reported "manual falls back to AF"). → Background
  broadcasts no longer write the controls, and `status()` reports live settings.
- **"Focus now" latency in manual.** Returning to manual needs the sweep result,
  so a manual-mode trigger always waits (bounded by `timeout_ms`). → Acceptable
  for an explicit action; the response still carries a fresh `af_state`.
- **Continuous AF can move the lens during a still capture.** → Out of scope to
  freeze automatically; the manual/one-shot modes plus the documented behaviour
  give operators a deterministic option.
- **Static catalog divergence.** The fallback `imx708` autofocus entry can drift
  from real bounds. → Runtime `camera_controls` always overrides it; tests cover
  both paths.
- **Thread-safety of focus state.** `af_state`/`lens_position` are written by the
  metadata thread and read by status/focus endpoints. → Guard with the existing
  metadata lock, as gain/exposure already are.

## Migration Plan

Additive and backwards-compatible: new capability fields default to
unsupported/false, new endpoints are opt-in, and no config key is added. Deploy
by updating the app (Ansible playbook run/restart); roll back by reverting the
commit — clients that never call `/focus` see no change. Hardware validation on
an IMX708 camera (the fleet's Camera Module 3 board) confirms trigger, wait,
periodic, and manual paths before considering the change done.

## Hardware validation

Validated on the fleet's Camera Module 3 Wide Noir (`imx708_wide_noir`) under
libcamera v0.7.2 (vc4 IPA), deployed via Ansible:

- `camera_controls`: `AfMode (0,2,0)`, `AfTrigger (0,1,0)`, `AfRange (0,2,0)`,
  `AfSpeed (0,1,0)`, `LensPosition (0.0,32.0,1.0)`. The **runtime** lens range
  (read while running) is `0.0–35.0`, default `1.0`; the static fallback was
  corrected to `0–32/1.0`.
- `AfState` metadata is present (0 idle, 1 scanning, 2 focused, 3 failed);
  `AfMode` is not reported in metadata, so focus mode is tracked in the worker.
- `AfMode=Auto` + `AfTrigger=Start` starts a scan, and `Cancel`→`Start` also
  starts a clean scan — the shipped `Cancel`→`Start` is safe and kept.
- Continuous AF drives the lens (observed 1.0 → 10.0 → 0.0 → 2.0 …), reaching
  `failed` on the dark, low-contrast bench scene; manual focus holds the exact
  requested position and clamps to the runtime max (999 → 35.0).
- A stale stored manual lens position is no longer surfaced in auto/continuous
  modes (live metadata wins); endpoint responses, capability flags, status
  payload, and 409 for the non-actuator imx290 cameras were all confirmed.
- A camera left in a 2 s manual exposure (from the UI shutter ladder) reported a
  stale `failed` because the poll was paused and the trigger no-opped. The
  AF-assist path is what makes `Focus now` work in that state; the stale flag
  stops the UI presenting the frozen value as live.
- Manual stability re-validated after the state-sync fix: manual lens 6.0 held
  over 6 s (mode did not revert), `Focus now` in manual returned
  `focus_mode:"manual"` locked at the achieved 1.54, and selecting manual cleared
  a 30 s refocus interval to 0.

## Open Questions

None. Both had been resolved by the hardware validation above: the `AfTrigger`
re-arm behaviour is safe with `Cancel`→`Start`, and `AfState` is reported by the
IPA.

# Design: imx708 mode switch fix

## Context

See `proposal.md`. The web UI's mode dropdown sends the exact mode object from
`GET /api/cameras` — for imx708 cameras that includes `"bit_depth": null`
(10-bit-only sensor, `_read_sensor_modes` leaves it `None`). The PUT
`/api/cameras/{id}/mode` body is validated by `ModeRequest`, which declared
`bit_depth: int` (required). Pydantic v2 rejects `null` for an `int` field →
FastAPI returns 422 before `CameraManager.configure` is ever called. The
frontend `applyMode()` catches and logs to the browser console only, so the
user sees the feed continue unchanged with no feedback.

Note: the sensor itself has no bit-depth selector for these modes, so sending
no bit depth is correct; `CameraMode.bit_depth` is already `int | None` and
`configure_mode` already omits the `sensor.bit_depth` key when `None`.

## Goals / Non-Goals

Goals:
- imx708 mode switches reconfigure the camera (accept `bit_depth: null`).
- Failures of mode/control calls are visible in the UI.
- Regression coverage for the null-bit-depth path.

Non-goals:
- Changing the live-feed rendering or lores sizing (the feed is intentionally
  capped at 1280x720; switching to the center-crop 1536x864 mode visibly
  narrows the FOV once the switch works).
- Renaming or otherwise restructuring the API.

## Decisions

1. **Make `ModeRequest.bit_depth` optional** (`int | None = None`) rather than
   defaulting it to a sentinel or dropping the field.
   Rationale: matches `CameraMode` and the nulls already emitted by
   `/api/cameras`; existing clients sending an int keep working unchanged.
   Alternative considered: `Optional[int]` on the frontend side only — rejected,
   the schema is the contract.

2. **Surface failures with the existing `toast()` helper** in `app.js`.
   Rationale: the helper already exists and is the established feedback
   mechanism; no new UI work. Applied to the four async handlers that currently
   only `console.error` (`applyMode`, `applyControls`, `applyFlip`,
   `setSingleMode`).

3. **Regression tests at both layers**: API test asserts `bit_depth: null`
   returns 200 (the exact 422 regression); camera-service test asserts the
   sensor config omits `bit_depth` for a `CameraMode(bit_depth=None)`.
   Rationale: the API test pins the contract, the service test pins the sensor
   configuration path.

## Risks / Trade-offs

- **Silently invalid bit depths** (e.g. `null` for an imx290): the service
  treats `None` as "no selector" and omits the field; libcamera then picks the
  sensor's default bit depth. Acceptable — the UI only sends values from the
  camera's own mode list.
- **`bit_depth: 0`**: still rejected (must be int in {10,12}? no validation
  exists today beyond the type) — unchanged behavior; out of scope.

## Migration Plan

Deploy the fix with the existing Ansible playbook (idempotent; source sync +
service restart on all Pis). No config/secrets changes. Rollback: revert the
routes.js/app.js change and re-run the playbook — the API simply returns to
rejecting null bit depths (the pre-existing behavior).

## Open Questions

None.

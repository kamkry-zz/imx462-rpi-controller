# Autofocus Test Plan (IMX708 / Camera Module 3)

Manual + automated test plan for the `add-autofocus-support` change
(`GET/POST/PUT /api/cameras/{id}/focus`). Autofocus is only available on sensors
with a VCM actuator; the Camera Module 3 (IMX708) is the only supported sensor
that has one.

## Scope

Verify capability discovery, on-demand single autofocus, periodic refocus,
continuous autofocus, manual focus, focus-state reporting, error handling, the
web UI, and safe interaction with reconfigures and long-exposure snapshots.

## Test hosts

| Host | Camera | Sensor | Expected focus support |
|---|---|---|---|
| `raspberrypi-zero-2w-2.krysdom` | cam0 | `imx708_wide_noir` | yes (autofocus + manual) |
| `raspberrypi-5-1.krysdom` | cam0 / cam1 | `imx290` / `imx708` | no / yes |
| `raspberrypi-5-2.krysdom` | cam0 / cam1 | `imx290` / `imx708` | no / yes |

API base URL: `http://<host>:8000`.

**Scene requirement:** point the camera at a well-lit, textured subject at
roughly 0.5–3 m. Autofocus legitimately reports `failed` on a dark or
featureless scene (observed on the bench), which is not a defect.

## 1. Automated (no hardware)

```sh
.venv/bin/python -m pytest tests/ -q      # expect all pass
.venv/bin/python -m ruff check src tests  # expect clean
openspec validate add-autofocus-support --strict
```

Covers: capability detection with/without focus controls, static imx708 fallback,
trigger-without-reconfigure, reconfigure re-applies settings without re-triggering,
manual clamp + persistence, periodic scheduling + skip-while-capturing, API
200/404/409/422 paths.

## 2. Deployment

```sh
ansible-playbook -i ansible/inventory.ini ansible/playbook.yml \
  --limit 'raspberrypi-zero-2w-2,raspberrypi-5-1,raspberrypi-5-2'
```

- [ ] All hosts `changed=... failed=0`.
- [ ] `systemctl is-active imx462-controller` → `active` on each.
- [ ] `journalctl -u imx462-controller -n 50` shows no startup errors.

## 3. Capability discovery

```sh
H=raspberrypi-zero-2w-2.krysdom
curl -s localhost:8000/api/cameras/0/capabilities   # run on the host
```

- [ ] IMX708 camera: `supports_autofocus: true`, `supports_manual_focus: true`,
      `lens_position_max` = runtime value (observed `35.0`), `lens_position_default` (observed `1.0`).
- [ ] IMX290 camera (5-1/5-2 cam0): both flags `false`, lens bounds `null`.

## 4. On-demand single autofocus

```sh
curl -s -X POST localhost:8000/api/cameras/0/focus/trigger \
  -H 'Content-Type: application/json' -d '{"wait":true,"timeout_ms":5000}'
```

- [ ] Returns `focus_mode: auto`; `af_state` settles to `focused` (or `failed` on a poor scene).
- [ ] Without `wait`, returns immediately with the current `af_state`.
- [ ] `range: "macro"|"full"` and `speed: "fast"` are accepted and echoed in `GET /focus`.
- [ ] Live view keeps streaming throughout (no stall).
- [ ] Non-AF camera (`/api/cameras/0/focus/trigger` on 5-1/5-2) → HTTP `409`.

## 4b. AF-assist in long-exposure mode

Autofocus needs a fast frame rate, so an explicit trigger in a long-exposure
state temporarily switches to auto exposure, sweeps, locks, and restores.

```sh
# Put the camera in a 2 s manual exposure.
curl -s -X PUT localhost:8000/api/cameras/0/controls -H 'Content-Type: application/json' \
  -d '{"controls":{"AeEnable":false,"ExposureTime":2000000,"AnalogueGain":1.0,"FrameDurationLimits":[2000000,2000000]}}'
curl -s localhost:8000/api/cameras/0/focus        # expect focus_stale:true, af_state:null
curl -s -X POST localhost:8000/api/cameras/0/focus/trigger -H 'Content-Type: application/json' \
  -d '{"wait":true,"timeout_ms":10000,"assist":true}'
```

- [ ] Before the trigger, `GET /focus` reports `focus_stale: true` and `af_state: null`.
- [ ] The trigger returns `assisted: true`, a fresh `af_state` (`focused`/`failed`),
      and `focus_mode: "manual"` locked at the achieved `lens_position`.
- [ ] Afterwards the camera is back at the manual exposure (settings show
      `ExposureTime: 2000000`) with focus locked.
- [ ] `assist:false` on the same state → HTTP `409`.
- [ ] Trigger while a snapshot/recording is in progress → HTTP `409`.
- [ ] `GET /focus` after the assist (still long exposure) reports `focus_stale: true`
      again; the UI shows *unknown*, not `failed`.

> Note: running `PUT /controls` from the browser UI while testing can race the
> API calls; use `curl` or close the UI tab for deterministic results.

## 5. Periodic refocus

```sh
curl -s -X PUT localhost:8000/api/cameras/0/focus \
  -H 'Content-Type: application/json' \
  -d '{"mode":"auto","refocus_interval_seconds":15}'
```

- [ ] `GET /focus` reports `refocus_interval_seconds: 15`.
- [ ] Over ~45 s, `af_state` transitions to `scanning` at least twice
      (poll `GET /settings`; the manager fires on its ~2 s tick).
- [ ] `refocus_interval_seconds: 0` stops further cycles.
- [ ] Refocus is **skipped** while a long single-frame capture is pending:
      set a >2 s shutter (single-frame mode), start a snapshot, and confirm no
      new `scanning` appears until it completes.
- [ ] Interval does not survive a service restart (runtime-only):
      `systemctl restart imx462-controller` → `GET /focus` shows `0`.

## 6. Continuous autofocus

```sh
curl -s -X PUT localhost:8000/api/cameras/0/focus \
  -H 'Content-Type: application/json' -d '{"mode":"continuous"}'
for i in $(seq 5); do sleep 1; curl -s localhost:8000/api/cameras/0/focus; echo; done
```

- [ ] `focus_mode: continuous`; `af_state` alternates `scanning`/`focused`
      (or `failed` on a poor scene) and `lens_position` changes between samples.
- [ ] The reported `lens_position` is the live lens reading, **not** a previously
      stored manual value.

## 7. Manual focus

```sh
curl -s -X PUT localhost:8000/api/cameras/0/focus \
  -H 'Content-Type: application/json' -d '{"mode":"manual","lens_position":5.0}'
curl -s localhost:8000/api/cameras/0/focus
```

- [ ] `focus_mode: manual`, `lens_position: 5.0`; image focus visibly changes.
- [ ] Out-of-range request (e.g. `999`) is **clamped** to `lens_position_max`
      (not rejected).
- [ ] Non-numeric value → HTTP `422`.
- [ ] **Persistence:** with a manual position set, change the camera mode
      (`PUT /api/cameras/0/mode`) and confirm the manual position is still applied
      and `GET /focus` still reports it.
- [ ] **No spurious refocus on reconfigure:** after setting manual (or single)
      mode, change mode/flip and confirm `af_state` does **not** briefly go
      `scanning` purely from the reconfigure.

## 7b. Manual-focus stability (UI)

Root cause of "manual falls back to AF": the 2 s status broadcast used to
overwrite the dropdown with a stale `focus_mode`.

- [ ] Select **Manual**, move the lens slider to defocus; the dropdown stays
      **Manual** across several broadcast cycles (≥10 s) — it must not revert to
      Auto.
- [ ] The lens stays where you set it; adjust the slider again and the mode is
      still Manual.
- [ ] **Focus now** while Manual: it briefly focuses (or assists), then returns
      to **Manual** at the achieved lens position (`GET /focus` →
      `focus_mode:"manual"`).
- [ ] The **Refocus every** selector is disabled in Manual and shows Off.
- [ ] Selecting Manual while an interval was set clears it
      (`GET /focus` → `refocus_interval_seconds: 0`).
- [ ] Switching Manual → Auto → Manual never silently re-triggers AF over the
      lock.

## 8. Scheduler / mode interaction

- [ ] Switch `continuous` → `manual`: lens snaps to the stored manual position.
- [ ] `manual` + `refocus_interval_seconds > 0`: periodic fires (mode is
      non-continuous) and drives a single AF cycle.
- [ ] `continuous` + interval set: no extra scheduled cycles (continuous already
      tracks the scene).

## 9. Status / WebSocket reporting

- [ ] `GET /api/cameras/0/settings` includes `focus_mode`, `af_state`, `focus_stale`, `lens_position`.
- [ ] With a stored long exposure (>1 s), `focus_stale: true` and `af_state: null`.
- [ ] WebSocket `ws://<host>:8000/api/ws` status payload includes the same focus
      fields under `settings["0"]`.
- [ ] Values update within ~2 s of a focus change.

## 10. Web UI

- [ ] Focus card is **hidden** for cameras without autofocus (5-1/5-2 cam0).
- [ ] Focus card is **shown** for an IMX708 camera, with mode/range/lens/interval
      controls and the state badge.
- [ ] Lens slider min/max reflect the reported bounds (0–35 observed).
- [ ] "Focus now" triggers a cycle; the badge shows scanning → focused/failed.
- [ ] Selecting Manual enables the lens slider; Auto/Continuous disables it.
- [ ] A bad request surfaces a toast (not a silent console error).

## 11. Error handling

| Request | Expected |
|---|---|
| `GET /api/cameras/99/focus` | `404` |
| `GET /api/cameras/0/focus` on imx290 | `409` |
| `POST /focus/trigger` on imx290 | `409` |
| `PUT /focus {"mode":"bogus"}` | `422` |
| `POST /focus/trigger {"wait":true,"timeout_ms":0}` | `422` |
| `PUT /focus {"mode":"manual","lens_position":"abc"}` | `422` |

## 12. Regression (non-actuator cameras unchanged)

- [ ] On 5-1/5-2 cam0 (imx290): mode switch, manual exposure, snapshot, and
      recording behave exactly as before.
- [ ] `/api/cameras` capabilities for imx290 report `supports_autofocus: false`.

## Acceptance criteria

All sections pass on at least one IMX708 host, the imx290 negative cases return
`409`/`false`, the automated suite is green, and no live-view stall or recording
loss is observed during focus operations.

## Rollback

Revert the commit and re-run the playbook (`--limit` the IMX708 hosts). Clients
that never call `/focus` are unaffected; the service restart returns cameras to
the default single-autofocus behavior.

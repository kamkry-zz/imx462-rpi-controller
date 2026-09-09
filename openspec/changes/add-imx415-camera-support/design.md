# Design: add IMX415 camera support

## Context

See `proposal.md` for the motivation. Relevant current state:

- The IMX462 (imx290 overlay) requires the vendor `imx290` tuning on Pi 5 only;
  the IMX415 needs **no vendor files** — `imx415` overlay + `sony,imx415`
  driver ship in the Raspberry Pi kernel (rpi-6.6.y Bookworm onward) and
  stock libcamera ships `imx415` tuning for both pisp and vc4.
- The overlay is fully generic in the role already: csi platforms get the bare
  line (defaults to Unicam 1, the standard connector), Pi 5 gets the `camN`
  suffix — exactly what `imx415` needs (`dtoverlay=imx415`; `cam0` would select
  the empty CM CSI0 bus on csi boards — same trap as imx290).
- Sensor facts: single full-array 3864x2192 RAW10 readout (no RAW12, no bit
  depth selector), gain 0–100 × 0.3 dB ≈ ISO 100–3160, 20-bit VMAX (long
  exposures). On 2-lane csi links (~720 Mbps/lane) the readout is
  bandwidth-bound to ~15–17 fps at **any** output resolution; 4-lane Pi 5 CAM1
  reaches ~30 fps. Runtime libcamera reads stay authoritative; the static
  catalogs only serve tests/no-hardware and the started-camera case.
- `MIN_FRAME_US = 16_666` (1/60 s) is hard-coded in `service.py`
  (`_apply_snapshot_exposure`, `_metadata_loop`) and `app.js` (manual-exposure
  branch, snapshot default) — invalid for a ~15 fps sensor whose minimum frame
  time is ~67 ms.

## Goals / Non-Goals

Goals:
- IMX415 works end-to-end as a configured camera on csi platforms (test target:
  `raspberrypi-zero-2w-1`, IMX415 replacing its IMX462).
- Manual exposure / snapshots never request frame durations below the sensor's
  minimum frame time.
- Configurator produces sensible imx415 configs for both 2-lane csi boards and
  4-lane Pi 5 CAM1, and deployment catches outdated OSes up front.

Non-goals:
- New kernel/driver/tuning packaging (relies on mainline + stock libcamera).
- Changing config.yaml schema (overlay/params/default_mode already free-form).
- Supporting 4K60/other vendor modes beyond what the stock driver exposes.
- WebRTC or capture changes (main/lores layout already mode-agnostic).

## Decisions

### 1. Per-mode minimum frame duration instead of the 1/60 s constant

`MIN_FRAME_US` becomes a floor computed from the selected mode's framerate:
`ceil(1_000_000 / framerate)` (60 fps → 16 667 µs ≈ today's behaviour; 15 fps
→ 66 667 µs). Two touch points:

- `service.py`: a small `_min_frame_us(mode)` helper; `_apply_snapshot_exposure`
  clamps `frame = max(exposure_us, _min_frame_us(self._mode))` (fall back to
  `MIN_FRAME_US` while `self._mode is None`); `_metadata_loop` derives its
  "slow frame" skip threshold from the same helper when no explicit
  `FrameDurationLimits` is set.
- `app.js`: a `minFrameUs()` helper reads the framerate of the mode currently
  selected in the mode dropdown (`JSON.parse(el.modeSelect.value).framerate`)
  and returns `Math.ceil(1e6 / fps)`, falling back to 16 666 when unknown.
  Used at the manual-exposure branch and the snapshot default.

Rationale: the mode dropdown already carries the target mode and libcamera
validates `FrameDurationLimits`, so deriving from the advertised framerate is
the smallest correct source. Alternatives: exposing `min_frame_duration_us`
through the capabilities API (more plumbing, and the min frame is really a
property of the *mode*, not the camera); using a per-sensor constant catalog
(duplicates what runtime mode reads already know).

### 2. Fallback catalog values for imx415

- `_MODEL_MODES["imx415"]`: two modes, `3840x2160 @ 15 fps` and
  `3840x2160 @ 30 fps`, both `bit_depth=None` (RAW10-only, mirrors how imx708
  is catalogued). The UI mode dropdown is populated from this static catalog
  (`_modes_for_model` in `GET /api/cameras`), so the second entry is what makes
  the 30 fps profile selectable. Runtime `_read_sensor_modes` reports the
  driver's single 3864x2192 mode; output_size cropping (e.g. to 1080p) stays a
  configure-time choice. 15 fps is the honest ceiling on 2-lane csi links; 30
  fps only materializes on 4-lane ports — libcamera clamps the frame rate down
  on 2-lane boards, so offering both is safe.
- `_MODEL_BOUNDS["imx415"]`: `(MIN_FRAME_US, 30_000_000, 1.0, 31.6)` — gain
  max mirrors 30 dB (0.3 dB × 100); the 30 s exposure ceiling matches the UI
  shutter ladder and the IMX462 precedent for long single-frame captures. These
  are approximations superseded by live libcamera reads.
- `supports_raw12` stays keyed on `"imx290" in model` — no change.

### 3. Configurator: `imx415` as an overlay choice with a 4-lane variant

`OVERLAYS` gains two choices that map to one physical overlay:

- `imx415` → `params: ""`, default mode `3840x2160@15` (no bit depth key).
- `imx415-4lane` → entry carries `"overlay": "imx415"` + `params: "4lane"`,
  default mode `3840x2160@30`. Only valid on a Pi 5 CAM1 4-lane port (or other
  4-lane hardware) — the prompt label says so.

`OVERLAYS` entries may now specify an optional `overlay` key (defaults to the
dict key); `_camera_entry` uses `spec.get("overlay", choice)` so the emitted
host_vars overlay is always the real device-tree name (`imx415`), while the
4-lane profile is only a configurator-level choice. Keeping it a separate
*choice* (not a follow-up boolean) keeps JSON answers files flat and
validation simple.

### 4. Ansible: auto-detect + preflight live in the camera-overlay role

The role already owns `config.txt`. When any configured camera has
`overlay == "imx415"`:

- Preflight (fail fast, before writing anything): the kernel overlay dtbo must
  exist (`/boot/firmware/overlays/imx415.dtbo` on firmware-partition hosts,
  `/boot/overlays/imx415.dtbo` elsewhere) and the platform's tuning file must
  exist (`/usr/share/libcamera/ipa/rpi/{pisp,vc4}/imx415.json` selected via the
  play-level `imx462_is_pi5_pisp` fact). Failure message points at
  `apt update && apt full-upgrade` (kernel + libcamera packages).
- `camera_auto_detect=0` is ensured via `lineinfile` only when imx415 is
  present; when no imx415 is configured the line is never touched (legacy
  deployments keep their current file).

Rationale: the dtbo lives next to the config.txt the role edits; the tuning
check needs the pisp/vc4 fact the play already computed. No new facts needed
beyond `imx462_has_imx415`.

### 5. Cosmetic UI fix rides along

`populateModes` builds `RAW${m.bit_depth}` unconditionally; for null bit depths
it renders `RAWundefined` (already broken for imx708). The label becomes
`${w}x${h} @${fps}fps` when `bit_depth` is null, `${w}x${h} RAW${d} @${fps}fps`
otherwise. Tiny, testable via the capability/mode payloads; folded in since
imx415 modes are bit-depth-less by construction.

## Risks / Trade-offs

- [The real max fps of the imx415 driver mode may be slightly above/below 15]
  → Runtime capability reads surface the true bounds; 15 fps is the advertised
  default and the UI mode list comes from libcamera.
- [`FrameDurationLimits` floor from framerate may still be marginally below the
  sensor's real line budget] → libcamera clamps rather than errors for slight
  over-requests; verification on `raspberrypi-zero-2w-1` will confirm the
  metadata loop reports the achieved frame rate.
- [`camera_auto_detect=0` lingers if an imx415 deployment is later switched to
  legacy sensors] → harmless (explicit `dtoverlay` lines still apply); the role
  only ever adds it for imx415, documented in deployment.md.
- [4K main stream + 1280x720 lores MJPEG load on the Zero 2 W vc4 pipeline]
  → the UI can select lower output resolutions; a 1080p main still reads out
  the full 4K array at ~15 fps, so 4K is the useful default.

## Migration Plan

1. Deploy to `raspberrypi-zero-2w-1`: regenerate the git-ignored host_vars with
   `scripts/configure.py` (imx415, no 4-lane), run the playbook, reboot to
   activate `dtoverlay=imx415`, verify with `rpicam-hello --list-cameras`.
2. Verify capabilities (modes/fps/gain/exposure), live view, a manual-exposure
   change, and a long single-frame snapshot on the host.
3. Rollback: revert host_vars to the imx290 entry and re-run the playbook
   (role rewrites the overlay line and removes stale suffixed lines; the
   imx290 vendor tuning task is untouched by this change).

## Open Questions

None — the exact achievable exposure ceiling and any colour-tuning quirks of
the vendor module are resolved empirically on the test host after deploy and
would only adjust fallback *catalog* numbers (documented as approximations),
not the design.

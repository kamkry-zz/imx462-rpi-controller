# Design

## Context

See proposal.md - Why. The controller previously targeted only the Pi 5
(pisp) camera pipeline. Deploying to a Raspberry Pi Zero 2 W revealed two
platform assumptions: (1) the Ansible roles emit `,camN` overlay suffixes and
install a pisp-only vendor tuning file unconditionally, and (2) the application
lets picamera2 add a default `raw` stream to the video configuration, which
aborts the vc4 pipeline, while capability reads (`Picamera2.sensor_modes`)
reconfigure the camera from outside the worker lock.

## Goals / Non-Goals

Goals:
- Make deployment and the camera runtime correct on both the pisp (Pi 5) and
  csi (Pi 3/4, Zero 2W) platforms without per-host manual flags.
- Preserve existing Pi 5 behavior exactly (overlay lines with `,camN`, vendor
  tuning installed, stream configuration unchanged in effect).

Non-Goals:
- Host registration (inventory/host_vars) — git-ignored local config.
- Pi 4 dual-connector (two cameras on csi) support — the csi overlay default is
  Unicam 1; a second connector would need hand-written config.txt lines.
- Performance tuning of software-MJPEG on the Zero 2W.

## Decisions

### 1. Detect the platform from `/proc/device-tree/model`, not the IPA dir
Both `/usr/share/libcamera/ipa/rpi/pisp` and `.../vc4` exist on every install,
so directory existence is not a reliable signal. The device model string
(`"Raspberry Pi 5"` in model) is authoritative.
- Implementation: play `pre_tasks` slurp the model file and set the host fact
  `imx462_is_pi5_pisp`, consumed by both roles.
- Alternative considered: a per-host `imx462_cam0_dtoverlay_suffix` flag —
  rejected: error-prone and duplicates knowledge that can be detected.

### 2. Overlay suffix emitted only on pisp
The csi-platform `imx290`/`imx327` overlays default to Unicam 1 (the standard
single connector on Pi 2/3B+/Zero 2W); `cam0` selects the Compute Module CSI0
layout (an empty bus). The Pi 5 (pisp) overlays default differently and accept
`cam0`/`cam1`.
- Implementation: split the role's "Ensure overlay" task — the pisp variant
  keeps the existing `,cam{{ id }}` line + regexp; the csi variant writes the
  bare line with an overlay-anchored regexp
  (`^dtoverlay={{ overlay }}(,[^\s]*)*\s*$`) so stale `,cam0` lines are
  rewritten in place and other overlays' lines are untouched. Stale-slot removal
  stays unchanged.
- Alternative considered: emitting `cam1` explicitly on csi — rejected: the csi
  overlay has no `cam1` parameter; the default is the correct wiring.

### 3. Vendor tuning install/restore gated on the platform fact
The `innomakerpi5_imx290.json` file targets `"target": "pisp"`. On non-Pi 5
platforms the role keeps the stock `imx290.json` and restores it from the
`.rpi-default` backup when a previous (pisp-assuming) run had replaced it,
making the role self-healing.

### 4. `raw=None` in `create_video_configuration`
picamera2 0.3.x defaults `raw={}`, injecting a raw stream into every video
configuration. The vc4 pipeline aborts (SIGABRT, `stl_vector.h operator[]`
assertion) on a `main`+`lores`+`raw` config at `camera.start()`. The live path
never uses raw (JPEG from `main`, MJPEG from `lores`), so passing `raw=None`
drops it on all platforms — safe on pisp, required on vc4.

### 5. Capability reads serialized, cached, skipped while running
`Picamera2.sensor_modes` internally reconfigures the camera (raising
`RuntimeError` if it is running) and was invoked directly on the worker's
Picamera2 from the API thread, racing `configure_mode`.
- Implementation: `CameraWorker.capabilities()` acquires the camera lock,
  computes via `read_capabilities` once, caches the result, and returns `None`
  (→ static catalog fallback in `CameraManager`) while the camera is started.
  `CameraManager.capabilities()` submits it to the worker executor so it
  serializes with `configure_mode`/`set_controls`.
- Alternative considered: caching at the manager level — rejected: the worker
  lock is the correct serialization point.

## Risks / Trade-offs

- Pi 4 dual-camera (csi) would map both slots to Unicam 1 → Mitigation:
  out of scope, documented; Pi 4 single-camera keeps working.
- Skipping dynamic capability reads while the camera runs returns the static
  catalog → Mitigation: the imx290 catalog matches the sensor's real modes and
  bounds; the dynamic read still runs on first use before streaming starts.
- `raw=None` changes the config on pisp too → Mitigation: raw was unused on
  pisp; both hosts verified streaming after deploy.

## Migration Plan

1. Deploy to the Zero 2W (`ansible-playbook --limit raspberrypi-zero-2w-1`):
   the camera-overlay task rewrites config.txt to the bare line; reboot.
2. Deploy to the Pi 5: behavior unchanged, verified streaming.
3. Rollback: revert the role/app changes and re-run the playbook; on the Zero
   2W revert config.txt to the `,cam0` line and reboot (sensor will NAK on the
   wrong bus again, i.e. previous broken state).

## Open Questions

None.

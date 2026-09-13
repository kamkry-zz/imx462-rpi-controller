## Why

The Inno Maker **CAM-MIPI-IMX415** (4K STARVIS sensor) is a drop-in camera for
the same controller, but the application has no awareness of it: the static
fallback catalogs, the setup configurator, the deployment role, and the
documented overlay semantics only know the existing sensors (imx290/462,
imx708, imx219, ...). Unlike the IMX462, the IMX415 needs **no vendor
driver or tuning install** — the `imx415` overlay + `sony,imx415` driver ship
in the Raspberry Pi kernel (rpi-6.6.y Bookworm and later) and raspberrypi's
libcamera already carries `imx415` tuning for both the vc4 and pisp pipelines.
Two hard-coded 1/60 s assumptions additionally break on a ~17 fps sensor: the
snapshot/manual-exposure paths would request frame durations shorter than the
sensor's minimum frame time.

## What Changes

- Add the `imx415` overlay as a first-class camera option end to end: setup
  configurator (`scripts/configure.py`), config examples, Ansible host_vars
  example, docs, and the static per-model fallback catalogs (modes +
  exposure/gain bounds) in the camera service. Runtime capability reads from
  libcamera remain authoritative.
- Default the IMX415 to **3840x2160 @ 15 fps** on the csi/vc4 platforms
  (Pi 3/4, Zero 2 W — 2-lane, bandwidth-bound readout at ~17 fps regardless of
  output size) and offer a Pi 5 CAM1 `4lane` variant with a 4K @ 30 fps
  default mode for high-end boards.
- Replace the hard-coded `1/60 s` minimum frame duration with a per-camera
  minimum derived from the selected mode's framerate, so manual exposures and
  snapshots on low-framerate sensors (imx415 ~15 fps → ~67 ms min frame) never
  request an out-of-range frame duration. Applies to both the backend snapshot
  path and the web UI control path.
- Fix the mode dropdown label rendering `RAWundefined` for sensors whose modes
  carry no bit depth (imx708 today, imx415 as well).
- Deployment: ensure `camera_auto_detect=0` in `config.txt` **only when an
  imx415 camera is configured** (the vendor's documented requirement; legacy
  imx290/imx708 setups keep current behavior), and fail fast in the app role
  when the target OS lacks IMX415 support (missing `imx415` overlay dtbo or
  libcamera tuning file) with an actionable message.
- Test and deploy on `raspberrypi-zero-2w-1`, replacing its IMX462.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `camera-control`: manual-exposure and snapshot frame durations must respect
  the sensor's per-mode minimum frame time instead of a fixed 1/60 s floor, so
  low-framerate sensors (imx415 at ~15 fps) never receive an out-of-range
  `FrameDurationLimits`; mode reporting must continue to surface bit-depth-less
  modes cleanly.
- `deployment`: the setup configurator and roles must treat `imx415` as a
  supported overlay (bare overlay line on csi platforms, platform-appropriate
  default mode, optional `4lane` profile for Pi 5 CAM1), ensure
  `camera_auto_detect=0` in `config.txt` when an imx415 is configured, and fail
  fast with an actionable message when the target OS lacks imx415
  kernel/libcamera support.

## Impact

- `src/imx462_controller/camera/service.py` — `_MODEL_MODES`/`_MODEL_BOUNDS`
  gain an `imx415` entry; min frame duration becomes per-sensor in
  `_apply_snapshot_exposure` and the snapshot-framerate logic.
- `src/imx462_controller/static/app.js` — mode label for null bit depth; min
  frame duration derived from the selected mode's framerate.
- `scripts/configure.py` — `OVERLAYS["imx415"]`, optional 4-lane profile
  question; emitted host_vars.
- Ansible — `roles/camera-overlay/tasks/main.yml` (`camera_auto_detect=0` when
  imx415 configured), `roles/app/tasks/main.yml` (imx415 preflight check).
- Templates/examples — `config.example.yaml`, `ansible/host_vars/pi.example.yml`.
- Docs — `docs/architecture.md`, `docs/deployment.md`, `AGENTS.md`,
  `openspec/project.md`.
- Tests — `tests/test_camera_service.py`, `tests/test_configure.py`,
  `tests/test_config.py`.
- No new Python dependencies; no config schema change (overlay is a free
  string; params already supported). External: deploy to
  `raspberrypi-zero-2w-1` (IMX415 replaces the IMX462 there).

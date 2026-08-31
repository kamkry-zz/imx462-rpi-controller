## Why

Deploying the controller to a Raspberry Pi Zero 2 W — the first
previous-generation ("csi"/vc4 libcamera pipeline) board — exposed Pi 5-centric
assumptions in both the Ansible deployment and the application runtime. On the
csi platform the `,camN` dtoverlay suffix selects the Compute Module CSI0 layout
(an empty bus, so the sensor never answers on I2C), the vendor tuning file is
Pi 5/pisp-only, and picamera2's default `raw` stream in the video configuration
crashes the vc4 pipeline (SIGABRT) as soon as the live view starts; capability
reads also raced camera reconfiguration.

## What Changes

- **Platform detection**: the playbook reads `/proc/device-tree/model` in
  `pre_tasks` and sets a shared `imx462_is_pi5_pisp` fact consumed by both roles.
- **Platform-aware dtoverlay**: the `camera-overlay` role appends `,camN` only on
  Pi 5 (pisp); on the csi platform it writes the bare
  `dtoverlay=<overlay>[,params]` line (overlay default = Unicam 1, the standard
  camera connector), rewriting any stale `,cam0` line in place.
- **Platform-aware tuning**: the `app` role installs the vendor
  `innomakerpi5_imx290.json` tuning file only on pisp and restores the stock
  tuning on non-Pi 5 platforms.
- **No raw stream in live configuration**: `CameraWorker.configure_mode` passes
  `raw=None` to `create_video_configuration`, producing `main` + `lores` only.
- **Serialized capability reads**: `CameraWorker.capabilities()` reads sensor
  modes/control bounds under the camera lock, caches the result, and skips the
  dynamic read while the camera is running (static catalog fallback);
  `CameraManager.capabilities()` runs it on the worker executor.
- **Docs**: AGENTS.md records the hard-won platform facts; README and deployment
  docs cover previous-gen platform support.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities
- `deployment`: platform-aware dtoverlay suffix (pisp vs csi) and vendor tuning
  install/restore rules
- `live-view`: the camera stream configuration must not include a raw stream
- `camera-control`: capability reads are serialized with camera operations,
  cached, and skipped while the camera is running

## Impact

- Ansible: `ansible/playbook.yml`, `ansible/roles/camera-overlay/tasks/main.yml`,
  `ansible/roles/app/tasks/main.yml`
- Application: `src/imx462_controller/camera/service.py`
- Tests: `tests/test_camera_service.py`, `tests/test_api.py` (fake
  `create_video_configuration` accepts `raw`; new capabilities cache/skip tests)
- Docs: `AGENTS.md`, `README.md`, `docs/deployment.md`, `openspec/project.md`
- No API changes, no new dependencies. The Zero 2W host registration itself
  (git-ignored inventory/host_vars) is out of scope.

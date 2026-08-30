## Why

The controller was built around a single sensor — the Inno Maker IMX462 (via the
`imx290` overlay) — with hardcoded sensor modes, exposure/gain bounds, and shutter
/ISO ladders. Two IMX462 cameras on one Pi 5 exceed the board's power budget (red
LED, no boot), so users instead pair the IMX462 with an original Raspberry Pi
Camera Module (e.g. Camera Module 3 Wide, `imx708`) on the second port. The
Camera Module 3 exposes a different overlay, different resolutions (no RAW12, no
1920x1080), and different exposure/gain ranges, so the app must treat each camera
as its own sensor instead of assuming IMX462 everywhere.

## What Changes

- Read each camera's sensor model, supported modes, and exposure/gain bounds from
  libcamera at runtime (`Picamera2.sensor_modes` / `camera_controls`), with a
  static per-model catalog as a fallback for no-hardware/test environments.
- Surface per-camera capabilities via `GET /api/cameras/{id}/capabilities` and
  enrich `GET /api/cameras` with per-camera `default_mode` + `capabilities`.
- Let each configured camera declare its own device-tree overlay and optional
  per-camera default mode in `config.yaml` (`overlay`, `overlay_params`,
  `default_mode`); `bit_depth` is optional (omitted for single-bit-depth sensors).
- Drive the frontend's mode list and shutter/ISO ladders from the selected
  camera's capabilities rather than hardcoded IMX462 constants.
- Generalize Ansible to write one `dtoverlay=...,camN` line per configured camera
  (removing stale overlays for unconfigured slots) and install the IMX462 tuning
  file only when an `imx290` camera is configured.
- Extend `scripts/configure.py` to prompt per-camera overlay (imx290 / imx708 /
  imx219 / imx477 / ov5647 / imx296) for hybrid boards.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `camera-control`: add per-sensor capabilities; make mode bit depth optional and
  exposure range sensor-driven.
- `configuration`: cameras declare their overlay and an optional per-camera
  default mode.
- `deployment`: per-camera dtoverlay application with stale-slot cleanup.

## Impact

- Code: `src/imx462_controller/config.py`, `camera/service.py`, `api/routes.py`,
  `static/app.js`; `scripts/configure.py`.
- Deployment: `ansible/roles/camera-overlay/tasks/main.yml`,
  `ansible/roles/app/tasks/main.yml`, `ansible/playbook.yml`, host_vars/inventory
  examples; `config.example.yaml`.
- Docs/specs: `AGENTS.md`, `README.md`, `docs/architecture.md`,
  `docs/deployment.md`, `openspec/project.md`.
- Downstream: the cat-watcher service (`krysdom-api`) adds a second `imx462`
  stream and reads per-sensor exposure bounds from the new capabilities endpoint.

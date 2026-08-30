## 1. Per-sensor capabilities

- [x] 1.1 Extend `CameraConfig` with `overlay`, `overlay_params`, and optional `default_mode`; make `DefaultMode.bit_depth` / `CameraMode.bit_depth` optional
- [x] 1.2 Add runtime capability readout (`read_capabilities`, `_read_sensor_modes`, `_bit_depth_from_format`) and a static per-model fallback catalog
- [x] 1.3 Omit `bit_depth` from the sensor config when `None` in `configure_mode`
- [x] 1.4 Add `CameraManager.capabilities()` and per-camera `default_mode`; lock-guard worker creation
- [x] 1.5 Add unit tests for capability readout, single-bit-depth omission, and per-camera default mode

## 2. API

- [x] 2.1 Add `GET /api/cameras/{id}/capabilities`
- [x] 2.2 Enrich `GET /api/cameras` with per-camera `default_mode` and `capabilities`
- [x] 2.3 Add API tests for the capabilities endpoint (200 + 404)

## 3. Frontend

- [x] 3.1 Drive shutter/ISO ladders from the selected camera's capabilities
- [x] 3.2 Use per-camera default mode and refresh capabilities on camera selection

## 4. Ansible & configurator

- [x] 4.1 Generalize the `camera-overlay` role to per-camera dtoverlay with stale-slot cleanup
- [x] 4.2 Install the imx290 tuning file only when an imx290 camera is configured
- [x] 4.3 Update host_vars/inventory examples and `config.example.yaml` for heterogeneous cameras
- [x] 4.4 Extend `scripts/configure.py` to prompt per-camera overlay; update tests

## 5. Docs & specs

- [x] 5.1 Update AGENTS.md, README, docs/architecture.md, docs/deployment.md, openspec/project.md
- [x] 5.2 Update camera-control, configuration, and deployment specs

## 6. Verification

- [x] 6.1 Run pytest + ruff
- [x] 6.2 Validate OpenSpec artifacts

## Why

There is no software to drive the Inno Maker IMX462 camera on a Raspberry Pi
beyond raw vendor CLI examples. We need a deployable, API-first controller that
supports one or two cameras, exposes photo/video/live-view over a lightweight web
app, and reports operation, status, and metrics via MQTT and OpenTelemetry.

## What Changes

- Add a Python (FastAPI) application running on Raspberry Pi 3/4/5 (Raspberry Pi
  OS Bookworm) that controls IMX462 cameras via Picamera2/libcamera.
- Support one or two cameras simultaneously (cam0/cam1) through the `imx290`
  device-tree overlay.
- Expose every operation via a REST (JSON) API; the web frontend is a thin client.
- Capture still photos and record videos (start/stop) per camera.
- Provide MJPEG live-view streaming and WebSocket status/control push.
- Publish operation events, heartbeat/status, and metrics to an external MQTT
  broker (paho-mqtt).
- Export metrics, traces, and correlated logs to the k3s observability stack via
  OpenTelemetry OTLP.
- Centralize non-secret configuration in `config.yaml` and secrets in `.env`, with
  a committed template/example for every configurable file.
- Provide Ansible automation to provision the Pi (deps, dtoverlay, app, systemd
  unit, config/secrets).
- Provide an interactive, stdlib-only setup configurator
  (`scripts/configure.py`) that generates the git-ignored Ansible inventory and
  host_vars (masked secrets) for deploying to a fresh Pi.
- License the project under Apache-2.0; keep all secrets out of version control
  (only `*.example` templates are committed).

## Capabilities

### New Capabilities
- `camera-control`: enumerate and select cameras, configure sensor mode
  (resolution, RAW bit depth, framerate).
- `capture`: still-photo capture and video recording (start/stop) per camera.
- `live-view`: MJPEG live stream and WebSocket status/control push.
- `telemetry`: MQTT publication of operation events, heartbeat/status, and metrics.
- `observability`: OpenTelemetry metrics, traces, and correlated log export via
  OTLP.
- `configuration`: loading and validation of `config.yaml` and `.env`, with
  templates for all configurable files.
- `deployment`: Ansible provisioning and systemd service lifecycle.

### Modified Capabilities
<!-- none -->

## Impact

- New code: `src/` application package, `pyproject.toml`, `tests/`,
  `scripts/configure.py`.
- New runtime dependencies: FastAPI, uvicorn, picamera2, paho-mqtt,
  opentelemetry-distro, PyYAML, python-dotenv.
- New deployment artifacts: `ansible/` playbook/roles, `deploy/` systemd unit
  template, `config.example.yaml`, `.env.example`, setup configurator
  (`scripts/configure.py`).
- Infrastructure: requires an OTLP endpoint reachable from the Pi (the k3s
  collector `otel-collector.observability.svc` is cluster-internal and must be
  exposed externally) and an MQTT broker reachable over the network.

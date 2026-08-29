# imx462-rpi-controller

## Purpose
Controller software for Inno Maker's IMX462 (STARVIS) camera sensor on Raspberry Pi.
Targets one or two cameras simultaneously, exposed via a lightweight web app and a
REST API, with MQTT telemetry and OpenTelemetry observability. Deployed with Ansible.

## Target platforms
- Raspberry Pi 5 (primary today), compatible with Raspberry Pi 3 and above.
- Raspberry Pi OS **Bookworm (Debian 12) / Trixie (Debian 13)** (libcamera +
  Picamera2 stack). Older Bullseye/legacy camera stack is out of scope.

## Tech stack
- Language: **Python** (Raspberry Pi OS ships Python 3.11–3.13 depending on release).
- Camera: **Picamera2** (libcamera Python binding). Vendor enumerates the IMX462
  through the `imx290` device-tree overlay (see Hardware below).
- API: **REST (JSON)** via **FastAPI** + **uvicorn**. SOAP and gRPC are explicitly
  rejected; MQTT is used for telemetry only, never for request/response.
- Concurrency: **thread-per-camera** (one `Picamera2` instance per camera in its own
  thread, driven by a `ThreadPoolExecutor`). libcamera must remain in a single
  process; do not split camera ownership across processes.
- Live view: **MJPEG** (`multipart/x-mixed-replace`) initially; **WebRTC** is a
  later follow-up. Low-latency status/control push uses **WebSocket**.
- Telemetry: **paho-mqtt** to an external broker (host/port/credentials in `.env`).
- Observability: **OpenTelemetry** SDK exporting **OTLP** (metrics + traces +
  correlated logs) to the existing k3s observability stack (configurable endpoint).
- Deployment: **Ansible** over SSH by IP (keys pre-exchanged).

## Hardware gotchas (do not re-derive)
- The IMX462 is driven via the **`imx290`** overlay, NOT `imx462`:
  `dtoverlay=imx290,clock-frequency=74250000,cam0` (and `cam1` for the second camera)
  appended to `/boot/firmware/config.txt` (Pi 5 path; legacy uses `/boot/config.txt`).
- Supported modes: RAW10/RAW12 at 1280x720@60 and 1920x1080@60.
- Verify with `rpicam-hello --list-cameras` after reboot.

## Configuration & secrets
- Non-secret config in a dedicated `config.yaml`.
- Secrets (MQTT credentials, OTel tokens) in a local `.env` (git-ignored).
- Every configurable file ships a committed template/example
  (`config.example.yaml`, `.env.example`, Ansible inventory/host_vars examples,
  systemd unit template).

## Repo conventions
- API-first: every capability is reachable via REST; the frontend is a thin client.
- OpenSpec (`spec-driven` schema) is the source of truth for all development.
- `AGENTS.md` holds agent directives; see it before implementing.

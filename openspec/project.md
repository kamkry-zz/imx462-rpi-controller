# imx462-rpi-controller

## Purpose
Controller software for Inno Maker's IMX462 (STARVIS) camera sensor on Raspberry Pi.
Targets one or two cameras simultaneously, exposed via a lightweight web app and a
REST API, with MQTT telemetry and OpenTelemetry observability. Deployed with Ansible.

## Target platforms
- Raspberry Pi 5 (primary today) and previous-gen boards: Pi 3/4 and **Pi Zero
  2 W** (verified) on the csi/vc4 libcamera pipeline.
- Raspberry Pi OS **Bookworm (Debian 12) / Trixie (Debian 13)** (libcamera +
  Picamera2 stack). Older Bullseye/legacy camera stack is out of scope.

## Tech stack
- Language: **Python** (Raspberry Pi OS ships Python 3.11–3.13 depending on release).
- Camera: **Picamera2** (libcamera Python binding). Sensors are enumerated
  through their device-tree overlay: the IMX462 via `imx290`, the Raspberry Pi
  Camera Module 3 / 3 Wide via `imx708`, plus `imx219`/`imx477`/`ov5647`/`imx296`
  (see Hardware below).
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
  `dtoverlay=imx290,clock-frequency=74250000,cam0` appended to
  `/boot/firmware/config.txt` (Pi 5 path; legacy uses `/boot/config.txt`).
- **`camN` suffix is Pi 5/pisp-only.** On the csi platform the `imx290` overlay
  defaults to Unicam 1 (the standard single camera connector); `cam0` there
  selects the Compute Module CSI0 layout (empty bus → sensor NAKs on I2C). The
  Ansible roles emit the suffix only on pisp and install the vendor tuning file
  only on Pi 5 (stock restored on non-Pi 5).
- Supported modes (IMX462-specific): RAW10/RAW12 at 1280x720@60 and 1920x1080@60.
- Heterogeneous sensors are supported: each configured camera declares its own
  overlay (`imx290`, `imx708` for the Camera Module 3 / 3 Wide, `imx219`, `imx477`,
  `ov5647`, `imx296`). Modes and exposure/gain bounds are read from libcamera at
  runtime (`Picamera2.sensor_modes` / `camera_controls`); the read serializes
  with camera ops, caches, and is skipped while the camera runs.
- **`create_video_configuration` is called with `raw=None`**: picamera2's default
  raw stream crashes the vc4 pipeline (`main`+`lores`+`raw` → SIGABRT).
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

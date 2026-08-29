## Context

Greenfield repository. Target is Raspberry Pi 3/4/5 running Raspberry Pi OS
Bookworm (Debian 12) or Trixie (Debian 13), with libcamera + Picamera2 available.
The IMX462 sensor enumerates via
the `imx290` overlay (`dtoverlay=imx290,clock-frequency=74250000,cam0|cam1`).
Motivation and scope are in `proposal.md`; requirements are in `specs/`.

## Goals / Non-Goals

**Goals:**
- Single Python process, thread-per-camera, REST-first, MJPEG + WebSocket
  streaming, MQTT telemetry, OTLP observability, config/secrets split, Ansible
  deploy.

**Non-Goals:**
- WebRTC live view (future follow-up).
- SOAP/gRPC APIs (rejected).
- Multi-process camera sharing (unsupported by libcamera).
- Bullseye/legacy `picamera` stack.

## Decisions

### REST (JSON) via FastAPI + uvicorn
REST is the lightweight, ubiquitous, frontend-friendly choice. **Alternatives
considered:** SOAP (verbose XML, no benefit), gRPC (binary, needs a browser
proxy, heavier on Pi 3), MQTT (pub/sub, not request/response). MQTT is retained
for telemetry only.

### Thread-per-camera concurrency
Picamera2 blocking capture releases the GIL and libcamera requires a single
process to own a camera, so each camera gets its own worker thread driven by a
`ThreadPoolExecutor`; FastAPI async routes offload blocking work to it. No
multi-process camera sharing.

### MJPEG live view + WebSocket push
MJPEG (`multipart/x-mixed-replace`) works in a plain `<img>` and on Pi 3. WebRTC
deferred. WebSocket carries low-latency status/control push. Live view uses a
**persistent `lores` MJPEG encoder** plus a feed thread that fans frames to
per-client subscriber queues, so control changes never tear the stream down.

### Camera controls at runtime
`set_controls` applies exposure/gain/WB at runtime (no reconfigure), so toggling
manual exposure never freezes the live view. Only `configure_mode` (mode change)
and `set_flip` reconfigure, which aborts the in-flight frame. The frontend sends
`FrameDurationLimits = (max(shutter, 1/60s), max(shutter, 1/60s))` so fast
shutters keep 60 fps. Shutter/ISO use 0.3 EV ladders; ISO is `AnalogueGain × 100`.

### Video container (MP4 remux)
The hardware H.264 encoder emits raw `.h264`; on stop the app remuxes to `.mp4`
via `ffmpeg -c copy` (present at `/usr/bin/ffmpeg`), falling back to `.h264` if
ffmpeg is absent. Captured media is exposed through `/api/assets` (list /
download / delete with metadata).

### Vendor tuning file
The IMX462 has a colour cast under the stock `imx290.json`. Ansible installs the
vendor's `innomakerpi5_imx290.json` as
`/usr/share/libcamera/ipa/rpi/pisp/imx290.json` (backing up the original to
`imx290.json.rpi-default`). `LIBCAMERA_RPI_TUNING_FILE` is not honored by this
libcamera build, so the model-name file is replaced instead.

### OpenTelemetry via `opentelemetry-distro[otlp]`
Auto-instrumentation for FastAPI/HTTP plus explicit camera-operation spans.
Metrics, traces, and correlated logs export over OTLP (HTTP/protobuf) to a
configurable endpoint. The k3s collector is cluster-internal
(`otel-collector.observability.svc:4318`); the external Pi needs an
externally-reachable endpoint (Gateway/HTTPRoute or NodePort). Uvicorn loggers
must be set to `propagate: True` for access logs to reach the OTel log handler.

### Config/secrets split with templates
Non-secret values in `config.yaml` (PyYAML), secrets in `.env` (python-dotenv),
git-ignored. Every configurable file has a committed `*.example` template.

### Ansible deploy + systemd
Playbook (SSH by IP) installs deps, applies the `imx290` dtoverlay to
`/boot/firmware/config.txt`, copies the app into a virtualenv, renders
config/`.env` from templates, and installs/enables a systemd unit (restart on
failure, start on boot). Inventory/host_vars git-ignored with `*.example`
templates.

### Repo layout
`src/` application package, `pyproject.toml`, `tests/`, `ansible/` (playbook,
roles; systemd unit in `ansible/roles/app/templates/`), `config.example.yaml`,
`.env.example`, `docs/`, `samples/` (example captured outputs).

## Risks / Trade-offs

- [OTLP endpoint unreachable from Pi] → endpoint is configurable; OTel SDK
  batches/retries and never blocks camera operations.
- [Pi 3 CPU constraints for multiple cameras] → one worker thread per camera,
  MJPEG over WebRTC keeps baseline cheap; document Pi 5 as recommended.
- [dtoverlay path differs between Pi 5 (`/boot/firmware`) and legacy] → Ansible
  role detects the firmware path instead of hardcoding.
- [libcamera single-process constraint] → enforce via architecture; never spawn
  a second process for the same camera.
- [Uvicorn access logs bypass OTel by default] → force `propagate: True` in the
  uvicorn log config (with a test).
- [External OTLP endpoint not yet exposed in the k3s cluster] → flagged as a
  deployment prerequisite; default config ships a placeholder endpoint.
- [Max exposure ≈ 1 s] → the sensor's 16-bit frame-length register caps exposure
  at ~1 s; the UI only offers shutter speeds up to 1 s (longer values are clamped).

## Migration Plan

1. Provision Pi with Ansible (deps + dtoverlay + app + systemd), reboot.
2. Verify `rpicam-hello --list-cameras` shows cam0 (and cam1).
3. Start the service; smoke-test REST endpoints, MJPEG, MQTT, and OTLP export.
4. Rollback = stop/disable the systemd unit and revert the config.txt overlay.

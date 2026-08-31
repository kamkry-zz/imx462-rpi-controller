# AGENTS.md

Directives for OpenCode sessions in this repo. OpenSpec (`openspec/`) is the source
of truth for planning; `openspec/project.md` holds the full stack/domain context.

## Hardware (hard-won — do not re-derive)
- The Inno Maker IMX462 is driven via the **`imx290`** overlay, not `imx462`:
  `dtoverlay=imx290,clock-frequency=74250000,cam0`. Append to
  `/boot/firmware/config.txt` on Pi 5 (`/boot/config.txt` on legacy), then
  `sudo reboot`. Verify with `rpicam-hello --list-cameras`.
  **Platform-dependent `camN` suffix**: on the csi platform (Pi 2/3B+/Zero 2W)
  the `imx290` overlay defaults to **Unicam 1 — the standard camera connector**,
  and `cam0` would select the Compute Module CSI0 layout instead (empty bus →
  `Error writing reg 0x3000: -5`; verified on `raspberrypi-zero-2w-1`). The
  Ansible `camera-overlay` role emits the suffix only on Pi 5 (pisp), where
  `cam0`/`cam1` select the RP1 CSI ports.
- Sensor modes: RAW10/RAW12 at `1280x720@60` and `1920x1080@60`.
- **Heterogeneous cameras** are supported: each configured camera declares its own
  device-tree overlay in `config.yaml` (`imx290` for the IMX462, `imx708` for the
  Camera Module 3 / 3 Wide, plus `imx219`/`imx477`/`ov5647`/`imx296`). The Ansible
  `camera-overlay` role writes one `dtoverlay=...,camN` line per camera and removes
  stale lines for unconfigured slots, so switching cam1 from `imx290` to `imx708` is
  handled by a re-run + reboot.
- Supported modes and exposure/gain bounds are **read from libcamera at runtime**
  (`Picamera2.sensor_modes` / `camera_controls`) and surfaced via
  `GET /api/cameras/{id}/capabilities`; a static per-model catalog is only a fallback
  for no-hardware/test environments. `bit_depth` is only passed to the sensor for
  multi-bit-depth RAW sensors (imx290); the IMX708 (10-bit only) omits it.
- Target: Raspberry Pi OS **Bookworm (Debian 12) / Trixie (Debian 13)** (libcamera +
  Picamera2). Supports Pi 3/4/5. Bullseye/legacy `picamera` stack is out of scope.
- Raspberry Pi OS ships no system `pip` (externally-managed env): run the app in a
  venv created with `--system-site-packages` so the apt-installed `picamera2` is
  importable. Newer images may not have a `pi` user — the default login user is
  `user` (uid 1000); use it as the systemd service user.

## Architecture constraints
- Camera access is via **Picamera2** in a **single process**, one instance per camera
  in its own thread (blocking capture releases the GIL). Never share one camera
  across processes.
- **REST-first**: every operation is exposed via FastAPI (JSON). The web frontend is
  a thin client only. SOAP/gRPC are rejected; MQTT is telemetry-only.
- Live view = **MJPEG** (`multipart/x-mixed-replace`) now; WebRTC is a later
  follow-up. Status/control push = WebSocket.
- Per-camera Picamera2 stream layout: `main` (YUV420, full-res) for stills +
  H.264 recording; `lores` (downscaled) for always-on MJPEG via the hardware
  `MJPEGEncoder`. This keeps live view and recording/photo independent. Video
  records raw H.264 then **remuxes to `.mp4`** via `ffmpeg`
  (`/usr/bin/ffmpeg`, `-c copy`); falls back to `.h264` if ffmpeg is absent.
- **`create_video_configuration` must be called with `raw=None`.** picamera2
  defaults to adding a `raw` stream, and a `main`+`lores`+`raw` config aborts
  the vc4 pipeline (`stl_vector.h operator[]` assertion, SIGABRT, on
  Pi 3/4/Zero 2W — verified on `raspberrypi-zero-2w-1`); the live path never
  uses raw (JPEG comes from `main`, MJPEG from `lores`).
- Capabilities are read via `Picamera2.sensor_modes`, which **reconfigures the
  camera internally** and raises if the camera is running — `read_capabilities`
  runs on the worker executor under the camera lock, caches its result, and
  skips the dynamic read while the camera is started (static catalog fallback).
- Live view uses a **persistent MJPEG encoder** + a feed thread that fans frames
  out to per-client subscriber queues (the stream is never torn down on control
  changes). `set_controls` applies at **runtime** (no reconfigure); only
  `configure_mode` (mode change) and `set_flip` reconfigure (aborting the
  in-flight frame).
- MQTT (paho-mqtt) publishes operation events, heartbeat/status, and metrics to an
  external broker.
- OTel exports OTLP (metrics + traces + correlated logs) to the k3s observability
  stack; the endpoint is configurable. NOTE: the cluster collector is
  `otel-collector.observability.svc` (cluster-internal) — the external Pi needs a
  reachable endpoint (Gateway/NodePort), not a `*.svc` name.

## Camera controls & hardware limits (hard-won — do not re-derive)
- **IMX462-specific ranges.** The ~115 s native exposure and ISO 100–3200 figures
  below apply to the IMX290/IMX462 only; other sensors (e.g. the Camera Module 3
  IMX708) expose their own bounds, read from libcamera via `/api/cameras/{id}/capabilities`.
- **Native exposure range up to ~115 s** — the IMX290/IMX462 24-bit `VMAX`
  register plus adjustable `HMAX` lets libcamera expose a single-frame exposure
  of ~115 s (verified: `ExposureTime` control max ≈ 115686258 µs at 1080p). The
  UI's 1–30 s shutter ladder is captured natively; no software stacking needed.
- **`set_controls` changes lag ~10 in-flight frames** — libcamera applies runtime
  control changes only after the buffered requests drain; at long exposures
  (e.g. 30 s/frame) that is *minutes*, so `capture_snapshot` applies the exposure
  via a **reconfigure** (`configure_mode` bakes controls into the config, applied
  on the first frame). The UI's manual-exposure changes still use runtime
  `set_controls` (fine at 60 fps, ~160 ms lag).
- **ISO = gain × 100** (`AnalogueGain` 1.0–31.6 → ISO 100–3200). `AnalogueGain`
  min is 1.0, so ISO < 100 (e.g. 50) is not achievable.
- Shutter and ISO use **0.3 EV (1/3-stop) ladders**; an **anti-flicker** selector
  (Off / 50 Hz / 60 Hz) filters the shutter list to mains-safe speeds (multiples
  of 1/100 s for 50 Hz, 1/120 s for 60 Hz) AND sets the real
  `AeFlickerPeriod` control (0 / 10000 / 8333 µs).
- White balance: `AwbEnable` toggle + `ColourTemperature` (Kelvin). `ColourGains`
  is ignored while AWB is on — always set `AwbEnable` alongside manual WB.
- `ExposureTime` must be paired with `FrameDurationLimits = (max(shutter, 1/60s),
  max(shutter, 1/60s))` so fast shutters keep 60 fps; reset to `(1/60s, 1/60s)`
  when Auto Exposure is re-enabled.
- **Single-frame capture mode** (`PUT /api/cameras/{id}/stream-mode`): switches
  between continuous MJPEG live view and an at-rest single-shot mode (MJPEG
  encoder torn down). `POST /api/cameras/{id}/snapshot` takes one still at the
  requested exposure and saves it to the gallery. The UI auto-enters single-frame
  mode when the selected shutter exceeds 2 s. **Entering continuous mode
  reconfigures the camera** so any pending exposure change (e.g. leaving a long
  single-frame exposure) applies immediately instead of lagging ~10 in-flight
  frames; the UI resets to auto exposure when the single-frame button is
  toggled off.
- Vendor tuning file `innomakerpi5_imx290.json` is installed as
  `/usr/share/libcamera/ipa/rpi/pisp/imx290.json` (original backed up to
  `imx290.json.rpi-default`) to correct the IMX462 colour cast. The env var
  `LIBCAMERA_RPI_TUNING_FILE` is NOT honored by this libcamera build. The
  vendor tuning is **Pi 5 (pisp) specific**; on previous-gen pipelines (vc4,
  e.g. Pi 3/4/Zero 2W) the role detects the device model (not the IPA dir —
  both `pisp` and `vc4` dirs exist on every install) and keeps the stock
  `imx290.json` (no vendor colour fix there), restoring it if previously
  installed.
- Current settings (gain/exposure) are read back via `capture_metadata()` from a
  background poll thread and surfaced in the WebSocket status payload (skipped
  while recording). The read runs **outside** the camera lock (with a timeout) so
  a stalled sensor can never freeze the feed thread or control operations.

## Configuration & secrets
- Non-secret values → `config.yaml`. Secrets → local `.env` (git-ignored).
- Every configurable file must have a committed template/example
  (`config.example.yaml`, `.env.example`, Ansible inventory/host_vars examples,
  systemd unit template). Add a template whenever you add a config key.
- Captured media lives in `capture.output_dir` (`/var/lib/imx462-controller/media`
  by default) and is exposed via `/api/assets` (list / download / delete, with
  filename+kind+size+modified metadata, traversal-safe).
- For a fresh Pi, generate the local (git-ignored) Ansible inventory + host_vars
  with `python3 scripts/configure.py` (interactive, masked secrets; JSON answers
  file + `--yes` for scripting).
- License: Apache-2.0 (see LICENSE). Never commit secrets, `config.yaml`,
  `.env`, `ansible/inventory.ini`, or `ansible/host_vars/*` (except `*.example.yml`).

## Commands
- Setup configurator: `python3 scripts/configure.py`
  (stdlib-only; writes git-ignored `ansible/inventory.ini` +
  `ansible/host_vars/<hostname>.yml`; run on the deploy machine before Ansible).
- Deploy: `ansible-playbook -i ansible/inventory.ini ansible/playbook.yml` (SSH by
  IP, keys pre-exchanged). Inventory/host_vars are git-ignored; use the `*.example`
  files as templates.
- Frontend design: use the `ui-ux-pro-max` skill; run its search scripts with
  `python3 .opencode/skills/ui-ux-pro-max/scripts/search.py ...` (see the skill).

## Development workflow
- All work is planned via OpenSpec (`spec-driven`): propose → specs → design → tasks,
  then apply. Start changes with `/opsx-propose`, implement with `/opsx-apply`,
  finalize with `/opsx-archive`.
- The propose/apply/archive skills live in `.opencode/skills/`; commands in
  `.opencode/commands/`.

## 1. Project scaffolding

- [x] 1.1 Create `pyproject.toml` with dependencies (fastapi, uvicorn, picamera2, paho-mqtt, opentelemetry-distro[otlp], PyYAML, python-dotenv, pydantic) and console script entrypoint
- [x] 1.2 Create `src/` package layout (config, camera, api, mqtt, otel, main)
- [x] 1.3 Add `config.example.yaml` and `.env.example` templates
- [x] 1.4 Add `.gitignore` entries for `.env`, `config.yaml`, Ansible inventory/host_vars, `__pycache__`, media output

## 2. Configuration & secrets

- [x] 2.1 Implement config loading/validation from `config.yaml` (server, cameras, mqtt topics, otel endpoint, output paths)
- [x] 2.2 Implement `.env` loading (MQTT credentials, tokens) via python-dotenv
- [x] 2.3 Fail fast with clear errors on missing/invalid config
- [x] 2.4 Add unit tests for config loading and validation

## 3. Camera control & capture

- [x] 3.1 Implement camera enumeration (cam0/cam1) and mode listing via Picamera2
- [x] 3.2 Implement per-camera worker threads with a `ThreadPoolExecutor`
- [x] 3.3 Implement sensor mode configuration (resolution, RAW bit depth, framerate)
- [x] 3.4 Implement still-photo capture to configured output directory
- [x] 3.5 Implement video start/stop recording
- [x] 3.6 Add unit tests for camera service logic (mocked Picamera2)

## 4. REST API

- [x] 4.1 Implement FastAPI app with routers for cameras, capture, and config
- [x] 4.2 Implement camera list/select/mode endpoints
- [x] 4.3 Implement photo capture and video start/stop endpoints
- [x] 4.4 Implement MJPEG live-view streaming endpoint
- [x] 4.5 Implement WebSocket status push endpoint
- [x] 4.6 Serve the static frontend from FastAPI
- [x] 4.7 Add API integration tests

## 5. MQTT telemetry

- [x] 5.1 Implement paho-mqtt client with auto-reconnect
- [x] 5.2 Publish operation events (photo/video/config)
- [x] 5.3 Publish periodic heartbeat/status
- [x] 5.4 Publish metrics
- [x] 5.5 Add tests for MQTT publisher (mocked client)

## 6. OpenTelemetry observability

- [x] 6.1 Wire opentelemetry-distro auto-instrumentation and OTLP exporter
- [x] 6.2 Add explicit spans for camera operations
- [x] 6.3 Force uvicorn log propagation (`propagate: True`) with a test
- [x] 6.4 Make OTLP endpoint/service name configurable; graceful degradation on unreachable endpoint

## 7. Frontend (ui-ux-pro-max)

- [x] 7.1 Generate design system with the `ui-ux-pro-max` skill
- [x] 7.2 Build single-page frontend (camera select, photo/video controls, MJPEG live view, status panel)
- [x] 7.3 Wire frontend to REST + WebSocket endpoints

## 8. Deployment (Ansible + systemd)

- [x] 8.1 Create Ansible playbook and roles (deps, dtoverlay, app deploy, config render, systemd unit)
- [x] 8.2 Add inventory/host_vars `*.example` templates
- [x] 8.3 Add systemd unit template with restart-on-failure
- [x] 8.4 Detect firmware config path (`/boot/firmware` vs `/boot`) in the dtoverlay role
- [x] 8.5 Document deploy + rollback steps

## 9. Verification

- [x] 9.1 Run lint/typecheck/test suite
- [x] 9.2 Validate OpenSpec artifacts (`openspec validate`)
- [x] 9.3 Smoke-test end-to-end on a Pi if available

## 10. Camera controls & assets (post-scaffolding)

- [x] 10.1 Add exposure controls (AE toggle, 0.3 EV shutter/ISO, ~1 s limit, runtime `set_controls`)
- [x] 10.2 Add white balance (AWB toggle + Kelvin) and H/V flip
- [x] 10.3 Add 50/60 Hz anti-flicker shutter filter
- [x] 10.4 Add assets gallery (list/download/delete with metadata, traversal-safe)
- [x] 10.5 Remux video to `.mp4` via ffmpeg with `.h264` fallback
- [x] 10.6 Add fullscreen live view and current ISO/shutter read-back
- [x] 10.7 Install vendor tuning file via Ansible for correct IMX462 colour

## 11. Long exposure & single-frame capture

- [x] 11.1 Extend the shutter ladder to 1/2/5/10/15/30 s; set `AeFlickerPeriod` on anti-flicker change
- [x] 11.2 Fix dropdown value formatting and mirror read-back gain/exposure into the disabled AE fields
- [x] 11.3 Guard control payloads against NaN/null and make `capture_metadata` non-blocking
- [x] 11.4 Add the `snapshot` endpoint (exposure applied via reconfigure; native exposures up to ~115 s)
- [x] 11.5 Add `stream-mode` + `snapshot` endpoints and the single-frame capture toggle
- [x] 11.6 Auto-enter single-frame mode for shutter > 2 s and set default mode on open
- [x] 11.7 Add tests for sanitization, snapshot (short + long exposure), stream mode, and settings read-back

## 12. Public release & setup configurator

- [x] 12.1 Add interactive ASCII/color setup configurator (`scripts/configure.py`, stdlib-only)
- [x] 12.2 Generate git-ignored Ansible inventory + host_vars; mask secrets; overwrite protection; `--answers-file` for scripting
- [x] 12.3 Add tests for the configurator (generated INI/YAML validity, CLI run, overwrite refusal)
- [x] 12.4 Harden `.gitignore` (un-ignore `*.example.yml`, ignore `build/` + `samples/`)
- [x] 12.5 Rewrite README; update AGENTS.md, docs (deployment/architecture)
- [x] 12.6 Document Apache-2.0 licensing and the secrets policy
- [x] 12.7 Update OpenSpec proposal/specs for the configurator + secrets handling

## 13. Continuous integration

- [x] 13.1 Add GitHub Actions workflow running pytest (Python 3.11/3.12/3.13) on PRs/pushes to `main`
- [x] 13.2 Add a ruff lint job to the CI workflow
- [x] 13.3 Document CI in README and add a CI requirement to the deployment spec

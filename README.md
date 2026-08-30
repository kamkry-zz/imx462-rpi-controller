# IMX462 RPi Controller

Controller software for the **Inno Maker IMX462** (Sony STARVIS) camera on a
Raspberry Pi (Pi 3/4/5, Raspberry Pi OS **Bookworm/Trixie**). API-first FastAPI
application with a thin web frontend: live MJPEG view, stills, video,
full exposure/ISO/white-balance control, long exposures up to ~30 s with a
single-frame capture mode, MQTT telemetry, and OpenTelemetry observability.
Deployed with Ansible.

## Features

- One or two cameras (`cam0`/`cam1`), heterogeneous sensors supported — the
  IMX462 via the `imx290` dtoverlay and Raspberry Pi Camera Modules (e.g. Camera
  Module 3 / 3 Wide via `imx708`) via their own overlays, each with per-camera
  modes and exposure/gain bounds read from libcamera
- MJPEG live view + WebSocket status push (current ISO/shutter, clients)
- Stills, video (H.264 → MP4 remux via ffmpeg), and long-exposure
  single-frame captures (1–30 s, native sensor exposures up to ~115 s)
- Manual exposure (1/600 s – 30 s), ISO (100–3200), white balance (Kelvin),
  H/V flip, 50/60 Hz anti-flicker, auto-exposure read-back
- Assets gallery (list / download / delete)
- MQTT events/status/metrics; OpenTelemetry OTLP metrics + traces + logs
- Ansible provisioning + systemd service

## Quick start (fresh Raspberry Pi)

1. **Generate local deployment files** (interactive, with ASCII/color prompts):

   ```sh
   python3 scripts/configure.py
   ```

   This writes the git-ignored `ansible/inventory.ini` and
   `ansible/host_vars/<hostname>.yml` (secrets included; masked during input).
   For scripting/CI, pass a JSON answers file:

   ```sh
   python3 scripts/configure.py --answers-file answers.json --yes
   ```

2. **Deploy** (SSH keys pre-exchanged, target powered on):

   ```sh
   ansible-playbook -i ansible/inventory.ini ansible/playbook.yml
   ```

3. **Reboot** the Pi to activate the camera dtoverlay, then open
   `http://<pi>:8000/`.

See [docs/deployment.md](docs/deployment.md) for details, prerequisites, and
rollback.

## Configuration & secrets

- Non-secret values live in `config.yaml` (rendered by Ansible from host_vars).
- Secrets (MQTT credentials, OTel headers) live in `.env` on the device and in
  `imx462_env` in `ansible/host_vars/<hostname>.yml` locally.
- Both are **git-ignored**; only `*.example` templates are committed. Never
  commit `config.yaml`, `.env`, `ansible/inventory.ini`, or host_vars.
- For production, encrypt the secrets with `ansible-vault encrypt` (see
  deployment docs).

## Development

- Spec-driven development via OpenSpec (`openspec/`) — see `AGENTS.md`.
- Tests: `python -m pytest` · Lint: `ruff check .`
- CI: GitHub Actions runs `pytest` (Python 3.11/3.12/3.13) and `ruff` on every
  pull request and push to `main` (`.github/workflows/ci.yml`).
- Dependencies: updated automatically via Renovate (`renovate.json`) — PRs are
  opened once the Renovate app is installed on the repository.

## License

Apache License 2.0. Copyright © 2026 the project contributors.
See [LICENSE](LICENSE).

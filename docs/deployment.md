# Deployment

## Prerequisites

- Target Raspberry Pi (3/4/5) running Raspberry Pi OS **Bookworm (Debian 12) or
  Trixie (Debian 13)**.
- SSH access by IP with pre-exchanged keys (passwordless for the `pi`/service user).
- A reachable MQTT broker and an externally-reachable OTLP endpoint (the k3s
  collector `otel-collector.observability.svc` is cluster-internal; expose it via
  Gateway/NodePort before deploying).

## Deploy

1. Generate the local Ansible inventory and host_vars (recommended):

   ```sh
   python3 scripts/configure.py
   ```

   This interactive, stdlib-only tool walks through the target, camera count,
   application, MQTT, and OpenTelemetry questions (secrets are masked during
   input) and writes the git-ignored `ansible/inventory.ini` and
   `ansible/host_vars/<hostname>.yml`. For scripting/CI, provide a JSON answers
   file:

   ```sh
   python3 scripts/configure.py --answers-file answers.json --yes
   ```

   Alternatively, copy the templates manually and edit:

   ```sh
   cp ansible/inventory.ini.example ansible/inventory.ini
   cp ansible/host_vars/pi.example.yml ansible/host_vars/<hostname>.yml
   ```

   Edit the target IP, camera count, config values, and secrets. For
   production, encrypt the secrets in host_vars:

   ```sh
   ansible-vault encrypt ansible/host_vars/<hostname>.yml
   ```

2. Run the playbook:
   ```sh
   ansible-playbook -i ansible/inventory.ini ansible/playbook.yml
   ```
   This installs `python3-picamera2`, creates the app venv
   (`--system-site-packages` so picamera2 is importable), renders `config.yaml`
   and `.env`, installs the systemd unit, and applies the `imx290` dtoverlay.

3. Reboot to activate the dtoverlay:
   ```sh
   ssh <host> sudo reboot
   ```

4. Verify:
   ```sh
   ssh <host> rpicam-hello --list-cameras        # shows cam0 (and cam1)
   ssh <host> systemctl status imx462-controller
   ```
   The web UI is served on `http://<host>:8000/`.

> **Secrets:** `config.yaml`, `.env`, `ansible/inventory.ini`, and
> `ansible/host_vars/<hostname>.yml` are git-ignored. Never commit them. Only
> the `*.example` templates belong in the repository.

## Rollback

1. Stop and disable the service:
   ```sh
   ssh <host> sudo systemctl disable --now imx462-controller
   ```
2. Remove the dtoverlay lines from `/boot/firmware/config.txt` (or
   `/boot/config.txt` on legacy) and reboot.
3. Optionally remove `/opt/imx462-controller` and the systemd unit file.

The systemd unit has `Restart=on-failure`, so a crashed service restarts
automatically; check `journalctl -u imx462-controller` for logs.

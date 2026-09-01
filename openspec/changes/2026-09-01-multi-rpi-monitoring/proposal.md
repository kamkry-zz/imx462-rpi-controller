## Why

The fleet now has three Raspberry Pis running the controller (Pi 5 `raspberrypi-5-2`, Zero 2 W `raspberrypi-zero-2w-1` with IMX462, and a newly added Zero 2 W `raspberrypi-zero-2w-2` with a Camera Module 3 Wide), but observability could not tell them apart: all hosts shared a single `service.name` and the node_exporter scrape covered only the Pi 5. Each Pi needs to be individually monitorable in Grafana/Loki/Prometheus.

## What Changes

- Deploy `raspberrypi-zero-2w-2` (Zero 2 W, single Camera Module 3 Wide via the `imx708` overlay) using the existing Ansible playbook and a new git-ignored inventory entry + host_vars.
- Add a stable per-host OpenTelemetry resource identity (`host.name` + `service.instance.id`, set via `OTEL_RESOURCE_ATTRIBUTES` in `.env`) to every provisioned Pi, so metrics, traces, and logs are split per host without changing the shared `service.name`.
- Extend the setup configurator (`scripts/configure.py`) and all committed templates/examples (`.env.example`, `ansible/host_vars/pi.example.yml`) with the new `OTEL_RESOURCE_ATTRIBUTES` key; add configurator test coverage.
- Scrape `node_exporter` on all three Pis from the cluster observability stack (collector scrape job `imx462-rpi` in the krysdom-api observability chart — already shipped; documented here as context).

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `observability`: per-host resource identity — each instance exports `host.name` and `service.instance.id` resource attributes so multi-Pi deployments are distinguishable in Prometheus (`instance` label), Loki (`host_name` label), and Tempo.
- `configuration`: the new `OTEL_RESOURCE_ATTRIBUTES` secrets key is honored from `.env` and covered by committed templates/examples.
- `deployment`: single-camera `imx708` deployments on csi-platform boards (bare overlay line, no `bit_depth`/params), and `prometheus-node-exporter` installed and enabled on every provisioned Pi.

## Impact

- `scripts/configure.py`: emits `OTEL_RESOURCE_ATTRIBUTES` (derived from the target hostname) in generated host_vars.
- `.env.example`, `ansible/host_vars/pi.example.yml`: document the new key.
- `tests/test_configure.py`: asserts the generated key.
- Ansible inventory/host_vars (git-ignored, applied live): `raspberrypi-zero-2w-2` entry + per-host `OTEL_RESOURCE_ATTRIBUTES` for all three Pis.
- External (already shipped): krysdom-api `observability/values.yaml` collector scrape targets for `raspberrypi-zero-2w-1.krysdom:9100` and `raspberrypi-zero-2w-2.krysdom:9100`.
- No application code changes; the OTel SDK merges `OTEL_RESOURCE_ATTRIBUTES` automatically.

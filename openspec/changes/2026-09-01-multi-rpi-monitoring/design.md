# Design: Multi-RPi monitoring

## Context

See `proposal.md` for motivation. Three Pis run the controller app; observability
could not attribute telemetry to a specific Pi (shared `service.name`, opaque
random `service.instance.id`), and only the Pi 5's node_exporter was scraped.

Key existing behavior (verified on live cluster):
- The app's `setup_telemetry` builds `Resource.create({"service.name": ...})` —
  the OTel Python SDK merges the `OTEL_RESOURCE_ATTRIBUTES` env var into that
  resource automatically, so **no application code changes are needed**.
- The systemd unit loads `.env` via `EnvironmentFile`, so any key rendered there
  is present in the process environment at startup.
- The cluster deployment collector has no `resource`/`k8sattributes` processors,
  so resource attributes from external Pis pass through unchanged; its
  Prometheus exporter maps `service.instance.id` → `instance` and
  `service.name` → `job`. Loki preserves resource attributes as labels
  (`host.name` → `host_name`).
- The Grafana `imx462-rpi-controller` dashboard queries `job="imx462-rpi-controller"`
  and `service="imx462-rpi-controller"` — the shared `service.name` must stay.

## Goals / Non-Goals

Goals:
- Stable per-Pi identity (`host.name`, `service.instance.id` = Pi FQDN) across
  metrics, traces, and logs, without touching app code.
- node_exporter scraped for all three Pis.
- Templates/examples updated so a future Pi gets the identity by default.

Non-goals:
- Splitting `service.name` per Pi or restructuring dashboards (kept working as-is).
- Any change to the collector pipeline (already passing attributes through).
- Monitoring beyond the camera fleet (cluster nodes, other external hosts).

## Decisions

1. **Configure identity via `OTEL_RESOURCE_ATTRIBUTES` in `.env` rather than a
   new config.yaml key or app code change.**
   Rationale: zero code change; the SDK merge behavior is standardized; the
   systemd `EnvironmentFile` already delivers `.env` to the process. A
   config.yaml `otel.resource_attributes` key would need code + model changes
   for no added value.
   Alternatives considered: per-Pi `OTEL_SERVICE_NAME` (breaks the shared
   dashboard), adding `host.name` in code (touches app for every Pi; no env
   override), collector-side attribute injection (can't know the source Pi
   reliably; all external flows share one collector endpoint).

2. **Value = Pi FQDN (`raspberrypi-5-2.krysdom`, ...).**
   Rationale: matches the node_exporter `instance` convention (`<fqdn>:9100`)
   and the LAN DNS names used in inventory/collector targets.
   Alternative: short hostname — rejected, inconsistent with existing targets.

3. **Keep `service.name` = `imx462-rpi-controller` on all Pis.**
   Rationale: the existing Grafana dashboard and Loki queries key on the shared
   name; per-Pi filtering is done with `instance` / `host_name` labels.
   Alternative: per-Pi service names — rejected (breaks dashboards; Grafana
   would need per-Pi dashboards or regex aggregation).

4. **Collector scrape targets for node_exporter live in the krysdom-api
   observability chart, one job `imx462-rpi` with three static targets.**
   Rationale: the observability chart already owns `prometheus/apps` scrape
   config (per its AGENTS.md, never add targets directly to Prometheus server).
   This part is already shipped (`f96e855`, ArgoCD-synced); documented here for
   completeness.

5. **Configurator derives the identity from `target_host`.**
   Rationale: host_vars generation should stay single-source; users can
   override the value in the generated file if the FQDN differs from the
   inventory alias.

## Risks / Trade-offs

- **Label cardinality**: `host_name` + `service_instance_id` as Loki stream
  labels for log lines adds stream cardinality per Pi (bounded: 3 hosts).
  → Acceptable; matches existing label usage.
- **Stale duplicate host_vars**: a `.krysdom`-suffixed host_vars file
  (`raspberrypi-5-2.krysdom.yml`) was silently ignored by Ansible (host aliases
  are short names). → Deleted during this change; future host_vars use the
  inventory alias as filename.
- **Identity set once at process start**: changing the value requires a
  service restart (playbook re-run). → Documented in the deployment flow
  (playbook restarts the service).
- **`instance` label overwritten for pre-restart series**: old random-UUID
  series linger until stale (5m after restart). → Transient; new series carry
  the FQDN.

## Migration Plan

Already executed operationally:
1. Per-Pi `OTEL_RESOURCE_ATTRIBUTES` added to all three host_vars
   (git-ignored); playbook re-run restarted each service (idempotent).
2. `raspberrypi-zero-2w-2` provisioned (imx708 host_vars + inventory entry),
   rebooted to activate the overlay.
3. krysdom-api observability chart: three scrape targets, committed + pushed
   (ArgoCD auto-sync), verified `up{job="imx462-rpi"} == 3`.

Remaining (this change's apply phase):
- Commit the tracked template/script updates and tests.
- Run pytest + ruff.
- (Optional) AGENTS.md note on per-Pi OTel identity.

Rollback: revert the template/script commit; on the Pis, remove
`OTEL_RESOURCE_ATTRIBUTES` from `.env` and re-run the playbook; for scraping,
remove the two zero targets from the observability chart (or keep — extra
targets are harmless if the hosts are up).

## Open Questions

None.

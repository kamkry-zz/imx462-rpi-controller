## ADDED Requirements

### Requirement: Per-host resource identity
The system SHALL attach a stable per-host OpenTelemetry resource identity
(`host.name` and `service.instance.id`) to all exported telemetry so metrics,
traces, and logs from multiple Raspberry Pis are distinguishable, while keeping
the shared service name for existing dashboards.

#### Scenario: Metrics distinguishable per Pi
- **WHEN** two or more Pis export metrics to the same OTLP endpoint
- **THEN** each metric series carries a distinct `service.instance.id` (surfaced
  as the Prometheus `instance` label) per Pi

#### Scenario: Logs carry host identity
- **WHEN** a Pi exports logs over OTLP
- **THEN** each log record carries `host.name` and `service.instance.id`
  identifying the originating Pi

#### Scenario: Identity survives restart
- **WHEN** a Pi's application process restarts
- **THEN** the resource identity remains stable (derived from the configured
  host, not a random per-process value)

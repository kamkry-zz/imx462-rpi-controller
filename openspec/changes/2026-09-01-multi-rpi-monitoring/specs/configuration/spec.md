## ADDED Requirements

### Requirement: Per-host OpenTelemetry identity configuration
The system SHALL support configuring per-host OpenTelemetry resource attributes
via the `OTEL_RESOURCE_ATTRIBUTES` key in `.env`, and SHALL document the key in
committed templates and examples.

#### Scenario: Identity configured via .env
- **WHEN** `.env` sets
  `OTEL_RESOURCE_ATTRIBUTES=host.name=...,service.instance.id=...`
- **THEN** the exported telemetry carries those resource attributes

#### Scenario: Configurator emits identity
- **WHEN** the setup configurator generates host_vars for a target host
- **THEN** the generated `imx462_env` includes `OTEL_RESOURCE_ATTRIBUTES`
  derived from the target hostname

#### Scenario: Templates document the key
- **WHEN** the repository is inspected
- **THEN** `.env.example` and `ansible/host_vars/pi.example.yml` document the
  `OTEL_RESOURCE_ATTRIBUTES` key

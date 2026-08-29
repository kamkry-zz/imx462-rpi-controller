# Observability Specification

## Purpose

Export metrics, traces, and correlated logs to an observability backend via
OpenTelemetry OTLP.

## Requirements

### Requirement: Export metrics
The system SHALL export runtime and application metrics (e.g. HTTP request
metrics, camera operation metrics, process metrics) via OTLP.

#### Scenario: Metrics exported
- **WHEN** the system is running
- **THEN** metrics are exported to the configured OTLP endpoint at the configured
  interval

### Requirement: Export traces
The system SHALL generate and export traces for API requests and camera
operations via OTLP.

#### Scenario: Request traced
- **WHEN** a client invokes an API operation
- **THEN** a span is created and exported to the configured OTLP endpoint

### Requirement: Export correlated logs
The system SHALL export logs via OTLP with trace and span correlation where
available.

#### Scenario: Logs correlated with traces
- **WHEN** a log is emitted within a traced request
- **THEN** the exported log carries the trace and span identifiers

### Requirement: Configurable endpoint
The system SHALL use the OTLP endpoint and service name from configuration, and
SHALL degrade gracefully (continue operating) if the endpoint is unreachable.

#### Scenario: Unreachable endpoint does not break operation
- **WHEN** the OTLP endpoint is unreachable
- **THEN** the system continues to operate and retries export in the background

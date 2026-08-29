## Purpose

Report operation events, status, and metrics to an external MQTT broker.

## ADDED Requirements

### Requirement: Publish operation events
The system SHALL publish an MQTT message when an operation occurs (e.g. photo
captured, recording started/stopped, camera configured).

#### Scenario: Event published on operation
- **WHEN** a capture, recording, or configuration operation completes
- **THEN** the system publishes an event to the configured MQTT topic with the
  operation details

### Requirement: Publish heartbeat and status
The system SHALL periodically publish a heartbeat/status message while running.

#### Scenario: Periodic heartbeat
- **WHEN** the system is running
- **THEN** it publishes a status/heartbeat message at the configured interval

### Requirement: Publish metrics
The system SHALL publish metrics (e.g. camera health, capture counts, uptime) to
the configured MQTT broker.

#### Scenario: Metrics published
- **WHEN** the system is running
- **THEN** it publishes metric values on the configured metrics topic

### Requirement: Configurable broker connection
The system SHALL connect to the MQTT broker using host, port, and credentials
from configuration, and SHALL retry on disconnection.

#### Scenario: Reconnect after disconnect
- **WHEN** the MQTT broker connection is lost
- **THEN** the system attempts to reconnect automatically

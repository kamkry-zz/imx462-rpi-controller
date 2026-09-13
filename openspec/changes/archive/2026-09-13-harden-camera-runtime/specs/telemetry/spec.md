## MODIFIED Requirements

### Requirement: Configurable broker connection
The system SHALL connect to the MQTT broker using host, port, and credentials
from configuration, and SHALL retry on disconnection. Retry SHALL cover the
initial connection attempt: a broker that is unreachable when the application
starts SHALL NOT permanently disable telemetry, and the connection SHALL be
established automatically once the broker becomes reachable, without requiring
an application restart.

#### Scenario: Reconnect after disconnect
- **WHEN** the MQTT broker connection is lost
- **THEN** the system attempts to reconnect automatically

#### Scenario: Broker unavailable at startup
- **WHEN** the application starts while the MQTT broker is unreachable
- **THEN** the application starts normally and telemetry begins publishing once
  the broker becomes reachable, without a restart

## MODIFIED Requirements

### Requirement: Load non-secret configuration
The system SHALL load non-secret configuration values (server, cameras, MQTT
topics, OTel endpoint, capture output paths and formats) from a dedicated
`config.yaml` file. The default video format SHALL be MP4. Each configured camera
SHALL declare its device-tree overlay and an optional per-camera default mode.

#### Scenario: Valid config loaded
- **WHEN** the system starts with a valid `config.yaml`
- **THEN** the configured values are applied

#### Scenario: Heterogeneous cameras configured
- **WHEN** the config declares cameras with different overlays (e.g. `imx290` and
  `imx708`)
- **THEN** each camera is driven by its own overlay and defaults to its own mode

#### Scenario: Missing or invalid config
- **WHEN** the `config.yaml` is missing or malformed
- **THEN** the system reports a clear error at startup and does not run with
  partial configuration

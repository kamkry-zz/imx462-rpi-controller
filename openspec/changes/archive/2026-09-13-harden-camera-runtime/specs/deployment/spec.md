## MODIFIED Requirements

### Requirement: Systemd service lifecycle
The system SHALL deploy the application as a systemd service that starts on boot
and restarts on failure. The unit SHALL allow a stop timeout long enough for the
application to finalize an active recording (remuxing raw video to its container)
during shutdown before the process is terminated.

#### Scenario: Service enabled and running
- **WHEN** deployment completes
- **THEN** the service is enabled, running, and configured to restart on failure

#### Scenario: Graceful stop with an active recording
- **WHEN** the service is stopped while a recording is active
- **THEN** the unit grants enough time for the recording to be finalized before
  terminating the process

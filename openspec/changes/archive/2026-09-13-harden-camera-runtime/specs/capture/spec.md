## ADDED Requirements

### Requirement: Recording finalized on reconfiguration
The system SHALL finalize an active recording when the camera is reconfigured
(mode change, orientation flip, a control change that rebuilds the camera
configuration, return to continuous stream mode, or a snapshot) instead of
discarding it: the encoder SHALL be stopped and the recorded stream remuxed to
the configured container, falling back to the raw stream when no remuxer is
available. Finalization SHALL also occur when a reconfigure fails after the
encoder was stopped, and when the application shuts down. Remuxing SHALL NOT
hold the camera lock, so live view and control operations continue while a
recording is finalized. Stop-recording and shutdown SHALL report the final path.

#### Scenario: Mode change while recording
- **WHEN** a recording is active and a client changes the camera mode
- **THEN** the recording is stopped and finalized (MP4 when the remuxer is
  available) and the mode change proceeds

#### Scenario: Control change while recording
- **WHEN** a recording is active and a client updates controls in a way that
  reconfigures the camera (e.g. `FrameDurationLimits`)
- **THEN** the recording is finalized rather than silently dropped

#### Scenario: Failed reconfigure while recording
- **WHEN** a recording is active and the reconfigure fails (e.g. the requested
  mode cannot be configured)
- **THEN** the recording is still finalized and the raw stream is not orphaned

#### Scenario: Shutdown while recording
- **WHEN** the application shuts down while a recording is active
- **THEN** the recording is finalized and the final path is logged

#### Scenario: Live view during finalization
- **WHEN** a recording is finalized after a reconfigure
- **THEN** live-view frames continue to be delivered while the remux runs

## MODIFIED Requirements

### Requirement: Single-frame snapshot
The system SHALL capture a single still with a requested total exposure time,
applying the exposure via a camera reconfigure so the result reflects the
requested exposure, and save it to the gallery. The requested exposure and gain
SHALL be positive and SHALL be clamped to the sensor's reported bounds (using
the capabilities read from libcamera when available) before being applied.

#### Scenario: Snapshot with short exposure
- **WHEN** a client requests a snapshot with a short exposure
- **THEN** the system captures a single frame at that exposure and saves it as an
  image file

#### Scenario: Snapshot with long exposure
- **WHEN** a client requests a snapshot with an exposure up to 30 s
- **THEN** the system captures a single frame at that exposure and saves it as an
  image file

#### Scenario: Snapshot outside the sensor bounds
- **WHEN** a client requests a snapshot with an exposure or gain outside the
  sensor's reported range
- **THEN** the request is clamped to the sensor's range before capture

#### Scenario: Non-positive snapshot request
- **WHEN** a client requests a snapshot with zero or negative exposure or gain
- **THEN** the system rejects the request with a validation error

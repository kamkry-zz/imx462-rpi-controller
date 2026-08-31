## MODIFIED Requirements

### Requirement: Per-sensor capabilities
The system SHALL report each camera's sensor model, supported modes, and exposure
and gain bounds, reading them from libcamera at runtime so heterogeneous sensors
(e.g. IMX462 and Camera Module 3) each report their own achievable ranges.
Capability reads SHALL be serialized with camera operations: reading a camera's
modes and bounds may reconfigure the camera, so the read SHALL be performed
under the camera lock, SHALL be cached after the first successful read, and
SHALL be skipped while the camera is running so it never interrupts an active
stream.

#### Scenario: Capabilities exposed per camera
- **WHEN** a client requests a camera's capabilities
- **THEN** the system returns that camera's supported modes, minimum and maximum
  exposure time, and minimum and maximum analogue gain

#### Scenario: Capabilities without hardware
- **WHEN** libcamera is unavailable or the camera cannot be opened
- **THEN** the system falls back to a static per-model catalog without erroring

#### Scenario: Capabilities while the camera is running
- **WHEN** a client requests capabilities while the camera is streaming
- **THEN** the system returns the cached (or static-catalog) capabilities without
  reconfiguring or interrupting the running camera

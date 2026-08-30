## ADDED Requirements

### Requirement: Per-sensor capabilities
The system SHALL report each camera's sensor model, supported modes, and exposure
and gain bounds, reading them from libcamera at runtime so heterogeneous sensors
(e.g. IMX462 and Camera Module 3) each report their own achievable ranges.

#### Scenario: Capabilities exposed per camera
- **WHEN** a client requests a camera's capabilities
- **THEN** the system returns that camera's supported modes, minimum and maximum
  exposure time, and minimum and maximum analogue gain

#### Scenario: Capabilities without hardware
- **WHEN** libcamera is unavailable or the camera cannot be opened
- **THEN** the system falls back to a static per-model catalog without erroring

## MODIFIED Requirements

### Requirement: Configure sensor mode
The system SHALL allow a client to set the resolution, bit depth (where the sensor
exposes multiple bit depths), and framerate of a selected camera from its
supported modes.

#### Scenario: Set a supported mode
- **WHEN** a client sets a supported resolution, bit depth, and framerate
- **THEN** the camera is reconfigured and subsequent captures use that mode

#### Scenario: Set an unsupported mode
- **WHEN** a client requests a mode the camera does not support
- **THEN** the system returns an error and leaves the current mode unchanged

### Requirement: Exposure controls
The system SHALL allow a client to enable or disable auto exposure and, when
disabled, set a manual shutter speed and ISO (in 0.3 EV steps) within the
sensor's reported exposure and gain range, applying changes at runtime without
stopping the live view.

#### Scenario: Manual shutter and ISO applied
- **WHEN** a client disables auto exposure and sets a shutter speed and ISO
- **THEN** the system applies the exposure and gain at runtime and keeps the live
  view streaming

#### Scenario: Re-enable auto exposure
- **WHEN** a client re-enables auto exposure
- **THEN** the system resets the frame duration and returns to automatic exposure

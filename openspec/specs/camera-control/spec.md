# Camera Control Specification

## Purpose

Enumerate, select, and configure the connected IMX462 camera sensor(s).

## Requirements

### Requirement: Enumerate cameras
The system SHALL enumerate all connected cameras and return their identifiers,
supported modes (resolution, RAW bit depth, framerate), and availability.

#### Scenario: List connected cameras
- **WHEN** a client requests the camera list
- **THEN** the system returns an entry per connected camera (cam0, cam1) with its
  identifier and supported modes

#### Scenario: No cameras connected
- **WHEN** a client requests the camera list and no camera is connected
- **THEN** the system returns an empty list without raising an error

### Requirement: Select an active camera
The system SHALL allow a client to select a specific camera as the target of
subsequent capture and streaming operations.

#### Scenario: Select a valid camera
- **WHEN** a client selects a camera that is present
- **THEN** subsequent operations are directed to that camera

#### Scenario: Select an invalid camera
- **WHEN** a client selects a camera identifier that is not connected
- **THEN** the system returns an error indicating the camera is unavailable

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

### Requirement: White balance
The system SHALL allow a client to enable or disable auto white balance and, when
disabled, set a manual white balance in Kelvin.

#### Scenario: Manual white balance applied
- **WHEN** a client disables auto white balance and sets a colour temperature
- **THEN** the system applies that temperature to the camera

### Requirement: Image orientation flip
The system SHALL allow a client to flip the image horizontally and/or vertically,
applying the flip to live view, stills, and video.

#### Scenario: Flip applied to all outputs
- **WHEN** a client enables a horizontal or vertical flip
- **THEN** the live view, photos, and videos are all flipped accordingly

### Requirement: Anti-flicker
The system SHALL allow a client to select a 50 Hz or 60 Hz anti-flicker setting
that restricts shutter speeds to mains-safe values and applies the corresponding
`AeFlickerPeriod` control to the sensor.

#### Scenario: Anti-flicker filters shutter speeds
- **WHEN** a client selects 50 Hz or 60 Hz anti-flicker
- **THEN** the shutter speed options are limited to values that are integer
  multiples of the mains half-period

#### Scenario: Anti-flicker control applied
- **WHEN** a client selects a 50 Hz or 60 Hz anti-flicker setting
- **THEN** the sensor's anti-flicker period is set to the matching period (10000 µs
  for 50 Hz, 8333 µs for 60 Hz, 0 for off)

### Requirement: Read back current settings
The system SHALL report the current analogue gain and exposure time in its status
payload, including while auto exposure is enabled.

#### Scenario: Current settings reported
- **WHEN** the camera is running with auto or manual exposure
- **THEN** the status payload includes the current gain and exposure time

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


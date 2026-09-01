## MODIFIED Requirements

### Requirement: Configure sensor mode
The system SHALL allow a client to set the resolution, bit depth, and framerate
of a selected camera from its supported modes. The bit depth SHALL be optional:
for sensors without a bit-depth selector (e.g. the 10-bit-only imx708), a mode
change SHALL accept a null/omitted bit depth and configure the sensor without
one.

#### Scenario: Set a supported mode
- **WHEN** a client sets a supported resolution, bit depth, and framerate
- **THEN** the camera is reconfigured and subsequent captures use that mode

#### Scenario: Set a mode without a bit depth
- **WHEN** a client sets a supported resolution and framerate for a sensor
  without a bit-depth selector, sending `bit_depth: null`
- **THEN** the camera is reconfigured without a bit-depth override and
  subsequent captures use that mode

#### Scenario: Set an unsupported mode
- **WHEN** a client requests a mode the camera does not support
- **THEN** the system returns an error and leaves the current mode unchanged

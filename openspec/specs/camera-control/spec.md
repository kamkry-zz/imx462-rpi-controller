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
modes may reconfigure the camera, so the full mode read SHALL be performed under
the camera lock, SHALL be cached after the first successful read, and SHALL only
be attempted while the camera is stopped so it never interrupts an active
stream. While the camera is running, the system SHALL read exposure and gain
bounds from the runtime control information (which remains valid while running)
and merge them onto the static per-model catalog, so clients receive real
per-sensor bounds even after the camera has started.
`min_frame_duration_us` SHALL reflect the mode actually running while the camera
is started, and the configured default mode otherwise.

#### Scenario: Capabilities exposed per camera
- **WHEN** a client requests a camera's capabilities
- **THEN** the system returns that camera's supported modes, minimum and maximum
  exposure time, and minimum and maximum analogue gain

#### Scenario: Capabilities without hardware
- **WHEN** libcamera is unavailable or the camera cannot be opened
- **THEN** the system falls back to a static per-model catalog without erroring

#### Scenario: Capabilities while the camera is running
- **WHEN** a client requests capabilities while the camera is streaming
- **THEN** the system returns the sensor's runtime exposure/gain bounds merged
  onto the static catalog without reconfiguring or interrupting the running
  camera

#### Scenario: Frame-duration floor while the camera is running
- **WHEN** the camera is running a mode that differs from its configured default
  mode
- **THEN** `min_frame_duration_us` reports the running mode's frame-duration
  floor (1/framerate)

### Requirement: Per-mode minimum frame duration
The system SHALL derive the minimum frame duration for manual exposure and
snapshot captures from the selected mode's framerate (1 / framerate) rather
than assuming a fixed 1/60 s frame time, so that low-framerate sensors such as
the IMX415 (full-array 3864x2192 readout, ~15 fps on 2-lane csi platforms) are
never sent a `FrameDurationLimits` below their achievable frame time. When a
manual shutter speed, snapshot exposure, or a `FrameDurationLimits` request
received via the controls API is shorter than the mode's minimum frame
duration, the system SHALL raise it to the mode-derived minimum before
applying it. Stored frame-duration limits SHALL be re-floored to the new mode's
minimum when the mode changes, so limits carried over from a faster mode are
never applied to a slower sensor. The capabilities payload SHALL report the
frame-duration floor as `min_frame_duration_us` — the floor of the camera's
configured default mode (falling back to its fastest advertised mode when no
default is configured) — so external clients that never switch modes (e.g.
cat-watcher) can floor their `FrameDurationLimits` requests per sensor instead
of hard-coding 1/60 s.

#### Scenario: Manual exposure on a low-framerate mode
- **WHEN** a camera runs in a 15 fps mode and a client sets a fast manual
  shutter (e.g. 1/250 s) with auto exposure off
- **THEN** the frame duration requested from the sensor is at least the
  mode-derived minimum (~67 ms for 15 fps), not the fixed 1/60 s floor

#### Scenario: Controls API request below the frame floor
- **WHEN** an external client (e.g. cat-watcher) sends
  `FrameDurationLimits: [16666, 16666]` while the camera runs a 15 fps mode
- **THEN** the applied frame duration is raised to the mode-derived minimum
  (~66 667 µs) and the request succeeds instead of failing or stalling

#### Scenario: Mode change with stored frame-duration limits
- **WHEN** the camera switches from a 60 fps mode to a 15 fps mode while manual
  frame-duration limits from the faster mode are stored
- **THEN** the applied frame duration is at least the 15 fps mode minimum
  (~66 667 µs) and the camera starts successfully

#### Scenario: Capabilities report the frame-duration floor
- **WHEN** a client requests a camera's capabilities
- **THEN** the payload includes `min_frame_duration_us` matching the camera's
  configured default mode (e.g. ~66 667 µs for an imx415 defaulting to 4K@15,
  ~16 667 µs for a 60 fps imx290)

#### Scenario: Snapshot exposure shorter than the frame duration
- **WHEN** a client takes a single-frame snapshot with an exposure shorter than
  the selected mode's minimum frame duration
- **THEN** the capture configures a frame duration of at least the mode-derived
  minimum and the capture succeeds

#### Scenario: Fast-framerate modes unchanged
- **WHEN** a camera runs in a 60 fps mode (e.g. imx290)
- **THEN** manual-exposure frame durations behave exactly as before (1/60 s
  floor), preserving existing behaviour on the IMX462

### Requirement: Bit-depth-less mode labels
The system SHALL present mode descriptions for sensors whose modes carry no bit
depth (single-bit-depth readout such as the 10-bit-only imx708 and imx415)
without an undefined RAW depth label.

#### Scenario: Mode list for a single-bit-depth sensor
- **WHEN** the web UI renders the supported modes of an imx415 or imx708 camera
- **THEN** each mode is labelled with its resolution and framerate only, with no
  `RAWundefined` fragment

### Requirement: Control payload validation
The system SHALL validate incoming camera control payloads before applying them:
malformed or out-of-shape values (e.g. a `FrameDurationLimits` that is not a
pair of finite numbers) SHALL be ignored rather than crashing control
application, and a payload that cannot be interpreted SHALL be rejected with a
client error instead of an internal error.

#### Scenario: Malformed frame-duration limits ignored
- **WHEN** a client sends `FrameDurationLimits` as a scalar, a non-numeric pair,
  or a list that is not exactly two values
- **THEN** the malformed value is dropped, other valid controls in the same
  payload still apply, and no internal error occurs

#### Scenario: Uninterpretable control payload rejected
- **WHEN** a control payload cannot be interpreted (unexpected value type)
- **THEN** the system responds with a client error (422) rather than a server
  error


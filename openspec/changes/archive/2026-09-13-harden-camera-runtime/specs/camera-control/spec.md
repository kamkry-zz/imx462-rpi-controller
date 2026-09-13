## ADDED Requirements

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

## MODIFIED Requirements

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

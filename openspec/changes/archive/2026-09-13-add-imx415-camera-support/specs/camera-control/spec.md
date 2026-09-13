## ADDED Requirements

### Requirement: Per-mode minimum frame duration
The system SHALL derive the minimum frame duration for manual exposure and
snapshot captures from the selected mode's framerate (1 / framerate) rather
than assuming a fixed 1/60 s frame time, so that low-framerate sensors such as
the IMX415 (full-array 3864x2192 readout, ~15 fps on 2-lane csi platforms) are
never sent a `FrameDurationLimits` below their achievable frame time. When a
manual shutter speed, snapshot exposure, or a `FrameDurationLimits` request
received via the controls API is shorter than the mode's minimum frame
duration, the system SHALL raise it to the mode-derived minimum before
applying it. The capabilities payload SHALL report the frame-duration floor as
`min_frame_duration_us` — the floor of the camera's configured default mode
(falling back to its fastest advertised mode when no default is configured) —
so external clients that never switch modes (e.g. cat-watcher) can floor their
`FrameDurationLimits` requests per sensor instead of hard-coding 1/60 s.

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

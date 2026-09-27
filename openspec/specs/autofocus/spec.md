# Autofocus Specification

## Purpose

Discover and control the lens autofocus of actuator-equipped cameras (e.g. the
Camera Module 3 / IMX708): on-demand single autofocus, continuous autofocus,
periodic refocus, and manual lens position, with focus-state feedback.

## Requirements

### Requirement: Autofocus capability discovery

The system SHALL detect autofocus support per camera at runtime from the sensor's
reported controls and advertise it in the camera capabilities payload. A camera
that exposes autofocus controls SHALL report `supports_autofocus: true`; a camera
that exposes a manual lens-position control SHALL report
`supports_manual_focus: true` together with the achievable lens-position
minimum, maximum, and default. Cameras without focus controls SHALL report both
flags as false and SHALL NOT expose focus controls in the UI. When libcamera is
unavailable, the system SHALL fall back to a static per-model catalog that marks
the IMX708 as autofocus-capable and all other supported sensors as not
autofocus-capable.

#### Scenario: Autofocus camera advertises support

- **WHEN** a client requests the capabilities of a camera whose sensor reports
  autofocus and lens-position controls
- **THEN** the payload reports `supports_autofocus: true`,
  `supports_manual_focus: true`, and the lens-position minimum, maximum, and
  default

#### Scenario: Non-autofocus camera advertises no support

- **WHEN** a client requests the capabilities of a camera whose sensor reports no
  focus controls (e.g. IMX462/IMX290, IMX219)
- **THEN** the payload reports `supports_autofocus: false` and
  `supports_manual_focus: false`

#### Scenario: Capability fallback without hardware

- **WHEN** libcamera is unavailable and the configured sensor model is an IMX708
- **THEN** the static fallback catalog reports autofocus and manual-focus support
  without erroring

### Requirement: Default single autofocus

When a camera with autofocus support is started or reconfigured, the system SHALL
default its focus mode to single autofocus, performing one focus cycle, unless a
client has selected another focus mode.

#### Scenario: Single autofocus on camera start

- **WHEN** an autofocus camera is configured and started and no focus mode was
  requested by a client
- **THEN** the camera runs in single-autofocus mode and performs one focus cycle

### Requirement: On-demand autofocus trigger

The system SHALL allow a client to trigger a single autofocus cycle on demand for
an autofocus-capable camera. On a camera running a fast-enough frame rate the
trigger SHALL apply without reconfiguring the camera, SHALL support selecting the
focus range and speed, and SHALL return the current focus state. The client SHALL
be able to request that the call wait until focus settles (focused or failed) up
to a client-provided timeout; when the timeout elapses the call SHALL return the
last observed focus state rather than failing. An explicit trigger SHALL succeed
even when the camera is in a long-exposure or manual state too slow for a focus
sweep: unless the client disables it, the system SHALL run an **AF-assist** —
temporarily switching to a fast, auto-exposure configuration, performing the
sweep, locking focus at the achieved position, and restoring the previous
exposure settings — and SHALL report in the response that the assist was used.
The client SHALL be able to disable the assist, in which case a slow-frame
trigger SHALL be rejected. An explicit trigger SHALL preserve the camera's
pre-trigger focus mode: a one-shot while in manual mode SHALL re-lock focus
(manual) at the achieved lens position, and a one-shot while in continuous mode
SHALL resume continuous tracking (rather than silently downgrading to single
autofocus). Triggering autofocus on a camera that does not support it, or while a
capture or recording is in progress, SHALL be rejected with a client error.

#### Scenario: Trigger autofocus without waiting

- **WHEN** a client triggers autofocus on an autofocus-capable camera running at
  a fast frame rate without requesting to wait
- **THEN** the system starts a single autofocus cycle and returns the current
  focus state without reconfiguring the camera

#### Scenario: Trigger autofocus and wait for settlement

- **WHEN** a client triggers autofocus requesting to wait with a timeout
- **THEN** the system blocks until the focus state is focused or failed, or until
  the timeout elapses, and returns the resulting focus state

#### Scenario: Trigger with focus range and speed

- **WHEN** a client triggers autofocus specifying a focus range and/or speed
- **THEN** the system applies those settings to the autofocus cycle

#### Scenario: Trigger on a non-autofocus camera

- **WHEN** a client triggers autofocus on a camera that does not advertise
  autofocus support
- **THEN** the system rejects the request with a client error and leaves the
  camera unchanged

#### Scenario: Trigger in a long-exposure state uses the assist

- **WHEN** a client triggers autofocus while the camera is in a long-exposure or
  manual state too slow for a focus sweep and assist is enabled
- **THEN** the system temporarily switches to a fast, auto-exposure configuration,
  performs the sweep, locks focus at the achieved position, restores the previous
  exposure settings, and returns a result indicating the assist was used

#### Scenario: Trigger with assist disabled in a long-exposure state

- **WHEN** a client triggers autofocus with assist disabled while the camera is in
  a long-exposure state
- **THEN** the system rejects the request with a client error and leaves the
  camera unchanged

#### Scenario: Trigger during a capture or recording

- **WHEN** a client triggers autofocus while a snapshot or recording is in
  progress
- **THEN** the system rejects the request with a client error

#### Scenario: Focus now from manual re-locks

- **WHEN** a client triggers autofocus while the camera is in manual focus mode
- **THEN** the system runs the sweep and leaves the camera in manual focus at the
  achieved lens position (the mode is not changed to single autofocus)

#### Scenario: Focus now from continuous resumes continuous

- **WHEN** a client triggers autofocus while the camera is in continuous focus mode
- **THEN** after the one-shot the camera resumes continuous autofocus

### Requirement: Periodic refocus

The system SHALL allow a client to configure a refocus interval for an
autofocus-capable camera. When the interval is greater than zero, the system
SHALL re-issue a single autofocus cycle at that interval in the background,
independent of any connected client. A value of zero SHALL disable periodic
refocus. The interval SHALL be runtime state and SHALL NOT be persisted to the
configuration file. Periodic refocus SHALL be disabled while the camera is in
manual focus mode (selecting manual SHALL zero the interval) and while the camera
is in continuous focus mode. The system SHALL skip a scheduled autofocus cycle
while a capture or recording is in progress and whenever the frame duration is
too slow for a practical focus sweep (e.g. a long single-frame exposure), so
refocus never interrupts a capture, overrides a manual lock, or toggles the
exposure of a long-exposure session.

#### Scenario: Periodic refocus re-triggers autofocus

- **WHEN** a client sets a positive refocus interval on an autofocus-capable
  camera
- **THEN** the system performs a single autofocus cycle at each interval until
  the interval is changed or disabled

#### Scenario: Disable periodic refocus

- **WHEN** a client sets the refocus interval to zero
- **THEN** the system stops performing periodic autofocus cycles

#### Scenario: Refocus skipped during a long exposure

- **WHEN** a periodic autofocus cycle becomes due while the camera is in a
  long-exposure state or a capture is pending
- **THEN** the system skips that cycle instead of interrupting the capture or
  changing the exposure

#### Scenario: Manual focus disables periodic refocus

- **WHEN** a client selects manual focus while a refocus interval is set
- **THEN** the interval is cleared and no scheduled autofocus overrides the
  manual lens position

### Requirement: Accurate focus state

The system SHALL report a camera's focus state only when it is current. When the
camera's frame duration is too slow for the metadata poll to stay fresh (e.g. a
long manual exposure), the system SHALL report the focus state as unknown and
flag it as stale through the focus endpoint, the settings payload, and the
status/WebSocket payload, rather than presenting the last observed state as if it
were live.

#### Scenario: Stale state reported as unknown

- **WHEN** the camera is in a long-exposure state and a client requests the focus
  state
- **THEN** the response reports the focus state as unknown with a stale flag,
  instead of the last observed state

#### Scenario: Fresh state reported normally

- **WHEN** the camera runs at a fast frame rate and a client requests the focus
  state
- **THEN** the response reports the current focus state without the stale flag

### Requirement: Focus locking after assist

After an AF-assist completes successfully, the system SHALL lock focus at the
achieved lens position (manual focus mode) so the lens holds for the subsequent
long exposure, and SHALL report the locked lens position. If no focus result was
obtained, the system SHALL restore the focus mode and lens position that were
active before the assist.

#### Scenario: Focus locked after assist

- **WHEN** an AF-assist achieves a focus result
- **THEN** the camera switches to manual focus at the achieved lens position and
  the focus state reports that position

#### Scenario: Failed assist restores previous focus

- **WHEN** an AF-assist obtains no lens-position result
- **THEN** the camera's previous focus mode and lens position are restored

### Requirement: Continuous autofocus

The system SHALL allow a client to select continuous autofocus for an
autofocus-capable camera, and SHALL allow switching back to single autofocus or
manual focus at any time without reconfiguring the camera.

#### Scenario: Enable continuous autofocus

- **WHEN** a client selects continuous autofocus
- **THEN** the camera continuously refocuses as the scene changes

#### Scenario: Switch from continuous to manual focus

- **WHEN** a client selects manual focus while continuous autofocus is active
- **THEN** the camera stops continuous autofocus and applies the requested lens
  position

### Requirement: Manual focus

The system SHALL allow a client to set a fixed lens position for a camera that
supports manual focus. The requested position SHALL be clamped to the sensor's
reported lens-position bounds. The applied lens position SHALL persist across
mode changes and other reconfigures, like other stored controls. A lens position
outside the sensor's supported range SHALL be clamped rather than rejected.

#### Scenario: Set manual focus

- **WHEN** a client selects manual focus and sets a lens position within the
  sensor's range
- **THEN** the system applies that lens position

#### Scenario: Manual focus survives a mode change

- **WHEN** a client has set a manual lens position and the camera is later
  reconfigured to a different mode
- **THEN** the manual lens position remains applied after the reconfigure

#### Scenario: Manual focus on a camera without the capability

- **WHEN** a client requests manual focus on a camera that does not advertise
  manual-focus support
- **THEN** the system rejects the request with a client error

### Requirement: Focus state reporting

The system SHALL report each autofocus-capable camera's focus mode, current focus
state (idle, scanning, focused, or failed), and current lens position through the
focus endpoint and the status/settings payload. Focus state SHALL be read from
the camera's runtime metadata, and reading it SHALL NOT block or stall the live
view, control operations, or capture.

#### Scenario: Focus state available via the focus endpoint

- **WHEN** a client requests the focus state of an autofocus-capable camera
- **THEN** the response includes the focus mode, focus state, and current lens
  position

#### Scenario: Focus state in the status payload

- **WHEN** the status/settings payload is produced for an autofocus-capable
  camera
- **THEN** it includes the focus mode, focus state, and current lens position

#### Scenario: Focus state on a non-autofocus camera

- **WHEN** a client requests the focus state of a camera without autofocus
  support
- **THEN** the system responds with a client error indicating focus is
  unsupported

### Requirement: Focus controls do not re-trigger on reconfigure

The system SHALL treat the one-shot autofocus trigger as a command, not as a
stored camera control: reconfiguring the camera (mode change, flip, snapshot
reconfigure, return to continuous stream mode) SHALL re-apply the persistent
focus settings (focus mode and manual lens position) but SHALL NOT itself start a
new autofocus cycle.

#### Scenario: Reconfigure does not start autofocus

- **WHEN** an autofocus camera in single-autofocus mode is reconfigured
- **THEN** the persistent focus settings are re-applied but no new autofocus
  cycle is started by the reconfigure

### Requirement: Focus request validation

The system SHALL validate focus requests before applying them: an unsupported
focus mode, a non-positive wait timeout, or a non-numeric lens position SHALL be
rejected with a client error, and no malformed request SHALL crash focus
application or the camera runtime.

#### Scenario: Invalid focus mode rejected

- **WHEN** a client sends a focus mode that is not manual, single, or continuous
- **THEN** the system responds with a client error and leaves the focus state
  unchanged

#### Scenario: Malformed wait timeout rejected

- **WHEN** a client triggers autofocus requesting to wait with a non-positive or
  non-numeric timeout
- **THEN** the system responds with a client error

### Requirement: Web UI focus controls

The web UI SHALL present focus controls only for a camera that advertises
autofocus support, and SHALL hide them otherwise. The controls SHALL allow
selecting the focus mode (manual, single, or continuous), triggering autofocus on
demand, setting a manual lens position, and choosing a refocus interval, and
SHALL display the current focus state.

#### Scenario: Focus controls shown for an autofocus camera

- **WHEN** the UI selects an autofocus-capable camera
- **THEN** the focus controls are shown with the camera's current focus mode,
  lens-position range, and focus state

#### Scenario: Focus controls hidden for other cameras

- **WHEN** the UI selects a camera without autofocus support
- **THEN** the focus controls are hidden

## MODIFIED Requirements

### Requirement: MJPEG live view
The system SHALL expose a continuous MJPEG stream of the selected camera via
HTTP multipart/x-mixed-replace. The camera SHALL be configured with a `main`
stream (full resolution, for stills and recording) and a `lores` stream
(downscaled, for MJPEG) only — the stream configuration SHALL NOT include a raw
stream, since picamera2's default raw stream crashes the previous-generation
(vc4) camera pipeline. The MJPEG encoding bitrate SHALL be fixed and independent
of the sensor mode and its frame rate, so live-view quality does not degrade in
low-framerate modes (e.g. the 4K mode of the Camera Module 3 Wide). Each camera
SHALL use a single persistent MJPEG feed path for the worker's lifetime:
tearing the encoder down (e.g. while reconfiguring the camera) SHALL NOT create
additional feed workers, and the feed SHALL resume when the encoder is
recreated. Subscribing to and unsubscribing from a stream SHALL NOT stall the
application's request handling while camera operations are in progress, so one
busy camera cannot freeze other streams, status pushes, or requests.

#### Scenario: Client subscribes to live view
- **WHEN** a client requests the live-view stream for a selected camera
- **THEN** the system responds with a continuous MJPEG stream of frames from that
  camera

#### Scenario: Live view for unavailable camera
- **WHEN** a client requests live view for a camera that is not connected
- **THEN** the system returns an error instead of a stream

#### Scenario: Stream starts on a previous-gen board
- **WHEN** a client requests live view on a previous-generation (vc4) platform
  board (e.g. Raspberry Pi Zero 2 W)
- **THEN** the camera starts with `main` and `lores` streams only and the MJPEG
  stream runs without a pipeline crash

#### Scenario: Live view quality stable across modes
- **WHEN** a client watches live view in a low-framerate sensor mode (e.g.
  4608x2592 at ~14 fps)
- **THEN** the MJPEG stream uses the same fixed bitrate as in other modes and
  does not show bitrate-driven compression artifacts

#### Scenario: Stream continues across reconfigurations
- **WHEN** a client is watching live view and the camera is reconfigured (mode,
  flip, or control change)
- **THEN** the stream resumes without the client reconnecting and no additional
  feed worker is created per reconfigure

#### Scenario: Busy camera does not stall other clients
- **WHEN** one camera is busy with a long capture or recording finalization
- **THEN** other cameras' streams, status pushes, and requests continue to be
  served

## MODIFIED Requirements

### Requirement: MJPEG live view
The system SHALL expose a continuous MJPEG stream of the selected camera via
HTTP multipart/x-mixed-replace. The camera SHALL be configured with a `main`
stream (full resolution, for stills and recording) and a `lores` stream
(downscaled, for MJPEG) only — the stream configuration SHALL NOT include a raw
stream, since picamera2's default raw stream crashes the previous-generation
(vc4) camera pipeline.

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

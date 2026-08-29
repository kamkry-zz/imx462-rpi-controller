## Purpose

Stream a live view of a camera and push status/control updates to clients.

## ADDED Requirements

### Requirement: MJPEG live view
The system SHALL expose a continuous MJPEG stream of the selected camera via
HTTP multipart/x-mixed-replace.

#### Scenario: Client subscribes to live view
- **WHEN** a client requests the live-view stream for a selected camera
- **THEN** the system responds with a continuous MJPEG stream of frames from that
  camera

#### Scenario: Live view for unavailable camera
- **WHEN** a client requests live view for a camera that is not connected
- **THEN** the system returns an error instead of a stream

### Requirement: WebSocket status and control push
The system SHALL provide a WebSocket endpoint that pushes live status (camera
state, capture state, health, current gain/exposure, and connected client
addresses) to connected clients.

#### Scenario: Client receives status updates
- **WHEN** a client connects to the WebSocket endpoint and camera state changes
- **THEN** the client receives a status update over the socket

#### Scenario: Multiple simultaneous clients
- **WHEN** more than one client is connected to the WebSocket endpoint
- **THEN** every connected client receives status updates

### Requirement: Fullscreen live view
The system SHALL allow a client to expand the live view to fullscreen.

#### Scenario: Toggle fullscreen
- **WHEN** a client activates fullscreen on the live view
- **THEN** the live view expands to fill the screen and can be exited back to the
  embedded view

### Requirement: Single-frame capture mode
The system SHALL allow a client to switch the live view between continuous
streaming and an at-rest single-frame mode, showing a single captured frame in
place of the continuous feed.

#### Scenario: Enter single-frame mode
- **WHEN** a client enables single-frame mode
- **THEN** the continuous feed is stopped and the camera is left at rest

#### Scenario: Capture a single frame
- **WHEN** a client triggers a capture in single-frame mode
- **THEN** the system takes one still and displays it in the live-view window

#### Scenario: Return to continuous feed
- **WHEN** a client disables single-frame mode
- **THEN** the continuous live view is restored

#### Scenario: Auto-enter for long exposures
- **WHEN** a client selects a shutter speed longer than 2 seconds
- **THEN** the system automatically switches to single-frame mode

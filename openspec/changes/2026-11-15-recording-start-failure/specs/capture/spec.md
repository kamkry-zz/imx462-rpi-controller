## ADDED Requirements

### Requirement: Recording start failure
The system SHALL report a recording that cannot start as a conflict (HTTP 409)
with a short message naming the cause, SHALL log it as a single line without a
traceback, and SHALL leave no empty recording file and no half-started encoder
behind. When the current sensor mode exceeds what the hardware H.264 encoder
supports (more than 8192 macroblocks per frame, about 1920x1080), the message
SHALL say so and suggest a smaller mode. The live view, photo capture and later
recording attempts SHALL be unaffected.

#### Scenario: Recording in a mode the hardware encoder cannot handle
- **WHEN** a client starts a recording while the camera runs 2304x1296 on a
  board with a hardware-only H.264 encoder
- **THEN** the response is 409 whose message names the resolution and suggests
  a smaller mode
- **AND** no empty `.h264` file remains and the camera keeps working

#### Scenario: Recording after a failed start
- **WHEN** the cause is removed (for example a smaller mode is selected) and the
  client starts a recording again
- **THEN** the recording starts and is finalized normally

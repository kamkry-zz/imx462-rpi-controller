## ADDED Requirements

### Requirement: Camera unavailable handling
The system SHALL answer requests for a configured camera that cannot be opened
(for example a broken camera-stack install or an absent sensor) with HTTP 503
and a short error detail, and SHALL log the failure as a single line without a
traceback. After a failed open the system SHALL fail fast without re-opening the
camera for a backoff period (30 s), then retry. Repeated identical failures
SHALL NOT be logged at error level again, and a successful retry SHALL resume
normal operation.

#### Scenario: Camera stack fails to import
- **WHEN** a client requests a photo and opening the camera raises an error
- **THEN** the response is 503 with a detail naming the camera and the error
- **AND** exactly one error-level log line is written, without a traceback

#### Scenario: Requests during the backoff
- **WHEN** further requests arrive within the backoff period after a failure
- **THEN** each is answered 503 without attempting to open the camera again

#### Scenario: Camera recovers
- **WHEN** a request arrives after the backoff and the camera now opens
- **THEN** the request succeeds and subsequent requests use the opened camera

## Purpose

Capture still photos and record video from a selected camera.

## ADDED Requirements

### Requirement: Capture a still photo
The system SHALL capture a single still image from the selected camera and
return the encoded image file.

#### Scenario: Successful photo capture
- **WHEN** a client requests a photo from a selected camera
- **THEN** the system returns an image file (e.g. JPEG) captured from that camera

#### Scenario: Photo capture with no camera
- **WHEN** a client requests a photo but no camera is selected or available
- **THEN** the system returns an error

### Requirement: Start and stop video recording
The system SHALL start recording video from the selected camera and stop it on
demand, producing a playable video file.

#### Scenario: Start recording
- **WHEN** a client starts recording on a selected camera
- **THEN** recording begins and the system reports the recording as active

#### Scenario: Stop recording
- **WHEN** a client stops recording
- **THEN** recording stops and the system returns the path or identifier of the
  produced video file

#### Scenario: Stop when not recording
- **WHEN** a client requests to stop recording while none is active
- **THEN** the system returns an error or an idempotent no-op response

### Requirement: Persist captured media
The system SHALL store captured photos and videos in a configurable output
directory with deterministic, unique filenames.

#### Scenario: Media written to output directory
- **WHEN** a photo or video is captured
- **THEN** the media file is written to the configured output directory with a
  unique filename

### Requirement: MP4 video container
The system SHALL produce video in the MP4 container format when a remuxer is
available, falling back to raw H.264 otherwise.

#### Scenario: Video remuxed to MP4
- **WHEN** recording stops and a remuxer (ffmpeg) is available
- **THEN** the recorded video is delivered as an MP4 file and the raw stream is
  removed

#### Scenario: Fallback to raw H.264
- **WHEN** recording stops and no remuxer is available
- **THEN** the recorded video is delivered as a raw H.264 file

### Requirement: Asset gallery
The system SHALL expose captured media through an asset listing with download and
delete operations and per-file metadata.

#### Scenario: List assets
- **WHEN** a client requests the asset list
- **THEN** the system returns the captured files with filename, kind, size, and
  modification time

#### Scenario: Download an asset
- **WHEN** a client downloads an asset by filename
- **THEN** the system returns the file with a download disposition

#### Scenario: Delete an asset
- **WHEN** a client deletes an asset by filename
- **THEN** the file is removed from the output directory

#### Scenario: Path traversal blocked
- **WHEN** a client requests a filename that escapes the media directory
- **THEN** the system rejects the request

### Requirement: Single-frame snapshot
The system SHALL capture a single still with a requested total exposure time,
applying the exposure via a camera reconfigure so the result reflects the
requested exposure, and save it to the gallery.

#### Scenario: Snapshot with short exposure
- **WHEN** a client requests a snapshot with a short exposure
- **THEN** the system captures a single frame at that exposure and saves it as an
  image file

#### Scenario: Snapshot with long exposure
- **WHEN** a client requests a snapshot with an exposure up to 30 s
- **THEN** the system captures a single frame at that exposure and saves it as an
  image file

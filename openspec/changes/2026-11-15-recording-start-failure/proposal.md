## Why

On the new SD card in `raspberrypi-zero-2w-2` (IMX708, default mode 2304x1296),
`POST /recording/start` returned a 500 with a full traceback, left an empty
`.h264` file behind and wrote nothing useful to the user. The Pi's hardware
H.264 encoder (V4L2, vc4 boards) is limited to H.264 level 4.2, 8192
macroblocks per frame (about 1920x1088); a 2304x1296 frame is 11664, so
picamera2 fails when it sets the level control (`0x00990a67`, ret -3). At
1536x864 recording works and remuxes to `.mp4`. picamera2's `Encoder.start`
marks the encoder running and opens the output file before the hardware setup
can fail, and does not register the encoder on failure.

## What Changes

- A recording that cannot start returns **409** with `Recording could not
  start: <error>` and, when the current mode exceeds the hardware limit, a hint
  to switch to a smaller mode. It logs one WARNING line, no traceback (the Pi
  journal is RAM-only, so log volume matters).
- The failed encoder is stopped (best effort) and its empty raw file removed;
  the camera, live view and later recordings are unaffected.

## Impact

- Code: `camera/service.py` (`start_recording`, `_discard_failed_recording`,
  `_recording_failure_message`, `_h264_frame_too_large`).
- Tests: `tests/test_camera_service.py`, `tests/test_api.py`.
- Docs: `AGENTS.md` (hardware H.264 limit).
- No API shape change beyond the status code for this failure (500 -> 409).

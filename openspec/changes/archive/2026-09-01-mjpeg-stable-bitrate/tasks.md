## 1. Pin the MJPEG bitrate

- [x] 1.1 Add module constant `MJPEG_BITRATE = 20_000_000` and pass
  `bitrate=MJPEG_BITRATE` to `MJPEGEncoder` in `_default_mjpeg_encoder_factory`
  (`src/imx462_controller/camera/service.py`)

## 2. Regression test

- [x] 2.1 Add a unit test asserting the default MJPEG encoder factory builds
  the encoder with `MJPEG_BITRATE` (stub `picamera2.encoders` imports so it runs
  without hardware; skip if not straightforward)

## 3. Verify

- [x] 3.1 Run `pytest` and `ruff` — all pass
- [x] 3.2 Deploy via the playbook and confirm on the zero-2w-2 UI that the
  4608x2592 mode's live feed is clean (no macroblocking), with other modes
  unchanged

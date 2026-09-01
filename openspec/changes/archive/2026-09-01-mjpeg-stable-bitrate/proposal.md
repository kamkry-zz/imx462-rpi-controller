## Why

In the 4K (4608x2592) mode of the Camera Module 3 Wide, the live view shows
heavy macroblocking ("big pixel-blocks") while other resolutions look clean.
picamera2 derives the hardware MJPEG encoder's bitrate from the encoder's
nominal framerate, which is pegged to the sensor mode's max frame rate: at 4K
(~14 fps) the bitrate collapses to ~6.4 Mbps versus ~13.3 Mbps in the
30fps-capped modes — on a harder, noisier (un-binned) source.

## What Changes

- Pin an explicit MJPEG encoder bitrate (20 Mbps) in the default live-view
  encoder factory so the bitrate no longer scales down with low sensor frame
  rates; the value becomes a named module constant.
- Live-view encode quality becomes stable across all sensor modes.

## Capabilities

### New Capabilities

- none

### Modified Capabilities

- `live-view`: the MJPEG live-view requirement now states that the encoding
  bitrate is fixed and independent of the sensor mode / frame rate, so quality
  does not degrade in low-framerate modes.

## Impact

- `src/imx462_controller/camera/service.py`: `_default_mjpeg_encoder_factory`
  passes `bitrate=20_000_000` (new module constant `MJPEG_BITRATE`).
- No config/API changes; tests already inject encoder fakes (no breakage).

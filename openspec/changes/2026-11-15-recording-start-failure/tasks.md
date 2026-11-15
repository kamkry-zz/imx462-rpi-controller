## 1. Recording start failure

- [x] 1.1 Catch encoder-factory and `start_encoder` failures in `CameraWorker.start_recording`, stop the failed encoder best-effort, remove the raw file, raise `RuntimeError` (routes map it to 409)
- [x] 1.2 Add a hint when the mode exceeds the hardware H.264 frame limit (8192 macroblocks)
- [x] 1.3 Log one WARNING line instead of a traceback
- [x] 1.4 Tests: cleanup and recovery, hint only for oversized modes, factory failure, encoder whose `stop()` raises, API 409 without traceback
- [ ] 1.5 Deploy to `raspberrypi-zero-2w-2` and verify the 409 at 2304x1296 and a working recording at 1536x864

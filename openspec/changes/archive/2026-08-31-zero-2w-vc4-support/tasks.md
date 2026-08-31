## 1. Platform detection

- [x] 1.1 Add play `pre_tasks` to `ansible/playbook.yml` that slurp
      `/proc/device-tree/model` and set the `imx462_is_pi5_pisp` host fact
- [x] 1.2 Refactor `ansible/roles/app/tasks/main.yml` to consume the play-level
      fact (drop its local slurp + `set_fact`)

## 2. Platform-aware camera overlay

- [x] 2.1 Split the `camera-overlay` role's "Ensure overlay" task: pisp variant
      keeps the `,cam{{ id }}` line and regexp; csi variant writes the bare
      `dtoverlay=<overlay>[,params]` line with an overlay-anchored regexp that
      rewrites stale `,cam0` lines in place
- [x] 2.2 Keep stale-slot removal for unconfigured slots unchanged

## 3. Platform-aware vendor tuning

- [x] 3.1 Gate the vendor tuning install block on `imx462_is_pi5_pisp`
- [x] 3.2 Restore the stock pisp `imx290.json` from the `.rpi-default` backup on
      non-Pi 5 platforms (self-healing)

## 4. Stream stability (raw stream removal)

- [x] 4.1 Pass `raw=None` to `create_video_configuration` in
      `CameraWorker.configure_mode` (`src/imx462_controller/camera/service.py`)

## 5. Capability read serialization

- [x] 5.1 Add `CameraWorker.capabilities()`: reads under the camera lock, caches
      the result, returns `None` while the camera is started
- [x] 5.2 Route `CameraManager.capabilities()` through the worker executor

## 6. Tests

- [x] 6.1 Update `FakePicamera2.create_video_configuration` in
      `tests/test_camera_service.py` and `tests/test_api.py` to accept `raw`
- [x] 6.2 Add tests: video config requests no raw stream; capabilities cached
      after first read; capabilities skipped while the camera is started

## 7. Docs

- [x] 7.1 AGENTS.md: csi-platform overlay suffix behavior (Unicam 1, `cam0` =
      Compute Module layout), `raw=None` requirement, capabilities read rules
- [x] 7.2 Update `README.md` / `docs/deployment.md` for previous-gen platform
      support
- [x] 7.3 Update `openspec/project.md` with the Zero 2W / vc4 platform context

## 8. Verification

- [x] 8.1 `python -m pytest` (87 passed) and `ruff check` clean
- [x] 8.2 Deploy to `raspberrypi-zero-2w-1`: bare overlay line in config.txt,
      reboot, sensor enumerated on `i2c@1`, live MJPEG stream serves with no
      aborts (`NRestarts=0`)
- [x] 8.3 Deploy to `raspberrypi-5-2` and verify streaming still works
- [x] 8.4 Validate OpenSpec artifacts

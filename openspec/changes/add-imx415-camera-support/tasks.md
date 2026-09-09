## 1. Camera service (src/imx462_controller/camera/service.py)

- [x] 1.1 Add `imx415` to `_MODEL_MODES` (single 3840x2160 @ 15 mode, `bit_depth=None`) and `_MODEL_BOUNDS` (`(MIN_FRAME_US, 30_000_000, 1.0, 31.6)`) with a comment that the sensor is RAW10-only / 2-lane csi boards are ~15 fps
- [x] 1.1b Offer a second 4K profile at 30 fps in `_MODEL_MODES["imx415"]` (selectable via the UI dropdown, which is fed from the static catalog); 30 fps is only reached on 4-lane ports — libcamera clamps on 2-lane boards
- [x] 1.2 Add a `_min_frame_us(mode)` helper (`ceil(1_000_000 / framerate)`, falling back to `MIN_FRAME_US` for `mode is None`)
- [x] 1.3 Use `_min_frame_us(self._mode)` in `_apply_snapshot_exposure` for the `frame` clamp
- [x] 1.4 Use `_min_frame_us(self._mode)` in `_metadata_loop` when no explicit `FrameDurationLimits` is present

## 2. Web UI (src/imx462_controller/static/app.js)

- [x] 2.1 Add a `minFrameUs()` helper deriving `Math.ceil(1e6 / framerate)` from the selected mode in the mode dropdown (fallback 16666)
- [x] 2.2 Replace the `MIN_FRAME_US` usages in the manual-exposure branch and the snapshot default with `minFrameUs()`
- [x] 2.3 Fix `populateModes` so null `bit_depth` renders `${w}x${h} @${fps}fps` instead of `RAWundefined`

## 3. Setup configurator (scripts/configure.py)

- [x] 3.1 Add `imx415` (params `""`, default mode 3840x2160@15, no bit depth) and `imx415-4lane` (`overlay: imx415`, params `"4lane"`, default mode 3840x2160@30) to `OVERLAYS`, with optional `overlay` key support in `_camera_entry`
- [x] 3.2 Update the cam0/cam1 overlay prompt hints to describe `imx415` and `imx415-4lane` (4-lane only on Pi 5 CAM1)
- [x] 3.3 Update `tests/test_configure.py` with imx415 + imx415-4lane rendering cases (overlay name, params, default mode incl. no bit_depth)

## 4. Ansible roles

- [x] 4.1 `roles/camera-overlay/tasks/main.yml`: compute `imx462_has_imx415` from `imx462_cameras`; ensure `camera_auto_detect=0` via lineinfile only when true
- [x] 4.2 `roles/camera-overlay/tasks/main.yml`: imx415 preflight — fail fast when `/boot/firmware/overlays/imx415.dtbo` (or `/boot/overlays/imx415.dtbo`) or the platform tuning file (`/usr/share/libcamera/ipa/rpi/{pisp,vc4}/imx415.json`) is missing, with an actionable `apt full-upgrade` message; runs only when imx415 configured
- [x] 4.3 `roles/camera-overlay/tasks/main.yml`: remove stale **bare** camera-overlay lines on csi platforms (found during the zero-2w-1 sensor switch: the old `dtoverlay=imx290,...` line survived because stale cleanup only matched `camN`-suffixed lines, leaving two camera overlays fighting over Unicam 1) — cleanup now removes any known-camera overlay line no longer configured; add `known_camera_overlays`/`configured_camera_overlays` facts

## 5. Templates and examples

- [x] 5.1 `config.example.yaml`: add an imx415 camera example (4K default) with comments on the 15 fps csi ceiling and the `4lane` Pi 5 CAM1 option
- [x] 5.2 `ansible/host_vars/pi.example.yml`: illustrate the imx415 entry (bare overlay, 4K@15 default_mode without bit_depth)

## 6. Documentation

- [x] 6.1 `docs/architecture.md` and `docs/deployment.md`: document imx415 support, overlay/bandwidth facts, auto-detect note, preflight behaviour
- [x] 6.2 `AGENTS.md` and `openspec/project.md`: record hard-won IMX415 facts (mainline overlay/driver/tuning, no vendor files, 2-lane ~15-17 fps ceiling, 4lane param, camN suffix same as imx290)

## 7. Tests

- [x] 7.1 `tests/test_camera_service.py`: imx415 fallback catalog (mode set, bounds, no RAW12) and `_min_frame_us` behaviour (60 fps → ~16 667, 15 fps → ~66 667)
- [x] 7.2 `tests/test_config.py`: imx415 overlay entry passes validation (mirrors the imx708 case)

## 8. Verify

- [x] 8.1 Run `pytest` and `ruff` locally — all pass
- [x] 8.2 Deploy to `raspberrypi-zero-2w-1` via the playbook with imx415 host_vars (IMX415 replaces IMX462), reboot, and confirm `rpicam-hello --list-cameras` lists the imx415
- [x] 8.3 On the host: check `GET /api/cameras/0/capabilities` (modes, exposure/gain bounds), live view, a manual-exposure change, and a single-frame snapshot at a long exposure

## 9. Capabilities contract for external clients (cat-watcher)

- [x] 9.1 Add `min_frame_duration_us` to `CameraCapabilities` — the frame-duration floor of the configured default mode (fallback: fastest advertised mode); populated in `read_capabilities(picam2, default_mode)` and `_capabilities_for_model`; included in `to_dict()`
- [x] 9.2 `set_controls` raises any incoming `FrameDurationLimits` below the active mode's floor to the mode-derived minimum (authoritative clamp for clients hard-coding 1/60 s)
- [x] 9.3 Tests: read_capabilities floor computation (fastest-mode fallback), default-mode floor for imx415 (66 667), static fallback (33 334), API payload key, and the set_controls clamp on a 15 fps mode
- [x] 9.4 Update the camera-control delta spec (`min_frame_duration_us` + controls-API clamp scenarios)

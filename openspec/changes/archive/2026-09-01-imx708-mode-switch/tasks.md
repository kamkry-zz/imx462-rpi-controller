## 1. Fix the mode API

- [x] 1.1 Make `ModeRequest.bit_depth` optional (`int | None = None`) in
  `src/imx462_controller/api/routes.py`

## 2. Surface UI errors

- [x] 2.1 Replace console-only `console.error` with `toast()` in `applyMode`,
  `applyControls`, `applyFlip`, and `setSingleMode` in
  `src/imx462_controller/static/app.js`

## 3. Regression tests

- [x] 3.1 Add `test_set_mode_bit_depth_null` in `tests/test_api.py`: PUT
  `/api/cameras/0/mode` with `bit_depth: null` returns 200 and `ok: true`
- [x] 3.2 Add a `configure_mode` case in `tests/test_camera_service.py` with
  `CameraMode(bit_depth=None)` asserting the sensor config has no `bit_depth`
  key

## 4. Verify

- [x] 4.1 Run `pytest` and `ruff` — all pass
- [x] 4.2 Deploy via the playbook (all Pis) and confirm on the zero-2w-2 UI
  that switching to 1536x864 reconfigures (journal shows
  `configured: CameraMode(width=1536, ...)`) and the FOV visibly narrows

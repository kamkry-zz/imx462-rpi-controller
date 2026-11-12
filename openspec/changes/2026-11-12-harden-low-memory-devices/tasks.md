## 1. Camera open failures

- [x] 1.1 Add `CameraUnavailableError` (not a `RuntimeError`, so routes do not map it to 409) and open cameras through `CameraManager._open_camera` with a 30 s fail-fast backoff (`CAMERA_RETRY_BACKOFF_S`)
- [x] 1.2 Log the first failure as one ERROR line (`type: message`, no traceback); demote repeats of the same error to DEBUG; log recovery at INFO
- [x] 1.3 App-level exception handler returns 503 `{"detail": ...}`; document 503 in the camera route responses
- [x] 1.4 Tests: open failure → 503 on photo/flip, opened once during the backoff, no traceback, one ERROR; retry after the backoff and recovery

## 2. Service memory guard

- [x] 2.1 Role defaults `imx462_memory_high/max/swap_max` (40%/50%/25%) and `imx462_enable_memory_cgroup`
- [x] 2.2 Unit template: `MemoryAccounting=yes`, `MemoryHigh`, `MemoryMax`, `MemorySwapMax`
- [x] 2.3 Append `cgroup_enable=memory` to `cmdline.txt` idempotently; warn that a reboot is required
- [ ] 2.4 Deploy, reboot each Pi, verify `memory` in `/sys/fs/cgroup/cgroup.controllers` and the limits via `systemctl show imx462-controller -p MemoryMax`

## 3. CMA on low-memory boards

- [x] 3.1 Role default `imx462_cma_mb` (192 on ≤512 MB RAM, else 0 = untouched)
- [x] 3.2 Rewrite an existing `dtoverlay=vc4-kms-v3d` line with `cma-N`, preserving other parameters; never add the overlay; warn that a reboot is required
- [ ] 3.3 After reboot on the Zeros, verify `CmaTotal` ≈ 192 MB and that live view, photos and a recording still work

## 4. Docs

- [x] 4.1 AGENTS.md: Trixie camera-stack leak, memory guard + cgroup, CMA, volatile journal / failing-SD guidance
- [x] 4.2 `host_vars/pi.example.yml`: document the new overridable variables

## Why

Both Pi Zero 2 W cameras kept getting stuck. Investigation (2026-11-12) found:

- `raspberrypi-zero-2w-1` died after ~3.5 days in a memory death spiral: swap
  100% full, ~35 MB available, 40–50% iowait, then a 3-hour hang. The
  controller leaks native memory on the Trixie camera stack (picamera2
  0.3.37/0.3.38 + libcamera 0.7.2) under sustained photo/flip load; Pi 5 hosts
  leak the same way (3.1 GB after 9.5 days) but have the RAM to hide it, and
  Bookworm hosts under identical load stay flat. `vc4-kms-v3d` additionally
  reserves 256 MB of the Zero's 416 MB as CMA, and the firmware's
  `cgroup_disable=memory` means no systemd memory limit can contain the leak.
- `raspberrypi-zero-2w-2` has a failing SD card (bit-flipped reads; corrupted
  numpy makes every camera request fail). Each failed request logged a full
  traceback, flooding the RAM-only journal (Pi OS keeps it volatile to protect
  SD cards) so crash evidence was lost within minutes.

## What Changes

- **Camera open failures**: a camera that fails to open raises
  `CameraUnavailableError`, answered as HTTP 503 with a one-line log; the
  manager fails fast during a 30 s backoff, then retries. Repeats of the same
  error log at DEBUG. No traceback per request.
- **Service memory guard**: the systemd unit sets `MemoryAccounting`,
  `MemoryHigh` (40%), `MemoryMax` (50%) and `MemorySwapMax` (25%) — role
  defaults, overridable per host. The app role appends `cgroup_enable=memory`
  to `cmdline.txt` so the limits are enforced (reboot required).
- **CMA on low-memory boards**: the camera-overlay role sets
  `dtoverlay=vc4-kms-v3d,cma-192` on boards with ≤512 MB RAM
  (`imx462_cma_mb`), preserving other overlay parameters (reboot required).

## Impact

- Code: `camera/service.py`, `api/app.py`, `api/routes.py`; tests in
  `tests/test_api.py`.
- Ansible: `roles/app` (defaults, unit template, cmdline task),
  `roles/camera-overlay` (defaults, CMA tasks), `host_vars/pi.example.yml`.
- Operations: one reboot per Pi after the next deploy to activate the memory
  cgroup (and CMA on the Zeros). The root-cause fix for the camera-stack leak
  is out of scope (follow-up once the leaking call is isolated on hardware).

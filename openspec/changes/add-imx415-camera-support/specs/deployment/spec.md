## ADDED Requirements

### Requirement: IMX415 sensor support in the setup configurator
The setup configurator SHALL offer the `imx415` overlay (Inno Maker
CAM-MIPI-IMX415 / other IMX415 modules) as a camera option. For the imx415 the
configurator SHALL default to a 3840x2160 @ 15 fps mode (the sensor reads out
its full 3864x2192 array regardless of output size, and 2-lane csi platforms
are bandwidth-bound to ~15-17 fps). When asked for a high-end board profile
(Pi 5, 4-lane CAM1 port), the configurator SHALL emit the overlay `4lane`
parameter and a 3840x2160 @ 30 fps default mode instead. Generated host_vars
SHALL carry the imx415 default mode without a bit depth (RAW10-only sensor).

#### Scenario: Configurator offers imx415 for a csi board
- **WHEN** the configurator runs for a Zero 2 W / Pi 3 / Pi 4 target and the
  user selects the `imx415` overlay
- **THEN** the generated camera entry declares the `imx415` overlay with no
  extra parameters and a 3840x2160 @ 15 fps default mode without a bit depth

#### Scenario: Configurator offers the 4-lane profile for a Pi 5 CAM1
- **WHEN** the user selects the `imx415` overlay with the 4-lane Pi 5 CAM1
  profile
- **THEN** the generated camera entry declares the `imx415` overlay with the
  `4lane` parameter and a 3840x2160 @ 30 fps default mode

### Requirement: IMX415 OS-support preflight
The deployment SHALL fail fast with an actionable message before provisioning
whenever an `imx415` camera is configured but the target OS cannot drive it:
either the kernel `imx415` device-tree overlay (dtbo) is missing from the boot
firmware partition, or the matching libcamera tuning file for the host's
platform (pisp on Pi 5, vc4 elsewhere) is absent. The message SHALL point at
the remedy (update the OS / kernel and libcamera packages).

#### Scenario: Preflight passes
- **WHEN** an `imx415` camera is configured and the target OS ships the
  `imx415` overlay and the libcamera tuning file
- **THEN** the playbook proceeds normally

#### Scenario: Preflight fails on an outdated OS
- **WHEN** an `imx415` camera is configured but the kernel overlay or tuning
  file is missing (e.g. un-updated Bookworm)
- **THEN** the playbook aborts with a message stating that IMX415 support is
  missing and how to install it

#### Scenario: Preflight skipped for other sensors
- **WHEN** no configured camera uses `imx415`
- **THEN** no imx415 preflight applies and provisioning proceeds as before

### Requirement: Disable camera auto-detection for imx415
When at least one configured camera uses the `imx415` overlay, the deployment
SHALL ensure `camera_auto_detect=0` is set in the firmware `config.txt`, as
required by the module vendor so the firmware does not probe the camera port.
When no configured camera uses `imx415`, the deployment SHALL NOT manage the
`camera_auto_detect` setting, leaving existing behaviour for legacy sensors
(imx290, imx708, ...) untouched.

#### Scenario: Auto-detect disabled for an imx415 deployment
- **WHEN** an `imx415` camera is configured and the playbook runs
- **THEN** `config.txt` contains `camera_auto_detect=0` and the overlay line
  for the camera

#### Scenario: Legacy deployments untouched
- **WHEN** only legacy sensors (e.g. `imx290`, `imx708`) are configured
- **THEN** the playbook neither adds nor removes `camera_auto_detect` lines

## MODIFIED Requirements

### Requirement: Camera overlay for one or two cameras
The deployment SHALL apply one device-tree overlay per configured camera, driven
by each camera's declared overlay (`imx290`, `imx708`, `imx219`, `imx477`,
`ov5647`, `imx296`, `imx415`), and SHALL remove stale overlay lines for
unconfigured camera slots. On the Pi 5 (pisp) platform each overlay line SHALL
carry the camera slot suffix (`cam0`/`cam1`); on previous-generation (csi)
platforms the overlay line SHALL omit the suffix so the overlay's default
(Unicam 1, the standard camera connector) applies, and any stale suffixed line
for a configured slot SHALL be rewritten to the bare form. When the sensor on a
csi-platform board changes (e.g. imx290 to imx415 on the same connector), the
deployment SHALL also remove the stale bare overlay line of any known camera
overlay that is no longer configured, so two camera overlays never fight over
Unicam 1; lines for non-camera overlays SHALL be left untouched.

#### Scenario: Configure two cameras
- **WHEN** the deployment is configured for two cameras on a Pi 5
- **THEN** both `cam0` and `cam1` overlays are applied and the device reboots to
  activate them

#### Scenario: Configure heterogeneous cameras
- **WHEN** the deployment is configured for an `imx290` camera on cam0 and an
  `imx708` camera on cam1
- **THEN** the matching `dtoverlay` lines are written to `config.txt` and any
  stale overlay for a slot is replaced, after which the device reboots to
  activate them

#### Scenario: Single camera on a previous-gen board
- **WHEN** the deployment is configured for one `imx290` camera on a csi
  platform board (e.g. Raspberry Pi Zero 2 W)
- **THEN** `config.txt` receives the bare
  `dtoverlay=imx290,clock-frequency=74250000` line without a `camN` suffix and
  the sensor is reachable on the standard camera connector

#### Scenario: Sensor switch on a previous-gen board
- **WHEN** the deployment for a csi platform board is reconfigured from an
  `imx290` camera to an `imx415` camera on the same connector
- **THEN** the stale bare `dtoverlay=imx290,...` line is removed, the new
  `dtoverlay=imx415` line is added, and unrelated `dtoverlay` lines remain
  untouched

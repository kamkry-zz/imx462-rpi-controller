# Deployment Specification

## Purpose

Provision the Raspberry Pi and manage the application service via Ansible.
## Requirements
### Requirement: Ansible provisioning
The system SHALL provide Ansible automation that, given a target IP and
pre-exchanged SSH keys, installs dependencies, applies the per-camera dtoverlay,
deploys the application, and renders configuration/secrets from templates.
The playbook SHALL detect the host's libcamera platform from the device model
(Pi 5 = pisp) and use it to drive platform-specific deployment steps.

#### Scenario: Provision a fresh Pi
- **WHEN** the playbook runs against a target Pi
- **THEN** dependencies are installed, the per-camera dtoverlay(s) are applied,
  the application is deployed, and config/secrets are rendered

#### Scenario: Re-run is idempotent
- **WHEN** the playbook is run again against an already-provisioned Pi
- **THEN** it makes no unintended changes and reports success

#### Scenario: Platform detected
- **WHEN** the playbook runs
- **THEN** it determines from the device model whether the host runs the Pi 5
  (pisp) or previous-generation (csi) camera platform and applies the matching
  overlay and tuning steps

### Requirement: Systemd service lifecycle
The system SHALL deploy the application as a systemd service that starts on boot
and restarts on failure. The unit SHALL allow a stop timeout long enough for the
application to finalize an active recording (remuxing raw video to its container)
during shutdown before the process is terminated.

#### Scenario: Service enabled and running
- **WHEN** deployment completes
- **THEN** the service is enabled, running, and configured to restart on failure

#### Scenario: Graceful stop with an active recording
- **WHEN** the service is stopped while a recording is active
- **THEN** the unit grants enough time for the recording to be finalized before
  terminating the process

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

### Requirement: Vendor camera tuning
When an `imx290` (IMX462) camera is configured, the deployment SHALL install the
vendor tuning file on the Pi 5 (pisp) platform to correct the IMX462 colour cast,
backing up the stock tuning first. On previous-generation (csi) platforms the
deployment SHALL keep the stock tuning file and SHALL restore it if the vendor
file was previously installed.

#### Scenario: Install vendor tuning on Pi 5
- **WHEN** an `imx290` camera is configured on a Pi 5
- **THEN** the vendor tuning file replaces the stock pisp `imx290.json` and the
  stock file is backed up

#### Scenario: Keep stock tuning on previous-gen platforms
- **WHEN** an `imx290` camera is configured on a csi platform board
- **THEN** the stock tuning file remains in place, or is restored from the
  backup if a previous install had replaced it

### Requirement: Interactive setup configurator
The system SHALL provide an interactive, stdlib-only command-line tool that
guides a user through the questions needed to deploy to a fresh Raspberry Pi and
generates the local Ansible inventory and host_vars.

#### Scenario: Generate deployment files
- **WHEN** the configurator runs with valid answers
- **THEN** it writes `ansible/inventory.ini` and
  `ansible/host_vars/<hostname>.yml`

#### Scenario: Scripted answers
- **WHEN** the configurator is given a JSON answers file
- **THEN** it generates the files without interactive prompts

#### Scenario: Secrets never printed
- **WHEN** the configurator collects secret values
- **THEN** they are masked during input and never written to stdout

### Requirement: Secrets kept out of the repository
The system SHALL keep all secrets out of version control: configuration and
secrets live in git-ignored local files, and only `*.example` templates are
committed.

#### Scenario: Secrets git-ignored
- **WHEN** the repository is inspected
- **THEN** `config.yaml`, `.env`, `ansible/inventory.ini`, and
  `ansible/host_vars/*` (except `*.example.yml`) are ignored by git

#### Scenario: Example template committed
- **WHEN** the repository is inspected
- **THEN** a `*.example.yml` host_vars template is present in the repository

### Requirement: Continuous integration
The system SHALL run the test suite and linter in CI on every pull request and
push to the default branch.

#### Scenario: PR runs tests and lint
- **WHEN** a pull request is opened against the default branch
- **THEN** the test suite (pytest) runs on supported Python versions and the
  linter (ruff) runs, and their results are reported on the PR

#### Scenario: Push to default branch runs CI
- **WHEN** a commit is pushed to the default branch
- **THEN** the same tests and lint run on the push

#### Scenario: Test results posted to the PR
- **WHEN** a pull request run finishes
- **THEN** a comment with the aggregated test results (passed/failed/skipped and
  failed test names) is posted to the pull request

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


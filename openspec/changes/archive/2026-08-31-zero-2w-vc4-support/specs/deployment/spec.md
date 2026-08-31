## MODIFIED Requirements

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

### Requirement: Camera overlay for one or two cameras
The deployment SHALL apply one device-tree overlay per configured camera, driven
by each camera's declared overlay (`imx290`, `imx708`, `imx219`, `imx477`,
`ov5647`, `imx296`), and SHALL remove stale overlay lines for unconfigured camera
slots. On the Pi 5 (pisp) platform each overlay line SHALL carry the camera slot
suffix (`cam0`/`cam1`); on previous-generation (csi) platforms the overlay line
SHALL omit the suffix so the overlay's default (Unicam 1, the standard camera
connector) applies, and any stale suffixed line for a configured slot SHALL be
rewritten to the bare form.

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

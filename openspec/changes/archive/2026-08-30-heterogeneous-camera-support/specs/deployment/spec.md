## MODIFIED Requirements

### Requirement: Ansible provisioning
The system SHALL provide Ansible automation that, given a target IP and
pre-exchanged SSH keys, installs dependencies, applies the per-camera dtoverlay,
deploys the application, and renders configuration/secrets from templates.

#### Scenario: Provision a fresh Pi
- **WHEN** the playbook runs against a target Pi
- **THEN** dependencies are installed, the per-camera dtoverlay(s) are applied,
  the application is deployed, and config/secrets are rendered

#### Scenario: Re-run is idempotent
- **WHEN** the playbook is run again against an already-provisioned Pi
- **THEN** it makes no unintended changes and reports success

### Requirement: Camera overlay for one or two cameras
The deployment SHALL apply one device-tree overlay per configured camera, driven
by each camera's declared overlay (`imx290`, `imx708`, `imx219`, `imx477`,
`ov5647`, `imx296`), and SHALL remove stale overlay lines for unconfigured camera
slots.

#### Scenario: Configure two cameras
- **WHEN** the deployment is configured for two cameras
- **THEN** both `cam0` and `cam1` overlays are applied and the device reboots to
  activate them

#### Scenario: Configure heterogeneous cameras
- **WHEN** the deployment is configured for an `imx290` camera on cam0 and an
  `imx708` camera on cam1
- **THEN** the matching `dtoverlay` lines are written to `config.txt` and any
  stale overlay for a slot is replaced, after which the device reboots to
  activate them

## ADDED Requirements

### Requirement: Host metrics export
The deployment SHALL install and enable `prometheus-node-exporter` on every
provisioned Pi so host metrics are available on port 9100 for external scraping.

#### Scenario: Node exporter running
- **WHEN** provisioning completes on a Pi
- **THEN** the `prometheus-node-exporter` service is installed, enabled, and
  running on port 9100

## MODIFIED Requirements

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

#### Scenario: Single imx708 camera on a previous-gen board
- **WHEN** the deployment is configured for one `imx708` camera on a csi
  platform board (e.g. Raspberry Pi Zero 2 W)
- **THEN** `config.txt` receives the bare `dtoverlay=imx708` line without a
  `camN` suffix, without overlay parameters, and without a bit-depth override,
  and the sensor is reachable on the standard camera connector

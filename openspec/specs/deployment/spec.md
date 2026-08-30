# Deployment Specification

## Purpose

Provision the Raspberry Pi and manage the application service via Ansible.

## Requirements

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

### Requirement: Systemd service lifecycle
The system SHALL deploy the application as a systemd service that starts on boot
and restarts on failure.

#### Scenario: Service enabled and running
- **WHEN** deployment completes
- **THEN** the service is enabled, running, and configured to restart on failure

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


# Configuration Specification

## Purpose

Centralize non-secret configuration and secrets, with templates for every
configurable file.

## Requirements

### Requirement: Load non-secret configuration
The system SHALL load non-secret configuration values (server, cameras, MQTT
topics, OTel endpoint, capture output paths and formats) from a dedicated
`config.yaml` file. The default video format SHALL be MP4.

#### Scenario: Valid config loaded
- **WHEN** the system starts with a valid `config.yaml`
- **THEN** the configured values are applied

#### Scenario: Missing or invalid config
- **WHEN** the `config.yaml` is missing or malformed
- **THEN** the system reports a clear error at startup and does not run with
  partial configuration

### Requirement: Load secrets from environment
The system SHALL load secrets (e.g. MQTT credentials, tokens) from a local
`.env` file, which is git-ignored.

#### Scenario: Secrets loaded
- **WHEN** the system starts with a valid `.env`
- **THEN** secrets are available to the running application

### Requirement: Templates for all configurable files
The repository SHALL contain a committed template/example for every configurable
file (`config.example.yaml`, `.env.example`, Ansible inventory/host_vars
examples, systemd unit template).

#### Scenario: Templates present
- **WHEN** a new configurable file or config key is added
- **THEN** a corresponding committed example/template exists

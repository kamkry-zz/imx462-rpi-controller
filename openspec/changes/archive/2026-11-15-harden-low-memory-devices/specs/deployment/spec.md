## ADDED Requirements

### Requirement: Service memory guard
The provisioning SHALL install the controller service with memory limits
(`MemoryHigh`, `MemoryMax`, `MemorySwapMax`, expressed as a share of physical
RAM and overridable per host) so that unbounded memory growth terminates and
restarts the service instead of exhausting the device. Because the Raspberry Pi
firmware disables the memory cgroup controller by default, provisioning SHALL
enable it on the kernel command line (`cgroup_enable=memory`) idempotently and
SHALL report that a reboot is required when it changes the command line.

#### Scenario: Fresh deploy on a Raspberry Pi
- **WHEN** the playbook runs against a Pi whose kernel command line lacks
  `cgroup_enable=memory`
- **THEN** the flag is appended once, the unit carries the memory limits, and
  the run reports that a reboot is required

#### Scenario: Re-run after reboot
- **WHEN** the playbook runs again
- **THEN** the command line is unchanged and no reboot warning is emitted

### Requirement: Contiguous memory sizing on low-memory boards
On boards with at most 512 MB of RAM the provisioning SHALL size the
`vc4-kms-v3d` contiguous-memory (CMA) reservation to a configurable value
(default 192 MB) by rewriting the existing overlay line, preserving its other
parameters, and SHALL report that a reboot is required when it changes it. It
SHALL NOT add the overlay when absent and SHALL leave larger boards untouched by
default.

#### Scenario: Pi Zero 2 W
- **WHEN** the playbook runs against a Pi Zero 2 W with `dtoverlay=vc4-kms-v3d`
- **THEN** the line becomes `dtoverlay=vc4-kms-v3d,cma-192` and a reboot is reported

#### Scenario: Pi 5
- **WHEN** the playbook runs against a board with more than 512 MB of RAM
- **THEN** the `vc4-kms-v3d` line is not modified

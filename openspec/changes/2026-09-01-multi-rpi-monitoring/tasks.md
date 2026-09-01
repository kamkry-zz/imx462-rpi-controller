## 1. Finalize tracked code changes

- [ ] 1.1 Commit `.env.example`, `ansible/host_vars/pi.example.yml`,
  `scripts/configure.py`, and `tests/test_configure.py` with a message
  describing per-host OTel identity support
- [ ] 1.2 Run the test suite (`pytest`) and linter (`ruff`) and confirm all
  pass, including `tests/test_configure.py` covering
  `OTEL_RESOURCE_ATTRIBUTES` generation

## 2. Documentation

- [ ] 2.1 Add a short AGENTS.md note: `OTEL_RESOURCE_ATTRIBUTES`
  (host.name/service.instance.id per Pi) and that node_exporter on all Pis is
  scraped via the observability collector job `imx462-rpi`

## 3. Verification (already applied live — re-confirm)

- [ ] 3.1 Confirm `up{job="imx462-rpi"}` reports 3 targets
  (`raspberrypi-5-2`, `raspberrypi-zero-2w-1`, `raspberrypi-zero-2w-2`, all on
  :9100)
- [ ] 3.2 Confirm app OTel metrics carry `instance="<fqdn>.krysdom"` per Pi and
  Loki log streams carry `host_name` per Pi

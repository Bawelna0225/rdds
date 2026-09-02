# RDDS Stage 25A — Fleet Readiness Inventory

Stage 25A adds a single, server-side assessment of operational readiness for
the sensor fleet. It reuses the health, heartbeat, source, configuration and
agent-version data already reported to RDDS. The sensor agent protocol and
runtime behavior are unchanged.

## Readiness states

- `ready` — the active sensor satisfies the complete policy;
- `attention` — the sensor remains usable but is degraded or below the
  recommended agent version;
- `blocked` — the active sensor does not satisfy a mandatory requirement;
- `excluded` — the sensor is disabled or in maintenance and is intentionally
  omitted from readiness percentages.

Disabled simulator records therefore do not make the active fleet look
unhealthy. Stage 25A exposes `rollout_eligible` as information only. Rollout
creation, start and advance behavior remain unchanged until Stage 25B.

## Policy

Migration `025_sensor_fleet_readiness.sql` creates the singleton
`sensor_fleet_readiness_policy` row with:

- minimum agent version `0.23.0`;
- recommended agent version `0.23.0`;
- connected source required;
- compliant managed configuration required.

Policy updates use optimistic revision checks and require an operator change
note. Every successful update creates the
`sensor_fleet_readiness_policy_changed` audit event.

## API

- `GET /api/v1/sensor-fleet/readiness` — viewer-accessible inventory, policy,
  summary and active-agent version distribution;
- `PUT /api/v1/sensor-fleet/readiness-policy` — administrator-only policy
  update protected by CSRF and policy revision.

## Web UI

The **Konto operatora → Administracja → Konfiguracja floty → Gotowość** tab
shows readiness totals, every sensor with explicit reason codes, the active
agent version distribution and the editable policy. The rollout target picker
also shows the current readiness assessment but does not disable any target in
this stage.

## Safety boundary

Stage 25A does not:

- change sensor-agent code or configuration;
- update or install agent software;
- reject a rollout target;
- start, advance, cancel or roll back a rollout;
- modify sensor lifecycle or health transitions.

Stage 25B may enforce readiness at rollout boundaries only after this inventory
has been validated against the real fleet.

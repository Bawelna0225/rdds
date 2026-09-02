# RDDS Stage 24B — controlled configuration rollouts

Stage 24B connects immutable configuration profile versions from Stage 24A to
sensor desired configuration. It adds explicit, operator-controlled batches and
does not automatically deploy a profile when the profile receives a new version.

## State machine

Every rollout starts as `draft`. Creating a rollout only validates and freezes
the target sensor list. It does not alter any sensor configuration.

`start` changes the rollout to `active` and deploys exactly one bounded batch.
`advance` is accepted only when every previously deployed target reports the
expected applied revision. A target in `error`, `superseded`, or
`awaiting_application` blocks the next batch.

After the final batch is compliant, one final `advance` marks the rollout
`completed`. `cancel` stops undeployed targets. It deliberately does not revert
already deployed targets; controlled rollback is reserved for Stage 24C.

## Safety boundaries

- A rollout references an explicit `(profile_id, profile_version)` pair.
- Target sensors are unique and limited to 100.
- A batch is limited to 25 sensors.
- Disabled or deleted sensors cannot be targeted.
- A sensor cannot belong to two draft/active rollouts.
- Each deployment increments the sensor desired revision monotonically.
- The previous desired configuration and previous profile assignment are saved
  before deployment for future rollback.
- Manual sensor configuration removes the current profile assignment and marks
  the rollout target as superseded through the derived status.
- All writes require administrator role, CSRF, and an operator change note.

## API

Viewer access:

```text
GET /api/v1/sensor-configuration-rollouts
GET /api/v1/sensor-configuration-rollouts/{rollout_id}
```

Administrator and CSRF protection required:

```text
POST /api/v1/sensor-configuration-rollouts
POST /api/v1/sensor-configuration-rollouts/{rollout_id}/start
POST /api/v1/sensor-configuration-rollouts/{rollout_id}/advance
POST /api/v1/sensor-configuration-rollouts/{rollout_id}/cancel
```

## Release boundary

Stage 24B adds no Web UI and no agent code. The existing v0.23 agent already
fetches and applies desired configuration revisions. Stage 24C will add the Web
workflow, explicit rollback, and final v0.24.0 release metadata.

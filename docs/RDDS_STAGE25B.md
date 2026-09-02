# RDDS Stage 25B — Rollout Readiness Enforcement

Stage 25B turns the Stage 25A readiness inventory into an authoritative safety
gate for configuration rollouts. It does not change the sensor agent, profile
format, rollback behavior, or database schema.

## Boundary rules

- Creating a rollout remains a draft-only planning operation. A draft may
  contain sensors that are not currently ready and never changes their desired
  configuration.
- Starting a rollout evaluates exactly the first bounded batch against the
  current readiness policy.
- Advancing an active rollout still requires every deployed target to be
  compliant, then evaluates exactly the next bounded batch.
- Completing a fully deployed rollout does not require a nonexistent next
  batch to pass readiness again.
- A batch is deployed only when every target is `ready`. The `attention`,
  `blocked`, and `excluded` states all block deployment.
- There is no administrator override in Stage 25B. A sensor or policy must be
  corrected and the action repeated explicitly.

## Transaction safety

The API locks the singleton readiness policy, target sensors, and their
configuration state before the authoritative evaluation. A policy update or
agent report cannot be interleaved between that evaluation and the desired
configuration write. If one target fails the gate, the transaction raises a
conflict before any desired revision is incremented, profile assignment is
changed, or rollout audit event is committed.

The API returns HTTP `409` with structured detail:

```json
{
  "detail": {
    "code": "rollout_readiness_blocked",
    "message": "next rollout batch is not ready: sensor-02=blocked",
    "policy_revision": 2,
    "blockers": [
      {
        "sensor_id": "00000000-0000-0000-0000-000000000000",
        "sensor_key": "sensor-02",
        "sequence": 2,
        "readiness_status": "blocked",
        "rollout_eligible": false,
        "reasons": [
          {"code": "source_disconnected", "severity": "blocked"}
        ]
      }
    ]
  }
}
```

## Web behavior

Rollout details show the live readiness state of every target and the policy
revision used to assess the next batch. Start or advance is disabled when the
loaded next batch is blocked. The API remains authoritative and returns the
structured conflict if readiness changes after the page was loaded.

## Validation

Run source and regression checks before rebuilding services:

```bash
python3 -m py_compile \
  server/api/app/fleet_readiness_store.py \
  server/api/app/configuration_rollout_store.py \
  server/api/app/main.py

node --check web/src/main.js
git diff --check

sudo docker compose run --rm --no-deps \
  -v "$PWD:/project:ro" \
  -w /project \
  -e PYTHONPATH=/project/server/api \
  api \
  python -m unittest discover -s /project/server/api/tests -v
```

No migration command is required for Stage 25B.

Runtime validation should use a new draft. First confirm that a ready sensor
can start normally. Then make a target fail one readiness requirement, refresh
the rollout detail, and verify that start/advance is disabled and the API
returns `409` without changing the target's desired revision.

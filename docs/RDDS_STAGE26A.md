# RDDS Stage 26A — Fleet readiness state history

Stage 26A adds durable, transition-based history for the fleet readiness
assessment introduced in Stage 25. It does not replace sensor health history.
Sensor health describes connectivity and source quality, while fleet readiness
also includes the active readiness policy, agent-version compatibility and
managed-configuration compliance.

## Safety boundary

Stage 26A does not change the sensor-agent protocol, managed configuration,
rollout enforcement, alert rules or Web UI. It does not add software delivery,
remote commands or automatic agent updates.

## Data model

Migration `027_sensor_fleet_readiness_history.sql` creates two tables:

- `sensor_fleet_readiness_state` stores one current recorded assessment per
  sensor, including the policy revision and freshness timestamps;
- `sensor_fleet_readiness_history` is append-only application history. It stores
  the first assessment and later material transitions with explicit previous
  and current values.

Readiness values are restricted to `ready`, `attention`, `blocked` and
`excluded`. Agent-version states use the same values as the authoritative Stage
25 evaluator. JSON reason collections must be arrays, and database constraints
ensure that only a `ready` sensor is rollout-eligible.

## Write amplification control

The API monitor evaluates readiness after sensor health refresh and before the
active-rollout safety monitor. It uses the same `assess_sensor_fleet_readiness`
function as the Web inventory and rollout gate.

An immutable history row is appended only when at least one material result
changes:

- readiness status;
- rollout eligibility;
- agent-version state;
- normalized reason set.

A policy revision that produces the same result does not create a history
event. An unchanged current-state row is refreshed at most once per
`RDDS_FLEET_READINESS_STATE_REFRESH_SECONDS`, which defaults to 300 seconds.
This keeps freshness observable without creating a periodic snapshot table.
The reconciliation transaction is protected by an advisory transaction lock so
multiple API workers cannot create duplicate transitions.

## API

Authenticated viewers can read transition history through:

```text
GET /api/v1/sensor-fleet/readiness-history
```

Supported query parameters:

- `sensor_id` — optional UUID filter;
- `hours` — 1 to 2160, default 24;
- `limit` — 1 to 1000, default 200;
- `offset` — non-negative pagination offset.

The response includes `total`, `limit`, `offset` and `events`. Results are
ordered from newest to oldest. Stage 26C will use this endpoint for the fleet
timeline and duration presentation.

## Deployment

Create an independent database backup before applying migration 027, then run:

```bash
sudo docker compose run --rm migrate
sudo docker compose up -d --build --force-recreate api
```

The existing agent and Web containers do not need rebuilding for Stage 26A.
The first monitor cycle creates one initial current-state row and one initial
history row for every non-deleted sensor. Later unchanged cycles do not append
history.

## Verification

After the API has been healthy for at least one monitor cycle:

```sql
SELECT
    sensor.sensor_key,
    state.policy_revision,
    state.readiness_status,
    state.rollout_eligible,
    state.state_changed_at,
    state.last_evaluated_at
FROM sensor_fleet_readiness_state AS state
JOIN sensors AS sensor ON sensor.id = state.sensor_id
ORDER BY sensor.sensor_key;
```

Initial history should contain exactly one row per evaluated sensor:

```sql
SELECT
    sensor.sensor_key,
    history.change_type,
    history.readiness_status,
    history.reasons,
    history.observed_at
FROM sensor_fleet_readiness_history AS history
JOIN sensors AS sensor ON sensor.id = history.sensor_id
ORDER BY history.observed_at, history.id;
```

Repeated unchanged monitor cycles may advance `last_evaluated_at`, but must not
increase the history-row count. Stage 26B will consume these durable transitions
to add delayed and deduplicated compliance alarms.

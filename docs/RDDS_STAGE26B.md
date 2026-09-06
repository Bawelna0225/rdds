# RDDS Stage 26B — delayed fleet-readiness alerts

Stage 26B turns persistent readiness transitions from Stage 26A into actionable
infrastructure alerts. A short readiness disturbance is retained in readiness
history, but it does not immediately create an operator alarm. Only a condition
that remains present beyond its configured delay opens an alert.

## Safety boundary

This stage does not change sensor-agent behavior, configuration delivery,
rollout eligibility, automatic rollout pause logic, or drone detection. It does
not execute commands on sensors. It only observes the readiness state already
calculated by the server.

## Independent alert kinds

The existing `sensor_alerts` table previously allowed one open alert per sensor.
That was safe while it represented only the detection-path health state, but it
would make a health alert and a readiness/compliance alert mutually exclusive.

Migration 028 adds:

- `alert_kind`: `health` or `readiness`;
- `condition_details`: a JSON object containing the readiness snapshot;
- one open alert per `(sensor_id, alert_kind)` instead of one per sensor.

Existing rows are backfilled as `health`. Health and readiness alerts can now be
open at the same time without suppressing each other.

## Qualification delays

Two environment settings control how long a new condition must remain present:

```text
RDDS_SENSOR_READINESS_ALERT_BLOCKED_AFTER_SECONDS=120
RDDS_SENSOR_READINESS_ALERT_ATTENTION_AFTER_SECONDS=600
```

Both values must be between 10 seconds and 24 hours. They are passed only to the
`alert-processor` service.

The delay is measured from `sensor_fleet_readiness_state.state_changed_at`.
Disabled and maintenance sensors have readiness status `excluded` and never
open readiness alerts.

## Deduplication and lifecycle

For each sensor the alert processor maintains at most one open readiness alert.
An already-open alert is updated when the readiness severity or reason snapshot
changes, rather than opening another row. Policy-revision-only refreshes update
the snapshot without increasing the occurrence counter.

An open readiness alert closes automatically when:

- the sensor becomes `ready` (`readiness_restored`);
- the sensor becomes `excluded` (`sensor_excluded`);
- the sensor is deleted (`sensor_deleted`);
- its current readiness state becomes unavailable
  (`readiness_state_unavailable`).

Acknowledgement remains an operator action through the existing sensor-alert
endpoint. Acknowledgement does not disable automatic recovery closure.

## Readiness snapshot

`condition_details` records:

- readiness status;
- policy revision;
- rollout eligibility;
- agent-version state;
- the complete list of readiness reasons.

While an alert remains open, this snapshot follows meaningful changes to its
condition. The regular sensor-alert API additionally returns the current
readiness state, so the UI can distinguish the last condition registered on the
alert from the current server assessment.

## Audit and UI

The existing sensor-alert audit event types are reused. Audit details now also
contain `alert_kind` and `condition_details`; Stage 26B does not expand the audit
event allow-list.

The existing **Alarmy sensorów** view labels readiness alerts as
`gotowość floty`, shows their snapshot and displays the current readiness state.
Stage 26C will add the full readiness timeline and duration analysis.

## Deployment

Create an independent database backup before applying migration 028, then run:

```bash
sudo docker compose run --rm migrate
sudo docker compose up -d --build --force-recreate api alert-processor web
```

The sensor agent does not need rebuilding.

## Verification

Confirm the new columns and partial unique index:

```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'sensor_alerts'
  AND column_name IN ('alert_kind', 'condition_details')
ORDER BY column_name;
```

Open alerts of both kinds can be inspected with:

```sql
SELECT
    sensor.sensor_key,
    alert.alert_kind,
    alert.state,
    alert.severity,
    alert.reason,
    alert.condition_details,
    alert.condition_started_at,
    alert.opened_at,
    alert.occurrence_count
FROM sensor_alerts AS alert
JOIN sensors AS sensor ON sensor.id = alert.sensor_id
WHERE alert.state IN ('active', 'acknowledged')
ORDER BY sensor.sensor_key, alert.alert_kind;
```

With every sensor ready or excluded, Stage 26B should initially create no new
readiness alert. A controlled runtime validation should temporarily create one
non-compliant condition, wait for the configured delay, verify one deduplicated
alert, restore the policy, and verify automatic closure.

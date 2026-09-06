# RDDS Stage 26C — fleet-readiness timeline and durations

Stage 26C completes the Stage 26 observability work by turning immutable
readiness transitions into an operator-facing timeline for one selected sensor.
It reports exact durations for readiness states without periodically copying
unchanged snapshots.

## Safety boundary

This stage is read-only at runtime. It does not change the sensor agent,
readiness policy, readiness evaluator, readiness-alert lifecycle, rollout
eligibility or rollout safety controls. It adds no database migration.

## Timeline semantics

The timeline uses `sensor_fleet_readiness_history` as its authoritative event
source. For every request the API reads:

- the last transition before the requested window as a boundary event;
- all transitions inside the requested window in ascending order;
- the current recorded readiness state as a defensive fallback.

The boundary event allows the first known state to start exactly at the window
boundary. If no earlier assessment exists, the API does not invent one. Time
before the first recorded assessment is returned as an explicit `unknown`
segment and included in `unknown_seconds`.

The summary reports:

- `ready_seconds`;
- `attention_seconds`;
- `blocked_seconds`;
- `excluded_seconds`;
- `unknown_seconds`;
- material transition and readiness-status change counts;
- `ready_percent`, calculated only over assessed time. Time marked `excluded`
  or `unknown` is not part of that percentage.

Reason-only changes split timeline segments and count as material transitions,
because they describe a real change in the server assessment even when the
top-level readiness status remains the same.

## API

Authenticated viewers can read one sensor timeline through:

```text
GET /api/v1/sensors/{sensor_uuid}/readiness-history?hours=24
```

Accepted windows are the same bounded set used by sensor-health history:

- `1` hour;
- `6` hours;
- `24` hours;
- `168` hours (7 days).

The response includes current readiness metadata, coverage boundaries, the
duration summary and chronologically ordered segments. A missing or logically
deleted sensor returns `404`; database failures return `503`.

## Web UI

The **Gotowość** tab in fleet administration makes every sensor row selectable.
The selected sensor receives:

- 1 h, 6 h, 24 h and 7 day window controls;
- state-duration cards and readiness percentage;
- a proportional colored timeline with a hatched unknown-data state;
- newest-first segment details with timestamps, policy revision and reasons.

Selection and history requests use independent request sequencing, so a slow
response for an earlier sensor or time window cannot overwrite the current
view.

## Deployment

Stage 26C changes only API and Web source:

```bash
sudo docker compose up -d --build --force-recreate api web
```

The database, alert processor and sensor agent require no rebuild for this
stage. Migrations 027 and 028 from Stage 26A/B must already be applied.

## Verification

Open **Administracja flotą → Gotowość**, select a sensor and switch between all
four time windows. The segment durations must add up to the requested window.
For a newly observed sensor the early part of a longer window should be shown
as **brak danych**, not as a fabricated readiness state.

The current readiness state, readiness alarms and rollout eligibility should
remain unchanged while the history panel is used.

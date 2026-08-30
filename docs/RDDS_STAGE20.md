# RDDS Stage 20 — fleet sensor health overview

Stage 20 adds one operational view for assessing the complete sensor network.
It complements individual sensor details without adding another periodic API
request to the live map refresh.

## Scope

- a fleet health panel opened from the `Sensory sprawne` summary card;
- current counts for online, degraded, offline and administratively excluded
  sensors;
- a 24-hour count of newly started issues, reason changes and recoveries;
- operational sorting with offline and degraded sensors first;
- filters for issues, healthy sensors and sensors outside active supervision;
- search by display name or sensor identifier;
- current source quality, reconnect, outbox, dead-letter and heartbeat data;
- row navigation to the existing sensor marker, sidebar card and detail panel;
- responsive layouts and distinct dark- and light-theme colors.

Zone alarms are intentionally not included. The overview answers whether the
detection network can be trusted; protected-zone incidents remain in their own
operational section.

## API

The operator UI loads the fleet snapshot from:

```text
GET /api/v1/sensors/health-overview
```

The endpoint requires a viewer session and returns the same current sensor
snapshot used by `GET /api/v1/sensors`, extended with:

```json
{
  "window_hours": 24,
  "sensors": [
    {
      "sensor_id": "skyspy-sensor-01",
      "issue_starts_24h": 2,
      "health_changes_24h": 1,
      "recoveries_24h": 1,
      "last_health_event_at": "2026-08-30T21:18:09Z"
    }
  ]
}
```

`issue_starts_24h` counts `sensor_degraded` and `sensor_offline` audit events.
Reason changes while a sensor remains degraded are reported separately as
`health_changes_24h`; `sensor_recovered` events form the recovery count.

The aggregation uses the existing `audit_events` table. Stage 20 therefore has
no database migration.

## Refresh boundary

The two-second map refresh still requests only current sensors, live tracks,
live trails and open alerts. The 24-hour aggregation is loaded when the panel
opens or when the operator presses `Odśwież`.

While the panel remains open, current values already received by the live map
are merged into its rows. This keeps status, heartbeat and queue values fresh
without repeatedly calculating the audit window.

## Operational order

Default sorting is:

1. offline;
2. degraded;
3. provisioning or otherwise unknown;
4. online;
5. maintenance;
6. disabled.

Within the same state, sensors with more issue starts in the last 24 hours are
shown first, followed by display name.

## Upgrade

No migration is required. Rebuild the API, web interface and development
sensor agent so its reported release version stays aligned:

```bash
sudo docker compose up -d --build --force-recreate \
  api web sensor-agent-emulator
```

The agent version is aligned with the release, but its delivery behavior is
unchanged. Physical field agents can be updated during their normal maintenance
window.

## Verification

```bash
python3 -m unittest discover -s sensor-agent/tests -v
python3 -m unittest discover -s skyspy-emulator/tests -v

sudo docker compose run --rm --no-deps \
  -v "$PWD:/project:ro" \
  -w /project \
  -e PYTHONPATH=/project/server/api \
  api \
  python -m unittest discover -s /project/server/api/tests -v

sh operations/tests/test_operations.sh

python3 -m py_compile \
  sensor-agent/rdds_agent.py \
  skyspy-emulator/main.py

node --check web/src/main.js
git diff --check
```

Expected API version: `0.20.0`.

Open the overview from the sensor summary, confirm that issue rows appear first,
exercise all filters, then select a row. The view should close and the matching
sensor should be visible on the map, selected in the sidebar and open in the
existing detail panel.

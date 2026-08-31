# RDDS Stage 21 — sensor health history and availability

Stage 21 turns the health transitions already recorded in `audit_events` into a
per-sensor operational history. It complements the Stage 20 fleet overview: the
overview answers what needs attention now, while the history explains how a
selected sensor behaved over the preceding hours or days.

## Scope

- health-history windows of 1 hour, 6 hours, 24 hours and 7 days;
- a chronological timeline of online, degraded, offline and administratively
  excluded periods;
- reason changes while a sensor remains degraded;
- availability and full-health percentages calculated only across active
  supervision time;
- online, degraded, offline and excluded durations;
- issue-start and recovery counts without double-counting duplicate audit
  records emitted by one state transition;
- a sensor-detail switch between health history and the existing stream-quality
  history;
- no additional request in the two-second live map refresh.

Stage 21 deliberately reuses the existing sensor audit trail. There is no new
health-history table and no database migration.

## API

The operator UI loads a selected sensor's history from:

```text
GET /api/v1/sensors/{sensor_id}/health-history?hours=24
```

The endpoint requires a viewer session. `hours` accepts `1`, `6`, `24` or `168`.
A representative response is:

```json
{
  "sensor_id": "skyspy-sensor-01",
  "display_name": "Sensor 01",
  "window_hours": 24,
  "coverage_seconds": 86400,
  "summary": {
    "availability_percent": 99.24,
    "healthy_percent": 96.51,
    "online_seconds": 80058,
    "degraded_seconds": 2260,
    "offline_seconds": 612,
    "excluded_seconds": 3470,
    "issue_count": 3,
    "recovery_count": 3
  },
  "timeline": [
    {
      "state": "online",
      "reason": "healthy",
      "started_at": "2026-08-30T10:00:00Z",
      "ended_at": "2026-08-30T18:31:14Z",
      "duration_seconds": 30674
    }
  ]
}
```

The query reads the most recent relevant audit transition preceding the window
plus transitions inside the requested window. This provides the state at the
window boundary without scanning the sensor's complete audit history.

## Metrics

Active supervision states are:

```text
online + degraded + offline
```

Availability treats a degraded sensor as reachable and still participating in
the system:

```text
(online + degraded) / (online + degraded + offline)
```

Full health measures only time in the `online` state:

```text
online / (online + degraded + offline)
```

`maintenance`, `disabled` and `provisioning` are excluded from both denominators.
The API reports their combined duration as `excluded_seconds`. Time before a
newly registered sensor existed is not included in coverage.

An issue starts when the timeline enters `degraded` or `offline` from a state
that was not already an issue. A reason change within `degraded`, or a change
from `degraded` to `offline`, does not create a second issue. A recovery is
counted when an issue returns directly to `online`.

## Audit source

The timeline reuses these existing event types:

- `sensor_registered`, `sensor_enabled`, `sensor_disabled`;
- `sensor_online`, `sensor_degraded`, `sensor_offline`;
- `sensor_health_changed`, `sensor_recovered`;
- `sensor_maintenance_started`, `sensor_maintenance_ended`.

The existing `(sensor_id, occurred_at, id)` audit index supports the lookup.
Stage 21 therefore does not add migration `018`.

## Operator UI

Selecting a sensor opens `Historia kondycji` by default. The operator can switch
to `Jakość strumienia` without leaving the sensor detail panel.

The health view contains:

- availability, full-health, issue, recovery, offline and excluded summaries;
- a compact proportional state bar for the selected period;
- a newest-first list of state/reason periods with timestamps and duration;
- window buttons for 1 h, 6 h, 24 h and 7 days.

Changing a history window performs one explicit API request. Stream-quality
samples are also loaded only when that view is selected.

## Refresh boundary

The live refresh remains limited to current sensors, live tracks, live trails
and open alerts. Neither endpoint below is part of the two-second loop:

```text
/api/v1/sensors/{sensor_id}/health-history
/api/v1/sensors/{sensor_id}/quality-history
```

History is fetched when a sensor is selected, when the history type changes or
when the operator chooses another time window.

## Upgrade

No database migration is required. Rebuild the API, web interface and development
sensor agent so their reported versions remain aligned:

```bash
sudo docker compose up -d --build --force-recreate \
  api web sensor-agent-emulator
```

Physical agents can be updated during a normal maintenance window; Stage 21 does
not change the ingest protocol or agent delivery behavior.

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

Expected API version: `0.21.0`.

Open a sensor and verify the 1 h, 6 h, 24 h and 7 day windows. Confirm that
maintenance and disabled time does not lower availability, a degraded reason
change does not increment the issue count, stream-quality history still opens,
and the browser does not request health history every two seconds.

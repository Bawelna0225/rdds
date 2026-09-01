# RDDS Stage 22 — sensor infrastructure alerts

Stage 22 turns the sensor-health state introduced in stages 17–21 into an
operator-facing infrastructure alarm lifecycle. It intentionally keeps drone
zone incidents and sensor faults as separate database entities: a zone incident
is tied to a track and protected zone, while a sensor alert is tied to one
sensor and its detection-path health.

## Goals

- open an infrastructure alert only after a health problem persists long enough
  to pass a configurable confirmation delay;
- keep at most one open infrastructure alert per sensor;
- update that alert when the health reason changes instead of creating alert
  storms;
- automatically close the alert when the sensor recovers, enters maintenance,
  is disabled or is deleted;
- allow operators to acknowledge an active infrastructure alert without hiding
  a fault that is still present;
- keep the complete open/acknowledged/reason-changed/closed lifecycle in the
  audit log;
- group three or more simultaneous alerts with the same health reason in the
  sidebar so a shared outage remains readable at the 20–100 sensor target
  scale.

## Storage model

Migration `018_sensor_alerts.sql` adds `sensor_alerts`. An alert stores the
sensor, state, severity, current reason, time the health condition began, time
the alert opened, acknowledgement metadata, automatic closure metadata and an
occurrence counter.

A partial unique index guarantees one row per sensor while the row is `active`
or `acknowledged`:

```text
sensor_id -> at most one open sensor_alert
```

`audit_events` gains `sensor_alert_id` and four event types:

- `sensor_alert_opened`;
- `sensor_alert_acknowledged`;
- `sensor_alert_reason_changed`;
- `sensor_alert_closed`.

## Confirmation delays

Health detection and alerting are deliberately separate. The normal sensor
health mechanism can mark a sensor degraded/offline immediately according to
its existing thresholds, while Stage 22 waits before opening an operator alarm.

Defaults:

```text
RDDS_SENSOR_ALERT_OFFLINE_AFTER_SECONDS=60
RDDS_SENSOR_ALERT_DEGRADED_AFTER_SECONDS=120
```

For a new `degraded` alert the delay starts at `sensors.health_issue_started_at`.
For a new `offline` alert it starts when the sensor enters the offline state
(`sensors.health_changed_at`). If a sensor already has an open infrastructure
alert, a later reason/severity change updates that same row immediately instead
of starting a second confirmation delay.

## Severity

Stage 22 reuses the existing RDDS severity vocabulary:

- `critical`: sensor offline;
- `high`: dead-letter data, unavailable/silent Sky-Spy source, or predominantly
  invalid source data;
- `medium`: unstable source, queue backlog, and other degraded conditions.

Infrastructure alerts do not reuse the drone-threat audible alarm profile in
this stage. They are visually prominent but remain distinguishable from an
actual protected-zone intrusion.

## Lifecycle

```text
sensor degraded/offline
        |
        | confirmation delay
        v
sensor_alert active
        |
        +---- operator acknowledges ----> acknowledged
        |
        +---- reason changes -----------> same row, new reason/severity
        |
        +---- recovery/maintenance/
              disable/delete -----------> closed by system
```

There is no manual close action for a still-failing sensor. Acknowledgement
means that an operator has seen the problem; closure means the monitored
condition has actually ended or the sensor has intentionally left supervision.

## API

Live alerts:

```text
GET /api/v1/sensor-alerts?include_closed=false
```

Archive:

```text
GET /api/v1/sensor-alerts?closed_only=true&limit=500
```

Acknowledge:

```text
POST /api/v1/sensor-alerts/{alert_id}/acknowledge
```

Audit timeline:

```text
GET /api/v1/audit/events?sensor_alert_id={alert_id}&limit=200
```

Read access requires the viewer role. Acknowledgement requires operator write
access and CSRF protection through the existing authenticated web session.

## Operator UI

The sidebar now separates:

- protected-zone alarms;
- sensor infrastructure alarms;
- their on-demand closed archives.

Three or more open sensor alerts with the same health reason are rendered as a
collapsible reason group. Individual sensor cards remain available inside the
group. Selecting an alert shows its duration, acknowledgement, current sensor
health and audited timeline, plus an `Otwórz sensor` action that navigates to the
existing sensor card and health history.

The global `Otwarte alarmy` summary counts both zone and sensor alerts.

## Processing and scale

The existing `alert-processor` worker evaluates both protected-zone intrusions
and sensor alerts. It does not create a new service. Sensor-alert updates are
rate-limited by SQL so an unchanged open incident is refreshed at most every 30
seconds instead of creating a write on every one-second alert cycle.

Closed sensor alerts use the existing alert-retention period.

For the intended 20–100 sensor deployment this keeps the model simple while
preserving a path to future fleet-level root-cause correlation. Grouping by
health reason is presentation-level grouping only; RDDS does not claim that
multiple sensors with the same reason share one proven root cause.

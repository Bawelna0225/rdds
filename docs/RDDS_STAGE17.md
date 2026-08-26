# RDDS stage 17 — sensor supervision

Stage 17 makes the state of the detection chain explicit. A quiet map no longer
implies that every receiver is healthy: RDDS reports the API link, the local
Sky-Spy source and delivery queues independently.

## Operational result

Each enabled sensor has one current state:

| State | Meaning |
| --- | --- |
| `provisioning` | registered, waiting for its first current heartbeat |
| `online` | heartbeat is current, Sky-Spy is responding and queues are healthy |
| `degraded` | agent is online but its source or delivery path needs attention |
| `offline` | no current agent heartbeat was received inside the configured window |
| `maintenance` | administrator intentionally suppresses health escalation |
| `disabled` | ingestion is administratively blocked |

The current reason is stored separately from the state. Stage 17 recognizes:

- `source_unavailable` — the serial/socket source cannot be opened;
- `source_silent` — the source is open but did not emit its periodic status;
- `queue_backlog` — the local delivery queue reached its warning threshold;
- `dead_letter` — at least one payload requires technical inspection;
- `heartbeat_timeout` — the API stopped receiving current heartbeats.

## No duplicate technical alarms

`health_issue_started_at` represents the beginning of one continuous problem.
The first transition to `degraded` or `offline` creates one audit event. An
escalation from degraded to offline changes the existing issue instead of
opening another one. Recovery clears the issue and creates `sensor_recovered`.

The following transitions are audited:

- `sensor_online`;
- `sensor_degraded`;
- `sensor_offline`;
- `sensor_health_changed`;
- `sensor_recovered`;
- `sensor_maintenance_started`;
- `sensor_maintenance_ended`.

## Current heartbeat semantics

Heartbeats describe current state and are not historical business events. The
agent therefore keeps only its newest pending heartbeat in SQLite. Observations
remain durable and ordered. On the server, a heartbeat updates the current
snapshot only when its reported timestamp is newer than the stored snapshot.
This prevents delayed replay from changing a recovered sensor back to an old
state.

The optional `rdds/1.0` heartbeat status fields added in this stage are:

```json
{
  "agent_version": "0.17.0",
  "source_connected": true,
  "source_last_message_at": "2026-08-26T12:00:00Z",
  "queue_depth": 0,
  "dead_letter_depth": 0
}
```

Older protocol clients remain valid because every new field is optional.

Disabling a sensor is a server-side ingestion block; it does not power down the
physical receiver or its host. Payloads explicitly rejected because of that
administrative state are discarded by the agent instead of being replayed or
moved to the technical dead-letter queue. Re-enabling starts with newly
received data and does not import detections from the disabled period.

## Configuration

```dotenv
RDDS_SENSOR_OFFLINE_AFTER_SECONDS=30
RDDS_SENSOR_QUEUE_WARNING_MESSAGES=100
RDDS_SENSOR_SOURCE_SILENT_AFTER_SECONDS=90
```

Sky-Spy firmware emits an idle scanning status every 60 seconds, hence the
90-second source-silence default. The API heartbeat timeout remains shorter
because the agent normally reports every 10 seconds.

## Interface

The sensor list is live operational data and continues to refresh without a
global loader. It now provides:

- healthy/monitored count;
- a visible technical warning summary;
- separate status and diagnostic reason;
- agent and source timestamps;
- source connection state;
- agent version, queue depth and dead-letter depth;
- automatic expansion of the sensor section when a new issue appears.

The same live/stored boundary is retained in the sidebar. Live tracks continue
to refresh independently, while ended tracks are loaded only after expanding a
separate `Archiwum tras` section. Opening the archive no longer replaces live
markers on the map. Protected-zone outlines and cards always use their severity
color: cyan for low, amber for medium, orange-red for high and red for critical.
The former ambiguous `Pokaż wszystkie` action is labelled `Dopasuj mapę`.
Operational sections are ordered from active alerts, live tracks and protected
zones through sensors to the on-demand archives and event log. Selecting a zone
polygon on the map expands the protected-zone section, highlights the matching
card and scrolls it into view. Zone popups reserve enough width for status,
severity and descriptions instead of collapsing their value column.

The display controls provide explicit dark and light themes, including map
tiles, popups and operational overlays. The sidebar can be hidden temporarily
to give the map the full workspace and restored from a persistent control on
the map. Both choices are saved in the browser. Selecting a protected zone on
the map restores a hidden sidebar before focusing its card.

Administrators can start maintenance with a mandatory reason and optional end
time. Heartbeats remain accepted during maintenance so that the latest health
snapshot is ready when maintenance ends. A disabled sensor remains different:
its individual token cannot ingest data.

## Migration

Migration `015_sensor_supervision.sql` adds the health snapshot, maintenance
metadata, heartbeat telemetry and audit transitions. It also backfills the
latest heartbeat and observation timestamps without rewriting historical
messages.

Before applying the migration, create and verify an independent database
backup. Stop the API while the migration changes the sensor status constraint.

```bash
cd /opt/rdds/source

sudo docker compose run --rm --no-deps \
  --entrypoint /usr/local/bin/backup.sh backup

sudo docker compose stop api
sudo docker compose run --rm migrate
sudo docker compose up -d --build --force-recreate \
  api web sensor-agent-emulator
```

The tracker and alert processor do not require rebuilding for this stage.

## Verification

```bash
curl -fsS http://127.0.0.1:8000/ | python3 -m json.tool

sudo docker compose exec -T database \
  psql -U rdds -d rdds -Atc \
  "SELECT migration_name
   FROM rdds_schema_migrations
   WHERE migration_name='015_sensor_supervision.sql';"

sudo docker compose exec -T database \
  psql -U rdds -d rdds -P pager=off -c \
  "SELECT sensor_key, status, health_reason, source_connected,
          reported_queue_depth, reported_dead_letter_depth,
          last_heartbeat_received_at, agent_version
   FROM sensors
   WHERE deleted_at IS NULL
   ORDER BY sensor_key;"
```

Expected API version: `0.17.0`.

## Acceptance scenarios

1. Stop `skyspy-emulator` while the agent remains running. The sensor becomes
   degraded with `source_unavailable`, but not offline.
2. Start the emulator again. The same issue is cleared and a recovery is
   recorded once.
3. Stop `sensor-agent-emulator`. After the heartbeat timeout the sensor becomes
   offline and one technical event is recorded.
4. Restart the agent. The sensor returns online without historical heartbeats
   temporarily restoring an older state.
5. Start maintenance, stop the source and wait beyond both thresholds. The
   sensor stays in maintenance and no health issue is opened.
6. End maintenance. The current heartbeat determines whether the sensor is
   healthy, degraded or offline.
7. Disable a sensor while its source is active, then enable it again. Messages
   from the disabled period do not create a queue or dead-letter warning.

## Tests

```bash
python3 -m unittest discover -s sensor-agent/tests -v

sudo docker compose run --rm --no-deps \
  -v "$PWD:/project:ro" \
  -w /project \
  -e PYTHONPATH=/project/server/api \
  api \
  python -m unittest discover -s /project/server/api/tests -v

sh operations/tests/test_operations.sh
python3 -m py_compile sensor-agent/rdds_agent.py skyspy-emulator/main.py
git diff --check
```

Do not enable retention or remove historical data as part of this migration.

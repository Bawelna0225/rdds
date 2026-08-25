# RDDS 0.13.1: live priority and track sessions

RDDS 0.13.1 prevents an offline sensor backlog from displacing current
observations and stops separate appearances of the same Remote ID from becoming
one indefinitely reopened track. It also extends the live map trail to 60
seconds without returning duplicate points from every contributing sensor.

This release does not change the stage 13 retention periods or perform database
partitioning. Those storage changes require a separate backup, capacity review
and migration plan.

## Track-session behavior

`entity_key` identifies the normalized Remote ID identity. `track_key` now
identifies one detection session of that entity. Migration
`011_track_sessions.sql` assigns every existing track its current `track_key` as
the initial `entity_key`; no existing observations or alerts are deleted.

The default lifecycle is:

| Silence since the newest observation | Result |
| --- | --- |
| less than 15 seconds | track remains `new` or `active` |
| 15–60 seconds | track becomes `stale` and retains its last known position |
| more than 60 seconds | track becomes `ended` |
| new observation within 60 seconds | the existing session continues |
| new observation after 60 seconds | a new session is created for the same entity |

The system intentionally does not claim whether silence was caused by landing,
power-off, radio obstruction or leaving receiver coverage. It records only the
observable event: the previous session ended and the identity was detected
again.

Historical observations replayed from a sensor outbox are matched to a session
by their `message_time`. They cannot replace the current position of a newer
live session.

## Live-data priority

The sensor agent sends a newly read observation and heartbeat immediately. Old
outbox messages are sent separately at a configurable rate:

```dotenv
RDDS_AGENT_REPLAY_MESSAGES_PER_SECOND=2
```

The allowed range is `0.1`–`100`. The default of two messages per second keeps
recovery predictable while current observations remain responsive. Increasing
this value should be done only after checking API, tracker and PostgreSQL load.

The tracker independently orders unprocessed live observations before replayed
rows. This protects live state even when several sensors reconnect together.

## Live trail

`GET /api/v1/tracks/trails` defaults to the last 60 seconds. Points are reduced
to at most one position per track and UTC second before the per-track limit is
applied. Sensor provenance remains in raw observations and track statistics;
only the map payload is deduplicated.

## Upgrade

Keep the existing `.env` and add:

```dotenv
RDDS_AGENT_REPLAY_MESSAGES_PER_SECOND=2
```

Run the migration and rebuild the services that contain changed code:

```bash
cd /opt/rdds/source
sudo docker compose stop tracker
sudo docker compose run --rm migrate
sudo docker compose up -d --build --force-recreate api tracker web
```

Stopping the old tracker before migration avoids a short compatibility window:
the previous tracker does not yet populate the new required `entity_key` column.

Recreate whichever Sky-Spy agent is in use:

```bash
# Emulated receiver
sudo docker compose up -d --build --force-recreate \
  sensor-agent-emulator skyspy-emulator

# Or physical receiver
sudo docker compose up -d --build --force-recreate sensor-agent
```

Verify that migration `011_track_sessions.sql` was applied, the API reports
`0.13.1`, current tracks have a 60-second trail, and a detection returning more
than 60 seconds after its previous observation receives a different track ID.

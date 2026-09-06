# RDDS Stage 27A — Agent Release Catalog

Stage 27A adds an audited, metadata-only catalog of RDDS sensor-agent releases.
It creates the inventory and lifecycle controls needed before any future agent
upgrade workflow is designed.

## Safety boundary

This stage deliberately does not modify sensor configuration, agent runtime,
ingest authentication, rollout state, or fleet-readiness policy. It does not:

- upload or store an artifact body;
- store or return a download URL;
- instruct an agent to download or install software;
- execute a process on a sensor;
- assign a release to a sensor;
- compare the catalog with fleet inventory automatically.

The catalog records only an artifact's identity: safe filename, SHA-256 digest,
byte size, version, compatibility metadata, channel, and release notes.

## Lifecycle

Every release starts as `draft` at revision 1. An administrator can edit only a
draft, using `expected_revision` to prevent lost updates. Publication is a
separate confirmed operation. Published metadata is immutable. A published
release may later be moved to `withdrawn`, with a mandatory reason; withdrawal
does not remove or downgrade software on any sensor.

Lifecycle transitions are one-way:

1. `draft` — editable metadata, not published;
2. `published` — immutable verified metadata;
3. `withdrawn` — immutable historical metadata excluded from the default list.

The database CHECK constraint validates the timestamps and actors required by
each state. All mutations are serialized with row locks and optimistic revision
checks.

## API

Viewer routes:

- `GET /api/v1/sensor-agent-releases`
- `GET /api/v1/sensor-agent-releases/{release_id}`

Administrator + CSRF routes:

- `POST /api/v1/sensor-agent-releases`
- `PUT /api/v1/sensor-agent-releases/{release_id}`
- `POST /api/v1/sensor-agent-releases/{release_id}/publish`
- `POST /api/v1/sensor-agent-releases/{release_id}/withdraw`

The list is bounded to 500 rows per request and omits withdrawn releases unless
`include_withdrawn=true` is explicitly requested.

## Audit

Stage 27A adds four audit event types:

- `sensor_agent_release_created`
- `sensor_agent_release_updated`
- `sensor_agent_release_published`
- `sensor_agent_release_withdrawn`

Every write includes the authenticated operator and a mandatory change note.
Create and update events retain full checked metadata; lifecycle events retain
the version and revision transition.

## Web UI

The fleet administration console includes a fourth tab, **Wydania agentów**.
It exposes draft creation, draft editing, publication, and withdrawal as
separate confirmed actions. The panel states that no package is uploaded and no
agent update is started. Published and withdrawn metadata is rendered read-only.

## Migration and compatibility

Migration `029_sensor_agent_releases.sql` creates a new independent table and
extends the audit-event allow-list. It does not seed a release, assign anything
to sensors, or require an agent/Web protocol change. Existing v0.26.0 agents
continue operating unchanged.

Stage 27A intentionally keeps the product version at `0.26.0`; the `0.27.0`
release is reserved until the broader Stage 27 scope is complete and validated.

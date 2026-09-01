# RDDS Stage 23A — sensor configuration control plane

Stage 23A adds the server-side foundation for centrally managed sensor-agent
configuration. It deliberately does not make running agents apply remote changes
yet. That behavior is reserved for Stage 23B after the database and API boundary
has been validated.

## Existing foundation reused

RDDS already provides per-sensor credentials, token rotation, sensor lifecycle,
heartbeat supervision, diagnostics and maintenance. Stage 23A does not duplicate
those mechanisms.

## Configuration state

Migration `020_sensor_configuration.sql` adds a one-to-one
`sensor_configuration_state` row for every sensor.

A sensor starts as `unmanaged` with `desired_revision = 0`. Saving the first
managed configuration creates revision 1. Later changes increment the revision.

The allow-list is intentionally small:

- `heartbeat_seconds`;
- `reconnect_seconds`;
- `request_timeout_seconds`;
- `replay_messages_per_second`.

Credential material, API URL, sensor identity, serial device path and baud rate
are not remotely configurable in Stage 23.

## API

Operators can inspect:

```text
GET /api/v1/sensors/{sensor_uuid}/configuration
```

Administrators can change:

```text
PUT /api/v1/sensors/{sensor_uuid}/configuration
```

Field agents can read the desired revision using their individual ingest token:

```text
GET /api/v1/agent/configuration
X-RDDS-Ingest-Token: <individual sensor token>
```

The shared legacy ingest token is rejected for this endpoint because it does not
identify one sensor strongly enough for per-device configuration.

## Compliance states

The sensor list exposes `unmanaged`, `unreported`, `pending`, `compliant` and
`error`. Stage 23A only creates the schema/API side. Stage 23B will add agent
reporting and application.

## Upgrade

```bash
sudo docker compose run --rm migrate
sudo docker compose up -d --build --force-recreate api
```

Do not change a physical sensor's managed configuration yet. Running 0.22.1
agents do not consume this endpoint.

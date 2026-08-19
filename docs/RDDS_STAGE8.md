# RDDS stage 8: sensor provisioning and individual credentials

Stage 8 prepares the standalone RDDS deployment for physical receivers. It adds
an administrative sensor lifecycle, individual ingest tokens, sensor telemetry
and audit events. No TAK Server integration is introduced.

## Credential model

New sensor tokens contain 256 bits of random material. The plaintext token is
returned only by the registration or rotation response and is displayed once
in the operator interface. PostgreSQL stores only its SHA-256 digest and a
non-secret prefix used to identify the active credential.

One sensor can have only one active individual credential. Rotation revokes the
previous credential in the same database transaction before issuing a new one.
A token is bound to the sensor key, so it cannot submit a payload using another
sensor's `sensor_id`. Disabling a sensor blocks its individual token.

## Legacy transition

The existing `RDDS_INGEST_TOKEN` remains enabled by default so the running
simulator is not interrupted during migration. It is accepted only for:

- an existing sensor that has no active individual credential; or
- a previously unknown sensor created automatically by legacy ingestion.

As soon as an individual credential is issued to a sensor, the shared token is
rejected for that sensor. A disabled sensor is also rejected in legacy mode.

After every real and simulated sensor has been converted, set this in `.env`:

```dotenv
RDDS_ALLOW_LEGACY_INGEST=false
```

Then recreate the API container. This disables the shared ingest path globally
and prevents automatic registration of unknown sensor identifiers.

## Database and audit

Migration 007 creates `sensor_credentials`, adds operator and message-counter
fields to `sensors`, and links sensor events to `audit_events`. Existing sensor
message counts and registration events are backfilled once. New events include:

- `sensor_registered`;
- `sensor_enabled` and `sensor_disabled`;
- `sensor_token_issued` and `sensor_token_rotated`.

PostgreSQL triggers increment heartbeat and observation counters only when a
new, non-duplicate message is inserted. This keeps the counters consistent even
during an API upgrade. The latest heartbeat supplies uptime, free heap, queue
depth and cellular RSSI to the sensor details panel.

## Administrative API

The following endpoints require `X-RDDS-Admin-Token`:

```text
POST  /api/v1/sensors
PATCH /api/v1/sensors/{sensor_uuid}
POST  /api/v1/sensors/{sensor_uuid}/token/rotate
```

Registration accepts a stable `sensor_key`, display name, optional WGS84
position and operator label. The registration and rotation responses contain
the only copy of the new plaintext `ingest_token`. Never put this token in a URL,
log, screenshot or Git commit.

Audit queries and exports support `category=sensors` and `sensor_id=<uuid>`.

## Operator interface

After unlocking operator mode, **Dodaj sensor** opens the registration form.
Sensor cards show their state and whether they still use the shared token or an
individual token. The card actions can:

- enable or disable the receiver;
- issue its first individual token;
- rotate an existing individual token.

Selecting a sensor displays its position, counters and latest heartbeat
telemetry. Sensor lifecycle actions appear in the existing audit journal and
timeline.

## Simulator transition

The simulator continues using `RDDS_INGEST_TOKEN` unless an entry exists in the
optional JSON map `RDDS_SIM_SENSOR_TOKENS_JSON`. For example, after issuing an
individual token to `sim-sensor-01`, add one line to `.env`:

```dotenv
RDDS_SIM_SENSOR_TOKENS_JSON={"sim-sensor-01":"PASTE_THE_NEW_TOKEN_HERE"}
```

Recreate the simulator immediately after saving the token. The `.env` file is
Git-ignored, but it is still plaintext on the VM and must remain readable only
by the RDDS administrator.

## Verification

Apply migration 007, rebuild the services and check API version `0.8.0`:

```bash
cd /opt/rdds/source
sudo docker compose run --rm migrate
sudo docker compose --profile simulation up -d --build
sudo docker compose ps -a
curl -fsS http://127.0.0.1:8000/ | python3 -m json.tool
curl -fsS http://127.0.0.1:8000/api/v1/sensors | python3 -m json.tool
```

In the browser:

1. unlock operator mode and register `rdds-test-01`;
2. keep the token panel open and run the heartbeat test below;
3. verify that the sensor changes from `provisioning` to `online` and uses an
   individual token;
4. close the token panel, then disable and re-enable the sensor while checking
   the audit journal after each action;
5. rotate the token and confirm that a different value is shown;
6. close the new token panel and verify that the plaintext value cannot be opened
   again from the sensor card.

Run this immediately after step 1, in a separate VM shell. Do not register the
same sensor again. The token is read without placing it in shell history:

```bash
read -rsp 'Token sensora: ' rdds_sensor_token
echo
rdds_sensor_boot_id=$(cat /proc/sys/kernel/random/uuid)
rdds_sensor_time=$(date --iso-8601=seconds)

curl -fsS -X POST \
  http://127.0.0.1:8000/api/v1/ingest/heartbeat \
  -H 'Content-Type: application/json' \
  -H "X-RDDS-Ingest-Token: ${rdds_sensor_token}" \
  --data-binary @- <<JSON
{
  "protocol_version": "rdds/1.0",
  "message_type": "heartbeat",
  "sensor": {
    "sensor_id": "rdds-test-01",
    "display_name": "RDDS test receiver",
    "boot_id": "${rdds_sensor_boot_id}",
    "sequence": 1,
    "timestamp": "${rdds_sensor_time}",
    "position": {"latitude": 52.2297, "longitude": 21.0122}
  },
  "status": {
    "uptime_seconds": 60,
    "free_heap_bytes": 196000,
    "queue_depth": 0,
    "cellular_rssi": -67
  }
}
JSON

unset rdds_sensor_token rdds_sensor_boot_id rdds_sensor_time
```

The API should return HTTP 202 with `accepted: true`, and the sensor card should
change to `online` with heartbeat telemetry. A token issued to another sensor
or a disabled sensor must return HTTP 403.

Do not disable legacy ingestion until all three simulator sensors have their
individual tokens configured and are reporting successfully.

# RDDS stage 5: protected zones and intrusion alerts

Stage 5 adds server-side geofencing. PostGIS compares every current drone track
with active protected polygons. The separate `alert-processor` service opens,
refreshes and closes intrusion alerts independently of the browser interface.
The system remains standalone and does not use TAK Server.

## Alert lifecycle

- `active`: a non-ended track is inside an active protected zone;
- `acknowledged`: an operator has accepted the alarm, but tracking continues;
- `closed`: the track left the zone, ended, the zone was disabled, or an
  administrator closed the alarm manually.

Only one open alert can exist for a given zone and track. A later re-entry after
closure creates a new alert and preserves the previous event as history.

## Security boundary

Reading zones and alerts is available to the operational map. Creating or
enabling zones and changing alert state requires the `X-RDDS-Admin-Token`
header. Set a separate random `RDDS_ADMIN_TOKEN`; do not reuse the database
password or sensor ingest token.

## Configure and start

Add the following settings to `.env`:

```dotenv
RDDS_ADMIN_TOKEN=REPLACE_WITH_A_RANDOM_64_HEX_CHARACTER_VALUE
RDDS_ALERT_POLL_SECONDS=1
```

Generate a token with `openssl rand -hex 32`, then rebuild the services:

```bash
sudo docker compose --profile simulation up -d --build
sudo docker compose --profile simulation ps -a
```

## Create the simulator test zone

Load the local `.env` into the current shell and submit the included polygon:

```bash
set -a
. ./.env
set +a

curl -fsS \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-RDDS-Admin-Token: ${RDDS_ADMIN_TOKEN}" \
  --data @docs/examples/simulator-protected-zone.json \
  http://127.0.0.1:8000/api/v1/zones \
  | python3 -m json.tool

unset RDDS_ADMIN_TOKEN
```

The zone intersects part of the circular `SIM-DRONE-ALPHA` route. An alert
should therefore open and close periodically. View it at
`http://192.168.10.169:8080` or query the API:

```bash
curl -fsS http://127.0.0.1:8000/api/v1/zones | python3 -m json.tool
curl -fsS http://127.0.0.1:8000/api/v1/alerts | python3 -m json.tool
curl -fsS 'http://127.0.0.1:8000/api/v1/alerts?include_closed=true' \
  | python3 -m json.tool
```

The API also exposes authenticated endpoints to acknowledge or close alerts and
to enable or disable zones. Their schemas are available in the local OpenAPI UI
at `http://192.168.10.169:8000/docs`.

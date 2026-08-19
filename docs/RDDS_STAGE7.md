# RDDS stage 7: incident history and audit log

Stage 7 adds a persistent, searchable record of protected-zone and intrusion
alert activity. The record is generated in PostgreSQL, not in the browser, so
it survives page reloads and service restarts. It remains part of the standalone
RDDS application and does not introduce TAK Server integration.

## Recorded events

The `audit_events` table stores these event types:

- `alert_opened` when the alert processor creates an intrusion alert;
- `alert_acknowledged` and `alert_closed` with the operator label supplied by
  the protected action;
- `zone_created`, `zone_enabled` and `zone_disabled` with the operator label.

Database triggers create the audit rows in the same transaction as the alert or
zone change. Existing alerts and zones are backfilled when migration 006 runs.
The migration is idempotent and can be run again by the Compose migration
service without intentionally duplicating the backfilled events.

The operator label is an audit label, not a verified individual identity. Stage
6 still uses one shared administrator token. Individual accounts, HTTPS and
role-based authorization remain production work.

## API

Recent events are available at:

```text
GET /api/v1/audit/events
GET /api/v1/audit/events?category=alerts&limit=100
GET /api/v1/audit/events?alert_id=<uuid>
GET /api/v1/audit/events?zone_id=<uuid>
```

Supported categories are `all`, `alerts` and `zones`. An exact `event_type`,
`offset` and `limit` can also be supplied. The response includes the total
matching row count and the selected page in newest-first order.

CSV and JSON exports use the same filters:

```text
GET /api/v1/audit/export?format=csv&category=all
GET /api/v1/audit/export?format=json&category=alerts
```

Exports are limited to 5,000 rows per request. Like the other read endpoints in
the current development-LAN deployment, audit reads are not authenticated and
may contain drone, zone and operator identifiers. Do not expose ports 8000 or
8080 to an untrusted network.

## Operator interface

The operational map includes a **Dziennik zdarzeń** section with an event
category filter and CSV/JSON export actions. Selecting an entry opens its
details and a chronological incident timeline. For an alert, the timeline is
limited to that alert. For a zone action, it shows all recorded activity linked
to that zone, including intrusion alerts.

Creating a zone or changing its active state now sends the operator label from
the unlocked browser session. API clients that omit this new optional field are
recorded as `api-admin` for backward compatibility.

## Verification

Rebuild the stack so migration 006 and both application images are applied:

```bash
cd /opt/rdds/source
sudo docker compose --profile simulation up -d --build
sudo docker compose ps
sudo docker compose logs --tail=80 migrate
```

Verify the service version and audit endpoint:

```bash
curl -fsS http://127.0.0.1:8000/ | python3 -m json.tool
curl -fsS 'http://127.0.0.1:8000/api/v1/audit/events?limit=10' \
  | python3 -m json.tool
curl -fsS 'http://127.0.0.1:8000/api/v1/system/summary' \
  | python3 -m json.tool
```

Open `http://192.168.10.169:8080`. Existing zones and alerts should already
appear as backfilled events. Unlock operator mode, toggle a zone, then
acknowledge or close an alert. The new entries should show the current operator
label and selecting one should display the related timeline. Finally, download
both export formats from the audit toolbar.

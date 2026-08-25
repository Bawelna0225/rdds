# RDDS 0.14.0: loading feedback and database capacity

RDDS 0.14.0 improves operator feedback while data is being fetched and gives
administrators a safe view of PostgreSQL growth. It does not mount PostgreSQL
data files into the API container and does not grant the application access to
the Docker socket or host filesystem.

## Loading behavior

- the first dashboard request renders skeleton cards in the sections that are
  being fetched;
- the two-second live refresh is intentionally silent: it updates sensors,
  active tracks, the 60-second live trail and open alerts without displaying a
  global loader;
- archived tracks, closed alerts, zones and audit events are stored views. They
  are fetched on demand instead of being downloaded by every live refresh;
- changing the audit category or selecting **Odśwież** displays skeletons only
  in the audit list;
- opening the track archive or closed-alert archive displays skeletons only in
  the affected list;
- loading an audit timeline or a recorded track history displays an inline
  indicator in the selection panel;
- lists expose `aria-busy` state to assistive technologies;
- the operator-account panel uses skeleton rows while accounts are fetched;
- administrative storage refreshes show an inline spinner;
- a failed request replaces its local skeletons with an explicit error state
  instead of leaving a permanent loading animation;
- reduced-motion browser preferences disable loading animations.

This boundary keeps current operational state responsive without repeatedly
querying saved historical rows. Newly closed alerts and new audit entries appear
after the operator refreshes or opens the corresponding stored-data view.

## Storage model

PostgreSQL databases do not have an intrinsic fixed maximum size. The API can
measure the real database size with `pg_database_size`, but it cannot safely
infer the amount of host storage that the administrator intends to allocate to
RDDS. The percentage therefore uses an explicit operational budget:

```dotenv
RDDS_DATABASE_CAPACITY_GB=20
RDDS_DATABASE_WARNING_PERCENT=70
RDDS_DATABASE_CRITICAL_PERCENT=85
```

`RDDS_DATABASE_CAPACITY_GB=0` is the safe default. In that mode the panel still
shows the measured database size and largest user table, but does not calculate
a misleading percentage. Select a budget below the physical volume capacity
and preserve enough free space for PostgreSQL maintenance, temporary files,
backups and the operating system.

The administrator-only `GET /api/v1/system/storage` response includes:

- database name and measured size;
- configured capacity budget and used percentage;
- `unconfigured`, `ok`, `warning`, `critical` or `exceeded` state;
- configured warning and critical thresholds;
- five largest user tables with approximate row counts.

Viewer and operator accounts cannot access this endpoint. The panel refreshes
when an administrator logs in, at most once per minute during normal operation,
and immediately when the administrator selects **Odśwież**.

## Upgrade from 0.13.1

Keep the existing `.env` file. Add the three values and choose the capacity
budget deliberately. No database migration is required.

```bash
cd /opt/rdds/source

grep -q '^RDDS_DATABASE_CAPACITY_GB=' .env ||
printf '\nRDDS_DATABASE_CAPACITY_GB=20\n' >> .env

grep -q '^RDDS_DATABASE_WARNING_PERCENT=' .env ||
printf 'RDDS_DATABASE_WARNING_PERCENT=70\n' >> .env

grep -q '^RDDS_DATABASE_CRITICAL_PERCENT=' .env ||
printf 'RDDS_DATABASE_CRITICAL_PERCENT=85\n' >> .env
```

Rebuild only the changed API and web images:

```bash
sudo docker compose up -d --build --force-recreate api web

curl -fsS http://127.0.0.1:8000/ |
python3 -m json.tool

sudo docker compose ps -a
sudo docker compose logs --tail=100 api web
```

The API root should report `0.14.0`. Log in as an administrator, open the
account menu and verify the storage panel. A viewer or operator should not see
the panel and should receive HTTP `403` from `/api/v1/system/storage`.

The capacity meter is an early-warning control, not a replacement for host disk
monitoring, verified backups or retention. A database can grow beyond the
configured budget; the panel reports `exceeded` but does not delete data.

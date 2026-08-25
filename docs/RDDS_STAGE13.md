# RDDS stage 13: backup, retention and HTTPS operations

Stage 13 hardens the standalone RDDS service before field hardware is attached.
It adds verified PostgreSQL backups, a deliberately guarded restore procedure,
configurable database retention and an optional TLS gateway. TAK Server and
hardware-dependent behavior remain outside this stage.

## Safety properties

- `backup` creates a PostgreSQL custom-format dump immediately after it starts
  and then at the configured interval;
- a dump is published only after `pg_restore --list` validates its structure;
- every published dump receives a SHA-256 sidecar file;
- a failed or interrupted dump remains hidden as a `.partial` file and is
  removed on exit;
- restore requires both an exact `/backups/*.dump` path and the literal
  `RESTORE_RDDS` confirmation value;
- restore verifies the checksum and archive structure before changing the
  database and uses one PostgreSQL transaction;
- data retention is disabled by default and supports a non-destructive dry run;
- scheduled maintenance uses a PostgreSQL advisory lock to prevent overlap and
  records its result in `maintenance_runs`;
- the migration runner records each applied filename and SHA-256 checksum in
  `rdds_schema_migrations`, skips verified history and stops on later changes;
- the TLS gateway runs unprivileged, accepts TLS 1.2/1.3 and keeps the API on the
  internal Compose network.

A backup on the same VM is not disaster recovery. Copy `.dump` and matching
`.sha256` files to a different machine, encrypted storage or offline medium.

## Upgrade from 0.12.0

Keep the current `.env`; do not replace it with `.env.example`. Add the following
values, adjusting UID, GID and paths for the `czarny` account:

```dotenv
RDDS_OPERATIONS_UID=1000
RDDS_OPERATIONS_GID=1000
RDDS_BACKUP_PATH=/opt/rdds/backups
RDDS_BACKUP_INTERVAL_SECONDS=86400
RDDS_BACKUP_RETENTION_DAYS=30

RDDS_RETENTION_ENABLED=false
RDDS_MAINTENANCE_INTERVAL_SECONDS=86400
RDDS_RETENTION_BATCH_SIZE=10000
RDDS_RETENTION_SESSIONS_DAYS=30
RDDS_RETENTION_HEARTBEATS_DAYS=30
RDDS_RETENTION_OBSERVATIONS_DAYS=90
RDDS_RETENTION_AUDIT_DAYS=365
RDDS_RETENTION_ALERTS_DAYS=365
RDDS_RETENTION_TRACKS_DAYS=365
```

Confirm the numeric identity and create the host backup directory:

```bash
id -u
id -g
sudo install -d -o czarny -g czarny -m 700 /opt/rdds/backups
```

Build and apply migration `010_operations.sql`:

```bash
cd /opt/rdds/source
sudo docker compose up -d --build
sudo docker compose ps -a
sudo docker compose logs --tail=100 migrate backup maintenance api
```

The first run after upgrading the migration runner records the existing
migrations. Later runs print `Skipping applied migration ...`. Never edit an
already recorded migration; add the next numbered file instead. A checksum
mismatch is an intentional deployment stop that requires investigation.

The API and maintenance containers must receive the same retention variables;
Compose supplies them to both. After changing the policy, recreate both services
so that the status endpoint and worker agree:

```bash
sudo docker compose up -d --force-recreate api maintenance
```

The `backup` service should become healthy after its first successful dump.
Verify the file independently on the VM:

```bash
cd /opt/rdds/backups
sha256sum -c rdds_*.dump.sha256
ls -lh rdds_*.dump rdds_*.dump.sha256
```

If more than one checksum exists, `sha256sum` checks every matching sidecar.

## Retention policy

The supplied values retain:

| Data | Default period | Rationale |
| --- | ---: | --- |
| expired/revoked sessions | 30 days | short-lived security metadata |
| raw sensor heartbeats | 30 days | receiver diagnostics |
| raw observations | 90 days | detailed detections, including sensitive pilot data |
| audit events | 365 days | operator and evidentiary history |
| closed alerts | 365 days | incident history |
| ended tracks | 365 days | summarized operational history |

Active or acknowledged alerts are never removed. An ended track is removed only
after its retention period and only if no alert or retained audit event still
references it. Sensors, protected zones and operator accounts are not physically
deleted by retention. Lifetime counters remain lifetime counters even after old
raw rows are removed.

First run a non-destructive count:

```bash
cd /opt/rdds/source
sudo docker compose run --rm maintenance \
  python -m app.maintenance --once --dry-run
```

Review the returned counts and verify that the latest backup also exists outside
the VM. Only then set `RDDS_RETENTION_ENABLED=true` in `.env` and recreate the
service:

```bash
sudo docker compose up -d --force-recreate api maintenance
sudo docker compose logs --tail=100 maintenance
```

An administrator can inspect the configured policy and latest result at
`GET /api/v1/system/maintenance`. Viewer and operator accounts cannot access
this endpoint.

## Guarded in-place restore

An in-place restore replaces the current RDDS database. Preserve the newest
current dump before proceeding. Stop every database writer while leaving the
database service running:

```bash
cd /opt/rdds/source
sudo docker compose stop \
  api tracker alert-processor maintenance simulator \
  sensor-agent sensor-agent-emulator web gateway backup
```

List backups and choose one exact filename. Do not use a glob in the restore
variable:

```bash
ls -lh /opt/rdds/backups
export RDDS_RESTORE_FILE=/backups/rdds_rdds_YYYYMMDDTHHMMSSZ.dump
export RDDS_RESTORE_CONFIRM=RESTORE_RDDS
sudo --preserve-env=RDDS_RESTORE_FILE,RDDS_RESTORE_CONFIRM \
  docker compose --profile restore run --rm restore
unset RDDS_RESTORE_FILE RDDS_RESTORE_CONFIRM
```

Start the normal stack and verify readiness, counts, login and the web map:

```bash
sudo docker compose up -d
curl -fsS http://127.0.0.1:8000/api/v1/health/ready \
  | python3 -m json.tool
sudo docker compose ps -a
```

For a real restore drill, use a separate VM or a separate test database. Merely
creating a dump is not proof that recovery works.

## Optional HTTPS gateway

For a trusted deployment, use a certificate issued for the final DNS name by a
trusted internal or public CA. Place the certificate and unencrypted private key
outside the Git repository, readable only by the account identified by
`RDDS_GATEWAY_UID/GID`:

```dotenv
RDDS_BIND_ADDRESS=127.0.0.1
RDDS_WEB_BIND_ADDRESS=127.0.0.1
RDDS_SESSION_COOKIE_SECURE=true
RDDS_HTTPS_BIND_ADDRESS=0.0.0.0
RDDS_HTTPS_PORT=8443
RDDS_GATEWAY_UID=1000
RDDS_GATEWAY_GID=1000
RDDS_TLS_CERT_FILE=/opt/rdds/tls/tls.crt
RDDS_TLS_KEY_FILE=/opt/rdds/tls/tls.key
```

Create the directory with restrictive permissions, copy the CA-provided files,
and start the profile:

```bash
sudo install -d -o czarny -g czarny -m 700 /opt/rdds/tls
chmod 600 /opt/rdds/tls/tls.crt /opt/rdds/tls/tls.key
cd /opt/rdds/source
sudo docker compose --profile tls up -d --build
sudo docker compose --profile tls ps
curl -fk https://127.0.0.1:8443/healthz
```

Use `https://SERVER_NAME:8443` in the browser. A temporary self-signed
certificate can validate mechanics in a closed lab but is not a production trust
model. Do not enable the Secure session cookie until users enter through HTTPS;
plain HTTP login will then intentionally stop working.

Before Internet or LTE exposure, also enforce a host firewall, restrict source
networks, disable legacy ingest after all sensors have individual credentials,
and decide whether a VPN or authenticated edge gateway is required. TLS protects
transport; it does not replace RDDS account and sensor authentication.

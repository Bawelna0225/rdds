# RDDS 0.15.0: operator sessions and security events

RDDS 0.15.0 adds local security-session administration without requiring
Active Directory, LDAP, OIDC or another identity provider. Existing RDDS
accounts and roles remain authoritative.

## Security model

The browser continues to receive an opaque session token in a `HttpOnly`,
`SameSite=Strict` cookie. The database stores only its SHA-256 digest. The new
security log never records passwords, raw session tokens, CSRF tokens, request
bodies or database credentials.

The administrator-only security center provides:

- active sessions with account, role, login time, last activity, idle expiry,
  source address and browser user agent;
- termination of one session or all other sessions belonging to an account;
- a separate log of successful and failed logins, account lockouts, logout and
  administrator session revocation;
- filters by time window, result, event type and username;
- CSV and JSON export;
- a warning when failed logins cross a configured threshold.

The normal operational audit log remains separate from the security-event log.
Administrator revocation actions are written to both so the operational audit
trail still attributes account-management changes.

## Failure warning

The warning is informational. It does not replace the existing per-account
lockout controlled by `RDDS_LOGIN_MAX_FAILURES` and `RDDS_LOGIN_LOCK_SECONDS`.

```dotenv
RDDS_SECURITY_FAILURE_WINDOW_MINUTES=15
RDDS_SECURITY_FAILURE_ALERT_COUNT=5
```

The first value defines the rolling observation window. The second defines how
many failed login attempts activate the administrator warning. A lockout is
also recorded as a high-severity event.

## Retention

Security events have an independent retention period:

```dotenv
RDDS_RETENTION_SECURITY_EVENTS_DAYS=180
```

Deletion is performed only by the existing maintenance service and therefore
still depends on `RDDS_RETENTION_ENABLED=true`. Keep retention disabled until a
dry run and an independently stored backup have been verified.

## Source addresses

The HTTPS gateway replaces a client-supplied forwarding chain at the public
trust boundary. The API records the first address forwarded by the RDDS proxy.
Keep the API bound to `127.0.0.1`; exposing it directly would allow a local
client to supply forwarding headers and would weaken the evidential value of
the recorded address.

## API

All endpoints below require the `administrator` role. Revocation endpoints
also require the session CSRF token.

- `GET /api/v1/security/summary`
- `GET /api/v1/security/sessions`
- `DELETE /api/v1/security/sessions/{session_id}`
- `POST /api/v1/security/operators/{operator_id}/sessions/revoke`
- `GET /api/v1/security/events`
- `GET /api/v1/security/export?format=csv|json`

The public session identifier returned by the administrative API is an
internal database UUID. It is not the cookie token and cannot authenticate a
request.

## Upgrade from 0.14.0

Add the settings if they are not already present:

```bash
cd /opt/rdds/source

grep -q '^RDDS_SECURITY_FAILURE_WINDOW_MINUTES=' .env ||
printf '\nRDDS_SECURITY_FAILURE_WINDOW_MINUTES=15\n' >> .env

grep -q '^RDDS_SECURITY_FAILURE_ALERT_COUNT=' .env ||
printf 'RDDS_SECURITY_FAILURE_ALERT_COUNT=5\n' >> .env

grep -q '^RDDS_RETENTION_SECURITY_EVENTS_DAYS=' .env ||
printf 'RDDS_RETENTION_SECURITY_EVENTS_DAYS=180\n' >> .env
```

Stop the API before the migration so no login request reaches code expecting
the new table before migration `012` is complete:

```bash
sudo docker compose stop api
sudo docker compose run --rm migrate

sudo docker compose up -d --build --force-recreate \
  api web maintenance
```

For an existing HTTPS deployment, also rebuild the changed gateway:

```bash
sudo docker compose --profile tls up -d --build --force-recreate gateway
```

Verify:

```bash
curl -fsS http://127.0.0.1:8000/ |
python3 -m json.tool

sudo docker compose exec -T database \
  psql -U rdds -d rdds -Atc \
  "SELECT migration_name FROM rdds_schema_migrations
   WHERE migration_name='012_operator_security.sql';"

sudo docker compose ps -a
sudo docker compose logs --tail=100 api web maintenance
```

The API root should report `0.15.0`. Log in as an administrator and open
**Bezpieczeństwo operatorów**. Use a private test window to create a second
session, verify that it appears in the list, and terminate it from the first
window. The terminated window should receive HTTP `401` on its next request.

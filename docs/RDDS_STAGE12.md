# RDDS stage 12: operator accounts, sessions and roles

Stage 12 replaces the shared `RDDS_ADMIN_TOKEN` used by the operator browser with
real RDDS accounts. TAK Server integration is intentionally outside this stage.
Individual sensor ingest tokens remain unchanged and continue to authenticate the
`/api/v1/ingest/*` endpoints.

## Security model

- passwords are stored only as Argon2id hashes;
- the browser receives a random session cookie marked `HttpOnly` and
  `SameSite=Strict`;
- PostgreSQL stores only the SHA-256 digest of the session token;
- every state-changing browser request requires `X-RDDS-CSRF-Token`;
- sessions expire after both an idle timeout and an absolute lifetime;
- five failed logins lock an account for 15 minutes by default;
- disabling, deleting, changing the role of, or resetting the password of an
  account revokes its active sessions;
- the last enabled administrator cannot be demoted, disabled or deleted;
- operation authors are derived from the authenticated account, never from an
  `actor` value supplied by the browser.

The cookie `Secure` flag is controlled by `RDDS_SESSION_COOKIE_SECURE`. It must
remain `false` while the development VM is accessed through plain HTTP. Set it to
`true` as soon as HTTPS terminates in front of the web service and before exposing
RDDS outside the trusted development network.

## Roles

| Role | Permissions |
| --- | --- |
| `viewer` | map, tracks, sensors, alerts, zones and audit log read access |
| `operator` | viewer access plus alert acknowledgement/closure and zone create/edit/enable/disable |
| `administrator` | all operator access plus sensor credentials, zone deletion and operator-account management |

## Upgrade from 0.11.1

Back up PostgreSQL and keep the existing `.env` file before upgrading. Apply the
0.12.0 patch, then add these development defaults to `.env`:

```dotenv
RDDS_SESSION_COOKIE_SECURE=false
RDDS_SESSION_IDLE_SECONDS=1800
RDDS_SESSION_ABSOLUTE_SECONDS=28800
RDDS_LOGIN_MAX_FAILURES=5
RDDS_LOGIN_LOCK_SECONDS=900
```

`RDDS_ADMIN_TOKEN` is no longer read by the 0.12 API. It may be left in `.env`
temporarily to make a code rollback to 0.11.1 possible, but it no longer grants
access to any operator endpoint.

Build and start the upgraded stack:

```bash
cd /opt/rdds/source
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose logs --tail=100 migrate api web
```

Migration `009_operator_auth.sql` is applied automatically by the existing
`migrate` service. Then create the first administrator from the VM console. The
password is requested interactively and therefore does not enter shell history or
the process list:

```bash
sudo docker compose run --rm api \
  python -m app.bootstrap_admin \
  --username czarny \
  --display-name "Administrator RDDS"
```

The bootstrap command refuses to run after the first administrator exists. Further
accounts are managed in the **Konta operatorów** panel.

Open `http://SERVER_IP:8080`, log in, and verify all three roles. An account created
in the web panel receives a temporary password and must change it at first login.

## Operational checks

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/live | python3 -m json.tool
curl -i http://127.0.0.1:8000/api/v1/sensors
sudo docker compose ps
sudo docker compose logs --tail=100 api web
```

The unauthenticated sensor-list request must return `401`; health endpoints remain
available for container monitoring. Confirm in the web interface that:

1. `viewer` cannot see mutation controls;
2. `operator` can acknowledge alerts and edit zones, but cannot manage sensors or
   accounts;
3. `administrator` can manage accounts and sensor credentials;
4. a missing or incorrect CSRF header causes `403` on a state-changing endpoint;
5. disabling an account ends its existing browser session.

## Before use outside the LAN

Terminate HTTPS in front of the web container, set
`RDDS_SESSION_COOKIE_SECURE=true`, restrict port 8000 to the host or backend network,
and retest login/logout through the final public hostname. Stage 12 supplies
application authentication but does not replace TLS, firewall policy, backups or
central identity management.

# RDDS hotfix 0.11.1

## Purpose

This maintenance release prevents the web reverse proxy from retaining an old
Docker address after the API container is recreated.

The web container now uses Docker's embedded DNS resolver (`127.0.0.11`) and a
shared Nginx upstream with dynamic name resolution. The `api` service address is
refreshed without restarting Nginx.

## Verification

Build and recreate the web and API services:

```bash
sudo docker compose up -d --build --force-recreate web api
```

Wait for the API to become healthy and verify access through the web proxy:

```bash
curl -fsS http://127.0.0.1:8080/api/v1/health/ready \
  | python3 -m json.tool
```

Recreate only the API container, wait up to 15 seconds for DNS refresh, and
repeat the proxy request:

```bash
sudo docker compose up -d --force-recreate api
sleep 15
curl -fsS http://127.0.0.1:8080/api/v1/health/ready \
  | python3 -m json.tool
```

Both proxy requests must return `status: ready`. No database volume is removed
or recreated by this procedure.

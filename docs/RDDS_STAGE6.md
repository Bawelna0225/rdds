# RDDS stage 6: operator controls

Stage 6 adds protected administrative controls to the standalone operational
map. An observer can continue to use the interface without credentials. An
operator can temporarily unlock additional actions with the existing RDDS
administrator token and an audit label identifying the operator.

## Operator mode

The browser verifies the supplied token through `/api/v1/admin/verify`. The
token is held only in the JavaScript memory of the current tab. It is not put in
a URL, `localStorage`, `sessionStorage` or a cookie. Reloading the page or using
the **Zablokuj** action removes it and returns the interface to read-only mode.

This is still a development-LAN security model. The application currently uses
plain HTTP, so operator mode must not be used over an untrusted network. A later
production stage must introduce HTTPS and individual authenticated accounts.

## Protected-zone editor

After unlocking operator mode:

1. select **Narysuj nową strefę**;
2. click at least three polygon points on the map;
3. finish drawing and enter the zone name, severity and optional description;
4. save the zone.

The browser closes the GeoJSON polygon automatically. The API and PostGIS still
perform the authoritative coordinate and geometry validation. A polygon can
contain up to 500 distinct points. Existing zones can be enabled or disabled
from their sidebar cards. Zones are not deleted because historical alerts keep
a referential link to the zone that generated them.

## Alert actions

An active alert can be acknowledged or closed from its sidebar card. An
acknowledgement records the supplied operator label while the alert continues
to track the intrusion. Manual closure does not suppress detection: when a
drone remains inside an active zone, the alert processor opens a new alert.

## Verification

```bash
sudo docker compose --profile simulation up -d --build
curl -fsS http://127.0.0.1:8000/api/v1/health/ready \
  | python3 -m json.tool
```

Open `http://192.168.10.169:8080`, unlock operator mode with the current
`RDDS_ADMIN_TOKEN`, create a small test zone and verify the zone toggle and
alert acknowledgement actions. The token must never be copied into screenshots
or diagnostic output.

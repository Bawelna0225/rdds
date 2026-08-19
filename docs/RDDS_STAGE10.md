# RDDS stage 10: operator workspace and entity lifecycle

Stage 10 reduces control-panel clutter and completes the administrative
lifecycle of protected zones and sensors. TAK Server integration remains
outside this stage.

## Operator workspace

The unlock form and administrative shortcuts now live in a menu in the upper
right corner. The button shows either `Obserwator` or the active operator name.
The administrator token continues to exist only in memory and is removed when
the operator locks the workspace or closes the browser tab.

The alerts, audit journal, tracks, sensors and protected zones sections can be
collapsed independently. Their collapsed state is saved in browser local
storage, so the layout survives a page reload without storing credentials.

## Zone and sensor actions

An unlocked operator can now use these actions from each entity card:

- protected zone: edit metadata and polygon, enable/disable, or delete;
- sensor: edit display name and fixed position, enable/disable, rotate its
  token, or delete.

Sensor keys are immutable because they identify the field device and are used
to bind ingest credentials. Deleting and recreating an entity under the same
key is intentionally not supported; use edit for a retained device and a new
key for a replacement device.

## Safe deletion

Migration 008 adds `deleted_at` and `deleted_by` to protected zones and sensors.
The API performs a logical deletion rather than removing referenced rows:

- a deleted zone is disabled and omitted from the operational map and list;
- all of that zone's open alerts are closed by the current operator;
- a deleted sensor is disabled and omitted from the map and list;
- all active credentials for that sensor are revoked immediately;
- observations, heartbeats, alerts and audit history remain available for
  evidence and diagnostics.

System summary counts include only visible zones, visible sensors and active
credentials belonging to visible sensors.

New audit event types are `zone_updated`, `zone_deleted`, `sensor_updated` and
`sensor_deleted`.

## Administrative API

The new endpoints require `X-RDDS-Admin-Token`:

```text
PUT    /api/v1/zones/{zone_uuid}
DELETE /api/v1/zones/{zone_uuid}
PUT    /api/v1/sensors/{sensor_uuid}
DELETE /api/v1/sensors/{sensor_uuid}
```

`PUT` uses a complete editable representation. A zone update includes its
name, description, severity, active state and GeoJSON polygon. A sensor update
includes its display name and optional WGS84 position. `DELETE` accepts the
operator label in an `actor` JSON field.

## Verification

Apply migration 008 and rebuild the services:

```bash
cd /opt/rdds/source
sudo docker compose run --rm migrate
sudo docker compose up -d --build
sudo docker compose ps -a
curl -fsS http://127.0.0.1:8000/ | python3 -m json.tool
```

The API root should report version `0.10.0`. In the browser:

1. open the upper-right operator menu and unlock the workspace;
2. collapse several sidebar sections, reload the page and confirm their state
   is retained;
3. edit a test zone's name and polygon, then verify `zone_updated` in the audit
   journal;
4. delete that test zone and confirm it disappears and its open alerts close;
5. edit a test sensor's display name and fixed position;
6. delete that sensor and confirm it disappears;
7. submit a heartbeat with its previous token and confirm HTTP 401;
8. confirm that deleted entity events and older observations remain in the
   audit/history views.

Run local static checks before committing:

```bash
cd /opt/rdds/source
python3 -m compileall -q server/api/app
node --check web/src/main.js
sudo docker compose build web
git diff --check
```

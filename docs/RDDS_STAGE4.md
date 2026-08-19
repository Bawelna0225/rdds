# RDDS stage 4: live operational map

Stage 4 adds a standalone browser interface in front of the existing RDDS API.
It deliberately does not depend on TAK Server. Nginx serves the static map and
proxies `/api/` requests to the internal `api` service, so the browser uses one
origin and the API does not need CORS configuration.

## Included functions

- live refresh every two seconds;
- sensor markers with online/offline state;
- drone markers with track state and heading;
- pilot markers and pilot-to-drone lines when the source reports a pilot
  position;
- selected-track history from the RDDS API;
- altitude, speed, heading, sensor count, timestamps and MGRS coordinates;
- responsive sidebar with track and sensor lists.

The interface is exposed on `RDDS_WEB_BIND_ADDRESS:RDDS_WEB_PORT` (by default
`0.0.0.0:8080`). On the development VM it should be available at
`http://192.168.10.169:8080`.

## Start and verify

```bash
sudo docker compose --profile simulation up -d --build
sudo docker compose --profile simulation ps -a
curl -fsS http://127.0.0.1:8080/healthz
```

The simulator should produce three sensor records and two moving drone tracks.
Select a track to display its observation history. The map remains useful when
the background tiles cannot be loaded, but the OpenStreetMap layer requires
Internet access from the operator's browser.

## Current deployment boundary

This is a development-LAN service. It has no operator authentication or HTTPS,
so it must not be exposed directly to the Internet. An offline or production
deployment should add an authenticated reverse proxy, TLS and a controlled tile
source (for example a local tile server). TAK integration remains a later,
separate stage.

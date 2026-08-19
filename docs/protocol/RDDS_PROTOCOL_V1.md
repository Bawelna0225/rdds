# RDDS protocol v1

RDDS v1 defines versioned JSON messages sent by a detection sensor to the
central server. It is transport-independent: the same envelope can be sent
from the USB forwarding bridge, LTE firmware, or simulator.

## Common rules

- Protocol identifier: `rdds/1.0`.
- Media type: `application/json`.
- Coordinates: WGS 84 latitude and longitude in decimal degrees.
- Time: ISO 8601 with an explicit UTC offset; UTC with `Z` or `+00:00` is
  recommended.
- Altitude and height: metres.
- Speed: metres per second.
- Heading: degrees in the range `[0, 360)`.
- RSSI: dBm.
- Every sensor creates a new random UUID `boot_id` after restart.
- Sequence numbers increase during one boot session.

The idempotency key is:

```text
(message_type, sensor_id, boot_id, sequence)
```

Resending the same message is accepted but does not create a duplicate database
record. This is required for LTE retry and offline queue operation.

## Ingestion authentication

Ingestion requests require the HTTP header:

```text
X-RDDS-Ingest-Token: <RDDS_INGEST_TOKEN>
```

Stage 8 adds individual sensor credentials that use the same header. The token
is bound to one `sensor_id`, can be rotated or revoked independently, and is the
required mode for the Stage 9 Sky-Spy sensor agent. The shared development token
is retained only for the documented legacy transition. Outside a trusted
development LAN, ingestion must use HTTPS.

## Heartbeat

Endpoint:

```text
POST /api/v1/ingest/heartbeat
```

Example:

```json
{
  "protocol_version": "rdds/1.0",
  "message_type": "heartbeat",
  "sensor": {
    "sensor_id": "sensor-pl-001",
    "display_name": "North observation point",
    "boot_id": "ec9d560b-f1d6-4e63-9bf3-852fca3c4ccc",
    "sequence": 12,
    "timestamp": "2026-08-19T08:45:00Z",
    "position": {
      "latitude": 52.2297,
      "longitude": 21.0122
    }
  },
  "status": {
    "uptime_seconds": 3600,
    "free_heap_bytes": 196000,
    "queue_depth": 0,
    "cellular_rssi": -67
  }
}
```

## Observation

Endpoint:

```text
POST /api/v1/ingest/observation
```

Example:

```json
{
  "protocol_version": "rdds/1.0",
  "message_type": "observation",
  "sensor": {
    "sensor_id": "sensor-pl-001",
    "boot_id": "ec9d560b-f1d6-4e63-9bf3-852fca3c4ccc",
    "sequence": 245,
    "timestamp": "2026-08-19T08:45:02Z",
    "position": {
      "latitude": 52.2297,
      "longitude": 21.0122
    }
  },
  "radio": {
    "transport": "ble",
    "channel": 37,
    "rssi": -72
  },
  "drone": {
    "mac": "02:00:00:00:00:01",
    "basic_id": "EXAMPLE-DRONE-001",
    "operator_id": "EXAMPLE-OPERATOR-001",
    "position": {
      "latitude": 52.2311,
      "longitude": 21.0193
    },
    "altitude_m": 110.0,
    "height_agl_m": 85.0,
    "speed_mps": 12.5,
    "heading_deg": 91.0,
    "emergency_status": "none"
  },
  "pilot_position": {
    "latitude": 52.2261,
    "longitude": 21.0091
  }
}
```

The complete machine-readable schema is stored at
`protocol/rdds-v1.schema.json`. Runtime schemas generated from the API models
are available from `GET /api/v1/protocol/schema` and in `/docs`.

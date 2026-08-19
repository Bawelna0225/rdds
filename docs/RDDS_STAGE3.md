# RDDS stage 3: track processing

Stage 3 turns raw observations into logical drone tracks while preserving every
source observation. The processor runs independently from the ingestion API so
temporary processor failure cannot block sensors from submitting data.

## Identity priority

The initial deterministic resolver uses the first available value in this
order:

1. Basic ID
2. Session ID
3. MAC address
4. Operator ID

The normalized value is hashed into a stable internal `track_key`. Multiple
sensors reporting the same Basic ID therefore contribute to one track. A later
stage will add confidence scoring and spatial-temporal correlation for messages
without a reliable identity.

## Track states

- `new`: only one observation has been linked.
- `active`: at least two observations and a recent update.
- `stale`: no update for the configured stale interval.
- `ended`: no update for the configured ended interval.
- `anomalous` and `no_gps`: reserved for later validation rules.

Development defaults are 15 seconds for `stale` and 60 seconds for `ended`.

## API

```text
GET /api/v1/tracks
GET /api/v1/tracks?include_ended=true
GET /api/v1/tracks/{track_id}/history?limit=500
```

The current track response includes drone and pilot coordinates, motion data,
observation count, identity source, and the number of contributing sensors.

## Verification

With the stage 2 simulator running:

```bash
curl -fsS http://127.0.0.1:8000/api/v1/tracks | python3 -m json.tool
sudo docker compose logs --tail=30 tracker
```

Expected result is two active tracks. Each should report three contributing
sensors. Stopping the simulator should change tracks to `stale` and then
`ended`, without deleting their history.

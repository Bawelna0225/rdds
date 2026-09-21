# RDDS 0.27.1: bounded track archive queries

RDDS 0.27.1 gives the track archive the same date-bounded, row-capped contract
that the alert and sensor-alert archives already had. It is a backend-only
step that prepares the API for a calendar-based archive UI without changing
any live operational query.

## Root cause

`GET /api/v1/tracks?include_ended=true` returned every ended track in the
database in one response, with no date filter and no row limit. The alert
(`/api/v1/alerts`) and sensor-alert (`/api/v1/sensor-alerts`) archives already
solved this with optional `closed_from`/`closed_before` filters and a capped
`limit`; the track archive was the one remaining unbounded list endpoint. As
the `tracks` table grows, this becomes an increasingly large, increasingly
slow response — a problem for any client, and especially costly on a mobile
connection.

## Changes

- `GET /api/v1/tracks` gains optional `ended_from`, `ended_before` and
  `limit` (default 200, maximum 1000), mirroring the existing alert archive
  contract exactly. Date filters require `include_ended=true`, must carry a
  UTC offset, and `ended_from` must be earlier than `ended_before` when both
  are given.
- Live (`include_ended=false`) track queries are completely unaffected: no
  limit is applied and no date filter is accepted, so the operational map
  keeps its existing unbounded behavior.
- A new `GET /api/v1/tracks/archive/calendar?month=YYYY-MM` endpoint returns
  the number of ended tracks per UTC calendar day for one month, so a
  calendar view can be populated without downloading the tracks themselves.
- The calendar query reuses the existing partial index
  `idx_tracks_retention (ended_at, id) WHERE state = 'ended'` from migration
  `010_operations.sql`. No new index and no database migration is required.

## Not in this change

The web UI still calls the old unbounded shape (`include_ended=true` with no
date range) from `loadArchivedTracks()`. Rewiring the archive panel to a
calendar/day picker that uses the new bounded parameters, and reworking that
panel's layout for phone-sized screens, is the planned follow-up on top of
this backend contract.

## Validation

```bash
python3 -m py_compile server/api/app/track_store.py server/api/app/main.py
node --check web/src/main.js
git diff --check

sudo docker compose run --rm --no-deps \
  -v "$PWD:/project:ro" -w /project \
  -e PYTHONPATH=/project/server/api api \
  python -m unittest discover -s /project/server/api/tests -v
```

Then rebuild `api` only (no `web` changes, no migration to apply) and verify:

```bash
curl -fsS "http://127.0.0.1:8000/api/v1/tracks?include_ended=true&limit=5" \
  -H "Cookie: $SESSION_COOKIE" | python3 -m json.tool

curl -fsS "http://127.0.0.1:8000/api/v1/tracks/archive/calendar?month=$(date +%Y-%m)" \
  -H "Cookie: $SESSION_COOKIE" | python3 -m json.tool
```

The first request should still return archived tracks (now capped at
`limit`); the second should return one `{date, track_count}` entry per day in
the current month that has at least one ended track. The live map and active
track list should show no behavioral change.

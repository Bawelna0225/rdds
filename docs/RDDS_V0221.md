# RDDS 0.22.1: archive performance hotfix

RDDS 0.22.1 fixes archive requests that became I/O-bound after the test
environment accumulated more than one million raw observations.

## Root cause

The closed intrusion-alert query included a lateral
`COUNT(DISTINCT observation.sensor_id)` for every returned alert. The track
archive similarly joined `track_observations` and `observations` only to
recalculate the number of contributing sensors.

Those aggregates are useful for live operational data but are not required to
list stored archives. With a multi-gigabyte `observations` table they caused
long `DataFileRead` waits and could exceed the reverse-proxy timeout.

## Changes

- `closed_only=true` intrusion-alert requests skip the historical contributing
  sensor aggregate;
- `include_ended=true` track-list requests skip
  `track_observations`/`observations`;
- archived tracks display an unknown sensor count (`—`) instead of a misleading
  zero when the lightweight archive path is used;
- live `include_ended=false` track requests keep their existing contributing
  sensor calculation;
- audit loading remains unchanged and continues to request at most 100 rows at
  a time;
- no database migration is required.

## Validation

After applying the hotfix, rebuild `api` and `web`, then verify:

```bash
curl -fsS http://127.0.0.1:8000/ | python3 -m json.tool

sudo docker compose run --rm --no-deps \
  -v "$PWD:/project:ro" \
  -w /project \
  -e PYTHONPATH=/project/server/api \
  api \
  python -m unittest discover -s /project/server/api/tests -v

node --check web/src/main.js
git diff --check
```

The API root should report `0.22.1`.

For a production-like benchmark, open **Zamknięte alarmy** and **Archiwum tras**
and watch `pg_stat_activity`. Those requests should no longer spend seconds
reading `observations` merely to populate archive cards.

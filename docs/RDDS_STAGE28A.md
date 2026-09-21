# RDDS Stage 28A — Trusted Agent Artifact Repository

Stage 28A turns the Stage 27 release catalog into a server-side artifact repository.
An administrator may upload the exact file described by a release. RDDS streams the
request to a temporary file, enforces the catalog size limit, calculates SHA-256 and
atomically places only matching content in persistent storage.

## Safety boundary

This stage has no sensor download endpoint, does not expose a filesystem path or URL,
does not assign an artifact to a sensor and does not install or execute anything. Agent
behavior and Stage 27 update-plan behavior remain unchanged.

New draft releases cannot be published until their artifact is verified. A legacy
release that was already published before migration 031 remains published and can be
backfilled. Withdrawn releases reject uploads.

## Storage and consistency

- Maximum object size: 512 MiB.
- Request type: `application/octet-stream`.
- Object key: `<first two SHA-256 characters>/<full SHA-256>`.
- Temporary files are created below `.staging`, flushed and atomically renamed.
- The browser checks filename and size; the API independently checks byte count and
  SHA-256 and never uses the supplied filename as a filesystem path.
- Registration locks the release and rechecks its revision and artifact metadata after
  streaming. A concurrent catalog edit therefore cannot validate the wrong artifact.
- Any draft metadata revision after upload reports the previous verification as `stale`
  until the file is uploaded again. The publish lifecycle revision preserves the verified
  state and does not rewrite the binary.

## Deployment

Create the host directory before rebuilding the API:

```bash
sudo install -d -o 10001 -g 10001 -m 0750 /opt/rdds/agent-artifacts
```

Set `RDDS_AGENT_ARTIFACT_PATH` if a different host location is required. The default
container path is `/var/lib/rdds/agent-artifacts`; only that mount is writable while the
rest of the API filesystem remains read-only.

The artifact directory is not part of `pg_dump`. Back up both PostgreSQL and
`RDDS_AGENT_ARTIFACT_PATH`, and restore them as one consistency set.

## Validation

```bash
python3 -m py_compile \
  server/api/app/agent_artifact_store.py \
  server/api/app/agent_release_store.py \
  server/api/app/config.py \
  server/api/app/main.py

node --check web/src/main.js
git diff --check

sudo docker compose run --rm --no-deps \
  -v "$PWD:/project:ro" -w /project \
  -e PYTHONPATH=/project/server/api api \
  python -m unittest discover -s /project/server/api/tests -v
```

Then apply migration `031`, rebuild API and Web, upload the existing
`rdds-v0.26.0-source.tar.gz` from its published release detail and verify that the UI
shows `zweryfikowany`. No request from a sensor should change as a result.

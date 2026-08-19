# RDDS stage 1: API and spatial database

This stage adds an independent server foundation without changing the original
Sky-Spy firmware or `mesh-mapper.py`.

## Components

- FastAPI service running as an unprivileged container user.
- PostgreSQL 16 with PostGIS 3.5.
- Persistent Docker volume for the database.
- Initial tables for sensors, heartbeats, raw observations, and fused tracks.
- Liveness and database-readiness endpoints.

## Development endpoints

- `GET /`
- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/system/summary`
- `GET /docs`

Authentication and HTTPS are intentionally deferred until the ingestion
protocol and simulator are operational. Do not expose port 8000 to the public
Internet.

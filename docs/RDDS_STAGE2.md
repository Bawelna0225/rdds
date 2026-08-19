# RDDS stage 2: ingestion protocol and simulator

Stage 2 adds authenticated RDDS v1 ingestion and a synthetic data source. It
does not perform RF detection and does not create fused tracks yet.

## New components

- Strict Pydantic request validation with unknown fields rejected.
- Shared development ingest token sent in `X-RDDS-Ingest-Token`.
- Idempotent heartbeat and observation writes.
- Automatic development provisioning of sensors by `sensor_id`.
- Background online/offline sensor status monitoring.
- Three simulated fixed sensors and two simulated moving drones.
- Machine-readable JSON Schema and protocol documentation.

## Start the simulation profile

```bash
sudo docker compose --profile simulation up -d --build
```

## Verify data flow

```bash
curl -fsS http://127.0.0.1:8000/api/v1/system/summary | python3 -m json.tool
curl -fsS http://127.0.0.1:8000/api/v1/sensors | python3 -m json.tool
sudo docker compose --profile simulation logs --tail=20 simulator
```

Expected sensor count is three. Observation and heartbeat counts increase while
the simulator is running. Track count remains zero until the track processor is
added in the next stage.

## Stop only the simulator

```bash
sudo docker compose --profile simulation stop simulator
```

After the configured offline timeout, all simulated sensors change to
`offline`. Starting the simulator again changes them back to `online`.

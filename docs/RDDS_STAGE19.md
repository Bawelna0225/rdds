# RDDS Stage 19 — automatic stream-quality supervision

Stage 19 turns the diagnostic counters introduced in Stage 18 into guarded,
automatic health decisions. It detects a connected Sky-Spy source that sends
mostly unusable input and a source that reconnects too often.

## Scope

- rolling quality samples calculated from per-boot counter deltas;
- configurable evaluation window, warm-up duration and minimum input count;
- malformed-stream threshold based on the ignored-line ratio;
- reconnect-rate threshold for an unstable Sky-Spy source;
- `source_data_invalid` and `source_unstable` sensor health reasons;
- audited health-reason changes, including changes between degraded reasons;
- latest quality window in sensor details and JSON diagnostic export;
- 18 recent quality samples loaded only when a sensor is selected.

Stage 19 does not classify RF reception quality. Input quality describes the
software stream delivered by Sky-Spy to the agent, not antenna performance,
receiver sensitivity or RF noise.

## Rolling calculation

For every heartbeat the API finds the oldest earlier heartbeat from the same
sensor and `sensor.boot_id` inside the configured rolling window. It calculates:

```text
input_delta       = current.input_lines_total - baseline.input_lines_total
parsed_delta      = current.parsed_detections_total - baseline.parsed_detections_total
ignored_delta     = current.ignored_lines_total - baseline.ignored_lines_total
reconnect_delta   = current.source_connections_total - baseline.source_connections_total
ignored_ratio     = ignored_delta / input_delta
```

The sample is discarded if time did not advance, a counter is missing or any
counter decreased. This makes an agent restart and counter reset safe.

Health precedence remains operational:

1. disconnected or silent source;
2. malformed stream;
3. unstable source connection;
4. API delivery failure;
5. dead-letter or outbox backlog;
6. healthy.

The warm-up duration applies to both new quality reasons. The ignored-ratio
test additionally requires the configured minimum number of input lines.

## Configuration

| Variable | Default | Meaning |
| --- | ---: | --- |
| `RDDS_SENSOR_QUALITY_WINDOW_SECONDS` | `60` | rolling baseline window |
| `RDDS_SENSOR_QUALITY_MIN_WINDOW_SECONDS` | `30` | warm-up before evaluation |
| `RDDS_SENSOR_QUALITY_MIN_INPUT_LINES` | `20` | minimum lines for ratio evaluation |
| `RDDS_SENSOR_QUALITY_MAX_IGNORED_PERCENT` | `80` | ignored-line percentage that degrades health |
| `RDDS_SENSOR_RECONNECT_WARNING_COUNT` | `3` | reconnects in the window that degrade health |

Defaults deliberately tolerate the periodic non-detection status lines emitted
by the normal emulator while recognizing the `malformed` and `disconnect`
fault modes used in Stage 18.

## Storage and API

Migration `017_sensor_stream_quality.sql` adds the calculated sample to each
heartbeat and copies the newest sample into the current sensor snapshot. It
also expands the health audit trigger so a reason transition such as
`source_data_invalid` to `source_unstable` creates one audit event even though
the sensor remains `degraded`.

The operator UI uses:

```text
GET /api/v1/sensors/{sensor_id}/quality-history?limit=18
```

The endpoint accepts limits from 1 to 120. It is not part of the two-second
dashboard refresh; history is loaded on demand when the operator selects a
sensor.

## Upgrade

```bash
sudo docker compose run --rm migrate

sudo docker compose up -d --build --force-recreate \
  api web sensor-agent-emulator
```

The Sky-Spy emulator does not need rebuilding for Stage 19. Recreate it only
when changing a fault-mode environment variable.

## Verification

```bash
python3 -m unittest discover -s sensor-agent/tests -v
python3 -m unittest discover -s skyspy-emulator/tests -v

sudo docker compose run --rm --no-deps \
  -v "$PWD:/project:ro" \
  -w /project \
  -e PYTHONPATH=/project/server/api \
  api \
  python -m unittest discover -s /project/server/api/tests -v

sh operations/tests/test_operations.sh

python3 -m py_compile \
  sensor-agent/rdds_agent.py \
  skyspy-emulator/main.py

node --check web/src/main.js
git diff --check
```

Expected API version: `0.19.0`.

For controlled verification, set the emulator to `malformed` for longer than
the warm-up period, restore `normal`, then repeat with `disconnect`. The sensor
should degrade with the matching reason, recover automatically after the bad
samples leave the rolling window, and keep outbox and dead-letter counts at
zero.

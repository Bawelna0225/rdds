# RDDS Stage 18 — sensor-path diagnostics

Stage 18 makes the complete path from the Sky-Spy stream to RDDS observable
before physical receiver validation. It extends the existing heartbeat instead
of introducing a second monitoring channel.

## Scope

- per-agent-boot input, parsing, queue and delivery counters;
- current source connection kind and connection lifetime;
- safe source and API error categories without raw exception text;
- queue capacity and age of the oldest pending message;
- last successful and failed delivery timestamps;
- server-side clock-offset calculation;
- grouped sensor diagnostics in the operator selection panel;
- JSON diagnostic export without credential material;
- controlled Sky-Spy emulator modes for silent, malformed and disconnect tests.

This stage does not claim firmware, antenna, RF noise-floor or receiver RSSI
measurements. Those values require support from the physical firmware and are
reserved for hardware validation.

## Heartbeat telemetry

The `rdds/1.0` heartbeat remains backward compatible. All Stage 18 fields are
optional, so a 0.17 agent can still report to a 0.18 API during a controlled
upgrade.

Counters reset when `sensor.boot_id` changes. They describe the current agent
process and must not be interpreted as lifetime sensor totals.

The API stores diagnostic fields in `sensor_heartbeats`. The sensor list joins
only the newest heartbeat and calculates:

```text
clock_offset_seconds = heartbeat.received_at - heartbeat.measured_at
```

This value includes network delay. It is a commissioning warning, not a
precision time-synchronization measurement.

## Operator diagnostics

Selecting a sensor shows four immediate checks:

1. Sky-Spy to agent connection;
2. agent to RDDS delivery;
3. local outbox state;
4. agent/server clock difference.

Detailed sections expose the input, parsed-detection, enqueue, retry, discard
and dead-letter counters. `Pobierz diagnostykę JSON` exports only a defined
allow-list of operational fields. Token prefixes, credentials and raw errors
are excluded.

## Emulator fault modes

Configure one mode in `.env` and recreate the emulator services:

```text
RDDS_SKYSPY_EMULATOR_FAULT_MODE=normal
```

Supported values:

| Mode | Behavior | Expected diagnostic effect |
| --- | --- | --- |
| `normal` | sends valid Sky-Spy data | parsed and enqueued counters increase |
| `silent` | keeps TCP open without sending bytes | `source_silent` after the configured grace period |
| `malformed` | sends invalid JSON lines | input and ignored counters increase |
| `disconnect` | closes the stream after a fixed count | source connection counter increases after reconnect |

`RDDS_SKYSPY_EMULATOR_DISCONNECT_AFTER_MESSAGES` controls the disconnect
threshold and defaults to `20`.

Return the mode to `normal` after each controlled test. Fault modes are intended
for an isolated development deployment, not production.

## Upgrade

Run the migration and rebuild the services that own the changed code:

```bash
sudo docker compose run --rm migrate

sudo docker compose up -d --build --force-recreate \
  api web skyspy-emulator sensor-agent-emulator
```

Hardware deployments rebuild `sensor-agent` instead of the emulator profile.

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

Expected API version: `0.18.0`.

## Hardware boundary

Stage 18A validates the software observability path with the emulator. Stage
18B begins only after a XIAO ESP32-S3 or ESP32-C5 receiver is connected. The
hardware test must cover USB removal and reconnect, host restart, network loss,
API restart, clock drift and a real Remote ID reception sample.

# RDDS stage 9: Sky-Spy sensor agent and durable delivery

Stage 9 connects the standalone RDDS backend to the newline-delimited JSON
stream produced by Sky-Spy. It adds a field-side sensor agent, a durable SQLite
outbox and a TCP serial emulator. TAK Server remains outside this stage.

## Data path

```text
Sky-Spy ESP32 -- USB serial 115200 --> sensor agent -- HTTPS/HTTP --> RDDS API
                                             |
                                             +--> SQLite outbox
```

The agent can read either a Linux serial device such as `/dev/ttyACM0` or a
PySerial URL. The `skyspy-emulation` Compose profile uses
`socket://skyspy-emulator:7000`, so the complete path can be tested before the
receiver hardware is available.

The upstream firmware writes one JSON object per detected packet. The same
serial stream also contains startup text, buzzer messages and periodic
`{"status":"scanning"}` objects. The agent ignores those non-detection lines,
normalizes `remote_id` to `basic_id`, accepts identity-only observations with
zero-filled GPS fields, and preserves the original object in `raw_remote_id`.

## Current firmware field mapping

| Sky-Spy field | RDDS field | Notes |
| --- | --- | --- |
| `mac` | `drone.mac` | normalized to lower-case |
| `rssi` | `radio.rssi` | dBm |
| `drone_lat`, `drone_long` | `drone.position` | omitted when either value is zero/invalid |
| `drone_altitude` | `drone.altitude_m` | added only with a valid drone position |
| `height_agl` | `drone.height_agl_m` | added only with a valid drone position |
| `speed` | `drone.speed_mps` | horizontal speed in m/s |
| `heading` | `drone.heading_deg` | degrees in the range 0 to less than 360 |
| `pilot_lat`, `pilot_long` | `pilot_position` | omitted when either value is zero/invalid |
| `basic_id` or `remote_id` | `drone.basic_id` | empty identifiers are omitted |
| `operator_id` or `op_id` | `drone.operator_id` | empty identifiers are omitted |
| `transport`, `channel` | `radio.transport`, `radio.channel` | BLE, Wi-Fi NAN or Wi-Fi Beacon source |

Stage 11 extends both bundled Sky-Spy firmware variants so these optional fields
are now serialized. The adapter remains backward compatible with the original
short JSON line, so older receivers and the enriched `skyspy/1.1` output can be
used during a gradual hardware rollout.

## Delivery guarantees

Every heartbeat and observation is written to SQLite before an HTTP request is
attempted. The queue uses full SQLite synchronization and FIFO replay. A server
duplicate is safe because the original RDDS `boot_id` and `sequence` remain in
the queued JSON payload.

- Network errors, HTTP 5xx, 408, 425 and 429 are retried with capped exponential
  backoff.
- HTTP 401/403 is retained and retried every 60 seconds so a corrected or
  rotated token can recover the same queue.
- Other permanent HTTP 4xx responses are moved to the `dead_letter` table so a
  malformed packet cannot block every later observation.
- The default limit is 250,000 queued messages. When it is reached, new input
  is rejected and logged instead of silently deleting the oldest evidence.
- The queue is stored in a named Docker volume and survives container rebuilds
  and VM restarts.

The periodic RDDS heartbeat includes the current `queue_depth`, which appears
in the existing sensor details panel. A large or increasing value means that
the field agent cannot drain its backlog.

## Configure the emulated receiver

Register a sensor with key `skyspy-sensor-01` in the operator interface and
copy its one-time individual ingest token. Add the following values to the
VM's Git-ignored `.env` file; never put the token in Git, command history or a
screenshot:

```dotenv
RDDS_AGENT_SENSOR_ID=skyspy-sensor-01
RDDS_AGENT_DISPLAY_NAME=Sky-Spy development receiver
RDDS_AGENT_SENSOR_TOKEN=PASTE_THE_INDIVIDUAL_TOKEN_HERE
RDDS_AGENT_SENSOR_LAT=52.229700
RDDS_AGENT_SENSOR_LON=21.012200
```

Start the software receiver path:

```bash
cd /opt/rdds/source
sudo docker compose --profile skyspy-emulation up -d --build
sudo docker compose ps -a
sudo docker compose logs --tail=50 sensor-agent-emulator skyspy-emulator
```

Within a few seconds the registered sensor should be online, its heartbeat and
observation counters should increase, and track `SKYSPY-EMULATED-01` should
appear on the map.

Do not run the `skyspy-emulation` and `skyspy-hardware` profiles at the same
time with the same sensor ID.

## Verify offline queue and replay

Leave the emulator and agent running, then stop only the API:

```bash
cd /opt/rdds/source
sudo docker compose stop api
sleep 15
sudo docker compose logs --tail=30 sensor-agent-emulator
```

The log should show retry backoff. Start the API again and watch the same agent
drain the persisted queue:

```bash
sudo docker compose start api
sudo docker compose logs -f sensor-agent-emulator
```

Stop following the log with `Ctrl+C`. On the next heartbeat the sensor panel's
queue depth should return to zero and the observation count should catch up.
Stopping or rebuilding `sensor-agent-emulator` during the outage is an
additional persistence test; the named volume must retain the backlog.

## Switch to physical Sky-Spy hardware later

After Proxmox USB passthrough exposes the receiver to this VM, identify its
stable device path. Prefer `/dev/serial/by-id/...` over `/dev/ttyACM0`, because
the latter can change after reconnects. Set it in `.env`:

```dotenv
RDDS_SKYSPY_DEVICE=/dev/serial/by-id/usb-YOUR_SKYSPY_DEVICE
```

Stop the emulation profile and start hardware mode:

```bash
cd /opt/rdds/source
sudo docker compose --profile skyspy-emulation stop \
  sensor-agent-emulator skyspy-emulator
sudo docker compose --profile skyspy-hardware up -d --build
sudo docker compose logs -f sensor-agent
```

The existing individual token and sensor key can be reused. The hardware agent
has a separate outbox volume from the emulator.

## Local checks

The parser and outbox tests do not need Docker or hardware:

```bash
cd /opt/rdds/source
python3 -m unittest discover -s sensor-agent/tests -v
python3 -m py_compile sensor-agent/rdds_agent.py skyspy-emulator/main.py
git diff --check
```

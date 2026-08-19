# RDDS stage 11: enriched Sky-Spy firmware output

Stage 11 closes the data gap between the Sky-Spy Remote ID decoder and the RDDS
sensor agent. The firmware already decoded operator identity, height, speed and
heading but discarded those values while building its USB serial JSON line.
Both firmware variants now emit the complete data set that RDDS can ingest.

TAK Server integration is intentionally outside this stage. The receiver is
still a passive Remote ID sensor connected to the standalone RDDS system.

## Changed firmware variants

- `src/main.cpp`: XIAO ESP32-S3 2.4 GHz receiver.
- `xiao-c5-5g/src/main.cpp`: XIAO ESP32-C5 dual-band receiver and its ESP32-S3
  compatibility environment.

The C5 PlatformIO environment uses the official board identifier
`seeed_xiao_esp32c5`. The older generic `esp32c5` identifier is not present in
the current pioarduino board registry.

The existing JSON keys remain valid. New output uses `format_version` value
`skyspy/1.1` and may add the following fields when they were decoded:

| Field | Meaning |
| --- | --- |
| `operator_id` | Remote ID operator identifier |
| `height_agl` | height above the transmitted reference, metres |
| `speed` | horizontal speed, metres per second |
| `heading` | course, degrees |
| `transport` | `ble`, `wifi_nan` or `wifi_beacon` |
| `channel` | Wi-Fi channel; omitted for BLE |
| `band` | existing dual-band firmware label, retained for diagnostics |

Position, altitude and motion fields are emitted only when a current drone
position is present. Pilot coordinates are emitted independently when the
Remote ID system message contains them. Identity-only messages therefore stay
valid and do not invent a zero coordinate or a stationary speed.

The serializer now uses ArduinoJson instead of a fixed `snprintf()` buffer.
This avoids silent truncation as fields are added and correctly escapes text
identifiers. Motion values are retained as floating-point numbers instead of
being rounded to integers before transmission.

Example enriched line:

```json
{"format_version":"skyspy/1.1","mac":"02:53:4b:59:00:01","rssi":-61,"transport":"wifi_nan","channel":6,"basic_id":"DRONE-01","operator_id":"OPERATOR-01","drone_lat":52.2297,"drone_long":21.0122,"drone_altitude":104.5,"height_agl":82.5,"speed":15.8,"heading":91.25,"pilot_lat":52.2281,"pilot_long":21.0141}
```

## Sensor-agent compatibility

The stage 9 parser already accepts the enriched field aliases. Stage 11 changes
the emulator to reproduce the firmware's exact names and adds regression tests
for:

- operator identity, height, speed and heading;
- Wi-Fi transport and channel;
- a `skyspy/1.1` identity-only message without a drone position;
- preservation of the original object in `raw_remote_id`.

The durable SQLite outbox, individual sensor token and replay behavior are
unchanged.

## Checks without receiver hardware

Run the software checks first:

```bash
cd /opt/rdds/source
python3 -m unittest discover -s sensor-agent/tests -v
python3 -m py_compile sensor-agent/rdds_agent.py skyspy-emulator/main.py
git diff --check
```

PlatformIO can compile all firmware environments without a connected board.
Use an isolated virtual environment; do not install it with `sudo`:

```bash
cd /opt/rdds/source
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade platformio

pio run -e seeed_xiao_esp32s3
pio run -d xiao-c5-5g -e seeed_xiao_esp32s3
pio run -d xiao-c5-5g -e seeed_xiao_esp32c5

deactivate
```

The `.pio/` and `.venv/` directories are ignored by Git. A successful compile
proves that both targets build, but does not validate radio reception. Flashing,
serial observation and comparison with a known Remote ID transmitter wait until
the physical receiver is available.

## Software-only end-to-end check

Rebuild the API, emulator and agent after applying the stage:

```bash
cd /opt/rdds/source
sudo docker compose --profile skyspy-emulation up -d --build
sudo docker compose ps -a
sudo docker compose logs --tail=40 skyspy-emulator sensor-agent-emulator
curl -fsS http://127.0.0.1:8000/ | python3 -m json.tool
```

The API root should report version `0.11.0`. The existing
`SKYSPY-EMULATED-01` track should contain operator ID, speed and heading, while
the sensor remains online with queue depth returning to zero.

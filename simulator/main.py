import json
import math
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

API_URL = os.getenv("RDDS_API_URL", "http://api:8000").rstrip("/")
LEGACY_INGEST_TOKEN = os.getenv("RDDS_INGEST_TOKEN", "")
CENTER_LAT = float(os.getenv("RDDS_SIM_CENTER_LAT", "52.229700"))
CENTER_LON = float(os.getenv("RDDS_SIM_CENTER_LON", "21.012200"))
INTERVAL_SECONDS = max(0.5, float(os.getenv("RDDS_SIM_INTERVAL_SECONDS", "2")))
HEARTBEAT_SECONDS = 10.0


def load_sensor_tokens() -> dict[str, str]:
    raw = os.getenv("RDDS_SIM_SENSOR_TOKENS_JSON", "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("RDDS_SIM_SENSOR_TOKENS_JSON is not valid JSON") from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(token, str) and token
        for key, token in value.items()
    ):
        raise RuntimeError("RDDS_SIM_SENSOR_TOKENS_JSON must map sensor IDs to tokens")
    return value


SENSOR_TOKENS = load_sensor_tokens()

SENSORS = (
    {
        "id": "sim-sensor-01",
        "name": "Simulator sensor North",
        "east": -650,
        "north": 650,
    },
    {
        "id": "sim-sensor-02",
        "name": "Simulator sensor East",
        "east": 750,
        "north": -100,
    },
    {
        "id": "sim-sensor-03",
        "name": "Simulator sensor South",
        "east": -250,
        "north": -800,
    },
)

DRONES = (
    {
        "mac": "02:00:00:00:00:01",
        "basic_id": "SIM-DRONE-ALPHA",
        "operator_id": "SIM-OPERATOR-01",
        "session_id": "SIM-SESSION-ALPHA",
        "radius": 520.0,
        "period": 150.0,
        "altitude": 110.0,
        "phase": 0.0,
    },
    {
        "mac": "02:00:00:00:00:02",
        "basic_id": "SIM-DRONE-BRAVO",
        "operator_id": "SIM-OPERATOR-02",
        "session_id": "SIM-SESSION-BRAVO",
        "radius": 920.0,
        "period": 230.0,
        "altitude": 75.0,
        "phase": math.pi,
    },
)

BOOT_IDS = {sensor["id"]: str(uuid4()) for sensor in SENSORS}
HEARTBEAT_SEQUENCES = {sensor["id"]: 0 for sensor in SENSORS}
OBSERVATION_SEQUENCES = {sensor["id"]: 0 for sensor in SENSORS}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def offset_position(east_m: float, north_m: float) -> dict[str, float]:
    latitude = CENTER_LAT + north_m / 111_320.0
    longitude = CENTER_LON + east_m / (111_320.0 * math.cos(math.radians(CENTER_LAT)))
    return {
        "latitude": round(latitude, 7),
        "longitude": round(longitude, 7),
    }


def distance_m(first: dict[str, float], second: dict[str, float]) -> float:
    latitude_scale = 111_320.0
    longitude_scale = latitude_scale * math.cos(math.radians(CENTER_LAT))
    north = (second["latitude"] - first["latitude"]) * latitude_scale
    east = (second["longitude"] - first["longitude"]) * longitude_scale
    return math.hypot(east, north)


def synthetic_rssi(distance: float) -> int:
    return max(
        -100, min(-25, round(-35.0 - 20.0 * math.log10(max(distance, 10.0) / 10.0)))
    )


def ingest_token_for(sensor_id: str) -> str:
    token = SENSOR_TOKENS.get(sensor_id, LEGACY_INGEST_TOKEN)
    if not token:
        raise RuntimeError(f"No ingest token configured for {sensor_id}")
    return token


def post(path: str, payload: dict[str, object], sensor_id: str) -> bool:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{API_URL}{path}",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-RDDS-Ingest-Token": ingest_token_for(sensor_id),
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            response.read()
        return True
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} for {path}: {detail}", flush=True)
    except URLError as exc:
        print(f"Connection error for {path}: {exc}", flush=True)
    return False


def sensor_context(
    sensor: dict[str, object], sequence: int, timestamp: str
) -> dict[str, object]:
    return {
        "sensor_id": sensor["id"],
        "display_name": sensor["name"],
        "boot_id": BOOT_IDS[sensor["id"]],
        "sequence": sequence,
        "timestamp": timestamp,
        "position": offset_position(sensor["east"], sensor["north"]),
    }


def send_heartbeats(timestamp: str, uptime_seconds: int) -> None:
    for sensor in SENSORS:
        sensor_id = sensor["id"]
        HEARTBEAT_SEQUENCES[sensor_id] += 1
        payload = {
            "protocol_version": "rdds/1.0",
            "message_type": "heartbeat",
            "sensor": sensor_context(
                sensor,
                HEARTBEAT_SEQUENCES[sensor_id],
                timestamp,
            ),
            "status": {
                "uptime_seconds": uptime_seconds,
                "free_heap_bytes": 196_000,
                "queue_depth": 0,
                "cellular_rssi": -67,
            },
        }
        post("/api/v1/ingest/heartbeat", payload, sensor_id)


def drone_state(
    drone: dict[str, object], elapsed: float
) -> tuple[dict[str, float], float, float]:
    angular_speed = 2.0 * math.pi / drone["period"]
    angle = drone["phase"] + angular_speed * elapsed
    radius = drone["radius"]
    position = offset_position(radius * math.cos(angle), radius * math.sin(angle))
    heading = math.degrees(angle + math.pi / 2.0) % 360.0
    speed = radius * angular_speed
    return position, heading, speed


def send_observations(timestamp: str, elapsed: float) -> int:
    sent = 0
    for drone in DRONES:
        position, heading, speed = drone_state(drone, elapsed)
        pilot_position = offset_position(
            drone["radius"] * 0.25, -drone["radius"] * 0.25
        )

        for sensor in SENSORS:
            sensor_id = sensor["id"]
            sensor_position = offset_position(sensor["east"], sensor["north"])
            range_m = distance_m(sensor_position, position)
            OBSERVATION_SEQUENCES[sensor_id] += 1

            payload = {
                "protocol_version": "rdds/1.0",
                "message_type": "observation",
                "sensor": sensor_context(
                    sensor,
                    OBSERVATION_SEQUENCES[sensor_id],
                    timestamp,
                ),
                "radio": {
                    "transport": "simulator",
                    "channel": 6,
                    "rssi": synthetic_rssi(range_m),
                },
                "drone": {
                    "mac": drone["mac"],
                    "basic_id": drone["basic_id"],
                    "operator_id": drone["operator_id"],
                    "session_id": drone["session_id"],
                    "position": position,
                    "altitude_m": drone["altitude"],
                    "height_agl_m": drone["altitude"],
                    "speed_mps": round(speed, 2),
                    "heading_deg": round(heading, 2),
                    "emergency_status": "none",
                },
                "pilot_position": pilot_position,
                "raw_remote_id": {
                    "source": "synthetic",
                    "rf_received": False,
                },
            }
            if post("/api/v1/ingest/observation", payload, sensor_id):
                sent += 1
    return sent


def main() -> None:
    started = time.monotonic()
    last_heartbeat = 0.0
    print(
        f"RDDS simulator started: {len(SENSORS)} sensors, {len(DRONES)} drones",
        flush=True,
    )

    while True:
        elapsed = time.monotonic() - started
        timestamp = utc_now()

        if elapsed - last_heartbeat >= HEARTBEAT_SECONDS or last_heartbeat == 0.0:
            send_heartbeats(timestamp, round(elapsed))
            last_heartbeat = elapsed

        sent = send_observations(timestamp, elapsed)
        print(f"Sent {sent} synthetic observations at {timestamp}", flush=True)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

import json
import math
import os
import socket
import time


HOST = "0.0.0.0"
PORT = int(os.getenv("RDDS_SKYSPY_EMULATOR_PORT", "7000"))
INTERVAL_SECONDS = max(
    0.1, float(os.getenv("RDDS_SKYSPY_EMULATOR_INTERVAL_SECONDS", "1"))
)
CENTER_LAT = float(os.getenv("RDDS_SKYSPY_EMULATOR_CENTER_LAT", "52.229700"))
CENTER_LON = float(os.getenv("RDDS_SKYSPY_EMULATOR_CENTER_LON", "21.012200"))


def offset_position(east_m: float, north_m: float) -> tuple[float, float]:
    latitude = CENTER_LAT + north_m / 111_320.0
    longitude = CENTER_LON + east_m / (
        111_320.0 * math.cos(math.radians(CENTER_LAT))
    )
    return round(latitude, 6), round(longitude, 6)


def detection(sequence: int) -> dict[str, object]:
    angle = sequence * 0.055
    radius = 430.0
    latitude, longitude = offset_position(
        radius * math.cos(angle), radius * math.sin(angle)
    )
    pilot_latitude, pilot_longitude = offset_position(120.0, -170.0)

    message: dict[str, object] = {
        "format_version": "skyspy/1.1",
        "mac": "02:53:4b:59:00:01",
        "rssi": -48 - sequence % 18,
        "pilot_lat": pilot_latitude,
        "pilot_long": pilot_longitude,
        "basic_id": "SKYSPY-EMULATED-01",
        "operator_id": "SKYSPY-OPERATOR-01",
        "transport": "wifi_nan",
        "channel": 6,
        "band": "2.4GHz",
    }

    # Every twentieth packet emulates an identity/system message without a
    # current drone location, exactly as the enriched firmware serializes it.
    if sequence % 20 != 0:
        message.update(
            {
                "drone_lat": latitude,
                "drone_long": longitude,
                "drone_altitude": 95.5 + sequence % 12,
                "height_agl": 72.5 + sequence % 8,
                "speed": 15.8,
                "heading": round(
                    math.degrees(angle + math.pi / 2) % 360,
                    2,
                ),
            }
        )

    return message


def send_line(connection: socket.socket, value: str | dict[str, object]) -> None:
    text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    connection.sendall(text.encode("utf-8") + b"\n")


def serve_connection(connection: socket.socket, address: tuple[str, int]) -> None:
    print(f"Sky-Spy emulator client connected: {address}", flush=True)
    sequence = 0
    started = time.monotonic()
    try:
        send_line(connection, "Buzzer initialized on GPIO3")
        send_line(connection, "Orange LED initialized on GPIO21 (inverted logic)")
        while True:
            sequence += 1
            if sequence % 15 == 0:
                send_line(connection, {"status": "scanning"})
            if sequence % 23 == 0:
                send_line(connection, "Heartbeat: Drone still in range")
            send_line(connection, detection(sequence))
            if sequence % 30 == 0:
                elapsed = round(time.monotonic() - started)
                print(f"Emulated {sequence} packets in {elapsed}s", flush=True)
            time.sleep(INTERVAL_SECONDS)
    except (BrokenPipeError, ConnectionResetError, OSError) as exc:
        print(f"Sky-Spy emulator client disconnected: {exc}", flush=True)


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)
        print(f"Sky-Spy serial emulator listening on {HOST}:{PORT}", flush=True)
        while True:
            connection, address = server.accept()
            with connection:
                serve_connection(connection, address)


if __name__ == "__main__":
    main()

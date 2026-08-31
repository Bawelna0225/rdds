from __future__ import annotations

import json
import logging
import math
import os
import re
import signal
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

try:
    import serial
except ImportError:  # Allows parser/outbox unit tests without pyserial on the host.
    serial = None


LOG = logging.getLogger("rdds-sensor-agent")
PROTOCOL_VERSION = "rdds/1.0"
AGENT_VERSION = "0.21.0"
OBSERVATION_PATH = "/api/v1/ingest/observation"
HEARTBEAT_PATH = "/api/v1/ingest/heartbeat"
RETRYABLE_HTTP_CODES = {401, 403, 408, 425, 429}
VALID_TRANSPORTS = {"ble", "wifi_nan", "wifi_beacon", "simulator", "unknown"}
DETECTION_KEYS = {
    "mac",
    "drone_lat",
    "pilot_lat",
    "basic_id",
    "remote_id",
    "operator_id",
    "op_id",
}


class ConfigurationError(RuntimeError):
    pass


class OutboxFull(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_url: str
    ingest_token: str
    sensor_id: str
    display_name: str
    source: str
    baud_rate: int
    sensor_position: dict[str, float] | None
    transport: str
    heartbeat_seconds: float
    reconnect_seconds: float
    request_timeout_seconds: float
    replay_messages_per_second: float
    spool_path: Path
    max_queue_messages: int

    @classmethod
    def from_environment(cls) -> Config:
        sensor_id = os.getenv("RDDS_AGENT_SENSOR_ID", "skyspy-sensor-01").strip()
        ingest_token = os.getenv("RDDS_AGENT_SENSOR_TOKEN", "").strip()
        if not ingest_token:
            raise ConfigurationError("RDDS_AGENT_SENSOR_TOKEN is required")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{3,128}", sensor_id):
            raise ConfigurationError("RDDS_AGENT_SENSOR_ID has an invalid format")

        display_name = os.getenv(
            "RDDS_AGENT_DISPLAY_NAME", "Sky-Spy receiver"
        ).strip()
        if not 1 <= len(display_name) <= 160:
            raise ConfigurationError("RDDS_AGENT_DISPLAY_NAME has an invalid length")

        api_url = os.getenv("RDDS_API_URL", "http://api:8000").rstrip("/")
        if not api_url.startswith(("http://", "https://")):
            raise ConfigurationError("RDDS_API_URL must use http:// or https://")
        source = os.getenv("RDDS_SKYSPY_SOURCE", "/dev/ttyACM0").strip()
        if not source:
            raise ConfigurationError("RDDS_SKYSPY_SOURCE cannot be empty")
        baud_rate = int(os.getenv("RDDS_SKYSPY_BAUD_RATE", "115200"))
        if baud_rate <= 0:
            raise ConfigurationError("RDDS_SKYSPY_BAUD_RATE must be positive")

        latitude_raw = os.getenv("RDDS_AGENT_SENSOR_LAT", "").strip()
        longitude_raw = os.getenv("RDDS_AGENT_SENSOR_LON", "").strip()
        if bool(latitude_raw) != bool(longitude_raw):
            raise ConfigurationError(
                "RDDS_AGENT_SENSOR_LAT and RDDS_AGENT_SENSOR_LON must be set together"
            )
        sensor_position = None
        if latitude_raw:
            latitude = float(latitude_raw)
            longitude = float(longitude_raw)
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ConfigurationError("sensor coordinates are outside WGS84 bounds")
            sensor_position = {"latitude": latitude, "longitude": longitude}

        transport = os.getenv("RDDS_AGENT_TRANSPORT", "unknown").strip().lower()
        if transport not in VALID_TRANSPORTS:
            raise ConfigurationError(
                f"RDDS_AGENT_TRANSPORT must be one of {sorted(VALID_TRANSPORTS)}"
            )
        replay_messages_per_second = float(
            os.getenv("RDDS_AGENT_REPLAY_MESSAGES_PER_SECOND", "2")
        )
        if not 0.1 <= replay_messages_per_second <= 100:
            raise ConfigurationError(
                "RDDS_AGENT_REPLAY_MESSAGES_PER_SECOND must be between 0.1 and 100"
            )

        return cls(
            api_url=api_url,
            ingest_token=ingest_token,
            sensor_id=sensor_id,
            display_name=display_name,
            source=source,
            baud_rate=baud_rate,
            sensor_position=sensor_position,
            transport=transport,
            heartbeat_seconds=max(
                2.0, float(os.getenv("RDDS_AGENT_HEARTBEAT_SECONDS", "10"))
            ),
            reconnect_seconds=max(
                0.5, float(os.getenv("RDDS_AGENT_RECONNECT_SECONDS", "3"))
            ),
            request_timeout_seconds=max(
                1.0, float(os.getenv("RDDS_AGENT_REQUEST_TIMEOUT_SECONDS", "5"))
            ),
            replay_messages_per_second=replay_messages_per_second,
            spool_path=Path(
                os.getenv(
                    "RDDS_AGENT_SPOOL_PATH",
                    "/var/lib/rdds-agent/outbox.sqlite3",
                )
            ),
            max_queue_messages=max(
                100, int(os.getenv("RDDS_AGENT_MAX_QUEUE_MESSAGES", "250000"))
            ),
        )


@dataclass(frozen=True)
class QueuedMessage:
    message_id: int
    path: str
    payload_json: str
    attempts: int


class Outbox:
    def __init__(self, path: Path, max_messages: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.max_messages = max_messages
        self.connection = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS dead_letter (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                attempts INTEGER NOT NULL,
                failed_at REAL NOT NULL,
                last_error TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS outbox_next_attempt_idx
                ON outbox (id, next_attempt_at);
            """
        )

    def close(self) -> None:
        self.connection.close()

    def depth(self) -> int:
        row = self.connection.execute("SELECT count(*) AS count FROM outbox").fetchone()
        return int(row["count"])

    def dead_letter_depth(self) -> int:
        row = self.connection.execute(
            "SELECT count(*) AS count FROM dead_letter"
        ).fetchone()
        return int(row["count"])

    def oldest_age_seconds(self, now: float | None = None) -> int | None:
        row = self.connection.execute(
            "SELECT MIN(created_at) AS oldest_created_at FROM outbox"
        ).fetchone()
        if row["oldest_created_at"] is None:
            return None
        current_time = time.time() if now is None else now
        return max(0, round(current_time - float(row["oldest_created_at"])))

    def enqueue(self, path: str, payload: dict[str, Any]) -> int:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT count(*) AS count FROM outbox"
            ).fetchone()
            if int(row["count"]) >= self.max_messages:
                raise OutboxFull(
                    f"outbox limit of {self.max_messages} messages was reached"
                )
            cursor = self.connection.execute(
                """
                INSERT INTO outbox (path, payload_json, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    path,
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                    time.time(),
                ),
            )
            self.connection.execute("COMMIT")
            return int(cursor.lastrowid)
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def replace_pending(self, path: str, payload: dict[str, Any]) -> int:
        """Keep only the newest state snapshot for a coalescible endpoint."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("DELETE FROM outbox WHERE path = ?", (path,))
            row = self.connection.execute(
                "SELECT count(*) AS count FROM outbox"
            ).fetchone()
            if int(row["count"]) >= self.max_messages:
                raise OutboxFull(
                    f"outbox limit of {self.max_messages} messages was reached"
                )
            cursor = self.connection.execute(
                """
                INSERT INTO outbox (path, payload_json, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    path,
                    json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                    time.time(),
                ),
            )
            self.connection.execute("COMMIT")
            return int(cursor.lastrowid)
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def oldest_due(self, now: float | None = None) -> QueuedMessage | None:
        now = time.time() if now is None else now
        row = self.connection.execute(
            """
            SELECT id, path, payload_json, attempts, next_attempt_at
            FROM outbox
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if row is None or float(row["next_attempt_at"]) > now:
            return None
        return QueuedMessage(
            message_id=int(row["id"]),
            path=str(row["path"]),
            payload_json=str(row["payload_json"]),
            attempts=int(row["attempts"]),
        )

    def get(self, message_id: int) -> QueuedMessage | None:
        row = self.connection.execute(
            """
            SELECT id, path, payload_json, attempts
            FROM outbox
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        if row is None:
            return None
        return QueuedMessage(
            message_id=int(row["id"]),
            path=str(row["path"]),
            payload_json=str(row["payload_json"]),
            attempts=int(row["attempts"]),
        )

    def acknowledge(self, message_id: int) -> None:
        self.connection.execute("DELETE FROM outbox WHERE id = ?", (message_id,))

    def retry(self, message_id: int, error: str, delay_seconds: float) -> None:
        self.connection.execute(
            """
            UPDATE outbox
            SET attempts = attempts + 1,
                next_attempt_at = ?,
                last_error = ?
            WHERE id = ?
            """,
            (time.time() + delay_seconds, error[:1000], message_id),
        )

    def move_to_dead_letter(self, message_id: int, error: str) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO dead_letter (
                    id, path, payload_json, created_at, attempts, failed_at, last_error
                )
                SELECT id, path, payload_json, created_at, attempts + 1, ?, ?
                FROM outbox
                WHERE id = ?
                """,
                (time.time(), error[:1000], message_id),
            )
            self.connection.execute("DELETE FROM outbox WHERE id = ?", (message_id,))
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip().strip("\x00")
    return stripped or None


def valid_position(latitude_value: Any, longitude_value: Any) -> dict[str, float] | None:
    latitude = finite_number(latitude_value)
    longitude = finite_number(longitude_value)
    if latitude is None or longitude is None:
        return None
    # Sky-Spy zero-fills fields that were not present in a Remote ID packet.
    if latitude == 0.0 or longitude == 0.0:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return {"latitude": latitude, "longitude": longitude}


def bounded_integer(value: Any, minimum: int, maximum: int) -> int | None:
    number = finite_number(value)
    if number is None:
        return None
    converted = round(number)
    if not minimum <= converted <= maximum:
        return None
    return converted


def normalize_detection(raw: dict[str, Any], transport: str) -> dict[str, Any] | None:
    if not any(key in raw for key in DETECTION_KEYS):
        return None

    drone_position = valid_position(raw.get("drone_lat"), raw.get("drone_long"))
    pilot_position = valid_position(raw.get("pilot_lat"), raw.get("pilot_long"))
    mac = optional_text(raw.get("mac"))
    basic_id = optional_text(raw.get("basic_id")) or optional_text(raw.get("remote_id"))
    operator_id = optional_text(raw.get("operator_id")) or optional_text(raw.get("op_id"))

    drone: dict[str, Any] = {}
    if mac:
        normalized_mac = mac.lower()
        if len(normalized_mac) == 17 and all(
            len(part) == 2 and all(character in "0123456789abcdef" for character in part)
            for part in normalized_mac.split(":")
        ):
            drone["mac"] = normalized_mac
    if basic_id:
        drone["basic_id"] = basic_id[:255]
    if operator_id:
        drone["operator_id"] = operator_id[:255]
    if drone_position:
        drone["position"] = drone_position

    if not any(key in drone for key in ("mac", "basic_id", "operator_id", "position")):
        return None

    if drone_position:
        altitude = finite_number(raw.get("drone_altitude"))
        if altitude is not None:
            drone["altitude_m"] = altitude
        height = finite_number(raw.get("height_agl_m", raw.get("height_agl")))
        if height is not None:
            drone["height_agl_m"] = height

    speed = finite_number(raw.get("speed_mps", raw.get("speed")))
    if speed is not None and speed >= 0:
        drone["speed_mps"] = speed
    heading = finite_number(raw.get("heading_deg", raw.get("heading")))
    if heading is not None and 0 <= heading < 360:
        drone["heading_deg"] = heading
    emergency_status = optional_text(raw.get("emergency_status"))
    if emergency_status:
        drone["emergency_status"] = emergency_status[:128]

    source_transport = optional_text(raw.get("transport"))
    radio_transport = (
        source_transport.lower()
        if source_transport and source_transport.lower() in VALID_TRANSPORTS
        else transport
    )
    radio: dict[str, Any] = {"transport": radio_transport}
    rssi = bounded_integer(raw.get("rssi"), -150, 20)
    if rssi is not None:
        radio["rssi"] = rssi
    channel = bounded_integer(raw.get("channel"), 0, 255)
    if channel is not None:
        radio["channel"] = channel

    return {
        "radio": radio,
        "drone": drone,
        "pilot_position": pilot_position,
        "raw_remote_id": raw,
    }


def parse_skyspy_line(line: bytes | str, transport: str = "unknown") -> dict[str, Any] | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="ignore")
    line = line.strip()
    opening_brace = line.find("{")
    if opening_brace < 0:
        return None
    try:
        raw = json.loads(line[opening_brace:])
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    if "heartbeat" in raw:
        return None
    return normalize_detection(raw, transport)


def source_kind(source: str) -> str:
    if source.startswith("socket://"):
        return "socket"
    if source.startswith("loop://"):
        return "loopback"
    if source.startswith("/"):
        return "serial"
    return "unknown"


def delivery_error_reason(error: str) -> str:
    if error.startswith("HTTP 401"):
        return "authentication_failed"
    if error.startswith("HTTP 403"):
        return "authorization_failed"
    if error.startswith("HTTP 4"):
        return "request_rejected"
    if error.startswith("HTTP 5"):
        return "server_error"
    if "timed out" in error.lower() or "timeout" in error.lower():
        return "timeout"
    if error.startswith("connection error"):
        return "connection_failed"
    return "delivery_failed"


class SensorAgent:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.outbox = Outbox(config.spool_path, config.max_queue_messages)
        self.boot_id = str(uuid4())
        self.sequence = 0
        self.started_monotonic = time.monotonic()
        self.last_heartbeat_monotonic = 0.0
        self.next_replay_monotonic = 0.0
        self.source_connection: Any = None
        self.source_connected_at: str | None = None
        self.next_source_connect_monotonic = 0.0
        self.last_source_message_at: str | None = None
        self.last_source_error_at: str | None = None
        self.last_source_error_reason: str | None = None
        self.running = True
        self.received_lines = 0
        self.parsed_detections = 0
        self.enqueued_observations = 0
        self.ignored_lines = 0
        self.source_connections = 0
        self.delivery_successes = 0
        self.delivery_retries = 0
        self.delivery_discards = 0
        self.delivery_dead_letters = 0
        self.last_delivery_success_at: str | None = None
        self.last_delivery_error_at: str | None = None
        self.last_delivery_error_reason: str | None = None

    def stop(self, signum: int | None = None, _frame: Any = None) -> None:
        if signum is not None:
            LOG.info("received signal %s; stopping", signum)
        self.running = False

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence

    def sensor_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {
            "sensor_id": self.config.sensor_id,
            "display_name": self.config.display_name,
            "boot_id": self.boot_id,
            "sequence": self.next_sequence(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if self.config.sensor_position is not None:
            context["position"] = self.config.sensor_position
        return context

    def enqueue_heartbeat(self) -> int:
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "message_type": "heartbeat",
            "sensor": self.sensor_context(),
            "status": {
                "uptime_seconds": round(time.monotonic() - self.started_monotonic),
                "queue_depth": self.outbox.depth(),
                "queue_capacity": self.config.max_queue_messages,
                "queue_oldest_age_seconds": self.outbox.oldest_age_seconds(),
                "dead_letter_depth": self.outbox.dead_letter_depth(),
                "agent_version": AGENT_VERSION,
                "source_kind": source_kind(self.config.source),
                "source_connected": self.source_connection is not None,
                "source_connected_at": self.source_connected_at,
                "source_last_message_at": self.last_source_message_at,
                "source_last_error_at": self.last_source_error_at,
                "source_last_error_reason": self.last_source_error_reason,
                "input_lines_total": self.received_lines,
                "parsed_detections_total": self.parsed_detections,
                "enqueued_observations_total": self.enqueued_observations,
                "ignored_lines_total": self.ignored_lines,
                "source_connections_total": self.source_connections,
                "delivery_success_total": self.delivery_successes,
                "delivery_retry_total": self.delivery_retries,
                "delivery_discard_total": self.delivery_discards,
                "delivery_dead_letter_total": self.delivery_dead_letters,
                "last_delivery_success_at": self.last_delivery_success_at,
                "last_delivery_error_at": self.last_delivery_error_at,
                "last_delivery_error_reason": self.last_delivery_error_reason,
            },
        }
        return self.outbox.replace_pending(HEARTBEAT_PATH, payload)

    def enqueue_detection(self, detection: dict[str, Any]) -> int:
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "message_type": "observation",
            "sensor": self.sensor_context(),
            **detection,
        }
        return self.outbox.enqueue(OBSERVATION_PATH, payload)

    def connect_source(self) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        now = time.monotonic()
        if now < self.next_source_connect_monotonic:
            return
        try:
            self.source_connection = serial.serial_for_url(
                self.config.source,
                baudrate=self.config.baud_rate,
                timeout=1,
            )
            self.source_connections += 1
            self.source_connected_at = datetime.now(timezone.utc).isoformat()
            LOG.debug(
                "connected to Sky-Spy source %s at %d baud",
                self.config.source,
                self.config.baud_rate,
            )
        except (serial.SerialException, OSError) as exc:
            LOG.warning("cannot open Sky-Spy source %s: %s", self.config.source, exc)
            self.source_connection = None
            self.source_connected_at = None
            self.last_source_error_at = datetime.now(timezone.utc).isoformat()
            self.last_source_error_reason = "open_failed"
            self.next_source_connect_monotonic = now + self.config.reconnect_seconds

    def disconnect_source(self) -> None:
        if self.source_connection is not None:
            try:
                self.source_connection.close()
            except OSError:
                LOG.debug("error while closing Sky-Spy source", exc_info=True)
        self.source_connection = None
        self.source_connected_at = None
        self.next_source_connect_monotonic = (
            time.monotonic() + self.config.reconnect_seconds
        )

    def read_source_once(self) -> None:
        if self.source_connection is None:
            self.connect_source()
            if self.source_connection is None:
                time.sleep(0.2)
                return
        try:
            line = self.source_connection.readline()
        except (serial.SerialException, OSError) as exc:
            LOG.warning("Sky-Spy source disconnected: %s", exc)
            self.last_source_error_at = datetime.now(timezone.utc).isoformat()
            self.last_source_error_reason = "read_failed"
            self.disconnect_source()
            return
        if not line:
            return
        self.received_lines += 1
        self.last_source_message_at = datetime.now(timezone.utc).isoformat()
        detection = parse_skyspy_line(line, self.config.transport)
        if detection is None:
            self.ignored_lines += 1
            return
        self.parsed_detections += 1
        try:
            message_id = self.enqueue_detection(detection)
            self.enqueued_observations += 1
            self.deliver_message_by_id(message_id)
        except OutboxFull as exc:
            LOG.error("detection rejected because %s", exc)

    def post_message(self, message: QueuedMessage) -> tuple[str, str]:
        request = Request(
            f"{self.config.api_url}{message.path}",
            data=message.payload_json.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-RDDS-Ingest-Token": self.config.ingest_token,
            },
        )
        try:
            with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                response.read()
            return "accepted", ""
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            error = f"HTTP {exc.code}: {detail}"
            if exc.code == 403:
                try:
                    response_payload = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    response_payload = None
                if (
                    isinstance(response_payload, dict)
                    and response_payload.get("detail") == "sensor is disabled"
                ):
                    return "discard", error
            if exc.code in RETRYABLE_HTTP_CODES or exc.code >= 500:
                return "retry", error
            return "dead_letter", error
        except (URLError, TimeoutError, OSError) as exc:
            return "retry", f"connection error: {exc}"

    def record_delivery_outcome(self, outcome: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if outcome == "accepted":
            self.delivery_successes += 1
            self.last_delivery_success_at = now
            return
        if outcome == "retry":
            self.delivery_retries += 1
        elif outcome == "discard":
            self.delivery_discards += 1
        elif outcome == "dead_letter":
            self.delivery_dead_letters += 1
        if error:
            self.last_delivery_error_at = now
            self.last_delivery_error_reason = (
                "sensor_disabled"
                if outcome == "discard"
                else delivery_error_reason(error)
            )

    def flush_outbox(self) -> int:
        now = time.monotonic()
        if now < self.next_replay_monotonic:
            return 0

        message = self.outbox.oldest_due()
        if message is None:
            return 0

        outcome, error = self.post_message(message)
        self.record_delivery_outcome(outcome, error)
        self.next_replay_monotonic = time.monotonic() + (
            1.0 / self.config.replay_messages_per_second
        )
        if outcome == "accepted":
            self.outbox.acknowledge(message.message_id)
            return 1
        if outcome == "discard":
            LOG.debug(
                "message %d discarded because sensor is administratively disabled",
                message.message_id,
            )
            self.outbox.acknowledge(message.message_id)
            return 0
        if outcome == "dead_letter":
            LOG.error(
                "message %d moved to dead letter: %s",
                message.message_id,
                error,
            )
            self.outbox.move_to_dead_letter(message.message_id, error)
            return 0

        attempts = message.attempts + 1
        if error.startswith(("HTTP 401", "HTTP 403")):
            delay = 60.0
        else:
            delay = min(60.0, 2.0 ** min(attempts, 6))
        self.outbox.retry(message.message_id, error, delay)
        LOG.warning(
            "delivery paused for %.0fs after attempt %d: %s",
            delay,
            attempts,
            error,
        )
        return 0

    def deliver_message_by_id(self, message_id: int) -> bool:
        """Try a newly queued message before draining the historical FIFO."""
        message = self.outbox.get(message_id)
        if message is None:
            return False

        outcome, error = self.post_message(message)
        self.record_delivery_outcome(outcome, error)
        if outcome == "accepted":
            self.outbox.acknowledge(message.message_id)
            return True
        if outcome == "discard":
            LOG.info(
                "current message %d discarded because sensor is administratively disabled",
                message.message_id,
            )
            self.outbox.acknowledge(message.message_id)
            return False
        if outcome == "dead_letter":
            LOG.error(
                "message %d moved to dead letter: %s",
                message.message_id,
                error,
            )
            self.outbox.move_to_dead_letter(message.message_id, error)
            return False

        attempts = message.attempts + 1
        delay = (
            60.0
            if error.startswith(("HTTP 401", "HTTP 403"))
            else min(60.0, 2.0 ** min(attempts, 6))
        )
        self.outbox.retry(message.message_id, error, delay)
        LOG.warning(
            "current message delivery deferred for %.0fs after attempt %d: %s",
            delay,
            attempts,
            error,
        )
        return False

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        LOG.info(
            "RDDS sensor agent started: sensor=%s source=%s queued=%d dead_letter=%d",
            self.config.sensor_id,
            self.config.source,
            self.outbox.depth(),
            self.outbox.dead_letter_depth(),
        )
        try:
            while self.running:
                now = time.monotonic()
                self.read_source_once()
                if (
                    self.last_heartbeat_monotonic == 0.0
                    or now - self.last_heartbeat_monotonic
                    >= self.config.heartbeat_seconds
                ):
                    try:
                        message_id = self.enqueue_heartbeat()
                        self.last_heartbeat_monotonic = now
                        self.deliver_message_by_id(message_id)
                    except OutboxFull as exc:
                        LOG.error("heartbeat rejected because %s", exc)

                self.flush_outbox()
        finally:
            self.disconnect_source()
            LOG.info(
                "agent stopped: lines=%d detections=%d ignored=%d queued=%d dead_letter=%d",
                self.received_lines,
                self.parsed_detections,
                self.ignored_lines,
                self.outbox.depth(),
                self.outbox.dead_letter_depth(),
            )
            self.outbox.close()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("RDDS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = Config.from_environment()
    except (ConfigurationError, ValueError) as exc:
        LOG.error("invalid configuration: %s", exc)
        raise SystemExit(2) from exc
    SensorAgent(config).run()


if __name__ == "__main__":
    main()

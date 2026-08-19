from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import settings
from app.models import HeartbeatEnvelope, ObservationEnvelope, SensorContext


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        connect_timeout=3,
        application_name="rdds-api",
        autocommit=False,
        row_factory=dict_row,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _coordinates(position: Any) -> tuple[float | None, float | None]:
    if position is None:
        return None, None
    return position.longitude, position.latitude


def _upsert_sensor(cursor: psycopg.Cursor, sensor: SensorContext) -> UUID:
    longitude, latitude = _coordinates(sensor.position)
    cursor.execute(
        """
        INSERT INTO sensors (
            sensor_key,
            display_name,
            status,
            fixed_position,
            last_seen_at
        )
        VALUES (
            %(sensor_key)s,
            %(display_name)s,
            'online',
            CASE
                WHEN CAST(%(longitude)s AS DOUBLE PRECISION) IS NULL
                  OR CAST(%(latitude)s AS DOUBLE PRECISION) IS NULL
                THEN NULL
                ELSE ST_SetSRID(
                    ST_MakePoint(
                        CAST(%(longitude)s AS DOUBLE PRECISION),
                        CAST(%(latitude)s AS DOUBLE PRECISION)
                    ),
                    4326
                )::geography
            END,
            NOW()
        )
        ON CONFLICT (sensor_key) DO UPDATE SET
            display_name = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM sensor_credentials AS credential
                    WHERE credential.sensor_id = sensors.id
                      AND credential.revoked_at IS NULL
                ) THEN sensors.display_name
                ELSE COALESCE(
                    %(provided_display_name)s,
                    sensors.display_name
                )
            END,
            status = CASE
                WHEN sensors.status = 'disabled' THEN 'disabled'
                ELSE 'online'
            END,
            fixed_position = COALESCE(sensors.fixed_position, EXCLUDED.fixed_position),
            last_seen_at = NOW(),
            updated_at = NOW()
        RETURNING id
        """,
        {
            "sensor_key": sensor.sensor_id,
            "display_name": sensor.display_name or sensor.sensor_id,
            "provided_display_name": sensor.display_name,
            "longitude": longitude,
            "latitude": latitude,
        },
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Sensor upsert returned no row")
    return row["id"]


def insert_heartbeat(
    payload: HeartbeatEnvelope,
    raw_message: dict[str, Any],
) -> tuple[UUID, int | None]:
    with connection() as conn, conn.cursor() as cursor:
        sensor_uuid = _upsert_sensor(cursor, payload.sensor)
        cursor.execute(
            """
            INSERT INTO sensor_heartbeats (
                sensor_id,
                sensor_boot_id,
                sequence,
                measured_at,
                uptime_seconds,
                free_heap_bytes,
                queue_depth,
                cellular_rssi,
                raw_message
            )
            VALUES (
                %(sensor_id)s,
                %(boot_id)s,
                %(sequence)s,
                %(measured_at)s,
                %(uptime_seconds)s,
                %(free_heap_bytes)s,
                %(queue_depth)s,
                %(cellular_rssi)s,
                %(raw_message)s
            )
            ON CONFLICT (sensor_id, sensor_boot_id, sequence) DO NOTHING
            RETURNING id
            """,
            {
                "sensor_id": sensor_uuid,
                "boot_id": payload.sensor.boot_id,
                "sequence": payload.sensor.sequence,
                "measured_at": payload.sensor.timestamp,
                "uptime_seconds": payload.status.uptime_seconds,
                "free_heap_bytes": payload.status.free_heap_bytes,
                "queue_depth": payload.status.queue_depth,
                "cellular_rssi": payload.status.cellular_rssi,
                "raw_message": Jsonb(raw_message),
            },
        )
        row = cursor.fetchone()
    return sensor_uuid, None if row is None else int(row["id"])


def insert_observation(
    payload: ObservationEnvelope,
    raw_message: dict[str, Any],
) -> tuple[UUID, int | None]:
    drone_longitude, drone_latitude = _coordinates(payload.drone.position)
    pilot_longitude, pilot_latitude = _coordinates(payload.pilot_position)

    with connection() as conn, conn.cursor() as cursor:
        sensor_uuid = _upsert_sensor(cursor, payload.sensor)
        cursor.execute(
            """
            INSERT INTO observations (
                sensor_id,
                sensor_boot_id,
                sequence,
                protocol_version,
                message_time,
                transport,
                channel,
                rssi,
                drone_mac,
                basic_id,
                operator_id,
                session_id,
                drone_position,
                pilot_position,
                altitude_m,
                height_agl_m,
                speed_mps,
                heading_deg,
                emergency_status,
                raw_message
            )
            VALUES (
                %(sensor_id)s,
                %(boot_id)s,
                %(sequence)s,
                %(protocol_version)s,
                %(message_time)s,
                %(transport)s,
                %(channel)s,
                %(rssi)s,
                %(drone_mac)s,
                %(basic_id)s,
                %(operator_id)s,
                %(session_id)s,
                CASE
                    WHEN CAST(%(drone_longitude)s AS DOUBLE PRECISION) IS NULL
                      OR CAST(%(drone_latitude)s AS DOUBLE PRECISION) IS NULL
                    THEN NULL
                    ELSE ST_SetSRID(
                        ST_MakePoint(
                            CAST(%(drone_longitude)s AS DOUBLE PRECISION),
                            CAST(%(drone_latitude)s AS DOUBLE PRECISION)
                        ),
                        4326
                    )::geography
                END,
                CASE
                    WHEN CAST(%(pilot_longitude)s AS DOUBLE PRECISION) IS NULL
                      OR CAST(%(pilot_latitude)s AS DOUBLE PRECISION) IS NULL
                    THEN NULL
                    ELSE ST_SetSRID(
                        ST_MakePoint(
                            CAST(%(pilot_longitude)s AS DOUBLE PRECISION),
                            CAST(%(pilot_latitude)s AS DOUBLE PRECISION)
                        ),
                        4326
                    )::geography
                END,
                %(altitude_m)s,
                %(height_agl_m)s,
                %(speed_mps)s,
                %(heading_deg)s,
                %(emergency_status)s,
                %(raw_message)s
            )
            ON CONFLICT (sensor_id, sensor_boot_id, sequence) DO NOTHING
            RETURNING id
            """,
            {
                "sensor_id": sensor_uuid,
                "boot_id": payload.sensor.boot_id,
                "sequence": payload.sensor.sequence,
                "protocol_version": payload.protocol_version,
                "message_time": payload.sensor.timestamp,
                "transport": payload.radio.transport,
                "channel": payload.radio.channel,
                "rssi": payload.radio.rssi,
                "drone_mac": payload.drone.mac,
                "basic_id": payload.drone.basic_id,
                "operator_id": payload.drone.operator_id,
                "session_id": payload.drone.session_id,
                "drone_longitude": drone_longitude,
                "drone_latitude": drone_latitude,
                "pilot_longitude": pilot_longitude,
                "pilot_latitude": pilot_latitude,
                "altitude_m": payload.drone.altitude_m,
                "height_agl_m": payload.drone.height_agl_m,
                "speed_mps": payload.drone.speed_mps,
                "heading_deg": payload.drone.heading_deg,
                "emergency_status": payload.drone.emergency_status,
                "raw_message": Jsonb(raw_message),
            },
        )
        row = cursor.fetchone()
    return sensor_uuid, None if row is None else int(row["id"])


def mark_stale_sensors() -> int:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE sensors
            SET status = 'offline', updated_at = NOW()
            WHERE status = 'online'
              AND last_seen_at < NOW() - (%s * INTERVAL '1 second')
            """,
            (settings.sensor_offline_after_seconds,),
        )
        return cursor.rowcount


def readiness() -> dict[str, str]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_database() AS database,
                current_user AS database_user,
                postgis_version() AS postgis_version
            """
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Database readiness query returned no row")
    return dict(row)


def system_summary() -> dict[str, int]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM sensors) AS sensors,
                (SELECT COUNT(*) FROM sensor_heartbeats) AS heartbeats,
                (SELECT COUNT(*) FROM observations) AS observations,
                (SELECT COUNT(*) FROM tracks) AS tracks,
                (SELECT COUNT(*) FROM protected_zones) AS zones,
                (SELECT COUNT(*) FROM audit_events) AS audit_events,
                (
                    SELECT COUNT(*)
                    FROM sensor_credentials
                    WHERE revoked_at IS NULL
                ) AS individual_sensor_credentials,
                (
                    SELECT COUNT(*)
                    FROM intrusion_alerts
                    WHERE state IN ('active', 'acknowledged')
                ) AS open_alerts
            """
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("System summary query returned no row")
    return {key: int(value) for key, value in row.items()}

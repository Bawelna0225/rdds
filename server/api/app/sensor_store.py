import hashlib
import secrets
from typing import Any, Literal
from uuid import UUID

from app.config import settings
from app.database import connection
from app.models import SensorMaintenance, SensorRegistration, SensorUpdate

LegacySensorAccess = Literal["allowed", "disabled", "individual_required"]

SENSOR_COLUMNS = """
    sensor.id,
    sensor.sensor_key AS sensor_id,
    sensor.display_name,
    sensor.status,
    ST_Y(sensor.fixed_position::geometry) AS latitude,
    ST_X(sensor.fixed_position::geometry) AS longitude,
    sensor.firmware_version,
    sensor.last_seen_at,
    sensor.health_reason,
    sensor.health_changed_at,
    sensor.health_issue_started_at,
    sensor.last_heartbeat_received_at AS last_heartbeat_at,
    sensor.last_heartbeat_reported_at,
    sensor.last_observation_received_at,
    sensor.agent_version,
    sensor.source_connected,
    sensor.source_last_message_at,
    sensor.reported_queue_depth AS queue_depth,
    sensor.reported_dead_letter_depth AS dead_letter_depth,
    sensor.maintenance_reason,
    sensor.maintenance_started_at,
    sensor.maintenance_started_by,
    sensor.maintenance_until,
    sensor.heartbeat_count,
    sensor.observation_count,
    sensor.created_by,
    sensor.updated_by,
    sensor.created_at,
    sensor.updated_at,
    CASE
        WHEN credential.id IS NULL THEN 'legacy'
        ELSE 'individual'
    END AS credential_mode,
    credential.token_prefix,
    credential.created_at AS token_created_at,
    credential.last_used_at AS token_last_used_at,
    heartbeat.uptime_seconds,
    heartbeat.free_heap_bytes,
    heartbeat.cellular_rssi,
    heartbeat.sensor_boot_id AS agent_boot_id,
    heartbeat.source_kind,
    heartbeat.source_connected_at,
    heartbeat.source_last_error_at,
    heartbeat.source_last_error_reason,
    heartbeat.input_lines_total,
    heartbeat.parsed_detections_total,
    heartbeat.enqueued_observations_total,
    heartbeat.ignored_lines_total,
    heartbeat.source_connections_total,
    heartbeat.queue_capacity,
    heartbeat.queue_oldest_age_seconds,
    heartbeat.delivery_success_total,
    heartbeat.delivery_retry_total,
    heartbeat.delivery_discard_total,
    heartbeat.delivery_dead_letter_total,
    heartbeat.last_delivery_success_at,
    heartbeat.last_delivery_error_at,
    heartbeat.last_delivery_error_reason,
    heartbeat.clock_offset_seconds
"""

SENSOR_JOINS = """
    LEFT JOIN LATERAL (
        SELECT
            active_credential.id,
            active_credential.token_prefix,
            active_credential.created_at,
            active_credential.last_used_at
        FROM sensor_credentials AS active_credential
        WHERE active_credential.sensor_id = sensor.id
          AND active_credential.revoked_at IS NULL
        ORDER BY active_credential.created_at DESC
        LIMIT 1
    ) AS credential ON TRUE
    LEFT JOIN LATERAL (
        SELECT
            latest_heartbeat.uptime_seconds,
            latest_heartbeat.free_heap_bytes,
            latest_heartbeat.cellular_rssi,
            latest_heartbeat.sensor_boot_id,
            latest_heartbeat.source_kind,
            latest_heartbeat.source_connected_at,
            latest_heartbeat.source_last_error_at,
            latest_heartbeat.source_last_error_reason,
            latest_heartbeat.input_lines_total,
            latest_heartbeat.parsed_detections_total,
            latest_heartbeat.enqueued_observations_total,
            latest_heartbeat.ignored_lines_total,
            latest_heartbeat.source_connections_total,
            latest_heartbeat.queue_capacity,
            latest_heartbeat.queue_oldest_age_seconds,
            latest_heartbeat.delivery_success_total,
            latest_heartbeat.delivery_retry_total,
            latest_heartbeat.delivery_discard_total,
            latest_heartbeat.delivery_dead_letter_total,
            latest_heartbeat.last_delivery_success_at,
            latest_heartbeat.last_delivery_error_at,
            latest_heartbeat.last_delivery_error_reason,
            EXTRACT(
                EPOCH FROM (
                    latest_heartbeat.received_at - latest_heartbeat.measured_at
                )
            )::DOUBLE PRECISION AS clock_offset_seconds
        FROM sensor_heartbeats AS latest_heartbeat
        WHERE latest_heartbeat.sensor_id = sensor.id
        ORDER BY latest_heartbeat.measured_at DESC, latest_heartbeat.received_at DESC
        LIMIT 1
    ) AS heartbeat ON TRUE
"""


def _new_token() -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, token_hash, token[:12]


def _read_sensor(cursor: Any, sensor_id: UUID) -> dict[str, Any] | None:
    cursor.execute(
        f"""
        SELECT {SENSOR_COLUMNS}
        FROM sensors AS sensor
        {SENSOR_JOINS}
        WHERE sensor.id = %s
        """,
        (sensor_id,),
    )
    row = cursor.fetchone()
    return None if row is None else dict(row)


def list_sensors() -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {SENSOR_COLUMNS}
            FROM sensors AS sensor
            {SENSOR_JOINS}
            WHERE sensor.deleted_at IS NULL
            ORDER BY sensor.sensor_key
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def register_sensor(
    payload: SensorRegistration,
    actor: str,
) -> tuple[dict[str, Any], str]:
    token, token_hash, token_prefix = _new_token()
    longitude = None if payload.position is None else payload.position.longitude
    latitude = None if payload.position is None else payload.position.latitude

    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO sensors (
                sensor_key,
                display_name,
                status,
                fixed_position,
                created_by,
                updated_by
            )
            VALUES (
                %(sensor_key)s,
                %(display_name)s,
                'provisioning',
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
                %(actor)s,
                %(actor)s
            )
            RETURNING id
            """,
            {
                "sensor_key": payload.sensor_key,
                "display_name": payload.display_name,
                "longitude": longitude,
                "latitude": latitude,
                "actor": actor,
            },
        )
        created = cursor.fetchone()
        if created is None:
            raise RuntimeError("Sensor registration returned no row")

        cursor.execute(
            """
            INSERT INTO sensor_credentials (
                sensor_id,
                token_hash,
                token_prefix,
                created_by
            )
            VALUES (%s, %s, %s, %s)
            """,
            (created["id"], token_hash, token_prefix, actor),
        )
        sensor = _read_sensor(cursor, created["id"])
        if sensor is None:
            raise RuntimeError("Registered sensor could not be read")

    return sensor, token


def set_sensor_enabled(
    sensor_id: UUID,
    enabled: bool,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE sensors
            SET
                status = CASE
                    WHEN %(enabled)s THEN
                        CASE
                            WHEN last_heartbeat_received_at IS NULL THEN 'provisioning'
                            ELSE 'offline'
                        END
                    ELSE 'disabled'
                END,
                health_reason = CASE
                    WHEN %(enabled)s THEN
                        CASE
                            WHEN last_heartbeat_received_at IS NULL
                            THEN 'awaiting_heartbeat'
                            ELSE 'heartbeat_timeout'
                        END
                    ELSE 'disabled'
                END,
                health_changed_at = NOW(),
                health_issue_started_at = CASE
                    WHEN %(enabled)s AND last_heartbeat_received_at IS NOT NULL
                    THEN NOW()
                    ELSE NULL
                END,
                maintenance_reason = NULL,
                maintenance_started_at = NULL,
                maintenance_started_by = NULL,
                maintenance_until = NULL,
                updated_by = %(actor)s,
                updated_at = NOW()
            WHERE id = %(sensor_id)s
              AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "enabled": enabled,
                "actor": actor,
                "sensor_id": sensor_id,
            },
        )
        updated = cursor.fetchone()
        if updated is None:
            return None
        return _read_sensor(cursor, updated["id"])


def set_sensor_maintenance(
    sensor_id: UUID,
    payload: SensorMaintenance,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE sensors
            SET
                status = CASE
                    WHEN %(enabled)s THEN 'maintenance'
                    WHEN last_heartbeat_received_at IS NULL
                      OR last_heartbeat_received_at <
                         NOW() - (%(offline_after)s * INTERVAL '1 second')
                    THEN 'offline'
                    WHEN source_connected IS FALSE THEN 'degraded'
                    WHEN source_connected IS TRUE
                     AND source_last_message_at IS NOT NULL
                     AND last_heartbeat_reported_at - source_last_message_at >=
                         (%(source_silent_after)s * INTERVAL '1 second')
                    THEN 'degraded'
                    WHEN COALESCE(reported_dead_letter_depth, 0) > 0
                    THEN 'degraded'
                    WHEN COALESCE(reported_queue_depth, 0) >= %(queue_warning)s
                    THEN 'degraded'
                    ELSE 'online'
                END,
                health_reason = CASE
                    WHEN %(enabled)s THEN 'maintenance'
                    WHEN last_heartbeat_received_at IS NULL
                      OR last_heartbeat_received_at <
                         NOW() - (%(offline_after)s * INTERVAL '1 second')
                    THEN 'heartbeat_timeout'
                    WHEN source_connected IS FALSE THEN 'source_unavailable'
                    WHEN source_connected IS TRUE
                     AND source_last_message_at IS NOT NULL
                     AND last_heartbeat_reported_at - source_last_message_at >=
                         (%(source_silent_after)s * INTERVAL '1 second')
                    THEN 'source_silent'
                    WHEN COALESCE(reported_dead_letter_depth, 0) > 0
                    THEN 'dead_letter'
                    WHEN COALESCE(reported_queue_depth, 0) >= %(queue_warning)s
                    THEN 'queue_backlog'
                    ELSE 'healthy'
                END,
                health_changed_at = NOW(),
                health_issue_started_at = CASE
                    WHEN %(enabled)s THEN NULL
                    WHEN last_heartbeat_received_at IS NULL
                      OR last_heartbeat_received_at <
                         NOW() - (%(offline_after)s * INTERVAL '1 second')
                      OR source_connected IS FALSE
                      OR (
                          source_connected IS TRUE
                          AND source_last_message_at IS NOT NULL
                          AND last_heartbeat_reported_at - source_last_message_at >=
                              (%(source_silent_after)s * INTERVAL '1 second')
                      )
                      OR COALESCE(reported_dead_letter_depth, 0) > 0
                      OR COALESCE(reported_queue_depth, 0) >= %(queue_warning)s
                    THEN NOW()
                    ELSE NULL
                END,
                maintenance_reason = CASE
                    WHEN %(enabled)s THEN %(reason)s
                    ELSE NULL
                END,
                maintenance_started_at = CASE
                    WHEN %(enabled)s THEN NOW()
                    ELSE NULL
                END,
                maintenance_started_by = CASE
                    WHEN %(enabled)s THEN %(actor)s
                    ELSE NULL
                END,
                maintenance_until = CASE
                    WHEN %(enabled)s THEN %(until)s
                    ELSE NULL
                END,
                updated_by = %(actor)s,
                updated_at = NOW()
            WHERE id = %(sensor_id)s
              AND deleted_at IS NULL
              AND status <> 'disabled'
              AND (%(enabled)s OR status = 'maintenance')
            RETURNING id
            """,
            {
                "sensor_id": sensor_id,
                "enabled": payload.enabled,
                "reason": None if payload.reason is None else payload.reason.strip(),
                "until": payload.until,
                "actor": actor,
                "offline_after": settings.sensor_offline_after_seconds,
                "queue_warning": settings.sensor_queue_warning_messages,
                "source_silent_after": settings.sensor_source_silent_after_seconds,
            },
        )
        updated = cursor.fetchone()
        if updated is None:
            return None
        return _read_sensor(cursor, updated["id"])


def rotate_sensor_token(
    sensor_id: UUID,
    actor: str,
) -> tuple[dict[str, Any], str] | None:
    token, token_hash, token_prefix = _new_token()

    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM sensors
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (sensor_id,),
        )
        sensor_row = cursor.fetchone()
        if sensor_row is None:
            return None

        cursor.execute(
            """
            UPDATE sensor_credentials
            SET revoked_at = NOW(), revoked_by = %s
            WHERE sensor_id = %s AND revoked_at IS NULL
            """,
            (actor, sensor_id),
        )
        cursor.execute(
            """
            INSERT INTO sensor_credentials (
                sensor_id,
                token_hash,
                token_prefix,
                created_by
            )
            VALUES (%s, %s, %s, %s)
            """,
            (sensor_id, token_hash, token_prefix, actor),
        )
        sensor = _read_sensor(cursor, sensor_id)
        if sensor is None:
            raise RuntimeError("Rotated sensor credential could not be read")

    return sensor, token


def update_sensor(
    sensor_id: UUID,
    payload: SensorUpdate,
    actor: str,
) -> dict[str, Any] | None:
    longitude = None if payload.position is None else payload.position.longitude
    latitude = None if payload.position is None else payload.position.latitude

    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE sensors
            SET
                display_name = %(display_name)s,
                fixed_position = CASE
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
                updated_by = %(actor)s,
                updated_at = NOW()
            WHERE id = %(sensor_id)s
              AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "sensor_id": sensor_id,
                "display_name": payload.display_name,
                "longitude": longitude,
                "latitude": latitude,
                "actor": actor,
            },
        )
        updated = cursor.fetchone()
        if updated is None:
            return None
        return _read_sensor(cursor, updated["id"])


def delete_sensor(sensor_id: UUID, actor: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM sensors
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (sensor_id,),
        )
        if cursor.fetchone() is None:
            return None

        cursor.execute(
            """
            UPDATE sensor_credentials
            SET revoked_at = NOW(), revoked_by = %s
            WHERE sensor_id = %s AND revoked_at IS NULL
            """,
            (actor, sensor_id),
        )
        cursor.execute(
            """
            UPDATE sensors
            SET
                status = 'disabled',
                health_reason = 'disabled',
                health_changed_at = NOW(),
                health_issue_started_at = NULL,
                maintenance_reason = NULL,
                maintenance_started_at = NULL,
                maintenance_started_by = NULL,
                maintenance_until = NULL,
                deleted_at = NOW(),
                deleted_by = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING id
            """,
            (actor, actor, sensor_id),
        )
        deleted = cursor.fetchone()
        if deleted is None:
            return None
        return _read_sensor(cursor, deleted["id"])


def authenticate_sensor_token(token: str) -> dict[str, Any] | None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                credential.id AS credential_id,
                sensor.id AS sensor_uuid,
                sensor.sensor_key,
                sensor.status
            FROM sensor_credentials AS credential
            JOIN sensors AS sensor ON sensor.id = credential.sensor_id
            WHERE credential.token_hash = %s
              AND credential.revoked_at IS NULL
              AND sensor.deleted_at IS NULL
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        cursor.execute(
            """
            UPDATE sensor_credentials
            SET last_used_at = NOW()
            WHERE id = %s
              AND (
                  last_used_at IS NULL
                  OR last_used_at < NOW() - INTERVAL '1 minute'
              )
            """,
            (row["credential_id"],),
        )
        return dict(row)


def legacy_sensor_access(sensor_key: str) -> LegacySensorAccess:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                sensor.status,
                EXISTS (
                    SELECT 1
                    FROM sensor_credentials AS credential
                    WHERE credential.sensor_id = sensor.id
                      AND credential.revoked_at IS NULL
                ) AS has_individual_credential
            FROM sensors AS sensor
            WHERE sensor.sensor_key = %s
            """,
            (sensor_key,),
        )
        row = cursor.fetchone()

    if row is None:
        return "allowed"
    if row["status"] == "disabled":
        return "disabled"
    if row["has_individual_credential"]:
        return "individual_required"
    return "allowed"

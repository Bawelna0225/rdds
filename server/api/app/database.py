from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import settings
from app.models import HeartbeatEnvelope, ObservationEnvelope, SensorContext
from app.sensor_health import SourceQuality, assess_heartbeat, measure_source_quality


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


def _heartbeat_source_quality(
    cursor: psycopg.Cursor,
    sensor_id: UUID,
    payload: HeartbeatEnvelope,
) -> SourceQuality | None:
    status = payload.status
    counters = (
        status.input_lines_total,
        status.parsed_detections_total,
        status.ignored_lines_total,
        status.source_connections_total,
    )
    if any(value is None for value in counters):
        return None

    cursor.execute(
        """
        SELECT
            measured_at,
            input_lines_total,
            parsed_detections_total,
            ignored_lines_total,
            source_connections_total
        FROM sensor_heartbeats
        WHERE sensor_id = %(sensor_id)s
          AND sensor_boot_id = %(boot_id)s
          AND measured_at < %(reported_at)s
          AND measured_at >= (
              %(reported_at)s
              - (%(window_seconds)s * INTERVAL '1 second')
          )
          AND input_lines_total IS NOT NULL
          AND parsed_detections_total IS NOT NULL
          AND ignored_lines_total IS NOT NULL
          AND source_connections_total IS NOT NULL
        ORDER BY measured_at ASC, received_at ASC
        LIMIT 1
        """,
        {
            "sensor_id": sensor_id,
            "boot_id": payload.sensor.boot_id,
            "reported_at": payload.sensor.timestamp,
            "window_seconds": settings.sensor_quality_window_seconds,
        },
    )
    baseline = cursor.fetchone()
    if baseline is None:
        return None
    return measure_source_quality(
        reported_at=payload.sensor.timestamp,
        baseline_at=baseline["measured_at"],
        input_lines_total=status.input_lines_total,
        parsed_detections_total=status.parsed_detections_total,
        ignored_lines_total=status.ignored_lines_total,
        source_connections_total=status.source_connections_total,
        baseline_input_lines_total=baseline["input_lines_total"],
        baseline_parsed_detections_total=baseline["parsed_detections_total"],
        baseline_ignored_lines_total=baseline["ignored_lines_total"],
        baseline_source_connections_total=baseline["source_connections_total"],
    )


def insert_heartbeat(
    payload: HeartbeatEnvelope,
    raw_message: dict[str, Any],
) -> tuple[UUID, int | None]:
    with connection() as conn, conn.cursor() as cursor:
        sensor_uuid = _upsert_sensor(cursor, payload.sensor)
        source_quality = _heartbeat_source_quality(cursor, sensor_uuid, payload)
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
                queue_capacity,
                queue_oldest_age_seconds,
                dead_letter_depth,
                cellular_rssi,
                agent_version,
                source_kind,
                source_connected,
                source_connected_at,
                source_last_message_at,
                source_last_error_at,
                source_last_error_reason,
                input_lines_total,
                parsed_detections_total,
                enqueued_observations_total,
                ignored_lines_total,
                source_connections_total,
                delivery_success_total,
                delivery_retry_total,
                delivery_discard_total,
                delivery_dead_letter_total,
                last_delivery_success_at,
                last_delivery_error_at,
                last_delivery_error_reason,
                quality_window_seconds,
                quality_input_lines,
                quality_parsed_detections,
                quality_ignored_lines,
                quality_reconnects,
                quality_ignored_ratio,
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
                %(queue_capacity)s,
                %(queue_oldest_age_seconds)s,
                %(dead_letter_depth)s,
                %(cellular_rssi)s,
                %(agent_version)s,
                %(source_kind)s,
                %(source_connected)s,
                %(source_connected_at)s,
                %(source_last_message_at)s,
                %(source_last_error_at)s,
                %(source_last_error_reason)s,
                %(input_lines_total)s,
                %(parsed_detections_total)s,
                %(enqueued_observations_total)s,
                %(ignored_lines_total)s,
                %(source_connections_total)s,
                %(delivery_success_total)s,
                %(delivery_retry_total)s,
                %(delivery_discard_total)s,
                %(delivery_dead_letter_total)s,
                %(last_delivery_success_at)s,
                %(last_delivery_error_at)s,
                %(last_delivery_error_reason)s,
                %(quality_window_seconds)s,
                %(quality_input_lines)s,
                %(quality_parsed_detections)s,
                %(quality_ignored_lines)s,
                %(quality_reconnects)s,
                %(quality_ignored_ratio)s,
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
                "queue_capacity": payload.status.queue_capacity,
                "queue_oldest_age_seconds": payload.status.queue_oldest_age_seconds,
                "dead_letter_depth": payload.status.dead_letter_depth,
                "cellular_rssi": payload.status.cellular_rssi,
                "agent_version": payload.status.agent_version,
                "source_kind": payload.status.source_kind,
                "source_connected": payload.status.source_connected,
                "source_connected_at": payload.status.source_connected_at,
                "source_last_message_at": payload.status.source_last_message_at,
                "source_last_error_at": payload.status.source_last_error_at,
                "source_last_error_reason": payload.status.source_last_error_reason,
                "input_lines_total": payload.status.input_lines_total,
                "parsed_detections_total": payload.status.parsed_detections_total,
                "enqueued_observations_total": payload.status.enqueued_observations_total,
                "ignored_lines_total": payload.status.ignored_lines_total,
                "source_connections_total": payload.status.source_connections_total,
                "delivery_success_total": payload.status.delivery_success_total,
                "delivery_retry_total": payload.status.delivery_retry_total,
                "delivery_discard_total": payload.status.delivery_discard_total,
                "delivery_dead_letter_total": payload.status.delivery_dead_letter_total,
                "last_delivery_success_at": payload.status.last_delivery_success_at,
                "last_delivery_error_at": payload.status.last_delivery_error_at,
                "last_delivery_error_reason": payload.status.last_delivery_error_reason,
                "quality_window_seconds": (
                    None if source_quality is None else source_quality.window_seconds
                ),
                "quality_input_lines": (
                    None if source_quality is None else source_quality.input_lines
                ),
                "quality_parsed_detections": (
                    None
                    if source_quality is None
                    else source_quality.parsed_detections
                ),
                "quality_ignored_lines": (
                    None if source_quality is None else source_quality.ignored_lines
                ),
                "quality_reconnects": (
                    None if source_quality is None else source_quality.reconnects
                ),
                "quality_ignored_ratio": (
                    None if source_quality is None else source_quality.ignored_ratio
                ),
                "raw_message": Jsonb(raw_message),
            },
        )
        row = cursor.fetchone()
        assessment = assess_heartbeat(
            payload.status,
            settings.sensor_queue_warning_messages,
            settings.sensor_source_silent_after_seconds,
            payload.sensor.timestamp,
            source_quality=source_quality,
            quality_min_window_seconds=(
                settings.sensor_quality_min_window_seconds
            ),
            quality_min_input_lines=settings.sensor_quality_min_input_lines,
            quality_max_ignored_ratio=(
                settings.sensor_quality_max_ignored_percent / 100
            ),
            reconnect_warning_count=settings.sensor_reconnect_warning_count,
        )
        cursor.execute(
            """
            UPDATE sensors
            SET
                status = CASE
                    WHEN status IN ('disabled', 'maintenance') THEN status
                    ELSE %(health_state)s
                END,
                health_reason = CASE
                    WHEN status = 'disabled' THEN 'disabled'
                    WHEN status = 'maintenance' THEN 'maintenance'
                    ELSE %(health_reason)s
                END,
                health_changed_at = CASE
                    WHEN status NOT IN ('disabled', 'maintenance')
                     AND (
                         status IS DISTINCT FROM %(health_state)s
                         OR health_reason IS DISTINCT FROM %(health_reason)s
                     )
                    THEN NOW()
                    ELSE health_changed_at
                END,
                health_issue_started_at = CASE
                    WHEN status IN ('disabled', 'maintenance') THEN NULL
                    WHEN %(health_state)s = 'online' THEN NULL
                    ELSE COALESCE(health_issue_started_at, NOW())
                END,
                last_heartbeat_received_at = NOW(),
                last_heartbeat_reported_at = %(reported_at)s,
                agent_version = %(agent_version)s,
                source_connected = %(source_connected)s,
                source_last_message_at = %(source_last_message_at)s,
                reported_queue_depth = %(queue_depth)s,
                reported_dead_letter_depth = %(dead_letter_depth)s,
                reported_quality_window_seconds = %(quality_window_seconds)s,
                reported_quality_input_lines = %(quality_input_lines)s,
                reported_quality_parsed_detections = %(quality_parsed_detections)s,
                reported_quality_ignored_lines = %(quality_ignored_lines)s,
                reported_quality_reconnects = %(quality_reconnects)s,
                reported_quality_ignored_ratio = %(quality_ignored_ratio)s,
                updated_at = NOW()
            WHERE id = %(sensor_id)s
              AND (
                  last_heartbeat_reported_at IS NULL
                  OR last_heartbeat_reported_at < %(reported_at)s
              )
            """,
            {
                "sensor_id": sensor_uuid,
                "reported_at": payload.sensor.timestamp,
                "health_state": assessment.state,
                "health_reason": assessment.reason,
                "agent_version": payload.status.agent_version,
                "source_connected": payload.status.source_connected,
                "source_last_message_at": payload.status.source_last_message_at,
                "queue_depth": payload.status.queue_depth,
                "dead_letter_depth": payload.status.dead_letter_depth,
                "quality_window_seconds": (
                    None if source_quality is None else source_quality.window_seconds
                ),
                "quality_input_lines": (
                    None if source_quality is None else source_quality.input_lines
                ),
                "quality_parsed_detections": (
                    None
                    if source_quality is None
                    else source_quality.parsed_detections
                ),
                "quality_ignored_lines": (
                    None if source_quality is None else source_quality.ignored_lines
                ),
                "quality_reconnects": (
                    None if source_quality is None else source_quality.reconnects
                ),
                "quality_ignored_ratio": (
                    None if source_quality is None else source_quality.ignored_ratio
                ),
            },
        )
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
            WITH expired AS (
                SELECT
                    id,
                    CASE
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
                        WHEN reported_quality_window_seconds >= %(quality_min_window)s
                         AND reported_quality_input_lines >= %(quality_min_input)s
                         AND reported_quality_ignored_ratio >= %(max_ignored_ratio)s
                        THEN 'degraded'
                        WHEN reported_quality_window_seconds >= %(quality_min_window)s
                         AND reported_quality_reconnects >= %(reconnect_warning)s
                        THEN 'degraded'
                        WHEN COALESCE(reported_dead_letter_depth, 0) > 0
                        THEN 'degraded'
                        WHEN COALESCE(reported_queue_depth, 0) >= %(queue_warning)s
                        THEN 'degraded'
                        ELSE 'online'
                    END AS next_status,
                    CASE
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
                        WHEN reported_quality_window_seconds >= %(quality_min_window)s
                         AND reported_quality_input_lines >= %(quality_min_input)s
                         AND reported_quality_ignored_ratio >= %(max_ignored_ratio)s
                        THEN 'source_data_invalid'
                        WHEN reported_quality_window_seconds >= %(quality_min_window)s
                         AND reported_quality_reconnects >= %(reconnect_warning)s
                        THEN 'source_unstable'
                        WHEN COALESCE(reported_dead_letter_depth, 0) > 0
                        THEN 'dead_letter'
                        WHEN COALESCE(reported_queue_depth, 0) >= %(queue_warning)s
                        THEN 'queue_backlog'
                        ELSE 'healthy'
                    END AS next_reason
                FROM sensors
                WHERE status = 'maintenance'
                  AND maintenance_until IS NOT NULL
                  AND maintenance_until <= NOW()
                  AND deleted_at IS NULL
            )
            UPDATE sensors AS sensor
            SET
                status = expired.next_status,
                health_reason = expired.next_reason,
                health_changed_at = NOW(),
                health_issue_started_at = CASE
                    WHEN expired.next_status IN ('degraded', 'offline') THEN NOW()
                    ELSE NULL
                END,
                maintenance_reason = NULL,
                maintenance_started_at = NULL,
                maintenance_started_by = NULL,
                maintenance_until = NULL,
                updated_by = 'system',
                updated_at = NOW()
            FROM expired
            WHERE sensor.id = expired.id
            """,
            {
                "offline_after": settings.sensor_offline_after_seconds,
                "queue_warning": settings.sensor_queue_warning_messages,
                "source_silent_after": (
                    settings.sensor_source_silent_after_seconds
                ),
                "quality_min_window": (
                    settings.sensor_quality_min_window_seconds
                ),
                "quality_min_input": settings.sensor_quality_min_input_lines,
                "max_ignored_ratio": (
                    settings.sensor_quality_max_ignored_percent / 100
                ),
                "reconnect_warning": settings.sensor_reconnect_warning_count,
            },
        )
        changed = cursor.rowcount
        cursor.execute(
            """
            UPDATE sensors
            SET
                status = 'offline',
                health_reason = 'heartbeat_timeout',
                health_changed_at = NOW(),
                health_issue_started_at = COALESCE(
                    health_issue_started_at,
                    NOW()
                ),
                updated_by = 'system',
                updated_at = NOW()
            WHERE status IN ('online', 'degraded')
              AND (
                  last_heartbeat_received_at IS NULL
                  OR last_heartbeat_received_at <
                     NOW() - (%s * INTERVAL '1 second')
              )
            """,
            (settings.sensor_offline_after_seconds,),
        )
        return changed + cursor.rowcount


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
                (
                    SELECT COUNT(*)
                    FROM sensors
                    WHERE deleted_at IS NULL
                ) AS sensors,
                (SELECT COUNT(*) FROM sensor_heartbeats) AS heartbeats,
                (SELECT COUNT(*) FROM observations) AS observations,
                (SELECT COUNT(*) FROM tracks) AS tracks,
                (
                    SELECT COUNT(*)
                    FROM protected_zones
                    WHERE deleted_at IS NULL
                ) AS zones,
                (SELECT COUNT(*) FROM audit_events) AS audit_events,
                (
                    SELECT COUNT(*)
                    FROM sensor_credentials AS credential
                    JOIN sensors AS sensor ON sensor.id = credential.sensor_id
                    WHERE credential.revoked_at IS NULL
                      AND sensor.deleted_at IS NULL
                ) AS individual_sensor_credentials,
                (
                    SELECT COUNT(*)
                    FROM intrusion_alerts
                    WHERE state IN ('active', 'acknowledged')
                ) AS open_intrusion_alerts,
                (
                    SELECT COUNT(*)
                    FROM sensor_alerts
                    WHERE state IN ('active', 'acknowledged')
                ) AS open_sensor_alerts,
                (
                    SELECT COUNT(*) FROM intrusion_alerts
                    WHERE state IN ('active', 'acknowledged')
                ) + (
                    SELECT COUNT(*) FROM sensor_alerts
                    WHERE state IN ('active', 'acknowledged')
                ) AS open_alerts
            """
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("System summary query returned no row")
    return {key: int(value) for key, value in row.items()}

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from app.config import settings
from app.database import connection
from app.models import (
    SensorMaintenance,
    SensorManagedConfiguration,
    SensorRegistration,
    SensorUpdate,
)

LegacySensorAccess = Literal["allowed", "disabled", "individual_required"]


HEALTH_HISTORY_EVENT_TYPES = (
    "sensor_registered",
    "sensor_enabled",
    "sensor_disabled",
    "sensor_online",
    "sensor_degraded",
    "sensor_offline",
    "sensor_health_changed",
    "sensor_recovered",
    "sensor_maintenance_started",
    "sensor_maintenance_ended",
)

MONITORED_SENSOR_STATES = {"online", "degraded", "offline"}
ISSUE_SENSOR_STATES = {"degraded", "offline"}


def _default_health_reason(state: str | None) -> str | None:
    return {
        "online": "healthy",
        "offline": "heartbeat_timeout",
        "maintenance": "maintenance",
        "disabled": "disabled",
        "provisioning": "awaiting_heartbeat",
    }.get(state)


def _health_event_target(event: dict[str, Any]) -> tuple[str | None, str | None]:
    details = event.get("details") or {}
    event_type = event.get("event_type")
    state = details.get("to_status")
    if state is None and event_type in {
        "sensor_registered",
        "sensor_enabled",
        "sensor_disabled",
    }:
        state = details.get("status")

    if event_type == "sensor_maintenance_started":
        reason = "maintenance"
    elif event_type == "sensor_disabled":
        reason = "disabled"
    else:
        reason = details.get("reason") or _default_health_reason(state)
    return state, reason


def _health_history_summary(
    *,
    sensor: dict[str, Any],
    events: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    created_at = sensor["created_at"]
    coverage_start = max(window_start, created_at)
    if coverage_start >= window_end:
        return {
            "coverage_start": coverage_start,
            "coverage_end": window_end,
            "coverage_seconds": 0,
            "summary": {
                "availability_percent": None,
                "healthy_percent": None,
                "online_seconds": 0,
                "degraded_seconds": 0,
                "offline_seconds": 0,
                "excluded_seconds": 0,
                "issue_count": 0,
                "recovery_count": 0,
            },
            "timeline": [],
        }

    prior_events = [event for event in events if event["occurred_at"] < coverage_start]
    window_events = [
        event
        for event in events
        if coverage_start <= event["occurred_at"] <= window_end
    ]

    initial_state: str | None = None
    initial_reason: str | None = None
    if prior_events:
        initial_state, initial_reason = _health_event_target(prior_events[-1])
    elif window_events:
        first_details = window_events[0].get("details") or {}
        initial_state = first_details.get("from_status")
        initial_reason = first_details.get("from_reason") or _default_health_reason(
            initial_state
        )
    if initial_state is None:
        if created_at >= window_start:
            initial_state = "provisioning"
            initial_reason = "awaiting_heartbeat"
        else:
            initial_state = sensor["status"]
            initial_reason = sensor["health_reason"]

    timeline: list[dict[str, Any]] = []
    state = initial_state
    reason = initial_reason or _default_health_reason(state)
    segment_start = coverage_start
    issue_count = 0
    recovery_count = 0

    for event in window_events:
        event_at = min(max(event["occurred_at"], coverage_start), window_end)
        next_state, next_reason = _health_event_target(event)
        if next_state is None:
            continue
        next_reason = next_reason or reason or _default_health_reason(next_state)
        if next_state == state and next_reason == reason:
            continue

        if event_at > segment_start:
            timeline.append(
                {
                    "state": state,
                    "reason": reason,
                    "started_at": segment_start,
                    "ended_at": event_at,
                    "duration_seconds": int((event_at - segment_start).total_seconds()),
                }
            )

        if next_state in ISSUE_SENSOR_STATES and state not in ISSUE_SENSOR_STATES:
            issue_count += 1
        if state in ISSUE_SENSOR_STATES and next_state == "online":
            recovery_count += 1

        state = next_state
        reason = next_reason
        segment_start = event_at

    if segment_start < window_end:
        timeline.append(
            {
                "state": state,
                "reason": reason,
                "started_at": segment_start,
                "ended_at": window_end,
                "duration_seconds": int((window_end - segment_start).total_seconds()),
            }
        )

    durations = {
        "online": 0,
        "degraded": 0,
        "offline": 0,
        "excluded": 0,
    }
    for segment in timeline:
        duration = segment["duration_seconds"]
        segment_state = segment["state"]
        if segment_state in MONITORED_SENSOR_STATES:
            durations[segment_state] += duration
        else:
            durations["excluded"] += duration

    monitored_seconds = (
        durations["online"] + durations["degraded"] + durations["offline"]
    )
    availability_percent = None
    healthy_percent = None
    if monitored_seconds > 0:
        availability_percent = round(
            100 * (durations["online"] + durations["degraded"]) / monitored_seconds,
            2,
        )
        healthy_percent = round(100 * durations["online"] / monitored_seconds, 2)

    return {
        "coverage_start": coverage_start,
        "coverage_end": window_end,
        "coverage_seconds": int((window_end - coverage_start).total_seconds()),
        "summary": {
            "availability_percent": availability_percent,
            "healthy_percent": healthy_percent,
            "online_seconds": durations["online"],
            "degraded_seconds": durations["degraded"],
            "offline_seconds": durations["offline"],
            "excluded_seconds": durations["excluded"],
            "issue_count": issue_count,
            "recovery_count": recovery_count,
        },
        "timeline": timeline,
    }

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
    configuration.desired_revision AS configuration_desired_revision,
    configuration.applied_revision AS configuration_applied_revision,
    configuration.apply_status AS configuration_apply_status,
    configuration.apply_error AS configuration_apply_error,
    configuration.reported_at AS configuration_reported_at,
    CASE
        WHEN configuration.sensor_id IS NULL
          OR configuration.desired_revision = 0 THEN 'unmanaged'
        WHEN configuration.apply_status = 'error' THEN 'error'
        WHEN configuration.applied_revision = configuration.desired_revision
          AND configuration.apply_status = 'applied' THEN 'compliant'
        WHEN configuration.applied_revision IS NULL THEN 'unreported'
        ELSE 'pending'
    END AS configuration_compliance,
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
    heartbeat.quality_window_seconds,
    heartbeat.quality_input_lines,
    heartbeat.quality_parsed_detections,
    heartbeat.quality_ignored_lines,
    heartbeat.quality_reconnects,
    heartbeat.quality_ignored_ratio,
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
    LEFT JOIN sensor_configuration_state AS configuration
        ON configuration.sensor_id = sensor.id
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
            latest_heartbeat.quality_window_seconds,
            latest_heartbeat.quality_input_lines,
            latest_heartbeat.quality_parsed_detections,
            latest_heartbeat.quality_ignored_lines,
            latest_heartbeat.quality_reconnects,
            latest_heartbeat.quality_ignored_ratio,
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


def list_sensor_health_overview() -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT
                {SENSOR_COLUMNS},
                COALESCE(health_24h.issue_starts_24h, 0) AS issue_starts_24h,
                COALESCE(health_24h.health_changes_24h, 0) AS health_changes_24h,
                COALESCE(health_24h.recoveries_24h, 0) AS recoveries_24h,
                health_24h.last_health_event_at
            FROM sensors AS sensor
            {SENSOR_JOINS}
            LEFT JOIN (
                SELECT
                    sensor_id,
                    COUNT(*) FILTER (
                        WHERE event_type IN ('sensor_degraded', 'sensor_offline')
                    )::INTEGER AS issue_starts_24h,
                    COUNT(*) FILTER (
                        WHERE event_type = 'sensor_health_changed'
                    )::INTEGER AS health_changes_24h,
                    COUNT(*) FILTER (
                        WHERE event_type = 'sensor_recovered'
                    )::INTEGER AS recoveries_24h,
                    MAX(occurred_at) AS last_health_event_at
                FROM audit_events
                WHERE occurred_at >= NOW() - INTERVAL '24 hours'
                  AND event_type IN (
                      'sensor_degraded',
                      'sensor_offline',
                      'sensor_health_changed',
                      'sensor_recovered'
                  )
                GROUP BY sensor_id
            ) AS health_24h ON health_24h.sensor_id = sensor.id
            WHERE sensor.deleted_at IS NULL
            ORDER BY sensor.sensor_key
            """
        )
        return [dict(row) for row in cursor.fetchall()]



def get_sensor_health_history(
    sensor_id: UUID,
    hours: int,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id,
                sensor_key AS sensor_id,
                display_name,
                status,
                health_reason,
                created_at,
                NOW() AS generated_at
            FROM sensors
            WHERE id = %s AND deleted_at IS NULL
            """,
            (sensor_id,),
        )
        sensor = cursor.fetchone()
        if sensor is None:
            return None

        window_end = sensor["generated_at"]
        window_start = window_end - timedelta(hours=hours)
        cursor.execute(
            """
            WITH prior_event AS (
                SELECT id, occurred_at, event_type, details
                FROM audit_events
                WHERE sensor_id = %(sensor_id)s
                  AND occurred_at < %(window_start)s
                  AND event_type = ANY(%(event_types)s)
                ORDER BY occurred_at DESC, id DESC
                LIMIT 1
            ),
            window_events AS (
                SELECT id, occurred_at, event_type, details
                FROM audit_events
                WHERE sensor_id = %(sensor_id)s
                  AND occurred_at >= %(window_start)s
                  AND occurred_at <= %(window_end)s
                  AND event_type = ANY(%(event_types)s)
            )
            SELECT id, occurred_at, event_type, details
            FROM prior_event
            UNION ALL
            SELECT id, occurred_at, event_type, details
            FROM window_events
            ORDER BY occurred_at, id
            """,
            {
                "sensor_id": sensor_id,
                "window_start": window_start,
                "window_end": window_end,
                "event_types": list(HEALTH_HISTORY_EVENT_TYPES),
            },
        )
        events = [dict(row) for row in cursor.fetchall()]

    history = _health_history_summary(
        sensor=dict(sensor),
        events=events,
        window_start=window_start,
        window_end=window_end,
    )
    return {
        "sensor_id": sensor["sensor_id"],
        "display_name": sensor["display_name"],
        "window_hours": hours,
        **history,
    }

def get_sensor_quality_history(
    sensor_id: UUID,
    limit: int,
) -> list[dict[str, Any]] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM sensors
            WHERE id = %s AND deleted_at IS NULL
            """,
            (sensor_id,),
        )
        if cursor.fetchone() is None:
            return None
        cursor.execute(
            """
            SELECT
                measured_at,
                quality_window_seconds AS window_seconds,
                quality_input_lines AS input_lines,
                quality_parsed_detections AS parsed_detections,
                quality_ignored_lines AS ignored_lines,
                quality_reconnects AS reconnects,
                quality_ignored_ratio AS ignored_ratio,
                CASE
                    WHEN quality_window_seconds >= %(quality_min_window)s
                     AND quality_input_lines >= %(quality_min_input)s
                     AND quality_ignored_ratio >= %(max_ignored_ratio)s
                    THEN 'source_data_invalid'
                    WHEN quality_window_seconds >= %(quality_min_window)s
                     AND quality_reconnects >= %(reconnect_warning)s
                    THEN 'source_unstable'
                    WHEN quality_window_seconds < %(quality_min_window)s
                      OR quality_input_lines < %(quality_min_input)s
                    THEN 'warming_up'
                    ELSE 'healthy'
                END AS reason
            FROM sensor_heartbeats
            WHERE sensor_id = %(sensor_id)s
              AND quality_window_seconds IS NOT NULL
            ORDER BY measured_at DESC, received_at DESC
            LIMIT %(limit)s
            """,
            {
                "sensor_id": sensor_id,
                "limit": limit,
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
            INSERT INTO sensor_configuration_state (sensor_id)
            VALUES (%s)
            ON CONFLICT (sensor_id) DO NOTHING
            """,
            (created["id"],),
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
            (created["id"], token_hash, token_prefix, actor),
        )
        sensor = _read_sensor(cursor, created["id"])
        if sensor is None:
            raise RuntimeError("Registered sensor could not be read")

    return sensor, token



def get_sensor_configuration(sensor_id: UUID) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                sensor.id AS sensor_id,
                sensor.sensor_key,
                sensor.display_name,
                configuration.desired_revision,
                configuration.desired_config,
                configuration.desired_updated_at,
                configuration.desired_updated_by,
                configuration.applied_revision,
                configuration.applied_config,
                configuration.apply_status,
                configuration.apply_error,
                configuration.reported_at,
                assignment.profile_id AS assigned_profile_id,
                assigned_profile.profile_key AS assigned_profile_key,
                assignment.profile_version AS assigned_profile_version,
                assignment.rollout_id AS assigned_rollout_id,
                assignment.assigned_at,
                assignment.assigned_by,
                CASE
                    WHEN configuration.sensor_id IS NULL
                      OR configuration.desired_revision = 0 THEN 'unmanaged'
                    WHEN configuration.apply_status = 'error' THEN 'error'
                    WHEN configuration.applied_revision = configuration.desired_revision
                      AND configuration.apply_status = 'applied'
                    THEN 'compliant'
                    WHEN configuration.applied_revision IS NULL THEN 'unreported'
                    ELSE 'pending'
                END AS compliance
            FROM sensors AS sensor
            LEFT JOIN sensor_configuration_state AS configuration
                ON configuration.sensor_id = sensor.id
            LEFT JOIN sensor_configuration_profile_assignments AS assignment
                ON assignment.sensor_id = sensor.id
            LEFT JOIN sensor_configuration_profiles AS assigned_profile
                ON assigned_profile.id = assignment.profile_id
            WHERE sensor.id = %s
              AND sensor.deleted_at IS NULL
            """,
            (sensor_id,),
        )
        row = cursor.fetchone()
        return None if row is None else dict(row)


def get_sensor_configuration_by_key(sensor_key: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                sensor.id AS sensor_id,
                sensor.sensor_key,
                configuration.desired_revision,
                configuration.desired_config
            FROM sensors AS sensor
            LEFT JOIN sensor_configuration_state AS configuration
                ON configuration.sensor_id = sensor.id
            WHERE sensor.sensor_key = %s
              AND sensor.deleted_at IS NULL
            """,
            (sensor_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        if result["desired_revision"] is None:
            result["desired_revision"] = 0
            result["desired_config"] = {}
        return result


def update_sensor_configuration(
    sensor_id: UUID,
    payload: SensorManagedConfiguration,
    actor: str,
) -> dict[str, Any] | None:
    desired_config = json.dumps(
        payload.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    )
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM sensors
            WHERE id = %s
              AND deleted_at IS NULL
            FOR UPDATE
            """,
            (sensor_id,),
        )
        if cursor.fetchone() is None:
            return None

        cursor.execute(
            """
            DELETE FROM sensor_configuration_profile_assignments
            WHERE sensor_id = %s
            RETURNING profile_id, profile_version, rollout_id, desired_revision
            """,
            (sensor_id,),
        )
        removed_assignment = cursor.fetchone()
        if removed_assignment is not None:
            cursor.execute(
                """
                INSERT INTO audit_events (
                    occurred_at,
                    event_type,
                    actor,
                    sensor_id,
                    details
                )
                VALUES (
                    NOW(),
                    'sensor_configuration_profile_unassigned',
                    %(actor)s,
                    %(sensor_id)s,
                    jsonb_build_object(
                        'profile_id', %(profile_id)s::uuid,
                        'profile_version', %(profile_version)s::bigint,
                        'rollout_id', %(rollout_id)s::uuid,
                        'desired_revision', %(desired_revision)s::bigint,
                        'reason', 'manual_configuration_update'
                    )
                )
                """,
                {
                    "actor": actor,
                    "sensor_id": sensor_id,
                    "profile_id": removed_assignment["profile_id"],
                    "profile_version": removed_assignment["profile_version"],
                    "rollout_id": removed_assignment["rollout_id"],
                    "desired_revision": removed_assignment["desired_revision"],
                },
            )

        cursor.execute(
            """
            INSERT INTO sensor_configuration_state (
                sensor_id,
                desired_revision,
                desired_config,
                desired_updated_at,
                desired_updated_by,
                apply_status,
                apply_error
            )
            VALUES (
                %(sensor_id)s,
                1,
                %(desired_config)s::jsonb,
                NOW(),
                %(actor)s,
                'unreported',
                NULL
            )
            ON CONFLICT (sensor_id) DO UPDATE
            SET
                desired_revision =
                    sensor_configuration_state.desired_revision + 1,
                desired_config = EXCLUDED.desired_config,
                desired_updated_at = NOW(),
                desired_updated_by = EXCLUDED.desired_updated_by,
                apply_status = CASE
                    WHEN sensor_configuration_state.applied_revision IS NULL
                    THEN 'unreported'
                    ELSE 'pending'
                END,
                apply_error = NULL
            RETURNING desired_revision
            """,
            {
                "sensor_id": sensor_id,
                "desired_config": desired_config,
                "actor": actor,
            },
        )
        changed = cursor.fetchone()
        if changed is None:
            raise RuntimeError("Sensor configuration update returned no row")

        cursor.execute(
            """
            INSERT INTO audit_events (
                occurred_at,
                event_type,
                actor,
                sensor_id,
                details
            )
            VALUES (
                NOW(),
                'sensor_configuration_changed',
                %(actor)s,
                %(sensor_id)s,
                jsonb_build_object(
                    'desired_revision', %(desired_revision)s,
                    'desired_config', %(desired_config)s::jsonb
                )
            )
            """,
            {
                "actor": actor,
                "sensor_id": sensor_id,
                "desired_revision": changed["desired_revision"],
                "desired_config": desired_config,
            },
        )

    return get_sensor_configuration(sensor_id)


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
                      OR (
                          reported_quality_window_seconds >= %(quality_min_window)s
                          AND reported_quality_input_lines >= %(quality_min_input)s
                          AND reported_quality_ignored_ratio >= %(max_ignored_ratio)s
                      )
                      OR (
                          reported_quality_window_seconds >= %(quality_min_window)s
                          AND reported_quality_reconnects >= %(reconnect_warning)s
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

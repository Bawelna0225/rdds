from datetime import datetime
from typing import Any
from uuid import UUID

from app.config import settings
from app.database import connection


SEVERITY_SQL = """
    CASE
        WHEN sensor.status = 'offline' THEN 'critical'
        WHEN sensor.health_reason IN (
            'dead_letter',
            'source_unavailable',
            'source_silent',
            'source_data_invalid'
        ) THEN 'high'
        ELSE 'medium'
    END
"""


def evaluate_sensor_alerts() -> tuple[int, int]:
    """Open/update qualified sensor alerts and close alerts after recovery."""
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO sensor_alerts (
                sensor_id,
                state,
                severity,
                reason,
                condition_started_at,
                opened_at,
                last_observed_at,
                occurrence_count
            )
            SELECT
                sensor.id,
                'active',
                {SEVERITY_SQL},
                sensor.health_reason,
                CASE
                    WHEN sensor.status = 'offline' THEN sensor.health_changed_at
                    ELSE sensor.health_issue_started_at
                END,
                NOW(),
                NOW(),
                1
            FROM sensors AS sensor
            WHERE sensor.deleted_at IS NULL
              AND sensor.health_issue_started_at IS NOT NULL
              AND sensor.status IN ('degraded', 'offline')
              AND (
                  EXISTS (
                      SELECT 1
                      FROM sensor_alerts AS existing
                      WHERE existing.sensor_id = sensor.id
                        AND existing.state IN ('active', 'acknowledged')
                  )
                  OR (
                      sensor.status = 'offline'
                      AND sensor.health_changed_at <=
                          NOW() - (%(offline_delay)s * INTERVAL '1 second')
                  )
                  OR (
                      sensor.status = 'degraded'
                      AND sensor.health_issue_started_at <=
                          NOW() - (%(degraded_delay)s * INTERVAL '1 second')
                  )
              )
            ON CONFLICT (sensor_id)
                WHERE state IN ('active', 'acknowledged')
            DO UPDATE SET
                severity = EXCLUDED.severity,
                reason = EXCLUDED.reason,
                last_observed_at = NOW(),
                occurrence_count = sensor_alerts.occurrence_count + CASE
                    WHEN sensor_alerts.reason IS DISTINCT FROM EXCLUDED.reason
                      OR sensor_alerts.severity IS DISTINCT FROM EXCLUDED.severity
                    THEN 1
                    ELSE 0
                END,
                updated_at = NOW()
            WHERE sensor_alerts.reason IS DISTINCT FROM EXCLUDED.reason
               OR sensor_alerts.severity IS DISTINCT FROM EXCLUDED.severity
               OR sensor_alerts.last_observed_at < NOW() - INTERVAL '30 seconds'
            """,
            {
                "offline_delay": settings.sensor_alert_offline_after_seconds,
                "degraded_delay": settings.sensor_alert_degraded_after_seconds,
            },
        )
        opened_or_refreshed = cursor.rowcount

        cursor.execute(
            """
            UPDATE sensor_alerts AS alert
            SET
                state = 'closed',
                closed_at = NOW(),
                closed_by = 'system',
                resolution = CASE
                    WHEN sensor.deleted_at IS NOT NULL THEN 'sensor_deleted'
                    WHEN sensor.status = 'maintenance' THEN 'maintenance'
                    WHEN sensor.status = 'disabled' THEN 'disabled'
                    ELSE 'recovered'
                END,
                last_observed_at = NOW(),
                updated_at = NOW()
            FROM sensors AS sensor
            WHERE alert.sensor_id = sensor.id
              AND alert.state IN ('active', 'acknowledged')
              AND (
                  sensor.deleted_at IS NOT NULL
                  OR sensor.status NOT IN ('degraded', 'offline')
                  OR sensor.health_issue_started_at IS NULL
              )
            """
        )
        closed = cursor.rowcount
    return opened_or_refreshed, closed


def list_sensor_alerts(
    *,
    include_closed: bool = False,
    closed_only: bool = False,
    closed_from: datetime | None = None,
    closed_before: datetime | None = None,
    alert_id: UUID | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                alert.id,
                alert.sensor_id,
                alert.state,
                alert.severity,
                alert.reason,
                alert.condition_started_at,
                alert.opened_at,
                alert.last_observed_at,
                alert.occurrence_count,
                alert.acknowledged_at,
                alert.acknowledged_by,
                alert.closed_at,
                alert.closed_by,
                alert.resolution,
                GREATEST(
                    0,
                    EXTRACT(EPOCH FROM (
                        COALESCE(alert.closed_at, NOW()) - alert.condition_started_at
                    ))
                )::double precision AS duration_seconds,
                sensor.sensor_key,
                sensor.display_name AS sensor_name,
                sensor.status AS sensor_status,
                sensor.health_reason AS sensor_health_reason,
                sensor.health_changed_at,
                sensor.health_issue_started_at,
                sensor.agent_version,
                sensor.source_connected,
                sensor.reported_queue_depth AS queue_depth,
                sensor.reported_dead_letter_depth AS dead_letter_depth,
                ST_Y(sensor.fixed_position::geometry) AS latitude,
                ST_X(sensor.fixed_position::geometry) AS longitude
            FROM sensor_alerts AS alert
            JOIN sensors AS sensor ON sensor.id = alert.sensor_id
            WHERE (
                CASE
                    WHEN %(closed_only)s THEN alert.state = 'closed'
                    ELSE %(include_closed)s OR alert.state <> 'closed'
                END
            )
              AND (
                  %(closed_from)s::timestamptz IS NULL
                  OR alert.closed_at >= %(closed_from)s
              )
              AND (
                  %(closed_before)s::timestamptz IS NULL
                  OR alert.closed_at < %(closed_before)s
              )
              AND (
                  %(alert_id)s::uuid IS NULL
                  OR alert.id = %(alert_id)s
              )
            ORDER BY
                CASE WHEN %(closed_only)s THEN alert.closed_at END DESC NULLS LAST,
                CASE WHEN NOT %(closed_only)s THEN
                    CASE alert.severity
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'medium' THEN 2
                        ELSE 1
                    END
                END DESC,
                alert.opened_at DESC
            LIMIT %(limit)s
            """,
            {
                "include_closed": include_closed,
                "closed_only": closed_only,
                "closed_from": closed_from,
                "closed_before": closed_before,
                "alert_id": alert_id,
                "limit": limit,
            },
        )
        return [dict(row) for row in cursor.fetchall()]


def acknowledge_sensor_alert(alert_id: UUID, actor: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE sensor_alerts
            SET
                state = 'acknowledged',
                acknowledged_at = NOW(),
                acknowledged_by = %s,
                updated_at = NOW()
            WHERE id = %s AND state = 'active'
            RETURNING id, state, acknowledged_at, acknowledged_by
            """,
            (actor, alert_id),
        )
        row = cursor.fetchone()
        return None if row is None else dict(row)

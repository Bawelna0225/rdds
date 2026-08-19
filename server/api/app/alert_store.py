import json
from typing import Any
from uuid import UUID

from app.database import connection
from app.models import ProtectedZoneCreate


ZONE_COLUMNS = """
    zone.id,
    zone.name,
    zone.description,
    zone.severity,
    zone.active,
    zone.created_by,
    zone.updated_by,
    ST_AsGeoJSON(zone.area::geometry)::jsonb AS geometry,
    zone.created_at,
    zone.updated_at
"""


def create_zone(payload: ProtectedZoneCreate) -> dict[str, Any]:
    geometry = json.dumps(payload.geometry.model_dump(mode="json"))
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            WITH candidate AS (
                SELECT ST_SetSRID(
                    ST_GeomFromGeoJSON(%(geometry)s),
                    4326
                ) AS area
            )
            INSERT INTO protected_zones (
                name,
                description,
                severity,
                active,
                created_by,
                updated_by,
                area
            )
            SELECT
                %(name)s,
                %(description)s,
                %(severity)s,
                %(active)s,
                %(actor)s,
                %(actor)s,
                candidate.area::geography
            FROM candidate
            WHERE ST_IsValid(candidate.area)
              AND NOT ST_IsEmpty(candidate.area)
            RETURNING id
            """,
            {
                "name": payload.name,
                "description": payload.description,
                "severity": payload.severity,
                "active": payload.active,
                "actor": payload.actor,
                "geometry": geometry,
            },
        )
        created = cursor.fetchone()
        if created is None:
            raise ValueError("protected zone polygon is not valid")

        cursor.execute(
            f"""
            SELECT {ZONE_COLUMNS}
            FROM protected_zones AS zone
            WHERE zone.id = %s
            """,
            (created["id"],),
        )
        zone = cursor.fetchone()
        if zone is None:
            raise RuntimeError("Created protected zone could not be read")
        return dict(zone)


def list_zones() -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {ZONE_COLUMNS}
            FROM protected_zones AS zone
            ORDER BY
                zone.active DESC,
                CASE zone.severity
                    WHEN 'critical' THEN 4
                    WHEN 'high' THEN 3
                    WHEN 'medium' THEN 2
                    ELSE 1
                END DESC,
                zone.name
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def set_zone_active(
    zone_id: UUID,
    active: bool,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE protected_zones
            SET active = %s, updated_by = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (active, actor, zone_id),
        )
        updated = cursor.fetchone()
        if updated is None:
            return None

        cursor.execute(
            f"""
            SELECT {ZONE_COLUMNS}
            FROM protected_zones AS zone
            WHERE zone.id = %s
            """,
            (updated["id"],),
        )
        zone = cursor.fetchone()
        return None if zone is None else dict(zone)


def list_alerts(
    include_closed: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                alert.id,
                alert.state,
                alert.severity,
                alert.first_detected_at,
                alert.last_detected_at,
                alert.detection_count,
                alert.acknowledged_at,
                alert.acknowledged_by,
                alert.closed_at,
                alert.closed_by,
                zone.id AS zone_id,
                zone.name AS zone_name,
                track.id AS track_id,
                track.track_key,
                track.last_basic_id AS basic_id,
                track.identity_key,
                track.state AS track_state,
                ST_Y(alert.last_position::geometry) AS latitude,
                ST_X(alert.last_position::geometry) AS longitude
            FROM intrusion_alerts AS alert
            JOIN protected_zones AS zone ON zone.id = alert.zone_id
            JOIN tracks AS track ON track.id = alert.track_id
            WHERE (%s OR alert.state <> 'closed')
            ORDER BY
                CASE alert.severity
                    WHEN 'critical' THEN 4
                    WHEN 'high' THEN 3
                    WHEN 'medium' THEN 2
                    ELSE 1
                END DESC,
                alert.last_detected_at DESC
            LIMIT %s
            """,
            (include_closed, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def acknowledge_alert(alert_id: UUID, actor: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE intrusion_alerts
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


def close_alert(alert_id: UUID, actor: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE intrusion_alerts
            SET
                state = 'closed',
                closed_at = NOW(),
                closed_by = %s,
                updated_at = NOW()
            WHERE id = %s AND state IN ('active', 'acknowledged')
            RETURNING id, state, closed_at, closed_by
            """,
            (actor, alert_id),
        )
        row = cursor.fetchone()
        return None if row is None else dict(row)


def evaluate_intrusions() -> tuple[int, int]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            WITH detected AS (
                SELECT
                    zone.id AS zone_id,
                    zone.severity,
                    track.id AS track_id,
                    track.last_seen_at AS detected_at,
                    track.last_position
                FROM protected_zones AS zone
                CROSS JOIN tracks AS track
                WHERE zone.active
                  AND track.state IN ('new', 'active', 'anomalous')
                  AND track.last_position IS NOT NULL
                  AND ST_Intersects(zone.area, track.last_position)
            )
            INSERT INTO intrusion_alerts (
                zone_id,
                track_id,
                state,
                severity,
                first_detected_at,
                last_detected_at,
                last_position,
                detection_count
            )
            SELECT
                detected.zone_id,
                detected.track_id,
                'active',
                detected.severity,
                detected.detected_at,
                detected.detected_at,
                detected.last_position,
                1
            FROM detected
            ON CONFLICT (zone_id, track_id)
                WHERE state IN ('active', 'acknowledged')
            DO UPDATE SET
                severity = EXCLUDED.severity,
                last_detected_at = GREATEST(
                    intrusion_alerts.last_detected_at,
                    EXCLUDED.last_detected_at
                ),
                last_position = CASE
                    WHEN EXCLUDED.last_detected_at >= intrusion_alerts.last_detected_at
                        THEN EXCLUDED.last_position
                    ELSE intrusion_alerts.last_position
                END,
                detection_count = intrusion_alerts.detection_count + CASE
                    WHEN EXCLUDED.last_detected_at > intrusion_alerts.last_detected_at
                        THEN 1
                    ELSE 0
                END,
                updated_at = NOW()
            WHERE EXCLUDED.last_detected_at > intrusion_alerts.last_detected_at
               OR EXCLUDED.severity IS DISTINCT FROM intrusion_alerts.severity
            """
        )
        detected = cursor.rowcount

        cursor.execute(
            """
            UPDATE intrusion_alerts AS alert
            SET
                state = 'closed',
                closed_at = NOW(),
                closed_by = 'system',
                updated_at = NOW()
            WHERE alert.state IN ('active', 'acknowledged')
              AND NOT EXISTS (
                  SELECT 1
                  FROM protected_zones AS zone
                  JOIN tracks AS track ON track.id = alert.track_id
                  WHERE zone.id = alert.zone_id
                    AND zone.active
                    AND track.state <> 'ended'
                    AND track.last_position IS NOT NULL
                    AND ST_Intersects(zone.area, track.last_position)
              )
            """
        )
        closed = cursor.rowcount
        return detected, closed

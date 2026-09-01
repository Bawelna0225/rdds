import json
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database import connection
from app.models import ProtectedZoneCreate, ProtectedZoneUpdate

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


def _read_zone(cursor: Any, zone_id: UUID) -> dict[str, Any] | None:
    cursor.execute(
        f"""
        SELECT {ZONE_COLUMNS}
        FROM protected_zones AS zone
        WHERE zone.id = %s
        """,
        (zone_id,),
    )
    row = cursor.fetchone()
    return None if row is None else dict(row)


def create_zone(payload: ProtectedZoneCreate, actor: str) -> dict[str, Any]:
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
                "actor": actor,
                "geometry": geometry,
            },
        )
        created = cursor.fetchone()
        if created is None:
            raise ValueError("protected zone polygon is not valid")

        zone = _read_zone(cursor, created["id"])
        if zone is None:
            raise RuntimeError("Created protected zone could not be read")
        return zone


def list_zones() -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {ZONE_COLUMNS}
            FROM protected_zones AS zone
            WHERE zone.deleted_at IS NULL
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
            WHERE id = %s AND deleted_at IS NULL
            RETURNING id
            """,
            (active, actor, zone_id),
        )
        updated = cursor.fetchone()
        if updated is None:
            return None

        return _read_zone(cursor, updated["id"])


def update_zone(
    zone_id: UUID,
    payload: ProtectedZoneUpdate,
    actor: str,
) -> dict[str, Any] | None:
    geometry = json.dumps(payload.geometry.model_dump(mode="json"))
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            WITH candidate AS (
                SELECT ST_SetSRID(
                    ST_GeomFromGeoJSON(%s),
                    4326
                ) AS area
            )
            SELECT ST_IsValid(area) AND NOT ST_IsEmpty(area) AS valid
            FROM candidate
            """,
            (geometry,),
        )
        validity = cursor.fetchone()
        if validity is None or not validity["valid"]:
            raise ValueError("protected zone polygon is not valid")

        cursor.execute(
            """
            WITH candidate AS (
                SELECT ST_SetSRID(
                    ST_GeomFromGeoJSON(%(geometry)s),
                    4326
                ) AS area
            )
            UPDATE protected_zones AS zone
            SET
                name = %(name)s,
                description = %(description)s,
                severity = %(severity)s,
                active = %(active)s,
                area = candidate.area::geography,
                updated_by = %(actor)s,
                updated_at = NOW()
            FROM candidate
            WHERE zone.id = %(zone_id)s
              AND zone.deleted_at IS NULL
            RETURNING zone.id
            """,
            {
                "zone_id": zone_id,
                "name": payload.name,
                "description": payload.description,
                "severity": payload.severity,
                "active": payload.active,
                "actor": actor,
                "geometry": geometry,
            },
        )
        updated = cursor.fetchone()
        if updated is None:
            return None
        return _read_zone(cursor, updated["id"])


def delete_zone(zone_id: UUID, actor: str) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM protected_zones
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (zone_id,),
        )
        if cursor.fetchone() is None:
            return None

        cursor.execute(
            """
            UPDATE intrusion_alerts
            SET
                state = 'closed',
                presence_state = CASE
                    WHEN presence_state = 'inside' THEN 'left'
                    ELSE presence_state
                END,
                presence_changed_at = CASE
                    WHEN presence_state = 'inside' THEN NOW()
                    ELSE presence_changed_at
                END,
                exited_at = CASE
                    WHEN presence_state = 'inside' THEN COALESCE(exited_at, NOW())
                    ELSE exited_at
                END,
                closed_at = NOW(),
                closed_by = %s,
                updated_at = NOW()
            WHERE zone_id = %s
              AND state IN ('active', 'acknowledged')
            """,
            (actor, zone_id),
        )
        cursor.execute(
            """
            UPDATE protected_zones
            SET
                active = FALSE,
                deleted_at = NOW(),
                deleted_by = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING id
            """,
            (actor, actor, zone_id),
        )
        deleted = cursor.fetchone()
        if deleted is None:
            return None
        return _read_zone(cursor, deleted["id"])


def list_alerts(
    include_closed: bool = False,
    limit: int = 200,
    closed_only: bool = False,
    closed_from: datetime | None = None,
    closed_before: datetime | None = None,
) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                alert.id,
                alert.state,
                alert.presence_state,
                alert.severity,
                alert.first_detected_at,
                alert.last_detected_at,
                alert.presence_changed_at,
                alert.exited_at,
                alert.detection_count,
                alert.acknowledged_at,
                alert.acknowledged_by,
                alert.closed_at,
                alert.closed_by,
                zone.id AS zone_id,
                COALESCE(alert.entry_zone_name, zone.name) AS zone_name,
                alert.entry_zone_description AS zone_description,
                zone.name AS current_zone_name,
                track.id AS track_id,
                COALESCE(alert.entry_track_key, track.track_key) AS track_key,
                COALESCE(alert.entry_basic_id, track.last_basic_id) AS basic_id,
                COALESCE(alert.entry_identity_key, track.identity_key) AS identity_key,
                alert.entry_operator_id AS operator_id,
                alert.entry_drone_mac AS drone_mac,
                alert.entry_sensor_key AS sensor_key,
                alert.entry_altitude_m AS altitude_m,
                alert.entry_speed_mps AS speed_mps,
                alert.entry_heading_deg AS heading_deg,
                ST_Y(alert.entry_position::geometry) AS latitude,
                ST_X(alert.entry_position::geometry) AS longitude,
                ST_Y(alert.entry_pilot_position::geometry) AS pilot_latitude,
                ST_X(alert.entry_pilot_position::geometry) AS pilot_longitude,
                track.state AS track_state,
                track.last_basic_id AS live_basic_id,
                track.last_operator_id AS live_operator_id,
                track.last_altitude_m AS live_altitude_m,
                track.last_speed_mps AS live_speed_mps,
                track.last_heading_deg AS live_heading_deg,
                track.last_seen_at AS live_last_seen_at,
                ST_Y(track.last_position::geometry) AS live_latitude,
                ST_X(track.last_position::geometry) AS live_longitude,
                ST_Y(track.last_pilot_position::geometry) AS live_pilot_latitude,
                ST_X(track.last_pilot_position::geometry) AS live_pilot_longitude,
                sensor_summary.contributing_sensors,
                GREATEST(
                    0,
                    EXTRACT(EPOCH FROM (
                        CASE
                            WHEN alert.presence_state = 'inside'
                                THEN alert.last_detected_at
                            ELSE COALESCE(alert.exited_at, alert.last_detected_at)
                        END - alert.first_detected_at
                    ))
                )::double precision AS presence_duration_seconds
            FROM intrusion_alerts AS alert
            JOIN protected_zones AS zone ON zone.id = alert.zone_id
            JOIN tracks AS track ON track.id = alert.track_id
            LEFT JOIN LATERAL (
                SELECT COUNT(DISTINCT observation.sensor_id) AS contributing_sensors
                FROM track_observations AS link
                JOIN observations AS observation
                    ON observation.id = link.observation_id
                WHERE link.track_id = track.id
                  AND NOT %(closed_only)s
            ) AS sensor_summary ON TRUE
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
                alert.last_detected_at DESC
            LIMIT %(limit)s
            """,
            {
                "include_closed": include_closed,
                "closed_only": closed_only,
                "closed_from": closed_from,
                "closed_before": closed_before,
                "limit": limit,
            },
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
                    zone.name AS zone_name,
                    zone.description AS zone_description,
                    track.id AS track_id,
                    track.last_seen_at AS detected_at,
                    track.track_key,
                    track.identity_key,
                    track.last_basic_id,
                    track.last_operator_id,
                    track.last_drone_mac,
                    sensor.sensor_key,
                    track.last_position,
                    track.last_pilot_position,
                    track.last_altitude_m,
                    track.last_speed_mps,
                    track.last_heading_deg
                FROM protected_zones AS zone
                CROSS JOIN tracks AS track
                LEFT JOIN observations AS observation
                    ON observation.id = track.last_observation_id
                LEFT JOIN sensors AS sensor ON sensor.id = observation.sensor_id
                WHERE zone.active
                  AND zone.deleted_at IS NULL
                  AND track.state IN ('new', 'active', 'anomalous')
                  AND track.last_position IS NOT NULL
                  AND ST_Intersects(zone.area, track.last_position)
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM intrusion_alerts AS open_alert
                          WHERE open_alert.zone_id = zone.id
                            AND open_alert.track_id = track.id
                            AND open_alert.state IN ('active', 'acknowledged')
                      )
                      OR COALESCE(
                          (
                              SELECT previous.presence_state
                              FROM intrusion_alerts AS previous
                              WHERE previous.zone_id = zone.id
                                AND previous.track_id = track.id
                                AND previous.state = 'closed'
                              ORDER BY
                                  previous.closed_at DESC NULLS LAST,
                                  previous.created_at DESC,
                                  previous.id DESC
                              LIMIT 1
                          ),
                          'left'
                      ) <> 'inside'
                  )
            )
            INSERT INTO intrusion_alerts (
                zone_id,
                track_id,
                state,
                severity,
                first_detected_at,
                last_detected_at,
                last_position,
                detection_count,
                presence_state,
                presence_changed_at,
                entry_zone_name,
                entry_zone_description,
                entry_track_key,
                entry_identity_key,
                entry_basic_id,
                entry_operator_id,
                entry_drone_mac,
                entry_sensor_key,
                entry_position,
                entry_pilot_position,
                entry_altitude_m,
                entry_speed_mps,
                entry_heading_deg
            )
            SELECT
                detected.zone_id,
                detected.track_id,
                'active',
                detected.severity,
                detected.detected_at,
                detected.detected_at,
                detected.last_position,
                1,
                'inside',
                detected.detected_at,
                detected.zone_name,
                detected.zone_description,
                detected.track_key,
                detected.identity_key,
                detected.last_basic_id,
                detected.last_operator_id,
                detected.last_drone_mac,
                detected.sensor_key,
                detected.last_position,
                detected.last_pilot_position,
                detected.last_altitude_m,
                detected.last_speed_mps,
                detected.last_heading_deg
            FROM detected
            ON CONFLICT (zone_id, track_id)
                WHERE state IN ('active', 'acknowledged')
            DO UPDATE SET
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
                presence_state = 'inside',
                presence_changed_at = CASE
                    WHEN intrusion_alerts.presence_state <> 'inside'
                        THEN EXCLUDED.last_detected_at
                    ELSE intrusion_alerts.presence_changed_at
                END,
                exited_at = NULL,
                updated_at = NOW()
            WHERE EXCLUDED.last_detected_at > intrusion_alerts.last_detected_at
               OR intrusion_alerts.presence_state <> 'inside'
            """
        )
        detected = cursor.rowcount

        cursor.execute(
            """
            WITH presence AS (
                SELECT
                    alert.id,
                    CASE
                        WHEN track.state IN ('stale', 'ended')
                          OR track.last_position IS NULL
                            THEN 'lost'
                        WHEN NOT zone.active OR zone.deleted_at IS NOT NULL
                            THEN 'left'
                        WHEN ST_Intersects(zone.area, track.last_position)
                            THEN 'inside'
                        ELSE 'left'
                    END AS next_presence
                FROM intrusion_alerts AS alert
                JOIN protected_zones AS zone ON zone.id = alert.zone_id
                JOIN tracks AS track ON track.id = alert.track_id
                WHERE alert.state IN ('active', 'acknowledged')
            )
            UPDATE intrusion_alerts AS alert
            SET
                presence_state = presence.next_presence,
                presence_changed_at = NOW(),
                exited_at = CASE
                    WHEN presence.next_presence = 'inside' THEN NULL
                    ELSE COALESCE(alert.exited_at, NOW())
                END,
                updated_at = NOW()
            FROM presence
            WHERE alert.id = presence.id
              AND alert.presence_state IS DISTINCT FROM presence.next_presence
            """
        )
        presence_changes = cursor.rowcount

        cursor.execute(
            """
            WITH latest_closed AS (
                SELECT DISTINCT ON (alert.zone_id, alert.track_id)
                    alert.id,
                    alert.zone_id,
                    alert.track_id,
                    alert.presence_state
                FROM intrusion_alerts AS alert
                WHERE alert.state = 'closed'
                ORDER BY
                    alert.zone_id,
                    alert.track_id,
                    alert.closed_at DESC NULLS LAST,
                    alert.created_at DESC,
                    alert.id DESC
            ), departed AS (
                SELECT latest.id
                FROM latest_closed AS latest
                JOIN protected_zones AS zone ON zone.id = latest.zone_id
                JOIN tracks AS track ON track.id = latest.track_id
                WHERE latest.presence_state = 'inside'
                  AND (
                      NOT zone.active
                      OR zone.deleted_at IS NOT NULL
                      OR (
                          track.last_position IS NOT NULL
                          AND NOT ST_Intersects(zone.area, track.last_position)
                      )
                  )
            )
            UPDATE intrusion_alerts AS alert
            SET
                presence_state = 'left',
                presence_changed_at = NOW(),
                exited_at = COALESCE(alert.exited_at, NOW()),
                updated_at = NOW()
            FROM departed
            WHERE alert.id = departed.id
              AND alert.presence_state = 'inside'
            """
        )
        closed_departures = cursor.rowcount
        return detected, presence_changes + closed_departures

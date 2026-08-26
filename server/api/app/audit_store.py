from typing import Any, Literal
from uuid import UUID

from app.database import connection

AuditCategory = Literal[
    "all",
    "detections",
    "alerts",
    "zones",
    "sensors",
    "operators",
]


def list_audit_events(
    category: AuditCategory = "all",
    event_type: str | None = None,
    alert_id: UUID | None = None,
    zone_id: UUID | None = None,
    track_id: UUID | None = None,
    sensor_id: UUID | None = None,
    operator_account_id: UUID | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    conditions: list[str] = []
    parameters: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }

    if category == "detections":
        conditions.append("event.event_type LIKE 'track_%%'")
    elif category == "alerts":
        conditions.append("event.event_type LIKE 'alert_%%'")
    elif category == "zones":
        conditions.append("event.event_type LIKE 'zone_%%'")
    elif category == "sensors":
        conditions.append("event.event_type LIKE 'sensor_%%'")
    elif category == "operators":
        conditions.append("event.event_type LIKE 'operator_%%'")

    if event_type is not None:
        conditions.append("event.event_type = %(event_type)s")
        parameters["event_type"] = event_type
    if alert_id is not None:
        conditions.append("event.alert_id = %(alert_id)s")
        parameters["alert_id"] = alert_id
    if zone_id is not None:
        conditions.append("event.zone_id = %(zone_id)s")
        parameters["zone_id"] = zone_id
    if track_id is not None:
        conditions.append("event.track_id = %(track_id)s")
        parameters["track_id"] = track_id
    if sensor_id is not None:
        conditions.append("event.sensor_id = %(sensor_id)s")
        parameters["sensor_id"] = sensor_id
    if operator_account_id is not None:
        conditions.append("event.operator_account_id = %(operator_account_id)s")
        parameters["operator_account_id"] = operator_account_id

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM audit_events AS event
            {where_clause}
            """,
            parameters,
        )
        count_row = cursor.fetchone()
        total = 0 if count_row is None else int(count_row["total"])

        cursor.execute(
            f"""
            SELECT
                event.id,
                event.occurred_at,
                event.event_type,
                event.actor,
                event.details,
                event.alert_id,
                event.zone_id,
                event.track_id,
                event.sensor_id,
                event.operator_account_id,
                alert.state AS alert_state,
                alert.presence_state AS alert_presence_state,
                alert.severity AS alert_severity,
                alert.first_detected_at,
                alert.last_detected_at,
                alert.detection_count,
                COALESCE(alert.entry_zone_name, zone.name) AS zone_name,
                COALESCE(alert.entry_track_key, track.track_key) AS track_key,
                COALESCE(alert.entry_basic_id, track.last_basic_id) AS basic_id,
                COALESCE(alert.entry_identity_key, track.identity_key) AS identity_key,
                COALESCE(alert.entry_operator_id, track.last_operator_id) AS operator_id,
                sensor.sensor_key,
                sensor.display_name AS sensor_name
                , operator_account.username AS account_username
                , operator_account.display_name AS account_display_name
                , operator_account.role AS account_role
            FROM audit_events AS event
            LEFT JOIN intrusion_alerts AS alert ON alert.id = event.alert_id
            LEFT JOIN protected_zones AS zone ON zone.id = event.zone_id
            LEFT JOIN tracks AS track ON track.id = event.track_id
            LEFT JOIN sensors AS sensor ON sensor.id = event.sensor_id
            LEFT JOIN operator_accounts AS operator_account
                ON operator_account.id = event.operator_account_id
            {where_clause}
            ORDER BY event.occurred_at DESC, event.id DESC
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            parameters,
        )
        events = [dict(row) for row in cursor.fetchall()]

    return events, total

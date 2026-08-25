from typing import Any

from app.config import settings
from app.database import connection


def retention_configuration() -> dict[str, Any]:
    return {
        "enabled": settings.retention_enabled,
        "maintenance_interval_seconds": settings.maintenance_interval_seconds,
        "batch_size": settings.retention_batch_size,
        "periods_days": {
            "operator_sessions": settings.retention_sessions_days,
            "sensor_heartbeats": settings.retention_heartbeats_days,
            "observations": settings.retention_observations_days,
            "audit_events": settings.retention_audit_days,
            "closed_alerts": settings.retention_alerts_days,
            "ended_tracks": settings.retention_tracks_days,
        },
    }


def get_maintenance_status() -> dict[str, Any]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id,
                started_at,
                finished_at,
                status,
                trigger_type,
                retention_settings,
                affected_rows,
                error_message
            FROM maintenance_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
        latest_run = cursor.fetchone()

    return {
        "retention": retention_configuration(),
        "latest_run": None if latest_run is None else dict(latest_run),
    }

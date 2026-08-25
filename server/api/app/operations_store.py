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


def get_database_storage() -> dict[str, Any]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_database() AS database_name,
                pg_database_size(current_database()) AS database_size_bytes
            """
        )
        database = cursor.fetchone()
        if database is None:
            raise RuntimeError("Database storage query returned no row")

        cursor.execute(
            """
            SELECT
                schemaname,
                relname AS table_name,
                pg_total_relation_size(relid) AS size_bytes,
                COALESCE(n_live_tup, 0)::BIGINT AS estimated_rows
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 5
            """
        )
        largest_tables = [dict(row) for row in cursor.fetchall()]

    database_size_bytes = int(database["database_size_bytes"])
    capacity_bytes = int(settings.database_capacity_gb * 1024**3)
    used_percent: float | None = None
    storage_status = "unconfigured"

    if capacity_bytes > 0:
        used_percent = round(database_size_bytes / capacity_bytes * 100, 2)
        if used_percent >= 100:
            storage_status = "exceeded"
        elif used_percent >= settings.database_critical_percent:
            storage_status = "critical"
        elif used_percent >= settings.database_warning_percent:
            storage_status = "warning"
        else:
            storage_status = "ok"

    return {
        "database_name": database["database_name"],
        "database_size_bytes": database_size_bytes,
        "capacity_bytes": capacity_bytes or None,
        "used_percent": used_percent,
        "status": storage_status,
        "thresholds": {
            "warning_percent": settings.database_warning_percent,
            "critical_percent": settings.database_critical_percent,
        },
        "largest_tables": largest_tables,
    }

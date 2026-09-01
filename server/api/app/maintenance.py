import argparse
import json
import logging
import time
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.config import settings
from app.database import connection
from app.operations_store import retention_configuration

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("rdds.maintenance")

ADVISORY_LOCK_ID = 724_337_013


def _delete_in_batches(
    cursor: psycopg.Cursor,
    *,
    table: str,
    id_column: str,
    predicate: str,
    parameters: Sequence[Any],
) -> int:
    total = 0
    while True:
        cursor.execute(
            f"""
            WITH candidates AS (
                SELECT {id_column}
                FROM {table}
                WHERE {predicate}
                ORDER BY {id_column}
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            DELETE FROM {table} AS target
            USING candidates
            WHERE target.{id_column} = candidates.{id_column}
            """,
            (*parameters, settings.retention_batch_size),
        )
        deleted = cursor.rowcount
        total += deleted
        if deleted < settings.retention_batch_size:
            return total


def _count_candidate_rows(cursor: psycopg.Cursor) -> dict[str, int]:
    queries: dict[str, tuple[str, tuple[Any, ...]]] = {
        "operator_sessions": (
            """
            SELECT COUNT(*) AS count
            FROM operator_sessions
            WHERE COALESCE(
                revoked_at,
                LEAST(expires_at, idle_expires_at)
            ) < NOW() - make_interval(days => %s)
            """,
            (settings.retention_sessions_days,),
        ),
        "operator_security_events": (
            """
            SELECT COUNT(*) AS count
            FROM operator_security_events
            WHERE occurred_at < NOW() - make_interval(days => %s)
            """,
            (settings.retention_security_events_days,),
        ),
        "audit_events": (
            """
            SELECT COUNT(*) AS count
            FROM audit_events
            WHERE occurred_at < NOW() - make_interval(days => %s)
            """,
            (settings.retention_audit_days,),
        ),
        "closed_sensor_alerts": (
            """
            SELECT COUNT(*) AS count
            FROM sensor_alerts
            WHERE state = 'closed'
              AND closed_at < NOW() - make_interval(days => %s)
            """,
            (settings.retention_alerts_days,),
        ),
        "closed_alerts": (
            """
            SELECT COUNT(*) AS count
            FROM intrusion_alerts
            WHERE state = 'closed'
              AND closed_at < NOW() - make_interval(days => %s)
            """,
            (settings.retention_alerts_days,),
        ),
        "observations": (
            """
            SELECT COUNT(*) AS count
            FROM observations
            WHERE received_at < NOW() - make_interval(days => %s)
            """,
            (settings.retention_observations_days,),
        ),
        "sensor_heartbeats": (
            """
            SELECT COUNT(*) AS count
            FROM sensor_heartbeats
            WHERE received_at < NOW() - make_interval(days => %s)
            """,
            (settings.retention_heartbeats_days,),
        ),
        "ended_tracks": (
            """
            SELECT COUNT(*) AS count
            FROM tracks AS track
            WHERE track.state = 'ended'
              AND track.ended_at < NOW() - make_interval(days => %s)
              AND NOT EXISTS (
                  SELECT 1 FROM intrusion_alerts AS alert
                  WHERE alert.track_id = track.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM audit_events AS event
                  WHERE event.track_id = track.id
              )
            """,
            (settings.retention_tracks_days,),
        ),
    }
    counts: dict[str, int] = {}
    for name, (query, parameters) in queries.items():
        cursor.execute(query, parameters)
        row = cursor.fetchone()
        counts[name] = int(row["count"])
    return counts


def _delete_expired_rows(cursor: psycopg.Cursor) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["operator_sessions"] = _delete_in_batches(
        cursor,
        table="operator_sessions",
        id_column="id",
        predicate="""
            COALESCE(revoked_at, LEAST(expires_at, idle_expires_at))
                < NOW() - make_interval(days => %s)
        """,
        parameters=(settings.retention_sessions_days,),
    )
    counts["operator_security_events"] = _delete_in_batches(
        cursor,
        table="operator_security_events",
        id_column="id",
        predicate="occurred_at < NOW() - make_interval(days => %s)",
        parameters=(settings.retention_security_events_days,),
    )
    counts["audit_events"] = _delete_in_batches(
        cursor,
        table="audit_events",
        id_column="id",
        predicate="occurred_at < NOW() - make_interval(days => %s)",
        parameters=(settings.retention_audit_days,),
    )
    counts["closed_sensor_alerts"] = _delete_in_batches(
        cursor,
        table="sensor_alerts",
        id_column="id",
        predicate="""
            state = 'closed'
            AND closed_at < NOW() - make_interval(days => %s)
        """,
        parameters=(settings.retention_alerts_days,),
    )
    counts["closed_alerts"] = _delete_in_batches(
        cursor,
        table="intrusion_alerts",
        id_column="id",
        predicate="""
            state = 'closed'
            AND closed_at < NOW() - make_interval(days => %s)
        """,
        parameters=(settings.retention_alerts_days,),
    )
    counts["observations"] = _delete_in_batches(
        cursor,
        table="observations",
        id_column="id",
        predicate="received_at < NOW() - make_interval(days => %s)",
        parameters=(settings.retention_observations_days,),
    )
    counts["sensor_heartbeats"] = _delete_in_batches(
        cursor,
        table="sensor_heartbeats",
        id_column="id",
        predicate="received_at < NOW() - make_interval(days => %s)",
        parameters=(settings.retention_heartbeats_days,),
    )
    counts["ended_tracks"] = _delete_in_batches(
        cursor,
        table="tracks",
        id_column="id",
        predicate="""
            state = 'ended'
            AND ended_at < NOW() - make_interval(days => %s)
            AND NOT EXISTS (
                SELECT 1 FROM intrusion_alerts AS alert
                WHERE alert.track_id = tracks.id
            )
            AND NOT EXISTS (
                SELECT 1 FROM audit_events AS event
                WHERE event.track_id = tracks.id
            )
        """,
        parameters=(settings.retention_tracks_days,),
    )
    return counts


def run_once(*, dry_run: bool, trigger_type: str) -> dict[str, Any]:
    configuration = retention_configuration()
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (ADVISORY_LOCK_ID,))
        lock_row = cursor.fetchone()
        if lock_row is None or not lock_row["acquired"]:
            return {"status": "skipped", "reason": "maintenance already running"}

        cursor.execute(
            """
            UPDATE maintenance_runs
            SET
                status = 'failed',
                finished_at = NOW(),
                error_message = 'maintenance worker ended before completion'
            WHERE status = 'running'
            """
        )
        cursor.execute(
            """
            INSERT INTO maintenance_runs (
                status,
                trigger_type,
                retention_settings
            )
            VALUES ('running', %s, %s)
            RETURNING id
            """,
            (trigger_type, Jsonb(configuration)),
        )
        run_row = cursor.fetchone()
        if run_row is None:
            raise RuntimeError("Maintenance run registration returned no row")
        run_id: UUID = run_row["id"]
        conn.commit()

        try:
            affected_rows = (
                _count_candidate_rows(cursor) if dry_run else _delete_expired_rows(cursor)
            )
            final_status = "dry_run" if dry_run else "succeeded"
            cursor.execute(
                """
                UPDATE maintenance_runs
                SET
                    status = %s,
                    finished_at = NOW(),
                    affected_rows = %s
                WHERE id = %s
                """,
                (final_status, Jsonb(affected_rows), run_id),
            )
            conn.commit()
            return {
                "id": str(run_id),
                "status": final_status,
                "affected_rows": affected_rows,
            }
        except Exception as exc:
            conn.rollback()
            message = str(exc)[:4000]
            cursor.execute(
                """
                UPDATE maintenance_runs
                SET
                    status = 'failed',
                    finished_at = NOW(),
                    error_message = %s
                WHERE id = %s
                """,
                (message, run_id),
            )
            conn.commit()
            raise
        finally:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
            conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="RDDS retention maintenance")
    parser.add_argument("--once", action="store_true", help="run once and exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count candidate rows without deleting them",
    )
    args = parser.parse_args()

    if args.once:
        if not settings.retention_enabled and not args.dry_run:
            raise SystemExit(
                "Retention is disabled. Use --dry-run or set "
                "RDDS_RETENTION_ENABLED=true."
            )
        print(json.dumps(run_once(dry_run=args.dry_run, trigger_type="manual")))
        return

    logger.info(
        "Maintenance service started; retention_enabled=%s interval_seconds=%s",
        settings.retention_enabled,
        settings.maintenance_interval_seconds,
    )
    while True:
        if settings.retention_enabled:
            try:
                result = run_once(dry_run=False, trigger_type="scheduled")
                logger.info("Maintenance result: %s", result)
            except (psycopg.Error, RuntimeError):
                logger.exception("Scheduled maintenance failed")
        else:
            logger.info("Retention is disabled; no data was deleted")
        time.sleep(settings.maintenance_interval_seconds)


if __name__ == "__main__":
    main()

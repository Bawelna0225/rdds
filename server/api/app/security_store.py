from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb

from app.config import settings
from app.database import connection

SecurityEventType = Literal[
    "login_succeeded",
    "login_failed",
    "account_locked",
    "session_logged_out",
    "session_revoked",
    "sessions_revoked",
]
SecurityOutcome = Literal["success", "failure"]


def _like_fragment(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def record_security_event(
    cursor: Any,
    *,
    event_type: SecurityEventType,
    outcome: SecurityOutcome,
    severity: Literal["info", "warning", "high"],
    operator_account_id: UUID | None = None,
    session_id: UUID | None = None,
    username: str | None = None,
    actor: str | None = None,
    remote_address: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO operator_security_events (
            event_type,
            outcome,
            severity,
            operator_account_id,
            session_id,
            username,
            actor,
            remote_address,
            user_agent,
            details
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            event_type,
            outcome,
            severity,
            operator_account_id,
            session_id,
            (username or "")[:64] or None,
            (actor or "")[:160] or None,
            (remote_address or "")[:128] or None,
            (user_agent or "")[:512] or None,
            Jsonb(details or {}),
        ),
    )


def list_active_sessions(current_session_id: UUID) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                session.id,
                session.operator_id,
                account.username,
                account.display_name,
                account.role,
                session.created_at,
                session.last_seen_at,
                session.expires_at,
                session.idle_expires_at,
                session.remote_address,
                session.user_agent,
                session.id = %s AS is_current
            FROM operator_sessions AS session
            JOIN operator_accounts AS account ON account.id = session.operator_id
            WHERE session.revoked_at IS NULL
              AND session.expires_at > NOW()
              AND session.idle_expires_at > NOW()
              AND account.enabled
              AND account.deleted_at IS NULL
            ORDER BY session.last_seen_at DESC, session.created_at DESC
            """,
            (current_session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_security_summary() -> dict[str, Any]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM operator_sessions AS session
                    JOIN operator_accounts AS account
                        ON account.id = session.operator_id
                    WHERE session.revoked_at IS NULL
                      AND session.expires_at > NOW()
                      AND session.idle_expires_at > NOW()
                      AND account.enabled
                      AND account.deleted_at IS NULL
                ) AS active_sessions,
                (
                    SELECT COUNT(*)
                    FROM operator_security_events
                    WHERE event_type = 'login_failed'
                      AND occurred_at >= NOW() - make_interval(mins => %s)
                ) AS recent_failures,
                (
                    SELECT COUNT(DISTINCT username)
                    FROM operator_security_events
                    WHERE event_type = 'login_failed'
                      AND username IS NOT NULL
                      AND occurred_at >= NOW() - make_interval(mins => %s)
                ) AS affected_usernames,
                (
                    SELECT COUNT(DISTINCT remote_address)
                    FROM operator_security_events
                    WHERE event_type = 'login_failed'
                      AND remote_address IS NOT NULL
                      AND occurred_at >= NOW() - make_interval(mins => %s)
                ) AS source_addresses,
                (
                    SELECT COUNT(*)
                    FROM operator_accounts
                    WHERE locked_until > NOW()
                      AND deleted_at IS NULL
                ) AS locked_accounts
            """,
            (
                settings.security_failure_window_minutes,
                settings.security_failure_window_minutes,
                settings.security_failure_window_minutes,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Security summary query returned no row")
        summary = dict(row)

    recent_failures = int(summary["recent_failures"])
    summary.update(
        {
            "failure_window_minutes": settings.security_failure_window_minutes,
            "failure_alert_count": settings.security_failure_alert_count,
            "alert_active": recent_failures >= settings.security_failure_alert_count,
        }
    )
    return summary


def list_security_events(
    *,
    event_type: SecurityEventType | None = None,
    outcome: SecurityOutcome | None = None,
    username: str | None = None,
    occurred_after: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    conditions: list[str] = []
    parameters: dict[str, Any] = {"limit": limit, "offset": offset}
    if event_type is not None:
        conditions.append("event.event_type = %(event_type)s")
        parameters["event_type"] = event_type
    if outcome is not None:
        conditions.append("event.outcome = %(outcome)s")
        parameters["outcome"] = outcome
    if username:
        conditions.append("event.username ILIKE %(username)s ESCAPE E'\\\\'")
        parameters["username"] = f"%{_like_fragment(username.strip()[:64])}%"
    if occurred_after is not None:
        conditions.append("event.occurred_at >= %(occurred_after)s")
        parameters["occurred_after"] = occurred_after

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM operator_security_events AS event
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
                event.outcome,
                event.severity,
                event.operator_account_id,
                event.session_id,
                event.username,
                event.actor,
                event.remote_address,
                event.user_agent,
                event.details,
                account.display_name AS account_display_name,
                account.role AS account_role
            FROM operator_security_events AS event
            LEFT JOIN operator_accounts AS account
                ON account.id = event.operator_account_id
            {where_clause}
            ORDER BY event.occurred_at DESC, event.id DESC
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            parameters,
        )
        return [dict(row) for row in cursor.fetchall()], total


def _audit_session_action(
    cursor: Any,
    *,
    event_type: Literal["operator_session_revoked", "operator_sessions_revoked"],
    actor: str,
    account_id: UUID,
    details: dict[str, Any],
) -> None:
    cursor.execute(
        """
        INSERT INTO audit_events (
            event_type, actor, operator_account_id, details
        )
        VALUES (%s, %s, %s, %s)
        """,
        (event_type, actor, account_id, Jsonb(details)),
    )


def record_security_export(
    *,
    actor: str,
    actor_id: UUID,
    export_format: Literal["csv", "json"],
    exported_rows: int,
    filters: dict[str, Any],
) -> None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO audit_events (
                event_type, actor, operator_account_id, details
            )
            VALUES ('operator_security_exported', %s, %s, %s)
            """,
            (
                actor,
                actor_id,
                Jsonb(
                    {
                        "format": export_format,
                        "exported_rows": exported_rows,
                        "filters": filters,
                    }
                ),
            ),
        )


def revoke_managed_session(
    *,
    session_id: UUID,
    current_session_id: UUID,
    actor_id: UUID,
    actor: str,
) -> Literal["revoked", "current", "inactive", "not_found"]:
    if session_id == current_session_id:
        return "current"
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                session.id,
                session.operator_id,
                session.revoked_at,
                session.expires_at,
                session.idle_expires_at,
                account.username
            FROM operator_sessions AS session
            JOIN operator_accounts AS account ON account.id = session.operator_id
            WHERE session.id = %s
            FOR UPDATE OF session
            """,
            (session_id,),
        )
        session = cursor.fetchone()
        if session is None:
            return "not_found"
        if (
            session["revoked_at"] is not None
            or session["expires_at"] <= datetime.now(session["expires_at"].tzinfo)
            or session["idle_expires_at"] <= datetime.now(session["idle_expires_at"].tzinfo)
        ):
            return "inactive"
        cursor.execute(
            """
            UPDATE operator_sessions
            SET
                revoked_at = NOW(),
                revoked_by_account_id = %s,
                revoked_by = %s,
                revoke_reason = 'administrator'
            WHERE id = %s AND revoked_at IS NULL
            """,
            (actor_id, actor, session_id),
        )
        details = {
            "target_username": session["username"],
        }
        record_security_event(
            cursor,
            event_type="session_revoked",
            outcome="success",
            severity="warning",
            operator_account_id=session["operator_id"],
            session_id=session_id,
            username=session["username"],
            actor=actor,
            details=details,
        )
        _audit_session_action(
            cursor,
            event_type="operator_session_revoked",
            actor=actor,
            account_id=session["operator_id"],
            details=details,
        )
    return "revoked"


def revoke_operator_sessions(
    *,
    operator_id: UUID,
    current_session_id: UUID,
    actor_id: UUID,
    actor: str,
) -> int | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT username
            FROM operator_accounts
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (operator_id,),
        )
        account = cursor.fetchone()
        if account is None:
            return None
        cursor.execute(
            """
            UPDATE operator_sessions
            SET
                revoked_at = NOW(),
                revoked_by_account_id = %s,
                revoked_by = %s,
                revoke_reason = 'administrator_bulk'
            WHERE operator_id = %s
              AND id <> %s
              AND revoked_at IS NULL
              AND expires_at > NOW()
              AND idle_expires_at > NOW()
            """,
            (actor_id, actor, operator_id, current_session_id),
        )
        revoked_count = cursor.rowcount
        details = {
            "target_username": account["username"],
            "revoked_sessions": revoked_count,
            "current_session_preserved": operator_id == actor_id,
        }
        record_security_event(
            cursor,
            event_type="sessions_revoked",
            outcome="success",
            severity="warning",
            operator_account_id=operator_id,
            username=account["username"],
            actor=actor,
            details=details,
        )
        _audit_session_action(
            cursor,
            event_type="operator_sessions_revoked",
            actor=actor,
            account_id=operator_id,
            details=details,
        )
        return revoked_count

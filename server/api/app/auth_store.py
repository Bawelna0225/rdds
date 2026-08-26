import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from psycopg.types.json import Jsonb

from app.config import settings
from app.database import connection
from app.models import OperatorCreate, OperatorPasswordReset, OperatorUpdate
from app.security_store import record_security_event

PASSWORD_HASHER = PasswordHasher()
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("RDDS-dummy-password-never-valid")


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def _public_account(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "enabled": row["enabled"],
        "must_change_password": row["must_change_password"],
        "last_login_at": row.get("last_login_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _audit(
    cursor: Any,
    event_type: str,
    actor: str,
    account_id: UUID,
    details: dict[str, Any] | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO audit_events (
            event_type, actor, operator_account_id, details
        )
        VALUES (%s, %s, %s, %s)
        """,
        (event_type, actor, account_id, Jsonb(details or {})),
    )


def _revoke_account_sessions(
    cursor: Any,
    *,
    account_id: UUID,
    username: str,
    actor: str,
    reason: str,
    exclude_session_id: UUID | None = None,
) -> int:
    cursor.execute(
        """
        UPDATE operator_sessions
        SET
            revoked_at = NOW(),
            revoked_by = %s,
            revoke_reason = %s
        WHERE operator_id = %s
          AND (%s::uuid IS NULL OR id <> %s::uuid)
          AND revoked_at IS NULL
          AND expires_at > NOW()
          AND idle_expires_at > NOW()
        """,
        (actor, reason, account_id, exclude_session_id, exclude_session_id),
    )
    revoked_count = cursor.rowcount
    if revoked_count:
        record_security_event(
            cursor,
            event_type="sessions_revoked",
            outcome="success",
            severity="warning",
            operator_account_id=account_id,
            username=username,
            actor=actor,
            details={"reason": reason, "revoked_sessions": revoked_count},
        )
    return revoked_count


def authenticate_login(
    username: str,
    password: str,
    user_agent: str | None,
    remote_address: str | None,
) -> tuple[dict[str, Any], str, str, datetime] | None:
    normalized = username.strip().lower()
    now = datetime.now(timezone.utc)

    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM operator_sessions
            WHERE created_at < NOW() - INTERVAL '30 days'
              AND (
                  revoked_at IS NOT NULL
                  OR expires_at <= NOW()
                  OR idle_expires_at <= NOW()
              )
            """
        )
        cursor.execute(
            """
            SELECT *
            FROM operator_accounts
            WHERE username = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (normalized,),
        )
        row = cursor.fetchone()
        if row is None:
            verify_password(DUMMY_PASSWORD_HASH, password)
            record_security_event(
                cursor,
                event_type="login_failed",
                outcome="failure",
                severity="warning",
                username=normalized,
                remote_address=remote_address,
                user_agent=user_agent,
                details={"reason": "unknown_account"},
            )
            return None

        password_valid = verify_password(row["password_hash"], password)
        if not row["enabled"]:
            record_security_event(
                cursor,
                event_type="login_failed",
                outcome="failure",
                severity="warning",
                operator_account_id=row["id"],
                username=normalized,
                remote_address=remote_address,
                user_agent=user_agent,
                details={"reason": "account_disabled"},
            )
            return None
        if row["locked_until"] is not None and row["locked_until"] > now:
            record_security_event(
                cursor,
                event_type="login_failed",
                outcome="failure",
                severity="high",
                operator_account_id=row["id"],
                username=normalized,
                remote_address=remote_address,
                user_agent=user_agent,
                details={"reason": "account_locked"},
            )
            return None
        if not password_valid:
            failed_count = int(row["failed_login_count"]) + 1
            locked_until = None
            if failed_count >= settings.login_max_failures:
                failed_count = 0
                locked_until = now + timedelta(seconds=settings.login_lock_seconds)
            cursor.execute(
                """
                UPDATE operator_accounts
                SET failed_login_count = %s, locked_until = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (failed_count, locked_until, row["id"]),
            )
            record_security_event(
                cursor,
                event_type="login_failed",
                outcome="failure",
                severity="warning" if locked_until is None else "high",
                operator_account_id=row["id"],
                username=normalized,
                remote_address=remote_address,
                user_agent=user_agent,
                details={
                    "reason": "invalid_credentials",
                    "account_locked": locked_until is not None,
                },
            )
            if locked_until is not None:
                record_security_event(
                    cursor,
                    event_type="account_locked",
                    outcome="failure",
                    severity="high",
                    operator_account_id=row["id"],
                    username=normalized,
                    remote_address=remote_address,
                    user_agent=user_agent,
                    details={"locked_until": locked_until.isoformat()},
                )
            return None

        password_hash = row["password_hash"]
        if PASSWORD_HASHER.check_needs_rehash(password_hash):
            password_hash = hash_password(password)

        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        csrf_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(seconds=settings.session_absolute_seconds)
        idle_expires_at = min(
            expires_at,
            now + timedelta(seconds=settings.session_idle_seconds),
        )
        cursor.execute(
            """
            UPDATE operator_accounts
            SET
                password_hash = %s,
                failed_login_count = 0,
                locked_until = NULL,
                last_login_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (password_hash, row["id"]),
        )
        account = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO operator_sessions (
                operator_id,
                token_hash,
                csrf_token,
                expires_at,
                idle_expires_at,
                user_agent,
                remote_address
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                row["id"],
                token_hash,
                csrf_token,
                expires_at,
                idle_expires_at,
                (user_agent or "")[:512] or None,
                (remote_address or "")[:128] or None,
            ),
        )
        session = cursor.fetchone()
        if session is None:
            raise RuntimeError("Authenticated session could not be read")
        record_security_event(
            cursor,
            event_type="login_succeeded",
            outcome="success",
            severity="info",
            operator_account_id=row["id"],
            session_id=session["id"],
            username=normalized,
            actor=normalized,
            remote_address=remote_address,
            user_agent=user_agent,
        )
        _audit(cursor, "operator_logged_in", normalized, row["id"])
        if account is None:
            raise RuntimeError("Authenticated account could not be read")
        return _public_account(dict(account)), raw_token, csrf_token, expires_at


def read_session(raw_token: str) -> dict[str, Any] | None:
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                session.id AS session_id,
                session.csrf_token,
                session.expires_at,
                account.*
            FROM operator_sessions AS session
            JOIN operator_accounts AS account ON account.id = session.operator_id
            WHERE session.token_hash = %s
              AND session.revoked_at IS NULL
              AND session.expires_at > NOW()
              AND session.idle_expires_at > NOW()
              AND account.enabled
              AND account.deleted_at IS NULL
            FOR UPDATE OF session
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        cursor.execute(
            """
            UPDATE operator_sessions
            SET
                last_seen_at = NOW(),
                idle_expires_at = LEAST(
                    expires_at,
                    NOW() + make_interval(secs => %s)
                )
            WHERE id = %s
            """,
            (settings.session_idle_seconds, row["session_id"]),
        )
        result = _public_account(dict(row))
        result.update(
            {
                "session_id": row["session_id"],
                "csrf_token": row["csrf_token"],
                "expires_at": row["expires_at"],
            }
        )
        return result


def revoke_session(session_id: UUID, actor: str, account_id: UUID) -> None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE operator_sessions
            SET
                revoked_at = COALESCE(revoked_at, NOW()),
                revoked_by = COALESCE(revoked_by, %s),
                revoke_reason = COALESCE(revoke_reason, 'logout')
            WHERE id = %s
            """,
            (actor, session_id),
        )
        record_security_event(
            cursor,
            event_type="session_logged_out",
            outcome="success",
            severity="info",
            operator_account_id=account_id,
            session_id=session_id,
            username=actor,
            actor=actor,
        )
        _audit(cursor, "operator_logged_out", actor, account_id)


def change_password(
    account_id: UUID,
    session_id: UUID,
    actor: str,
    current_password: str,
    new_password: str,
) -> bool:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT password_hash
            FROM operator_accounts
            WHERE id = %s AND enabled AND deleted_at IS NULL
            FOR UPDATE
            """,
            (account_id,),
        )
        row = cursor.fetchone()
        if row is None or not verify_password(row["password_hash"], current_password):
            return False
        cursor.execute(
            """
            UPDATE operator_accounts
            SET
                password_hash = %s,
                must_change_password = FALSE,
                password_changed_at = NOW(),
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (hash_password(new_password), actor, account_id),
        )
        _revoke_account_sessions(
            cursor,
            account_id=account_id,
            username=actor,
            actor=actor,
            reason="password_change",
            exclude_session_id=session_id,
        )
        _audit(cursor, "operator_password_changed", actor, account_id)
        return True


def list_accounts() -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT *
            FROM operator_accounts
            WHERE deleted_at IS NULL
            ORDER BY role DESC, username
            """
        )
        return [_public_account(dict(row)) for row in cursor.fetchall()]


def create_account(payload: OperatorCreate, actor: str) -> dict[str, Any]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO operator_accounts (
                username, display_name, password_hash, role,
                created_by, updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                payload.username,
                payload.display_name,
                hash_password(payload.temporary_password),
                payload.role,
                actor,
                actor,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Created operator account could not be read")
        _audit(
            cursor,
            "operator_created",
            actor,
            row["id"],
            {"username": row["username"], "role": row["role"]},
        )
        return _public_account(dict(row))


def _active_administrator_count(cursor: Any, excluded_id: UUID | None = None) -> int:
    cursor.execute(
        """
        SELECT id
        FROM operator_accounts
        WHERE role = 'administrator'
          AND enabled
          AND deleted_at IS NULL
          AND (%s::uuid IS NULL OR id <> %s::uuid)
        FOR UPDATE
        """,
        (excluded_id, excluded_id),
    )
    return len(cursor.fetchall())


def update_account(
    account_id: UUID,
    payload: OperatorUpdate,
    actor: str,
) -> dict[str, Any] | Literal["last_administrator"] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT * FROM operator_accounts
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (account_id,),
        )
        current = cursor.fetchone()
        if current is None:
            return None
        if (
            current["role"] == "administrator"
            and payload.role != "administrator"
            and _active_administrator_count(cursor, account_id) == 0
        ):
            return "last_administrator"
        cursor.execute(
            """
            UPDATE operator_accounts
            SET display_name = %s, role = %s, updated_by = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.display_name, payload.role, actor, account_id),
        )
        row = cursor.fetchone()
        if payload.role != current["role"]:
            _revoke_account_sessions(
                cursor,
                account_id=account_id,
                username=current["username"],
                actor=actor,
                reason="role_changed",
            )
        _audit(
            cursor,
            "operator_updated",
            actor,
            account_id,
            {"role": payload.role, "display_name": payload.display_name},
        )
        return None if row is None else _public_account(dict(row))


def set_account_enabled(
    account_id: UUID,
    enabled: bool,
    actor: str,
) -> dict[str, Any] | Literal["last_administrator"] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT * FROM operator_accounts
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (account_id,),
        )
        current = cursor.fetchone()
        if current is None:
            return None
        if (
            not enabled
            and current["role"] == "administrator"
            and current["enabled"]
            and _active_administrator_count(cursor, account_id) == 0
        ):
            return "last_administrator"
        cursor.execute(
            """
            UPDATE operator_accounts
            SET enabled = %s, updated_by = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (enabled, actor, account_id),
        )
        row = cursor.fetchone()
        if not enabled:
            _revoke_account_sessions(
                cursor,
                account_id=account_id,
                username=current["username"],
                actor=actor,
                reason="account_disabled",
            )
        _audit(
            cursor,
            "operator_enabled" if enabled else "operator_disabled",
            actor,
            account_id,
        )
        return None if row is None else _public_account(dict(row))


def reset_account_password(
    account_id: UUID,
    payload: OperatorPasswordReset,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE operator_accounts
            SET
                password_hash = %s,
                must_change_password = TRUE,
                password_changed_at = NOW(),
                failed_login_count = 0,
                locked_until = NULL,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (hash_password(payload.temporary_password), actor, account_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        _revoke_account_sessions(
            cursor,
            account_id=account_id,
            username=row["username"],
            actor=actor,
            reason="password_reset",
        )
        _audit(cursor, "operator_password_changed", actor, account_id, {"reset": True})
        return _public_account(dict(row))


def delete_account(
    account_id: UUID,
    actor: str,
) -> dict[str, Any] | Literal["last_administrator"] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT * FROM operator_accounts
            WHERE id = %s AND deleted_at IS NULL
            FOR UPDATE
            """,
            (account_id,),
        )
        current = cursor.fetchone()
        if current is None:
            return None
        if (
            current["role"] == "administrator"
            and current["enabled"]
            and _active_administrator_count(cursor, account_id) == 0
        ):
            return "last_administrator"
        cursor.execute(
            """
            UPDATE operator_accounts
            SET
                enabled = FALSE,
                deleted_at = NOW(),
                deleted_by = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (actor, actor, account_id),
        )
        row = cursor.fetchone()
        _revoke_account_sessions(
            cursor,
            account_id=account_id,
            username=current["username"],
            actor=actor,
            reason="account_deleted",
        )
        _audit(
            cursor,
            "operator_deleted",
            actor,
            account_id,
            {"username": current["username"]},
        )
        return None if row is None else _public_account(dict(row))


def create_bootstrap_administrator(
    username: str,
    display_name: str,
    password: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('rdds-bootstrap-admin'))")
        cursor.execute(
            """
            SELECT 1 FROM operator_accounts
            WHERE role = 'administrator' AND deleted_at IS NULL
            FOR UPDATE
            """
        )
        if cursor.fetchone() is not None:
            return None
        cursor.execute(
            """
            INSERT INTO operator_accounts (
                username, display_name, password_hash, role,
                must_change_password, created_by, updated_by
            )
            VALUES (%s, %s, %s, 'administrator', FALSE, 'bootstrap', 'bootstrap')
            RETURNING *
            """,
            (username, display_name, hash_password(password)),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Bootstrap administrator could not be read")
        _audit(
            cursor,
            "operator_created",
            "bootstrap",
            row["id"],
            {"username": username, "role": "administrator"},
        )
        return _public_account(dict(row))

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.database import connection
from app.models import (
    SensorAgentReleaseAction,
    SensorAgentReleaseCreate,
    SensorAgentReleaseUpdate,
)


class AgentReleaseConflict(RuntimeError):
    pass


RELEASE_COLUMNS = """
    release.id,
    release.version,
    release.revision,
    release.channel,
    release.status,
    release.artifact_filename,
    release.artifact_sha256,
    release.artifact_size_bytes,
    release.minimum_agent_version,
    release.protocol_version,
    release.release_notes,
    release.created_at,
    release.created_by,
    release.updated_at,
    release.updated_by,
    release.published_at,
    release.published_by,
    release.withdrawn_at,
    release.withdrawn_by,
    release.withdrawal_reason
"""


def _read_release(
    cursor: Any,
    release_id: UUID,
    *,
    for_update: bool = False,
) -> dict[str, Any] | None:
    lock = " FOR UPDATE" if for_update else ""
    cursor.execute(
        f"""
        SELECT {RELEASE_COLUMNS}
        FROM sensor_agent_releases AS release
        WHERE release.id = %s{lock}
        """,
        (release_id,),
    )
    row = cursor.fetchone()
    return None if row is None else dict(row)


def _metadata_from_payload(
    payload: SensorAgentReleaseCreate | SensorAgentReleaseUpdate,
) -> dict[str, Any]:
    return payload.model_dump(
        mode="json",
        exclude={"expected_revision", "change_note"},
    )


def _audit_metadata(release: dict[str, Any]) -> str:
    return json.dumps(
        {
            "version": release["version"],
            "revision": release["revision"],
            "channel": release["channel"],
            "status": release["status"],
            "artifact_filename": release["artifact_filename"],
            "artifact_sha256": release["artifact_sha256"],
            "artifact_size_bytes": release["artifact_size_bytes"],
            "minimum_agent_version": release["minimum_agent_version"],
            "protocol_version": release["protocol_version"],
            "release_notes": release["release_notes"],
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def list_sensor_agent_releases(
    *,
    include_withdrawn: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)::BIGINT AS total
            FROM sensor_agent_releases
            WHERE (%s OR status <> 'withdrawn')
            """,
            (include_withdrawn,),
        )
        total_row = cursor.fetchone()
        total = 0 if total_row is None else int(total_row["total"])
        cursor.execute(
            f"""
            SELECT {RELEASE_COLUMNS}
            FROM sensor_agent_releases AS release
            WHERE (%(include_withdrawn)s OR release.status <> 'withdrawn')
            ORDER BY
                CASE release.status
                    WHEN 'published' THEN 0
                    WHEN 'draft' THEN 1
                    ELSE 2
                END,
                release.created_at DESC,
                release.version DESC
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            {
                "include_withdrawn": include_withdrawn,
                "limit": limit,
                "offset": offset,
            },
        )
        releases = [dict(row) for row in cursor.fetchall()]
    return releases, total


def get_sensor_agent_release(release_id: UUID) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        return _read_release(cursor, release_id)


def create_sensor_agent_release(
    *,
    payload: SensorAgentReleaseCreate,
    actor: str,
) -> dict[str, Any]:
    metadata = _metadata_from_payload(payload)
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO sensor_agent_releases (
                version,
                channel,
                artifact_filename,
                artifact_sha256,
                artifact_size_bytes,
                minimum_agent_version,
                protocol_version,
                release_notes,
                created_by,
                updated_by
            )
            VALUES (
                %(version)s,
                %(channel)s,
                %(artifact_filename)s,
                %(artifact_sha256)s,
                %(artifact_size_bytes)s,
                %(minimum_agent_version)s,
                %(protocol_version)s,
                %(release_notes)s,
                %(actor)s,
                %(actor)s
            )
            RETURNING id
            """,
            {**metadata, "actor": actor},
        )
        created = cursor.fetchone()
        if created is None:
            raise RuntimeError("Sensor agent release insert returned no row")
        release_id = created["id"]
        release = _read_release(cursor, release_id)
        if release is None:
            raise RuntimeError("Created sensor agent release could not be read")
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_agent_release_created',
                %(actor)s,
                jsonb_build_object(
                    'release_id', %(release_id)s::uuid,
                    'release', %(release)s::jsonb,
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "actor": actor,
                "release_id": release_id,
                "release": _audit_metadata(release),
                "change_note": payload.change_note,
            },
        )
        return release


def update_sensor_agent_release(
    *,
    release_id: UUID,
    payload: SensorAgentReleaseUpdate,
    actor: str,
) -> dict[str, Any] | None:
    metadata = _metadata_from_payload(payload)
    with connection() as conn, conn.cursor() as cursor:
        before = _read_release(cursor, release_id, for_update=True)
        if before is None:
            return None
        if before["status"] != "draft":
            raise AgentReleaseConflict(
                "published or withdrawn release metadata is immutable"
            )
        if before["revision"] != payload.expected_revision:
            raise AgentReleaseConflict(
                "agent release changed; refresh before saving"
            )
        cursor.execute(
            """
            UPDATE sensor_agent_releases
            SET
                version = %(version)s,
                revision = revision + 1,
                channel = %(channel)s,
                artifact_filename = %(artifact_filename)s,
                artifact_sha256 = %(artifact_sha256)s,
                artifact_size_bytes = %(artifact_size_bytes)s,
                minimum_agent_version = %(minimum_agent_version)s,
                protocol_version = %(protocol_version)s,
                release_notes = %(release_notes)s,
                updated_at = NOW(),
                updated_by = %(actor)s
            WHERE id = %(release_id)s
              AND revision = %(expected_revision)s
              AND status = 'draft'
            RETURNING id
            """,
            {
                **metadata,
                "release_id": release_id,
                "expected_revision": payload.expected_revision,
                "actor": actor,
            },
        )
        if cursor.fetchone() is None:
            raise AgentReleaseConflict(
                "agent release changed; refresh before saving"
            )
        after = _read_release(cursor, release_id)
        if after is None:
            raise RuntimeError("Updated sensor agent release could not be read")
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_agent_release_updated',
                %(actor)s,
                jsonb_build_object(
                    'release_id', %(release_id)s::uuid,
                    'before', %(before)s::jsonb,
                    'after', %(after)s::jsonb,
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "actor": actor,
                "release_id": release_id,
                "before": _audit_metadata(before),
                "after": _audit_metadata(after),
                "change_note": payload.change_note,
            },
        )
        return after


def publish_sensor_agent_release(
    *,
    release_id: UUID,
    payload: SensorAgentReleaseAction,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        before = _read_release(cursor, release_id, for_update=True)
        if before is None:
            return None
        if before["status"] != "draft":
            raise AgentReleaseConflict("only a draft release can be published")
        if before["revision"] != payload.expected_revision:
            raise AgentReleaseConflict(
                "agent release changed; refresh before publishing"
            )
        cursor.execute(
            """
            UPDATE sensor_agent_releases
            SET
                status = 'published',
                revision = revision + 1,
                updated_at = NOW(),
                updated_by = %(actor)s,
                published_at = NOW(),
                published_by = %(actor)s
            WHERE id = %(release_id)s
              AND revision = %(expected_revision)s
              AND status = 'draft'
            RETURNING id
            """,
            {
                "release_id": release_id,
                "expected_revision": payload.expected_revision,
                "actor": actor,
            },
        )
        if cursor.fetchone() is None:
            raise AgentReleaseConflict(
                "agent release changed; refresh before publishing"
            )
        after = _read_release(cursor, release_id)
        if after is None:
            raise RuntimeError("Published sensor agent release could not be read")
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_agent_release_published',
                %(actor)s,
                jsonb_build_object(
                    'release_id', %(release_id)s::uuid,
                    'version', %(version)s::text,
                    'from_revision', %(from_revision)s::bigint,
                    'revision', %(revision)s::bigint,
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "actor": actor,
                "release_id": release_id,
                "version": after["version"],
                "from_revision": before["revision"],
                "revision": after["revision"],
                "change_note": payload.change_note,
            },
        )
        return after


def withdraw_sensor_agent_release(
    *,
    release_id: UUID,
    payload: SensorAgentReleaseAction,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        before = _read_release(cursor, release_id, for_update=True)
        if before is None:
            return None
        if before["status"] != "published":
            raise AgentReleaseConflict("only a published release can be withdrawn")
        if before["revision"] != payload.expected_revision:
            raise AgentReleaseConflict(
                "agent release changed; refresh before withdrawing"
            )
        cursor.execute(
            """
            UPDATE sensor_agent_releases
            SET
                status = 'withdrawn',
                revision = revision + 1,
                updated_at = NOW(),
                updated_by = %(actor)s,
                withdrawn_at = NOW(),
                withdrawn_by = %(actor)s,
                withdrawal_reason = %(change_note)s
            WHERE id = %(release_id)s
              AND revision = %(expected_revision)s
              AND status = 'published'
            RETURNING id
            """,
            {
                "release_id": release_id,
                "expected_revision": payload.expected_revision,
                "change_note": payload.change_note,
                "actor": actor,
            },
        )
        if cursor.fetchone() is None:
            raise AgentReleaseConflict(
                "agent release changed; refresh before withdrawing"
            )
        after = _read_release(cursor, release_id)
        if after is None:
            raise RuntimeError("Withdrawn sensor agent release could not be read")
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_agent_release_withdrawn',
                %(actor)s,
                jsonb_build_object(
                    'release_id', %(release_id)s::uuid,
                    'version', %(version)s::text,
                    'from_revision', %(from_revision)s::bigint,
                    'revision', %(revision)s::bigint,
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "actor": actor,
                "release_id": release_id,
                "version": after["version"],
                "from_revision": before["revision"],
                "revision": after["revision"],
                "change_note": payload.change_note,
            },
        )
        return after

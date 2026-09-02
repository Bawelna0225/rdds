from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.database import connection
from app.models import (
    SensorConfigurationProfileCreate,
    SensorConfigurationProfileUpdate,
    SensorConfigurationProfileVersionCreate,
)


PROFILE_COLUMNS = """
    profile.id,
    profile.profile_key,
    profile.display_name,
    profile.description,
    profile.enabled,
    profile.current_version,
    current.id AS current_version_id,
    current.configuration AS current_configuration,
    current.change_note AS current_change_note,
    current.created_at AS current_version_created_at,
    current.created_by AS current_version_created_by,
    version_count.total AS version_count,
    profile.created_at,
    profile.created_by,
    profile.updated_at,
    profile.updated_by
"""

PROFILE_JOINS = """
    JOIN sensor_configuration_profile_versions AS current
      ON current.profile_id = profile.id
     AND current.version = profile.current_version
    JOIN LATERAL (
        SELECT COUNT(*)::bigint AS total
        FROM sensor_configuration_profile_versions AS version
        WHERE version.profile_id = profile.id
    ) AS version_count ON TRUE
"""


def _configuration_json(configuration: Any) -> str:
    return json.dumps(
        configuration.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    )


def _read_profile(cursor: Any, profile_id: UUID) -> dict[str, Any] | None:
    cursor.execute(
        f"""
        SELECT {PROFILE_COLUMNS}
        FROM sensor_configuration_profiles AS profile
        {PROFILE_JOINS}
        WHERE profile.id = %s
        """,
        (profile_id,),
    )
    row = cursor.fetchone()
    return None if row is None else dict(row)


def list_sensor_configuration_profiles(
    *,
    include_disabled: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)::bigint AS total
            FROM sensor_configuration_profiles
            WHERE (%s OR enabled)
            """,
            (include_disabled,),
        )
        total_row = cursor.fetchone()
        total = 0 if total_row is None else int(total_row["total"])
        cursor.execute(
            f"""
            SELECT {PROFILE_COLUMNS}
            FROM sensor_configuration_profiles AS profile
            {PROFILE_JOINS}
            WHERE (%(include_disabled)s OR profile.enabled)
            ORDER BY profile.display_name, profile.profile_key
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            {
                "include_disabled": include_disabled,
                "limit": limit,
                "offset": offset,
            },
        )
        return [dict(row) for row in cursor.fetchall()], total


def get_sensor_configuration_profile(profile_id: UUID) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        return _read_profile(cursor, profile_id)


def list_sensor_configuration_profile_versions(
    *,
    profile_id: UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT current_version
            FROM sensor_configuration_profiles
            WHERE id = %s
            """,
            (profile_id,),
        )
        if cursor.fetchone() is None:
            return None
        cursor.execute(
            """
            SELECT COUNT(*)::bigint AS total
            FROM sensor_configuration_profile_versions
            WHERE profile_id = %s
            """,
            (profile_id,),
        )
        total_row = cursor.fetchone()
        total = 0 if total_row is None else int(total_row["total"])
        cursor.execute(
            """
            SELECT
                id,
                profile_id,
                version,
                configuration,
                change_note,
                created_at,
                created_by
            FROM sensor_configuration_profile_versions
            WHERE profile_id = %(profile_id)s
            ORDER BY version DESC
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            {
                "profile_id": profile_id,
                "limit": limit,
                "offset": offset,
            },
        )
        return [dict(row) for row in cursor.fetchall()], total


def create_sensor_configuration_profile(
    *,
    payload: SensorConfigurationProfileCreate,
    actor: str,
) -> dict[str, Any]:
    configuration = _configuration_json(payload.configuration)
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO sensor_configuration_profiles (
                profile_key,
                display_name,
                description,
                enabled,
                current_version,
                created_by,
                updated_by
            )
            VALUES (
                %(profile_key)s,
                %(display_name)s,
                %(description)s,
                TRUE,
                1,
                %(actor)s,
                %(actor)s
            )
            RETURNING id
            """,
            {
                "profile_key": payload.profile_key,
                "display_name": payload.display_name,
                "description": payload.description,
                "actor": actor,
            },
        )
        created = cursor.fetchone()
        if created is None:
            raise RuntimeError("Configuration profile insert returned no row")
        profile_id = created["id"]
        cursor.execute(
            """
            INSERT INTO sensor_configuration_profile_versions (
                profile_id,
                version,
                configuration,
                change_note,
                created_by
            )
            VALUES (
                %(profile_id)s,
                1,
                %(configuration)s::jsonb,
                %(change_note)s,
                %(actor)s
            )
            """,
            {
                "profile_id": profile_id,
                "configuration": configuration,
                "change_note": payload.change_note,
                "actor": actor,
            },
        )
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_configuration_profile_created',
                %(actor)s,
                jsonb_build_object(
                    'profile_id', %(profile_id)s::uuid,
                    'profile_key', %(profile_key)s::text,
                    'version', 1,
                    'configuration', %(configuration)s::jsonb,
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "actor": actor,
                "profile_id": profile_id,
                "profile_key": payload.profile_key,
                "configuration": configuration,
                "change_note": payload.change_note,
            },
        )
        profile = _read_profile(cursor, profile_id)
        if profile is None:
            raise RuntimeError("Created configuration profile could not be read")
        return profile


def update_sensor_configuration_profile(
    *,
    profile_id: UUID,
    payload: SensorConfigurationProfileUpdate,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT profile_key, display_name, description, enabled
            FROM sensor_configuration_profiles
            WHERE id = %s
            FOR UPDATE
            """,
            (profile_id,),
        )
        previous = cursor.fetchone()
        if previous is None:
            return None
        cursor.execute(
            """
            UPDATE sensor_configuration_profiles
            SET
                display_name = %(display_name)s,
                description = %(description)s,
                enabled = %(enabled)s,
                updated_at = NOW(),
                updated_by = %(actor)s
            WHERE id = %(profile_id)s
            """,
            {
                "profile_id": profile_id,
                "display_name": payload.display_name,
                "description": payload.description,
                "enabled": payload.enabled,
                "actor": actor,
            },
        )
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_configuration_profile_updated',
                %(actor)s,
                jsonb_build_object(
                    'profile_id', %(profile_id)s::uuid,
                    'profile_key', %(profile_key)s::text,
                    'before', jsonb_build_object(
                        'display_name', %(old_display_name)s::text,
                        'description', %(old_description)s::text,
                        'enabled', %(old_enabled)s::boolean
                    ),
                    'after', jsonb_build_object(
                        'display_name', %(display_name)s::text,
                        'description', %(description)s::text,
                        'enabled', %(enabled)s::boolean
                    )
                )
            )
            """,
            {
                "profile_id": profile_id,
                "profile_key": previous["profile_key"],
                "old_display_name": previous["display_name"],
                "old_description": previous["description"],
                "old_enabled": previous["enabled"],
                "display_name": payload.display_name,
                "description": payload.description,
                "enabled": payload.enabled,
                "actor": actor,
            },
        )
        return _read_profile(cursor, profile_id)


def create_sensor_configuration_profile_version(
    *,
    profile_id: UUID,
    payload: SensorConfigurationProfileVersionCreate,
    actor: str,
) -> dict[str, Any] | None:
    configuration = _configuration_json(payload.configuration)
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT profile_key, current_version
            FROM sensor_configuration_profiles
            WHERE id = %s
            FOR UPDATE
            """,
            (profile_id,),
        )
        profile = cursor.fetchone()
        if profile is None:
            return None
        next_version = int(profile["current_version"]) + 1
        cursor.execute(
            """
            INSERT INTO sensor_configuration_profile_versions (
                profile_id,
                version,
                configuration,
                change_note,
                created_by
            )
            VALUES (
                %(profile_id)s,
                %(version)s,
                %(configuration)s::jsonb,
                %(change_note)s,
                %(actor)s
            )
            """,
            {
                "profile_id": profile_id,
                "version": next_version,
                "configuration": configuration,
                "change_note": payload.change_note,
                "actor": actor,
            },
        )
        cursor.execute(
            """
            UPDATE sensor_configuration_profiles
            SET
                current_version = %(version)s,
                updated_at = NOW(),
                updated_by = %(actor)s
            WHERE id = %(profile_id)s
            """,
            {
                "profile_id": profile_id,
                "version": next_version,
                "actor": actor,
            },
        )
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_configuration_profile_version_created',
                %(actor)s,
                jsonb_build_object(
                    'profile_id', %(profile_id)s::uuid,
                    'profile_key', %(profile_key)s::text,
                    'previous_version', %(previous_version)s::bigint,
                    'version', %(version)s::bigint,
                    'configuration', %(configuration)s::jsonb,
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "profile_id": profile_id,
                "profile_key": profile["profile_key"],
                "previous_version": profile["current_version"],
                "version": next_version,
                "configuration": configuration,
                "change_note": payload.change_note,
                "actor": actor,
            },
        )
        return _read_profile(cursor, profile_id)

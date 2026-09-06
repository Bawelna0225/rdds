from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from app.database import connection
from app.models import SensorAgentUpdatePlanAction, SensorAgentUpdatePlanCreate


class AgentUpdatePlanConflict(RuntimeError):
    pass


PLAN_COLUMNS = """
    plan.id,
    plan.revision,
    plan.status,
    plan.release_id,
    plan.release_version,
    plan.release_channel,
    plan.release_artifact_sha256,
    plan.release_minimum_agent_version,
    plan.release_protocol_version,
    plan.target_count,
    plan.eligible_count,
    plan.change_note,
    plan.created_at,
    plan.created_by,
    plan.cancelled_at,
    plan.cancelled_by,
    plan.cancellation_reason,
    release.status AS current_release_status
"""


TARGET_COLUMNS = """
    target.plan_id,
    target.sensor_id,
    target.sequence,
    target.sensor_key,
    target.sensor_status,
    target.reported_agent_version,
    target.eligibility_status,
    target.update_eligible,
    target.reason_codes,
    target.assessed_at
"""


def _parse_version(value: str | None) -> tuple[int, int, int] | None:
    if value is None or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is None:
        return None
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _read_plan(
    cursor: Any,
    plan_id: UUID,
    *,
    for_update: bool = False,
) -> dict[str, Any] | None:
    lock = " FOR UPDATE OF plan" if for_update else ""
    cursor.execute(
        f"""
        SELECT {PLAN_COLUMNS}
        FROM sensor_agent_update_plans AS plan
        JOIN sensor_agent_releases AS release ON release.id = plan.release_id
        WHERE plan.id = %s{lock}
        """,
        (plan_id,),
    )
    row = cursor.fetchone()
    return None if row is None else dict(row)


def _read_targets(cursor: Any, plan_id: UUID) -> list[dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT {TARGET_COLUMNS}
        FROM sensor_agent_update_plan_targets AS target
        WHERE target.plan_id = %s
        ORDER BY target.sequence
        """,
        (plan_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _read_plan_with_targets(
    cursor: Any,
    plan_id: UUID,
    *,
    for_update: bool = False,
) -> dict[str, Any] | None:
    plan = _read_plan(cursor, plan_id, for_update=for_update)
    if plan is None:
        return None
    plan["targets"] = _read_targets(cursor, plan_id)
    return plan


def _assess_target(
    sensor: dict[str, Any],
    release: dict[str, Any],
) -> dict[str, Any]:
    current = _parse_version(sensor["agent_version"])
    target = _parse_version(release["version"])
    minimum = _parse_version(release["minimum_agent_version"])
    if target is None or minimum is None:
        raise RuntimeError("published release contains an invalid semantic version")

    reasons: list[str] = []
    if sensor["status"] not in {"online", "degraded"}:
        eligibility_status = "inactive"
        reasons.append("sensor_not_online")
        if current is None:
            reasons.append("agent_version_unreported")
    elif current is None:
        eligibility_status = "unreported"
        reasons.append("agent_version_unreported")
    elif current == target:
        eligibility_status = "already_current"
        reasons.append("target_release_already_installed")
    elif current > target:
        eligibility_status = "ahead"
        reasons.append("target_release_is_older")
    elif current < minimum:
        eligibility_status = "below_minimum"
        reasons.append("agent_version_below_release_minimum")
    else:
        eligibility_status = "eligible"

    return {
        "sensor_id": sensor["id"],
        "sensor_key": sensor["sensor_key"],
        "sensor_status": sensor["status"],
        "reported_agent_version": sensor["agent_version"],
        "eligibility_status": eligibility_status,
        "update_eligible": eligibility_status == "eligible",
        "reason_codes": reasons,
    }


def list_sensor_agent_update_plans(
    *,
    include_cancelled: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)::BIGINT AS total
            FROM sensor_agent_update_plans
            WHERE (%s OR status <> 'cancelled')
            """,
            (include_cancelled,),
        )
        count_row = cursor.fetchone()
        total = 0 if count_row is None else int(count_row["total"])
        cursor.execute(
            f"""
            SELECT {PLAN_COLUMNS}
            FROM sensor_agent_update_plans AS plan
            JOIN sensor_agent_releases AS release ON release.id = plan.release_id
            WHERE (%(include_cancelled)s OR plan.status <> 'cancelled')
            ORDER BY
                CASE plan.status WHEN 'draft' THEN 0 ELSE 1 END,
                plan.created_at DESC,
                plan.id DESC
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            {
                "include_cancelled": include_cancelled,
                "limit": limit,
                "offset": offset,
            },
        )
        plans = [dict(row) for row in cursor.fetchall()]
    return plans, total


def get_sensor_agent_update_plan(plan_id: UUID) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        return _read_plan_with_targets(cursor, plan_id)


def create_sensor_agent_update_plan(
    *,
    payload: SensorAgentUpdatePlanCreate,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id,
                version,
                revision,
                channel,
                status,
                artifact_sha256,
                minimum_agent_version,
                protocol_version
            FROM sensor_agent_releases
            WHERE id = %s
            FOR SHARE
            """,
            (payload.release_id,),
        )
        release_row = cursor.fetchone()
        if release_row is None:
            return None
        release = dict(release_row)
        if release["status"] != "published":
            raise AgentUpdatePlanConflict(
                "only a published agent release can be used by an update plan"
            )

        cursor.execute(
            """
            SELECT id, sensor_key, status, agent_version
            FROM sensors
            WHERE id = ANY(%s)
              AND deleted_at IS NULL
            """,
            (payload.sensor_ids,),
        )
        sensors_by_id = {row["id"]: dict(row) for row in cursor.fetchall()}
        missing = [
            str(sensor_id)
            for sensor_id in payload.sensor_ids
            if sensor_id not in sensors_by_id
        ]
        if missing:
            raise AgentUpdatePlanConflict(
                "one or more target sensors are unavailable: " + ", ".join(missing)
            )

        targets = [
            _assess_target(sensors_by_id[sensor_id], release)
            for sensor_id in payload.sensor_ids
        ]
        eligible_count = sum(target["update_eligible"] for target in targets)
        cursor.execute(
            """
            INSERT INTO sensor_agent_update_plans (
                release_id,
                release_version,
                release_channel,
                release_artifact_sha256,
                release_minimum_agent_version,
                release_protocol_version,
                target_count,
                eligible_count,
                change_note,
                created_by
            )
            VALUES (
                %(release_id)s,
                %(release_version)s,
                %(release_channel)s,
                %(release_artifact_sha256)s,
                %(release_minimum_agent_version)s,
                %(release_protocol_version)s,
                %(target_count)s,
                %(eligible_count)s,
                %(change_note)s,
                %(actor)s
            )
            RETURNING id
            """,
            {
                "release_id": release["id"],
                "release_version": release["version"],
                "release_channel": release["channel"],
                "release_artifact_sha256": release["artifact_sha256"],
                "release_minimum_agent_version": release["minimum_agent_version"],
                "release_protocol_version": release["protocol_version"],
                "target_count": len(targets),
                "eligible_count": eligible_count,
                "change_note": payload.change_note,
                "actor": actor,
            },
        )
        created = cursor.fetchone()
        if created is None:
            raise RuntimeError("Sensor agent update plan insert returned no row")
        plan_id = created["id"]
        cursor.executemany(
            """
            INSERT INTO sensor_agent_update_plan_targets (
                plan_id,
                sensor_id,
                sequence,
                sensor_key,
                sensor_status,
                reported_agent_version,
                eligibility_status,
                update_eligible,
                reason_codes
            )
            VALUES (
                %(plan_id)s,
                %(sensor_id)s,
                %(sequence)s,
                %(sensor_key)s,
                %(sensor_status)s,
                %(reported_agent_version)s,
                %(eligibility_status)s,
                %(update_eligible)s,
                %(reason_codes)s::jsonb
            )
            """,
            [
                {
                    **target,
                    "plan_id": plan_id,
                    "sequence": sequence,
                    "reason_codes": json.dumps(target["reason_codes"]),
                }
                for sequence, target in enumerate(targets, start=1)
            ],
        )
        audit_targets = [
            {
                "sensor_id": str(target["sensor_id"]),
                "sensor_key": target["sensor_key"],
                "reported_agent_version": target["reported_agent_version"],
                "eligibility_status": target["eligibility_status"],
                "update_eligible": target["update_eligible"],
                "reason_codes": target["reason_codes"],
            }
            for target in targets
        ]
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_agent_update_plan_created',
                %(actor)s,
                jsonb_build_object(
                    'plan_id', %(plan_id)s::uuid,
                    'release_id', %(release_id)s::uuid,
                    'release_version', %(release_version)s::text,
                    'release_channel', %(release_channel)s::text,
                    'target_count', %(target_count)s::integer,
                    'eligible_count', %(eligible_count)s::integer,
                    'targets', %(targets)s::jsonb,
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "actor": actor,
                "plan_id": plan_id,
                "release_id": release["id"],
                "release_version": release["version"],
                "release_channel": release["channel"],
                "target_count": len(targets),
                "eligible_count": eligible_count,
                "targets": json.dumps(audit_targets),
                "change_note": payload.change_note,
            },
        )
        plan = _read_plan_with_targets(cursor, plan_id)
        if plan is None:
            raise RuntimeError("Created sensor agent update plan could not be read")
        return plan


def cancel_sensor_agent_update_plan(
    *,
    plan_id: UUID,
    payload: SensorAgentUpdatePlanAction,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        before = _read_plan(cursor, plan_id, for_update=True)
        if before is None:
            return None
        if before["status"] != "draft":
            raise AgentUpdatePlanConflict("only a draft update plan can be cancelled")
        if before["revision"] != payload.expected_revision:
            raise AgentUpdatePlanConflict(
                "agent update plan changed; refresh before cancelling"
            )
        cursor.execute(
            """
            UPDATE sensor_agent_update_plans
            SET
                status = 'cancelled',
                revision = revision + 1,
                cancelled_at = NOW(),
                cancelled_by = %(actor)s,
                cancellation_reason = %(change_note)s
            WHERE id = %(plan_id)s
              AND revision = %(expected_revision)s
              AND status = 'draft'
            RETURNING id
            """,
            {
                "plan_id": plan_id,
                "expected_revision": payload.expected_revision,
                "actor": actor,
                "change_note": payload.change_note,
            },
        )
        if cursor.fetchone() is None:
            raise AgentUpdatePlanConflict(
                "agent update plan changed; refresh before cancelling"
            )
        cursor.execute(
            """
            INSERT INTO audit_events (occurred_at, event_type, actor, details)
            VALUES (
                NOW(),
                'sensor_agent_update_plan_cancelled',
                %(actor)s,
                jsonb_build_object(
                    'plan_id', %(plan_id)s::uuid,
                    'release_id', %(release_id)s::uuid,
                    'release_version', %(release_version)s::text,
                    'from_revision', %(from_revision)s::bigint,
                    'revision', (%(from_revision)s::bigint + 1),
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "actor": actor,
                "plan_id": plan_id,
                "release_id": before["release_id"],
                "release_version": before["release_version"],
                "from_revision": before["revision"],
                "change_note": payload.change_note,
            },
        )
        plan = _read_plan_with_targets(cursor, plan_id)
        if plan is None:
            raise RuntimeError("Cancelled sensor agent update plan could not be read")
        return plan

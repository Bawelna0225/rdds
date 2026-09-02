from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.database import connection
from app.fleet_readiness_store import assess_sensor_fleet_readiness
from app.models import (
    SensorConfigurationRolloutAction,
    SensorConfigurationRolloutCreate,
)


class RolloutConflict(RuntimeError):
    pass


class RolloutReadinessConflict(RolloutConflict):
    def __init__(
        self,
        *,
        policy_revision: int,
        blockers: list[dict[str, Any]],
    ) -> None:
        self.policy_revision = policy_revision
        self.blockers = blockers
        summary = ", ".join(
            f"{item['sensor_key']}={item['readiness_status']}"
            for item in blockers
        )
        super().__init__(f"next rollout batch is not ready: {summary}")

    def api_detail(self) -> dict[str, Any]:
        return {
            "code": "rollout_readiness_blocked",
            "message": str(self),
            "policy_revision": self.policy_revision,
            "blockers": self.blockers,
        }


class RolloutRecoveryConflict(RolloutConflict):
    def __init__(
        self,
        *,
        policy_revision: int,
        blockers: list[dict[str, Any]],
    ) -> None:
        self.policy_revision = policy_revision
        self.blockers = blockers
        summary = ", ".join(
            f"{item['sensor_key']}={item['code']}" for item in blockers
        )
        super().__init__(f"paused rollout is not safe to resume: {summary}")

    def api_detail(self) -> dict[str, Any]:
        return {
            "code": "rollout_resume_blocked",
            "message": str(self),
            "policy_revision": self.policy_revision,
            "blockers": self.blockers,
        }


ROLLOUT_SELECT = """
    rollout.id,
    rollout.profile_id,
    profile.profile_key,
    profile.display_name AS profile_display_name,
    profile.enabled AS profile_enabled,
    rollout.profile_version,
    rollout.status,
    rollout.batch_size,
    rollout.target_count,
    rollout.change_note,
    rollout.created_at,
    rollout.created_by,
    rollout.started_at,
    rollout.started_by,
    rollout.completed_at,
    rollout.cancelled_at,
    rollout.cancelled_by,
    rollout.paused_at,
    rollout.paused_by,
    rollout.pause_reason,
    rollout.pause_policy_revision,
    rollout.resume_count,
    rollout.rolled_back_at,
    rollout.rolled_back_by,
    rollout.rollback_note,
    rollout.updated_at,
    COALESCE(summary.undeployed_count, 0) AS undeployed_count,
    COALESCE(summary.deployed_count, 0) AS deployed_count,
    COALESCE(summary.compliant_count, 0) AS compliant_count,
    COALESCE(summary.error_count, 0) AS error_count,
    COALESCE(summary.superseded_count, 0) AS superseded_count,
    COALESCE(summary.awaiting_application_count, 0) AS awaiting_application_count,
    COALESCE(summary.rolled_back_count, 0) AS rolled_back_count,
    COALESCE(summary.rollback_compliant_count, 0) AS rollback_compliant_count,
    COALESCE(summary.rollback_pending_count, 0) AS rollback_pending_count,
    COALESCE(summary.rollback_error_count, 0) AS rollback_error_count,
    COALESCE(summary.rollback_superseded_count, 0) AS rollback_superseded_count
"""


ROLLOUT_JOINS = """
    JOIN sensor_configuration_profiles AS profile
      ON profile.id = rollout.profile_id
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) FILTER (
                WHERE target.desired_revision IS NULL
            )::INTEGER AS undeployed_count,
            COUNT(*) FILTER (
                WHERE target.desired_revision IS NOT NULL
            )::INTEGER AS deployed_count,
            COUNT(*) FILTER (
                WHERE target.desired_revision IS NOT NULL
                  AND target.rolled_back_at IS NULL
                  AND configuration.desired_revision = target.desired_revision
                  AND configuration.applied_revision = target.desired_revision
                  AND configuration.apply_status = 'applied'
            )::INTEGER AS compliant_count,
            COUNT(*) FILTER (
                WHERE target.desired_revision IS NOT NULL
                  AND target.rolled_back_at IS NULL
                  AND configuration.desired_revision = target.desired_revision
                  AND configuration.apply_status = 'error'
            )::INTEGER AS error_count,
            COUNT(*) FILTER (
                WHERE target.desired_revision IS NOT NULL
                  AND target.rolled_back_at IS NULL
                  AND configuration.desired_revision IS DISTINCT FROM
                      target.desired_revision
            )::INTEGER AS superseded_count,
            COUNT(*) FILTER (
                WHERE target.desired_revision IS NOT NULL
                  AND target.rolled_back_at IS NULL
                  AND configuration.desired_revision = target.desired_revision
                  AND NOT (
                      configuration.applied_revision = target.desired_revision
                      AND configuration.apply_status = 'applied'
                  )
                  AND configuration.apply_status <> 'error'
            )::INTEGER AS awaiting_application_count,
            COUNT(*) FILTER (
                WHERE target.rolled_back_at IS NOT NULL
            )::INTEGER AS rolled_back_count,
            COUNT(*) FILTER (
                WHERE target.rolled_back_at IS NOT NULL
                  AND configuration.desired_revision = target.rollback_revision
                  AND configuration.applied_revision = target.rollback_revision
                  AND configuration.apply_status = 'applied'
            )::INTEGER AS rollback_compliant_count,
            COUNT(*) FILTER (
                WHERE target.rolled_back_at IS NOT NULL
                  AND configuration.desired_revision = target.rollback_revision
                  AND NOT (
                      configuration.applied_revision = target.rollback_revision
                      AND configuration.apply_status = 'applied'
                  )
                  AND configuration.apply_status <> 'error'
            )::INTEGER AS rollback_pending_count,
            COUNT(*) FILTER (
                WHERE target.rolled_back_at IS NOT NULL
                  AND configuration.desired_revision = target.rollback_revision
                  AND configuration.apply_status = 'error'
            )::INTEGER AS rollback_error_count,
            COUNT(*) FILTER (
                WHERE target.rolled_back_at IS NOT NULL
                  AND configuration.desired_revision IS DISTINCT FROM
                      target.rollback_revision
            )::INTEGER AS rollback_superseded_count
        FROM sensor_configuration_rollout_targets AS target
        LEFT JOIN sensor_configuration_state AS configuration
          ON configuration.sensor_id = target.sensor_id
        WHERE target.rollout_id = rollout.id
    ) AS summary ON TRUE
"""


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def _audit(
    cursor: Any,
    *,
    event_type: str,
    actor: str,
    details: dict[str, Any],
    sensor_id: UUID | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO audit_events (
            occurred_at,
            event_type,
            actor,
            sensor_id,
            details
        )
        VALUES (NOW(), %s, %s, %s, %s::jsonb)
        """,
        (event_type, actor, sensor_id, _json(details)),
    )


def _read_rollout_base(cursor: Any, rollout_id: UUID) -> dict[str, Any] | None:
    cursor.execute(
        f"""
        SELECT {ROLLOUT_SELECT}
        FROM sensor_configuration_rollouts AS rollout
        {ROLLOUT_JOINS}
        WHERE rollout.id = %s
        """,
        (rollout_id,),
    )
    row = cursor.fetchone()
    return None if row is None else dict(row)


def _target_status(target: dict[str, Any], rollout_status: str) -> str:
    if target["rolled_back_at"] is not None:
        rollback_revision = target["rollback_revision"]
        if target["current_desired_revision"] != rollback_revision:
            return "rollback_superseded"
        if target["current_apply_status"] == "error":
            return "rollback_error"
        if (
            target["current_applied_revision"] == rollback_revision
            and target["current_apply_status"] == "applied"
        ):
            return "rolled_back"
        return "rollback_pending"
    desired_revision = target["desired_revision"]
    if desired_revision is None:
        return "cancelled" if rollout_status == "cancelled" else "pending"
    if target["current_desired_revision"] != desired_revision:
        return "superseded"
    if target["current_apply_status"] == "error":
        return "error"
    if (
        target["current_applied_revision"] == desired_revision
        and target["current_apply_status"] == "applied"
    ):
        return "compliant"
    return "awaiting_application"


def _read_rollout_targets(
    cursor: Any,
    rollout_id: UUID,
    rollout_status: str,
) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT
            target.rollout_id,
            target.sensor_id,
            sensor.sensor_key,
            sensor.display_name AS sensor_display_name,
            sensor.status AS sensor_status,
            target.sequence,
            target.desired_revision,
            target.previous_desired_revision,
            target.previous_desired_config,
            target.previous_profile_id,
            previous_profile.profile_key AS previous_profile_key,
            target.previous_profile_version,
            target.previous_rollout_id,
            target.deployed_at,
            target.deployed_by,
            target.rollback_revision,
            target.rolled_back_at,
            target.rolled_back_by,
            configuration.desired_revision AS current_desired_revision,
            configuration.applied_revision AS current_applied_revision,
            configuration.apply_status AS current_apply_status,
            configuration.apply_error AS current_apply_error,
            configuration.reported_at,
            assignment.profile_id AS assigned_profile_id,
            assignment.profile_version AS assigned_profile_version,
            assignment.rollout_id AS assigned_rollout_id
        FROM sensor_configuration_rollout_targets AS target
        JOIN sensors AS sensor
          ON sensor.id = target.sensor_id
        LEFT JOIN sensor_configuration_state AS configuration
          ON configuration.sensor_id = target.sensor_id
        LEFT JOIN sensor_configuration_profile_assignments AS assignment
          ON assignment.sensor_id = target.sensor_id
        LEFT JOIN sensor_configuration_profiles AS previous_profile
          ON previous_profile.id = target.previous_profile_id
        WHERE target.rollout_id = %s
        ORDER BY target.sequence
        """,
        (rollout_id,),
    )
    targets: list[dict[str, Any]] = []
    for row in cursor.fetchall():
        target = dict(row)
        target["target_status"] = _target_status(target, rollout_status)
        targets.append(target)
    return targets


def _readiness_assessment(
    cursor: Any,
    targets: list[dict[str, Any]],
    *,
    lock: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy, sensors = assess_sensor_fleet_readiness(
        cursor,
        sensor_ids=[target["sensor_id"] for target in targets],
        lock=lock,
    )
    by_id = {sensor["id"]: sensor for sensor in sensors}
    assessments: list[dict[str, Any]] = []
    for target in targets:
        sensor = by_id.get(target["sensor_id"])
        if sensor is None:
            assessments.append(
                {
                    "sensor_id": target["sensor_id"],
                    "sensor_key": target["sensor_key"],
                    "sequence": target["sequence"],
                    "readiness_status": "blocked",
                    "rollout_eligible": False,
                    "reasons": [
                        {"code": "sensor_missing", "severity": "blocked"}
                    ],
                }
            )
            continue
        assessments.append(
            {
                "sensor_id": target["sensor_id"],
                "sensor_key": target["sensor_key"],
                "sequence": target["sequence"],
                "readiness_status": sensor["readiness_status"],
                "rollout_eligible": sensor["rollout_eligible"],
                "reasons": sensor["reasons"],
            }
        )
    return policy, assessments


def _next_batch_readiness(
    cursor: Any,
    targets: list[dict[str, Any]],
    *,
    lock: bool,
) -> dict[str, Any]:
    policy, assessments = _readiness_assessment(cursor, targets, lock=lock)
    return _readiness_result(policy, assessments)


def _readiness_result(
    policy: dict[str, Any],
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers = [item for item in assessments if not item["rollout_eligible"]]
    return {
        "policy_revision": policy["revision"],
        "eligible": not blockers,
        "target_count": len(assessments),
        "targets": assessments,
        "blockers": blockers,
    }


def _rollout_recovery_result(
    policy: dict[str, Any],
    targets: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    assessment_by_id = {item["sensor_id"]: item for item in assessments}
    timeout_seconds = int(policy["rollout_application_timeout_seconds"])
    now = datetime.now(timezone.utc)
    blockers: list[dict[str, Any]] = []
    for target in targets:
        if target["desired_revision"] is None or target["rolled_back_at"] is not None:
            continue
        assessment = assessment_by_id.get(target["sensor_id"])
        base = {
            "sensor_id": target["sensor_id"],
            "sensor_key": target["sensor_key"],
            "sequence": target["sequence"],
            "desired_revision": target["desired_revision"],
        }
        if target["current_desired_revision"] != target["desired_revision"]:
            blockers.append(
                {
                    **base,
                    "code": "configuration_superseded",
                    "readiness_status": (
                        None if assessment is None
                        else assessment["readiness_status"]
                    ),
                    "reasons": [] if assessment is None else assessment["reasons"],
                }
            )
            continue
        if target["current_apply_status"] == "error":
            blockers.append(
                {
                    **base,
                    "code": "configuration_error",
                    "apply_error": target["current_apply_error"],
                    "readiness_status": (
                        None if assessment is None
                        else assessment["readiness_status"]
                    ),
                    "reasons": [] if assessment is None else assessment["reasons"],
                }
            )
            continue

        applied = (
            target["current_applied_revision"] == target["desired_revision"]
            and target["current_apply_status"] == "applied"
        )
        reasons = [] if assessment is None else assessment["reasons"]
        non_configuration_reasons = [
            reason for reason in reasons
            if not str(reason.get("code", "")).startswith("configuration_")
        ]
        if non_configuration_reasons:
            blockers.append(
                {
                    **base,
                    "code": "sensor_not_ready",
                    "readiness_status": (
                        None if assessment is None
                        else assessment["readiness_status"]
                    ),
                    "reasons": non_configuration_reasons,
                }
            )
            continue
        if applied:
            if assessment is None or not assessment["rollout_eligible"]:
                blockers.append(
                    {
                        **base,
                        "code": "sensor_not_ready",
                        "readiness_status": (
                            "blocked" if assessment is None
                            else assessment["readiness_status"]
                        ),
                        "reasons": reasons,
                    }
                )
            continue

        deployed_at = target["deployed_at"]
        elapsed_seconds = 0
        if deployed_at is not None:
            elapsed_seconds = max(0, int((now - deployed_at).total_seconds()))
        if elapsed_seconds >= timeout_seconds:
            blockers.append(
                {
                    **base,
                    "code": "configuration_application_timeout",
                    "elapsed_seconds": elapsed_seconds,
                    "timeout_seconds": timeout_seconds,
                    "readiness_status": (
                        None if assessment is None
                        else assessment["readiness_status"]
                    ),
                    "reasons": reasons,
                }
            )

    return {
        "policy_revision": policy["revision"],
        "application_timeout_seconds": timeout_seconds,
        "safe_to_resume": not blockers,
        "blockers": blockers,
    }


def _read_rollout_details(cursor: Any, rollout_id: UUID) -> dict[str, Any] | None:
    rollout = _read_rollout_base(cursor, rollout_id)
    if rollout is None:
        return None
    targets = _read_rollout_targets(cursor, rollout_id, rollout["status"])
    rollout["targets"] = targets
    readiness_policy, target_readiness = _readiness_assessment(
        cursor,
        targets,
        lock=False,
    )
    readiness_by_id = {item["sensor_id"]: item for item in target_readiness}
    for target in targets:
        readiness = readiness_by_id[target["sensor_id"]]
        target["readiness_status"] = readiness["readiness_status"]
        target["rollout_eligible"] = readiness["rollout_eligible"]
        target["readiness_reasons"] = readiness["reasons"]
    rollout["recovery"] = _rollout_recovery_result(
        readiness_policy,
        targets,
        target_readiness,
    )
    next_targets = [
        target for target in targets
        if target["desired_revision"] is None
    ][:rollout["batch_size"]]
    next_target_ids = {target["sensor_id"] for target in next_targets}
    rollout["next_batch_readiness"] = _readiness_result(
        readiness_policy,
        [
            item for item in target_readiness
            if item["sensor_id"] in next_target_ids
        ],
    )
    next_batch_eligible = rollout["next_batch_readiness"]["eligible"]
    rollout["can_start"] = (
        rollout["status"] == "draft" and next_batch_eligible
    )
    rollout["can_advance"] = (
        rollout["status"] == "active"
        and all(
            target["target_status"] in {"pending", "compliant"}
            for target in targets
        )
        and next_batch_eligible
    )
    rollout["can_resume"] = (
        rollout["status"] == "paused"
        and rollout["recovery"]["safe_to_resume"]
    )
    rollout["can_cancel"] = rollout["status"] in {"draft", "active", "paused"}
    deployed_targets = [
        target for target in targets if target["desired_revision"] is not None
    ]
    rollout["can_rollback"] = (
        rollout["status"] in {"paused", "completed", "cancelled"}
        and rollout["rolled_back_at"] is None
        and bool(deployed_targets)
        and all(
            target["previous_desired_revision"] is not None
            and target["previous_desired_revision"] >= 1
            and target["current_desired_revision"] == target["desired_revision"]
            and target["assigned_rollout_id"] == rollout["id"]
            for target in deployed_targets
        )
    )
    return rollout


def list_sensor_configuration_rollouts(
    *,
    include_terminal: bool,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)::bigint AS total
            FROM sensor_configuration_rollouts
            WHERE (%s OR status IN ('draft', 'active', 'paused'))
            """,
            (include_terminal,),
        )
        count_row = cursor.fetchone()
        total = 0 if count_row is None else int(count_row["total"])
        cursor.execute(
            f"""
            SELECT {ROLLOUT_SELECT}
            FROM sensor_configuration_rollouts AS rollout
            {ROLLOUT_JOINS}
            WHERE (
                %(include_terminal)s
                OR rollout.status IN ('draft', 'active', 'paused')
            )
            ORDER BY rollout.created_at DESC, rollout.id DESC
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            {
                "include_terminal": include_terminal,
                "limit": limit,
                "offset": offset,
            },
        )
        return [dict(row) for row in cursor.fetchall()], total


def get_sensor_configuration_rollout(
    rollout_id: UUID,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        return _read_rollout_details(cursor, rollout_id)


def create_sensor_configuration_rollout(
    *,
    payload: SensorConfigurationRolloutCreate,
    actor: str,
) -> dict[str, Any]:
    sensor_ids = payload.sensor_ids
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                profile.id,
                profile.profile_key,
                profile.enabled,
                version.configuration
            FROM sensor_configuration_profiles AS profile
            JOIN sensor_configuration_profile_versions AS version
              ON version.profile_id = profile.id
             AND version.version = %(profile_version)s
            WHERE profile.id = %(profile_id)s
            FOR SHARE OF profile
            """,
            {
                "profile_id": payload.profile_id,
                "profile_version": payload.profile_version,
            },
        )
        profile = cursor.fetchone()
        if profile is None:
            raise RolloutConflict("configuration profile version does not exist")
        if not profile["enabled"]:
            raise RolloutConflict("configuration profile is disabled")

        cursor.execute(
            """
            SELECT id, sensor_key, status
            FROM sensors
            WHERE id = ANY(%s::uuid[])
              AND deleted_at IS NULL
            ORDER BY id
            FOR UPDATE
            """,
            (sensor_ids,),
        )
        sensors = cursor.fetchall()
        found_ids = {row["id"] for row in sensors}
        missing = [str(sensor_id) for sensor_id in sensor_ids if sensor_id not in found_ids]
        if missing:
            raise RolloutConflict(f"sensors do not exist: {', '.join(missing)}")
        disabled = [row["sensor_key"] for row in sensors if row["status"] == "disabled"]
        if disabled:
            raise RolloutConflict(f"disabled sensors cannot be targeted: {', '.join(disabled)}")

        cursor.execute(
            """
            SELECT target.sensor_id, rollout.id AS rollout_id
            FROM sensor_configuration_rollout_targets AS target
            JOIN sensor_configuration_rollouts AS rollout
              ON rollout.id = target.rollout_id
            WHERE target.sensor_id = ANY(%s::uuid[])
              AND rollout.status IN ('draft', 'active', 'paused')
            LIMIT 1
            """,
            (sensor_ids,),
        )
        overlap = cursor.fetchone()
        if overlap is not None:
            raise RolloutConflict(
                "a target sensor already belongs to draft or active rollout "
                f"{overlap['rollout_id']}"
            )

        cursor.execute(
            """
            INSERT INTO sensor_configuration_rollouts (
                profile_id,
                profile_version,
                status,
                batch_size,
                target_count,
                change_note,
                created_by
            )
            VALUES (%s, %s, 'draft', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                payload.profile_id,
                payload.profile_version,
                payload.batch_size,
                len(sensor_ids),
                payload.change_note,
                actor,
            ),
        )
        created = cursor.fetchone()
        if created is None:
            raise RuntimeError("Configuration rollout insert returned no row")
        rollout_id = created["id"]
        cursor.executemany(
            """
            INSERT INTO sensor_configuration_rollout_targets (
                rollout_id,
                sensor_id,
                sequence
            )
            VALUES (%s, %s, %s)
            """,
            [
                (rollout_id, sensor_id, sequence)
                for sequence, sensor_id in enumerate(sensor_ids, start=1)
            ],
        )
        _audit(
            cursor,
            event_type="sensor_configuration_rollout_created",
            actor=actor,
            details={
                "rollout_id": rollout_id,
                "profile_id": payload.profile_id,
                "profile_key": profile["profile_key"],
                "profile_version": payload.profile_version,
                "batch_size": payload.batch_size,
                "sensor_ids": sensor_ids,
                "change_note": payload.change_note,
            },
        )
        rollout = _read_rollout_details(cursor, rollout_id)
        if rollout is None:
            raise RuntimeError("Created configuration rollout could not be read")
        return rollout


def _get_locked_rollout(cursor: Any, rollout_id: UUID) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT
            rollout.*,
            profile.profile_key,
            profile.enabled AS profile_enabled,
            version.configuration
        FROM sensor_configuration_rollouts AS rollout
        JOIN sensor_configuration_profiles AS profile
          ON profile.id = rollout.profile_id
        JOIN sensor_configuration_profile_versions AS version
          ON version.profile_id = rollout.profile_id
         AND version.version = rollout.profile_version
        WHERE rollout.id = %s
        FOR UPDATE OF rollout, profile
        """,
        (rollout_id,),
    )
    row = cursor.fetchone()
    return None if row is None else dict(row)


def _deployed_blockers(cursor: Any, rollout_id: UUID) -> list[str]:
    cursor.execute(
        """
        SELECT
            sensor.sensor_key,
            target.desired_revision,
            configuration.desired_revision AS current_desired_revision,
            configuration.applied_revision AS current_applied_revision,
            configuration.apply_status AS current_apply_status
        FROM sensor_configuration_rollout_targets AS target
        JOIN sensors AS sensor
          ON sensor.id = target.sensor_id
        LEFT JOIN sensor_configuration_state AS configuration
          ON configuration.sensor_id = target.sensor_id
        WHERE target.rollout_id = %s
          AND target.desired_revision IS NOT NULL
        ORDER BY target.sequence
        """,
        (rollout_id,),
    )
    blockers: list[str] = []
    for row in cursor.fetchall():
        if row["current_desired_revision"] != row["desired_revision"]:
            status = "superseded"
        elif row["current_apply_status"] == "error":
            status = "error"
        elif (
            row["current_applied_revision"] == row["desired_revision"]
            and row["current_apply_status"] == "applied"
        ):
            continue
        else:
            status = "awaiting_application"
        blockers.append(f"{row['sensor_key']}={status}")
    return blockers


def _deploy_next_batch(
    cursor: Any,
    *,
    rollout: dict[str, Any],
    actor: str,
    change_note: str,
) -> int:
    if not rollout["profile_enabled"]:
        raise RolloutConflict("configuration profile is disabled")
    cursor.execute(
        """
        SELECT
            target.sensor_id,
            target.sequence,
            sensor.sensor_key,
            sensor.status
        FROM sensor_configuration_rollout_targets AS target
        JOIN sensors AS sensor
          ON sensor.id = target.sensor_id
        WHERE target.rollout_id = %(rollout_id)s
          AND target.desired_revision IS NULL
        ORDER BY target.sequence
        LIMIT %(batch_size)s
        FOR UPDATE OF target
        """,
        {
            "rollout_id": rollout["id"],
            "batch_size": rollout["batch_size"],
        },
    )
    targets = cursor.fetchall()
    readiness = _next_batch_readiness(cursor, targets, lock=True)
    if not readiness["eligible"]:
        raise RolloutReadinessConflict(
            policy_revision=int(readiness["policy_revision"]),
            blockers=readiness["blockers"],
        )
    deployed: list[dict[str, Any]] = []
    desired_config_json = _json(rollout["configuration"])
    for target in targets:
        if target["status"] == "disabled":
            raise RolloutConflict(
                f"target sensor is disabled: {target['sensor_key']}"
            )
        cursor.execute(
            """
            SELECT desired_revision, desired_config, applied_revision
            FROM sensor_configuration_state
            WHERE sensor_id = %s
            FOR UPDATE
            """,
            (target["sensor_id"],),
        )
        configuration = cursor.fetchone()
        if configuration is None:
            cursor.execute(
                """
                INSERT INTO sensor_configuration_state (sensor_id)
                VALUES (%s)
                RETURNING desired_revision, desired_config, applied_revision
                """,
                (target["sensor_id"],),
            )
            configuration = cursor.fetchone()
        if configuration is None:
            raise RuntimeError("Sensor configuration state could not be initialized")

        cursor.execute(
            """
            SELECT profile_id, profile_version, rollout_id
            FROM sensor_configuration_profile_assignments
            WHERE sensor_id = %s
            FOR UPDATE
            """,
            (target["sensor_id"],),
        )
        previous_assignment = cursor.fetchone()
        desired_revision = int(configuration["desired_revision"]) + 1
        cursor.execute(
            """
            UPDATE sensor_configuration_state
            SET
                desired_revision = %(desired_revision)s,
                desired_config = %(desired_config)s::jsonb,
                desired_updated_at = NOW(),
                desired_updated_by = %(actor)s,
                apply_status = CASE
                    WHEN applied_revision IS NULL THEN 'unreported'
                    ELSE 'pending'
                END,
                apply_error = NULL
            WHERE sensor_id = %(sensor_id)s
            """,
            {
                "sensor_id": target["sensor_id"],
                "desired_revision": desired_revision,
                "desired_config": desired_config_json,
                "actor": actor,
            },
        )
        cursor.execute(
            """
            UPDATE sensor_configuration_rollout_targets
            SET
                desired_revision = %(desired_revision)s,
                previous_desired_revision = %(previous_desired_revision)s,
                previous_desired_config = %(previous_desired_config)s::jsonb,
                previous_profile_id = %(previous_profile_id)s,
                previous_profile_version = %(previous_profile_version)s,
                previous_rollout_id = %(previous_rollout_id)s,
                deployed_at = NOW(),
                deployed_by = %(actor)s
            WHERE rollout_id = %(rollout_id)s
              AND sensor_id = %(sensor_id)s
            """,
            {
                "rollout_id": rollout["id"],
                "sensor_id": target["sensor_id"],
                "desired_revision": desired_revision,
                "previous_desired_revision": configuration["desired_revision"],
                "previous_desired_config": _json(configuration["desired_config"]),
                "previous_profile_id": (
                    None if previous_assignment is None
                    else previous_assignment["profile_id"]
                ),
                "previous_profile_version": (
                    None if previous_assignment is None
                    else previous_assignment["profile_version"]
                ),
                "previous_rollout_id": (
                    None if previous_assignment is None
                    else previous_assignment["rollout_id"]
                ),
                "actor": actor,
            },
        )
        cursor.execute(
            """
            INSERT INTO sensor_configuration_profile_assignments (
                sensor_id,
                profile_id,
                profile_version,
                rollout_id,
                desired_revision,
                assigned_at,
                assigned_by
            )
            VALUES (%s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (sensor_id) DO UPDATE
            SET
                profile_id = EXCLUDED.profile_id,
                profile_version = EXCLUDED.profile_version,
                rollout_id = EXCLUDED.rollout_id,
                desired_revision = EXCLUDED.desired_revision,
                assigned_at = EXCLUDED.assigned_at,
                assigned_by = EXCLUDED.assigned_by
            """,
            (
                target["sensor_id"],
                rollout["profile_id"],
                rollout["profile_version"],
                rollout["id"],
                desired_revision,
                actor,
            ),
        )
        change_details = {
            "desired_revision": desired_revision,
            "desired_config": rollout["configuration"],
            "source": "profile_rollout",
            "rollout_id": rollout["id"],
            "profile_id": rollout["profile_id"],
            "profile_key": rollout["profile_key"],
            "profile_version": rollout["profile_version"],
        }
        _audit(
            cursor,
            event_type="sensor_configuration_changed",
            actor=actor,
            sensor_id=target["sensor_id"],
            details=change_details,
        )
        _audit(
            cursor,
            event_type="sensor_configuration_profile_assigned",
            actor=actor,
            sensor_id=target["sensor_id"],
            details={**change_details, "change_note": change_note},
        )
        deployed.append(
            {
                "sensor_id": target["sensor_id"],
                "sensor_key": target["sensor_key"],
                "desired_revision": desired_revision,
            }
        )

    if deployed:
        _audit(
            cursor,
            event_type="sensor_configuration_rollout_batch_deployed",
            actor=actor,
            details={
                "rollout_id": rollout["id"],
                "profile_id": rollout["profile_id"],
                "profile_version": rollout["profile_version"],
                "targets": deployed,
                "change_note": change_note,
            },
        )
        cursor.execute(
            """
            UPDATE sensor_configuration_rollouts
            SET updated_at = NOW()
            WHERE id = %s
            """,
            (rollout["id"],),
        )
    return len(deployed)


def start_sensor_configuration_rollout(
    *,
    rollout_id: UUID,
    payload: SensorConfigurationRolloutAction,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        rollout = _get_locked_rollout(cursor, rollout_id)
        if rollout is None:
            return None
        if rollout["status"] != "draft":
            raise RolloutConflict("only a draft rollout can be started")
        cursor.execute(
            """
            UPDATE sensor_configuration_rollouts
            SET
                status = 'active',
                started_at = NOW(),
                started_by = %(actor)s,
                updated_at = NOW()
            WHERE id = %(rollout_id)s
            """,
            {"rollout_id": rollout_id, "actor": actor},
        )
        _audit(
            cursor,
            event_type="sensor_configuration_rollout_started",
            actor=actor,
            details={
                "rollout_id": rollout_id,
                "profile_id": rollout["profile_id"],
                "profile_version": rollout["profile_version"],
                "batch_size": rollout["batch_size"],
                "change_note": payload.change_note,
            },
        )
        _deploy_next_batch(
            cursor,
            rollout=rollout,
            actor=actor,
            change_note=payload.change_note,
        )
        return _read_rollout_details(cursor, rollout_id)


def monitor_active_sensor_configuration_rollouts() -> int:
    """Pause unsafe active rollouts; never deploy or resume automatically."""
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id
            FROM sensor_configuration_rollouts
            WHERE status = 'active'
            ORDER BY started_at, id
            """
        )
        rollout_ids = [row["id"] for row in cursor.fetchall()]

    paused_count = 0
    for rollout_id in rollout_ids:
        with connection() as conn, conn.cursor() as cursor:
            rollout = _get_locked_rollout(cursor, rollout_id)
            if rollout is None or rollout["status"] != "active":
                continue
            targets = _read_rollout_targets(cursor, rollout_id, "active")
            policy, assessments = _readiness_assessment(
                cursor,
                targets,
                lock=True,
            )
            targets = _read_rollout_targets(cursor, rollout_id, "active")
            recovery = _rollout_recovery_result(policy, targets, assessments)
            if recovery["safe_to_resume"]:
                continue

            pause_reason = {
                "code": "automatic_safety_pause",
                **recovery,
            }
            actor = "system:rollout-monitor"
            cursor.execute(
                """
                UPDATE sensor_configuration_rollouts
                SET
                    status = 'paused',
                    paused_at = NOW(),
                    paused_by = %(actor)s,
                    pause_reason = %(pause_reason)s::jsonb,
                    pause_policy_revision = %(policy_revision)s,
                    updated_at = NOW()
                WHERE id = %(rollout_id)s
                  AND status = 'active'
                """,
                {
                    "rollout_id": rollout_id,
                    "actor": actor,
                    "pause_reason": _json(pause_reason),
                    "policy_revision": policy["revision"],
                },
            )
            if cursor.rowcount != 1:
                continue
            _audit(
                cursor,
                event_type="sensor_configuration_rollout_paused",
                actor=actor,
                details={
                    "rollout_id": rollout_id,
                    "profile_id": rollout["profile_id"],
                    "profile_version": rollout["profile_version"],
                    "pause_reason": pause_reason,
                },
            )
            paused_count += 1
    return paused_count


def resume_sensor_configuration_rollout(
    *,
    rollout_id: UUID,
    payload: SensorConfigurationRolloutAction,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        rollout = _get_locked_rollout(cursor, rollout_id)
        if rollout is None:
            return None
        if rollout["status"] != "paused":
            raise RolloutConflict("only a paused rollout can be resumed")

        targets = _read_rollout_targets(cursor, rollout_id, "paused")
        policy, assessments = _readiness_assessment(cursor, targets, lock=True)
        targets = _read_rollout_targets(cursor, rollout_id, "paused")
        recovery = _rollout_recovery_result(policy, targets, assessments)
        if not recovery["safe_to_resume"]:
            raise RolloutRecoveryConflict(
                policy_revision=int(policy["revision"]),
                blockers=recovery["blockers"],
            )

        previous_pause = rollout["pause_reason"]
        cursor.execute(
            """
            UPDATE sensor_configuration_rollouts
            SET
                status = 'active',
                paused_at = NULL,
                paused_by = NULL,
                pause_reason = NULL,
                pause_policy_revision = NULL,
                resume_count = resume_count + 1,
                updated_at = NOW()
            WHERE id = %s
            """,
            (rollout_id,),
        )
        _audit(
            cursor,
            event_type="sensor_configuration_rollout_resumed",
            actor=actor,
            details={
                "rollout_id": rollout_id,
                "profile_id": rollout["profile_id"],
                "profile_version": rollout["profile_version"],
                "previous_pause_reason": previous_pause,
                "policy_revision": policy["revision"],
                "change_note": payload.change_note,
            },
        )
        return _read_rollout_details(cursor, rollout_id)


def advance_sensor_configuration_rollout(
    *,
    rollout_id: UUID,
    payload: SensorConfigurationRolloutAction,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        rollout = _get_locked_rollout(cursor, rollout_id)
        if rollout is None:
            return None
        if rollout["status"] != "active":
            raise RolloutConflict("only an active rollout can be advanced")
        blockers = _deployed_blockers(cursor, rollout_id)
        if blockers:
            raise RolloutConflict(
                "deployed targets are not compliant: " + ", ".join(blockers)
            )
        cursor.execute(
            """
            SELECT COUNT(*)::integer AS pending_count
            FROM sensor_configuration_rollout_targets
            WHERE rollout_id = %s
              AND desired_revision IS NULL
            """,
            (rollout_id,),
        )
        pending_row = cursor.fetchone()
        pending_count = 0 if pending_row is None else int(pending_row["pending_count"])
        if pending_count == 0:
            cursor.execute(
                """
                UPDATE sensor_configuration_rollouts
                SET
                    status = 'completed',
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (rollout_id,),
            )
            _audit(
                cursor,
                event_type="sensor_configuration_rollout_completed",
                actor=actor,
                details={
                    "rollout_id": rollout_id,
                    "profile_id": rollout["profile_id"],
                    "profile_version": rollout["profile_version"],
                    "target_count": rollout["target_count"],
                    "change_note": payload.change_note,
                },
            )
        else:
            _deploy_next_batch(
                cursor,
                rollout=rollout,
                actor=actor,
                change_note=payload.change_note,
            )
        return _read_rollout_details(cursor, rollout_id)


def cancel_sensor_configuration_rollout(
    *,
    rollout_id: UUID,
    payload: SensorConfigurationRolloutAction,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        rollout = _get_locked_rollout(cursor, rollout_id)
        if rollout is None:
            return None
        if rollout["status"] not in {"draft", "active", "paused"}:
            raise RolloutConflict(
                "only a draft, active, or paused rollout can be cancelled"
            )
        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE desired_revision IS NOT NULL)::integer
                    AS deployed_count,
                COUNT(*) FILTER (WHERE desired_revision IS NULL)::integer
                    AS undeployed_count
            FROM sensor_configuration_rollout_targets
            WHERE rollout_id = %s
            """,
            (rollout_id,),
        )
        counts = cursor.fetchone()
        cursor.execute(
            """
            UPDATE sensor_configuration_rollouts
            SET
                status = 'cancelled',
                cancelled_at = NOW(),
                cancelled_by = %(actor)s,
                paused_at = NULL,
                paused_by = NULL,
                pause_reason = NULL,
                pause_policy_revision = NULL,
                updated_at = NOW()
            WHERE id = %(rollout_id)s
            """,
            {"rollout_id": rollout_id, "actor": actor},
        )
        _audit(
            cursor,
            event_type="sensor_configuration_rollout_cancelled",
            actor=actor,
            details={
                "rollout_id": rollout_id,
                "profile_id": rollout["profile_id"],
                "profile_version": rollout["profile_version"],
                "deployed_count": 0 if counts is None else counts["deployed_count"],
                "undeployed_count": 0 if counts is None else counts["undeployed_count"],
                "deployed_targets_rolled_back": False,
                "was_paused": rollout["status"] == "paused",
                "change_note": payload.change_note,
            },
        )
        return _read_rollout_details(cursor, rollout_id)


def _is_complete_managed_configuration(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    fields = {
        "heartbeat_seconds",
        "reconnect_seconds",
        "request_timeout_seconds",
        "replay_messages_per_second",
    }
    return fields == set(value) and all(
        isinstance(value[field], (int, float)) and not isinstance(value[field], bool)
        for field in fields
    )


def rollback_sensor_configuration_rollout(
    *,
    rollout_id: UUID,
    payload: SensorConfigurationRolloutAction,
    actor: str,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        rollout = _get_locked_rollout(cursor, rollout_id)
        if rollout is None:
            return None
        if rollout["status"] not in {"paused", "completed", "cancelled"}:
            raise RolloutConflict(
                "only a paused, completed, or cancelled rollout can be rolled back"
            )
        if rollout["rolled_back_at"] is not None:
            raise RolloutConflict("configuration rollout was already rolled back")

        if rollout["status"] == "paused":
            cursor.execute(
                """
                UPDATE sensor_configuration_rollouts
                SET
                    status = 'cancelled',
                    cancelled_at = NOW(),
                    cancelled_by = %(actor)s,
                    paused_at = NULL,
                    paused_by = NULL,
                    pause_reason = NULL,
                    pause_policy_revision = NULL,
                    updated_at = NOW()
                WHERE id = %(rollout_id)s
                """,
                {"rollout_id": rollout_id, "actor": actor},
            )
            _audit(
                cursor,
                event_type="sensor_configuration_rollout_cancelled",
                actor=actor,
                details={
                    "rollout_id": rollout_id,
                    "profile_id": rollout["profile_id"],
                    "profile_version": rollout["profile_version"],
                    "deployed_targets_rolled_back": True,
                    "was_paused": True,
                    "reason": "rollback_from_paused",
                    "change_note": payload.change_note,
                },
            )

        cursor.execute(
            """
            SELECT
                target.*,
                sensor.sensor_key
            FROM sensor_configuration_rollout_targets AS target
            JOIN sensors AS sensor
              ON sensor.id = target.sensor_id
            WHERE target.rollout_id = %s
              AND target.desired_revision IS NOT NULL
            ORDER BY target.sequence
            FOR UPDATE OF target, sensor
            """,
            (rollout_id,),
        )
        targets = [dict(row) for row in cursor.fetchall()]
        if not targets:
            raise RolloutConflict("configuration rollout has no deployed targets")

        prepared: list[dict[str, Any]] = []
        blockers: list[str] = []
        for target in targets:
            cursor.execute(
                """
                SELECT desired_revision, desired_config, applied_revision
                FROM sensor_configuration_state
                WHERE sensor_id = %s
                FOR UPDATE
                """,
                (target["sensor_id"],),
            )
            configuration = cursor.fetchone()
            cursor.execute(
                """
                SELECT profile_id, profile_version, rollout_id, desired_revision
                FROM sensor_configuration_profile_assignments
                WHERE sensor_id = %s
                FOR UPDATE
                """,
                (target["sensor_id"],),
            )
            assignment = cursor.fetchone()
            if configuration is None:
                blockers.append(f"{target['sensor_key']}=configuration_missing")
                continue
            if configuration["desired_revision"] != target["desired_revision"]:
                blockers.append(f"{target['sensor_key']}=superseded")
                continue
            if assignment is None or assignment["rollout_id"] != rollout_id:
                blockers.append(f"{target['sensor_key']}=assignment_changed")
                continue
            if (
                target["previous_desired_revision"] is None
                or target["previous_desired_revision"] < 1
                or not _is_complete_managed_configuration(
                    target["previous_desired_config"]
                )
            ):
                blockers.append(f"{target['sensor_key']}=no_safe_snapshot")
                continue
            prepared.append(
                {
                    "target": target,
                    "configuration": dict(configuration),
                    "assignment": dict(assignment),
                }
            )
        if blockers:
            raise RolloutConflict(
                "rollout cannot be rolled back: " + ", ".join(blockers)
            )

        rolled_back: list[dict[str, Any]] = []
        for item in prepared:
            target = item["target"]
            configuration = item["configuration"]
            rollback_revision = int(configuration["desired_revision"]) + 1
            previous_config_json = _json(target["previous_desired_config"])
            cursor.execute(
                """
                UPDATE sensor_configuration_state
                SET
                    desired_revision = %(rollback_revision)s,
                    desired_config = %(desired_config)s::jsonb,
                    desired_updated_at = NOW(),
                    desired_updated_by = %(actor)s,
                    apply_status = CASE
                        WHEN applied_revision IS NULL THEN 'unreported'
                        ELSE 'pending'
                    END,
                    apply_error = NULL
                WHERE sensor_id = %(sensor_id)s
                """,
                {
                    "sensor_id": target["sensor_id"],
                    "rollback_revision": rollback_revision,
                    "desired_config": previous_config_json,
                    "actor": actor,
                },
            )
            cursor.execute(
                """
                UPDATE sensor_configuration_rollout_targets
                SET
                    rollback_revision = %(rollback_revision)s,
                    rolled_back_at = NOW(),
                    rolled_back_by = %(actor)s
                WHERE rollout_id = %(rollout_id)s
                  AND sensor_id = %(sensor_id)s
                """,
                {
                    "rollout_id": rollout_id,
                    "sensor_id": target["sensor_id"],
                    "rollback_revision": rollback_revision,
                    "actor": actor,
                },
            )

            change_details = {
                "desired_revision": rollback_revision,
                "desired_config": target["previous_desired_config"],
                "source": "rollout_rollback",
                "rollout_id": rollout_id,
                "rolled_back_from_revision": target["desired_revision"],
                "restored_snapshot_revision": target["previous_desired_revision"],
            }
            _audit(
                cursor,
                event_type="sensor_configuration_changed",
                actor=actor,
                sensor_id=target["sensor_id"],
                details=change_details,
            )

            if target["previous_profile_id"] is None:
                cursor.execute(
                    """
                    DELETE FROM sensor_configuration_profile_assignments
                    WHERE sensor_id = %s
                    """,
                    (target["sensor_id"],),
                )
                _audit(
                    cursor,
                    event_type="sensor_configuration_profile_unassigned",
                    actor=actor,
                    sensor_id=target["sensor_id"],
                    details={
                        **change_details,
                        "profile_id": rollout["profile_id"],
                        "profile_version": rollout["profile_version"],
                        "reason": "rollout_rollback",
                    },
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO sensor_configuration_profile_assignments (
                        sensor_id,
                        profile_id,
                        profile_version,
                        rollout_id,
                        desired_revision,
                        assigned_at,
                        assigned_by
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (sensor_id) DO UPDATE
                    SET
                        profile_id = EXCLUDED.profile_id,
                        profile_version = EXCLUDED.profile_version,
                        rollout_id = EXCLUDED.rollout_id,
                        desired_revision = EXCLUDED.desired_revision,
                        assigned_at = EXCLUDED.assigned_at,
                        assigned_by = EXCLUDED.assigned_by
                    """,
                    (
                        target["sensor_id"],
                        target["previous_profile_id"],
                        target["previous_profile_version"],
                        target["previous_rollout_id"],
                        rollback_revision,
                        actor,
                    ),
                )
                _audit(
                    cursor,
                    event_type="sensor_configuration_profile_assigned",
                    actor=actor,
                    sensor_id=target["sensor_id"],
                    details={
                        **change_details,
                        "profile_id": target["previous_profile_id"],
                        "profile_version": target["previous_profile_version"],
                        "restored_rollout_id": target["previous_rollout_id"],
                        "reason": "rollout_rollback",
                    },
                )
            rolled_back.append(
                {
                    "sensor_id": target["sensor_id"],
                    "sensor_key": target["sensor_key"],
                    "rollback_revision": rollback_revision,
                    "restored_snapshot_revision": target[
                        "previous_desired_revision"
                    ],
                }
            )

        cursor.execute(
            """
            UPDATE sensor_configuration_rollouts
            SET
                rolled_back_at = NOW(),
                rolled_back_by = %(actor)s,
                rollback_note = %(rollback_note)s,
                updated_at = NOW()
            WHERE id = %(rollout_id)s
            """,
            {
                "rollout_id": rollout_id,
                "actor": actor,
                "rollback_note": payload.change_note,
            },
        )
        _audit(
            cursor,
            event_type="sensor_configuration_rollout_rolled_back",
            actor=actor,
            details={
                "rollout_id": rollout_id,
                "profile_id": rollout["profile_id"],
                "profile_version": rollout["profile_version"],
                "targets": rolled_back,
                "change_note": payload.change_note,
            },
        )
        return _read_rollout_details(cursor, rollout_id)

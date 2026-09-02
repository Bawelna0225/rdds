from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.database import connection
from app.models import SensorFleetReadinessPolicyUpdate


class FleetReadinessPolicyConflict(RuntimeError):
    pass


POLICY_COLUMNS = """
    id,
    revision,
    minimum_agent_version,
    recommended_agent_version,
    require_source_connected,
    require_configuration_compliance,
    rollout_application_timeout_seconds,
    updated_at,
    updated_by
"""


READINESS_SENSOR_COLUMNS = """
    sensor.id,
    sensor.sensor_key,
    sensor.display_name,
    sensor.status,
    sensor.health_reason,
    sensor.agent_version,
    sensor.source_connected,
    sensor.last_heartbeat_received_at AS last_heartbeat_at,
    sensor.last_observation_received_at,
    sensor.maintenance_reason,
    sensor.maintenance_until,
    configuration.desired_revision AS configuration_desired_revision,
    configuration.applied_revision AS configuration_applied_revision,
    configuration.apply_status AS configuration_apply_status,
    configuration.apply_error AS configuration_apply_error,
    configuration.reported_at AS configuration_reported_at
"""


def _parse_agent_version(value: str | None) -> tuple[int, int, int] | None:
    if value is None or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is None:
        return None
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _configuration_compliance(sensor: dict[str, Any]) -> str:
    desired = sensor["configuration_desired_revision"]
    applied = sensor["configuration_applied_revision"]
    apply_status = sensor["configuration_apply_status"]
    if desired is None or desired == 0:
        return "unmanaged"
    if apply_status == "error":
        return "error"
    if applied == desired and apply_status == "applied":
        return "compliant"
    if applied is None:
        return "unreported"
    return "pending"


def _reason(code: str, severity: str) -> dict[str, str]:
    return {"code": code, "severity": severity}


def _evaluate_sensor(
    sensor: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    result = dict(sensor)
    compliance = _configuration_compliance(sensor)
    result["configuration_compliance"] = compliance

    status = sensor["status"]
    if status == "disabled":
        result.update(
            readiness_status="excluded",
            rollout_eligible=False,
            agent_version_state="not_assessed",
            reasons=[_reason("sensor_disabled", "excluded")],
        )
        return result
    if status == "maintenance":
        result.update(
            readiness_status="excluded",
            rollout_eligible=False,
            agent_version_state="not_assessed",
            reasons=[_reason("sensor_maintenance", "excluded")],
        )
        return result

    reasons: list[dict[str, str]] = []
    if status == "offline":
        reasons.append(_reason("sensor_offline", "blocked"))
    elif status == "degraded":
        reasons.append(_reason("sensor_degraded", "attention"))
    elif status != "online":
        reasons.append(_reason("sensor_not_online", "blocked"))

    if sensor["last_heartbeat_at"] is None:
        reasons.append(_reason("heartbeat_missing", "blocked"))

    current_version = _parse_agent_version(sensor["agent_version"])
    minimum_version = _parse_agent_version(policy["minimum_agent_version"])
    recommended_version = _parse_agent_version(policy["recommended_agent_version"])
    if current_version is None:
        version_state = "unknown"
        reasons.append(_reason("agent_version_unknown", "blocked"))
    elif minimum_version is not None and current_version < minimum_version:
        version_state = "below_minimum"
        reasons.append(_reason("agent_version_below_minimum", "blocked"))
    elif recommended_version is not None and current_version < recommended_version:
        version_state = "below_recommended"
        reasons.append(_reason("agent_version_below_recommended", "attention"))
    else:
        version_state = "compliant"

    if (
        policy["require_source_connected"]
        and sensor["source_connected"] is not True
    ):
        reasons.append(_reason("source_disconnected", "blocked"))

    if policy["require_configuration_compliance"] and compliance != "compliant":
        reasons.append(_reason(f"configuration_{compliance}", "blocked"))

    severities = {item["severity"] for item in reasons}
    if "blocked" in severities:
        readiness_status = "blocked"
    elif "attention" in severities:
        readiness_status = "attention"
    else:
        readiness_status = "ready"

    result.update(
        readiness_status=readiness_status,
        rollout_eligible=readiness_status == "ready",
        agent_version_state=version_state,
        reasons=reasons,
    )
    return result


def _read_policy(cursor: Any, *, for_update: bool = False) -> dict[str, Any]:
    lock = " FOR UPDATE" if for_update else ""
    cursor.execute(
        f"""
        SELECT {POLICY_COLUMNS}
        FROM sensor_fleet_readiness_policy
        WHERE id = 1{lock}
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("sensor fleet readiness policy is missing")
    return dict(row)


def assess_sensor_fleet_readiness(
    cursor: Any,
    *,
    sensor_ids: list[UUID] | None = None,
    lock: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate selected sensors under one policy revision and transaction."""
    policy = _read_policy(cursor, for_update=lock)
    selected_ids = None if sensor_ids is None else list(sensor_ids)
    if selected_ids == []:
        return policy, []

    if lock and selected_ids is not None:
        cursor.execute(
            """
            SELECT id
            FROM sensors
            WHERE id = ANY(%s::uuid[])
            ORDER BY id
            FOR UPDATE
            """,
            (selected_ids,),
        )
        cursor.fetchall()
        cursor.execute(
            """
            SELECT sensor_id
            FROM sensor_configuration_state
            WHERE sensor_id = ANY(%s::uuid[])
            ORDER BY sensor_id
            FOR UPDATE
            """,
            (selected_ids,),
        )
        cursor.fetchall()

    filter_clause = ""
    parameters: tuple[Any, ...] = ()
    if selected_ids is not None:
        filter_clause = "AND sensor.id = ANY(%s::uuid[])"
        parameters = (selected_ids,)
    cursor.execute(
        f"""
            SELECT {READINESS_SENSOR_COLUMNS}
            FROM sensors AS sensor
            LEFT JOIN sensor_configuration_state AS configuration
              ON configuration.sensor_id = sensor.id
            WHERE sensor.deleted_at IS NULL
              {filter_clause}
            ORDER BY sensor.sensor_key
        """,
        parameters,
    )
    sensors = [_evaluate_sensor(dict(row), policy) for row in cursor.fetchall()]
    return policy, sensors


def get_sensor_fleet_readiness() -> dict[str, Any]:
    with connection() as conn, conn.cursor() as cursor:
        policy, sensors = assess_sensor_fleet_readiness(cursor)

    counts = Counter(sensor["readiness_status"] for sensor in sensors)
    assessed = [
        sensor for sensor in sensors
        if sensor["readiness_status"] != "excluded"
    ]
    versions = Counter(
        sensor["agent_version"] or "unknown"
        for sensor in assessed
    )
    return {
        "generated_at": datetime.now(timezone.utc),
        "policy": policy,
        "summary": {
            "total_count": len(sensors),
            "assessed_count": len(assessed),
            "ready_count": counts["ready"],
            "attention_count": counts["attention"],
            "blocked_count": counts["blocked"],
            "excluded_count": counts["excluded"],
            "rollout_eligible_count": sum(
                1 for sensor in sensors if sensor["rollout_eligible"]
            ),
        },
        "version_distribution": [
            {"agent_version": version, "sensor_count": count}
            for version, count in sorted(
                versions.items(),
                key=lambda item: (
                    _parse_agent_version(item[0]) is None,
                    _parse_agent_version(item[0]) or (0, 0, 0),
                ),
            )
        ],
        "sensors": sensors,
    }


def update_sensor_fleet_readiness_policy(
    *,
    payload: SensorFleetReadinessPolicyUpdate,
    actor: str,
) -> dict[str, Any]:
    with connection() as conn, conn.cursor() as cursor:
        before = _read_policy(cursor, for_update=True)
        if before["revision"] != payload.expected_revision:
            raise FleetReadinessPolicyConflict(
                "fleet readiness policy changed; refresh before saving"
            )

        cursor.execute(
            f"""
            UPDATE sensor_fleet_readiness_policy
            SET
                revision = revision + 1,
                minimum_agent_version = %(minimum_agent_version)s,
                recommended_agent_version = %(recommended_agent_version)s,
                require_source_connected = %(require_source_connected)s,
                require_configuration_compliance =
                    %(require_configuration_compliance)s,
                rollout_application_timeout_seconds =
                    COALESCE(
                        %(rollout_application_timeout_seconds)s,
                        rollout_application_timeout_seconds
                    ),
                updated_at = NOW(),
                updated_by = %(actor)s
            WHERE id = 1
              AND revision = %(expected_revision)s
            RETURNING {POLICY_COLUMNS}
            """,
            {
                **payload.model_dump(mode="json"),
                "actor": actor,
            },
        )
        row = cursor.fetchone()
        if row is None:
            raise FleetReadinessPolicyConflict(
                "fleet readiness policy changed; refresh before saving"
            )
        after = dict(row)
        cursor.execute(
            """
            INSERT INTO audit_events (
                event_type,
                actor,
                details
            )
            VALUES (
                'sensor_fleet_readiness_policy_changed',
                %(actor)s,
                jsonb_build_object(
                    'before', %(before)s::jsonb,
                    'after', %(after)s::jsonb,
                    'change_note', %(change_note)s::text
                )
            )
            """,
            {
                "actor": actor,
                "before": _policy_audit_json(before),
                "after": _policy_audit_json(after),
                "change_note": payload.change_note,
            },
        )
        return after


def _policy_audit_json(policy: dict[str, Any]) -> str:
    return json.dumps(
        {
            "revision": policy["revision"],
            "minimum_agent_version": policy["minimum_agent_version"],
            "recommended_agent_version": policy["recommended_agent_version"],
            "require_source_connected": policy["require_source_connected"],
            "require_configuration_compliance": policy[
                "require_configuration_compliance"
            ],
            "rollout_application_timeout_seconds": policy[
                "rollout_application_timeout_seconds"
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    )

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.config import settings
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


READINESS_STATE_COLUMNS = """
    sensor_id,
    policy_revision,
    readiness_status,
    rollout_eligible,
    agent_version_state,
    reasons,
    first_observed_at,
    state_changed_at,
    last_evaluated_at
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


def _normalized_reasons(sensor: dict[str, Any]) -> list[dict[str, str]]:
    return sorted(
        [
            {
                "code": str(reason["code"]),
                "severity": str(reason["severity"]),
            }
            for reason in sensor["reasons"]
        ],
        key=lambda reason: (reason["severity"], reason["code"]),
    )


def _readiness_assessment(sensor: dict[str, Any]) -> dict[str, Any]:
    return {
        "readiness_status": sensor["readiness_status"],
        "rollout_eligible": bool(sensor["rollout_eligible"]),
        "agent_version_state": sensor["agent_version_state"],
        "reasons": _normalized_reasons(sensor),
    }


def _assessment_changed(
    recorded: dict[str, Any],
    assessment: dict[str, Any],
) -> bool:
    return any(
        recorded[field] != assessment[field]
        for field in (
            "readiness_status",
            "rollout_eligible",
            "agent_version_state",
            "reasons",
        )
    )


def _insert_readiness_history(
    cursor: Any,
    *,
    sensor_id: UUID,
    policy_revision: int,
    assessment: dict[str, Any],
    observed_at: datetime,
    previous: dict[str, Any] | None,
) -> None:
    cursor.execute(
        """
        INSERT INTO sensor_fleet_readiness_history (
            sensor_id,
            policy_revision,
            change_type,
            previous_readiness_status,
            readiness_status,
            previous_rollout_eligible,
            rollout_eligible,
            previous_agent_version_state,
            agent_version_state,
            previous_reasons,
            reasons,
            observed_at
        )
        VALUES (
            %(sensor_id)s,
            %(policy_revision)s,
            %(change_type)s,
            %(previous_readiness_status)s,
            %(readiness_status)s,
            %(previous_rollout_eligible)s,
            %(rollout_eligible)s,
            %(previous_agent_version_state)s,
            %(agent_version_state)s,
            %(previous_reasons)s,
            %(reasons)s,
            %(observed_at)s
        )
        """,
        {
            "sensor_id": sensor_id,
            "policy_revision": policy_revision,
            "change_type": "initial" if previous is None else "changed",
            "previous_readiness_status": (
                None if previous is None else previous["readiness_status"]
            ),
            "readiness_status": assessment["readiness_status"],
            "previous_rollout_eligible": (
                None if previous is None else previous["rollout_eligible"]
            ),
            "rollout_eligible": assessment["rollout_eligible"],
            "previous_agent_version_state": (
                None if previous is None else previous["agent_version_state"]
            ),
            "agent_version_state": assessment["agent_version_state"],
            "previous_reasons": (
                None if previous is None else Jsonb(previous["reasons"])
            ),
            "reasons": Jsonb(assessment["reasons"]),
            "observed_at": observed_at,
        },
    )


def reconcile_sensor_fleet_readiness(
    *,
    observed_at: datetime | None = None,
) -> dict[str, int]:
    """Persist current readiness and append history only for real changes."""
    evaluated_at = observed_at or datetime.now(timezone.utc)
    refresh_before = evaluated_at - timedelta(
        seconds=settings.fleet_readiness_state_refresh_seconds
    )
    initial_states = 0
    changed_states = 0
    refreshed_states = 0

    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended('rdds:fleet-readiness-history', 0))"
        )
        policy, sensors = assess_sensor_fleet_readiness(cursor)
        sensor_ids = sorted(
            (sensor["id"] for sensor in sensors),
            key=str,
        )
        recorded_by_sensor: dict[UUID, dict[str, Any]] = {}
        if sensor_ids:
            cursor.execute(
                f"""
                SELECT {READINESS_STATE_COLUMNS}
                FROM sensor_fleet_readiness_state
                WHERE sensor_id = ANY(%s::uuid[])
                ORDER BY sensor_id
                FOR UPDATE
                """,
                (sensor_ids,),
            )
            recorded_by_sensor = {
                row["sensor_id"]: dict(row)
                for row in cursor.fetchall()
            }

        for sensor in sorted(sensors, key=lambda item: str(item["id"])):
            sensor_id = sensor["id"]
            assessment = _readiness_assessment(sensor)
            previous = recorded_by_sensor.get(sensor_id)
            if previous is None:
                cursor.execute(
                    """
                    INSERT INTO sensor_fleet_readiness_state (
                        sensor_id,
                        policy_revision,
                        readiness_status,
                        rollout_eligible,
                        agent_version_state,
                        reasons,
                        first_observed_at,
                        state_changed_at,
                        last_evaluated_at
                    )
                    VALUES (
                        %(sensor_id)s,
                        %(policy_revision)s,
                        %(readiness_status)s,
                        %(rollout_eligible)s,
                        %(agent_version_state)s,
                        %(reasons)s,
                        %(evaluated_at)s,
                        %(evaluated_at)s,
                        %(evaluated_at)s
                    )
                    """,
                    {
                        "sensor_id": sensor_id,
                        "policy_revision": policy["revision"],
                        **assessment,
                        "reasons": Jsonb(assessment["reasons"]),
                        "evaluated_at": evaluated_at,
                    },
                )
                _insert_readiness_history(
                    cursor,
                    sensor_id=sensor_id,
                    policy_revision=policy["revision"],
                    assessment=assessment,
                    observed_at=evaluated_at,
                    previous=None,
                )
                initial_states += 1
                continue

            changed = _assessment_changed(previous, assessment)
            policy_changed = previous["policy_revision"] != policy["revision"]
            refresh_due = previous["last_evaluated_at"] <= refresh_before
            if not (changed or policy_changed or refresh_due):
                continue

            cursor.execute(
                """
                UPDATE sensor_fleet_readiness_state
                SET
                    policy_revision = %(policy_revision)s,
                    readiness_status = %(readiness_status)s,
                    rollout_eligible = %(rollout_eligible)s,
                    agent_version_state = %(agent_version_state)s,
                    reasons = %(reasons)s,
                    state_changed_at = %(state_changed_at)s,
                    last_evaluated_at = %(evaluated_at)s
                WHERE sensor_id = %(sensor_id)s
                """,
                {
                    "sensor_id": sensor_id,
                    "policy_revision": policy["revision"],
                    **assessment,
                    "reasons": Jsonb(assessment["reasons"]),
                    "state_changed_at": (
                        evaluated_at if changed else previous["state_changed_at"]
                    ),
                    "evaluated_at": evaluated_at,
                },
            )
            if changed:
                _insert_readiness_history(
                    cursor,
                    sensor_id=sensor_id,
                    policy_revision=policy["revision"],
                    assessment=assessment,
                    observed_at=evaluated_at,
                    previous=previous,
                )
                changed_states += 1
            else:
                refreshed_states += 1

    return {
        "evaluated": len(sensors),
        "initial_states": initial_states,
        "changed_states": changed_states,
        "refreshed_states": refreshed_states,
        "history_events": initial_states + changed_states,
    }


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


def list_sensor_fleet_readiness_history(
    *,
    sensor_id: UUID | None = None,
    hours: int = 24,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filter_parameters = {
        "sensor_id": sensor_id,
        "hours": hours,
    }
    page_parameters = {
        **filter_parameters,
        "limit": limit,
        "offset": offset,
    }
    history_filter = """
        history.observed_at >= NOW() - (%(hours)s * INTERVAL '1 hour')
        AND (
            %(sensor_id)s::uuid IS NULL
            OR history.sensor_id = %(sensor_id)s
        )
    """
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)::BIGINT AS total
            FROM sensor_fleet_readiness_history AS history
            WHERE {history_filter}
            """,
            filter_parameters,
        )
        total_row = cursor.fetchone()
        total = 0 if total_row is None else int(total_row["total"])
        cursor.execute(
            f"""
            SELECT
                history.id,
                history.sensor_id,
                sensor.sensor_key,
                sensor.display_name AS sensor_name,
                history.policy_revision,
                history.change_type,
                history.previous_readiness_status,
                history.readiness_status,
                history.previous_rollout_eligible,
                history.rollout_eligible,
                history.previous_agent_version_state,
                history.agent_version_state,
                history.previous_reasons,
                history.reasons,
                history.observed_at
            FROM sensor_fleet_readiness_history AS history
            JOIN sensors AS sensor ON sensor.id = history.sensor_id
            WHERE {history_filter}
            ORDER BY history.observed_at DESC, history.id DESC
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            page_parameters,
        )
        events = [dict(row) for row in cursor.fetchall()]
    return events, total


def _readiness_timeline_segment(
    *,
    readiness_status: str,
    rollout_eligible: bool | None,
    agent_version_state: str | None,
    reasons: list[dict[str, str]],
    policy_revision: int | None,
    started_at: datetime,
    ended_at: datetime,
) -> dict[str, Any]:
    return {
        "readiness_status": readiness_status,
        "rollout_eligible": rollout_eligible,
        "agent_version_state": agent_version_state,
        "reasons": reasons,
        "policy_revision": policy_revision,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": max(
            0.0,
            round((ended_at - started_at).total_seconds(), 3),
        ),
    }


def _readiness_timeline_summary(
    *,
    current_state: dict[str, Any],
    events: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    """Build an honest, gap-aware readiness timeline for one sensor."""
    prior_events = [event for event in events if event["observed_at"] < window_start]
    window_events = [
        event
        for event in events
        if window_start <= event["observed_at"] <= window_end
    ]

    timeline: list[dict[str, Any]] = []

    def append_segment(
        state: dict[str, Any],
        started_at: datetime,
        ended_at: datetime,
    ) -> None:
        if ended_at <= started_at:
            return
        timeline.append(
            _readiness_timeline_segment(
                readiness_status=state["readiness_status"],
                rollout_eligible=state.get("rollout_eligible"),
                agent_version_state=state.get("agent_version_state"),
                reasons=list(state.get("reasons") or []),
                policy_revision=state.get("policy_revision"),
                started_at=started_at,
                ended_at=ended_at,
            )
        )

    def event_state(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "readiness_status": event["readiness_status"],
            "rollout_eligible": event["rollout_eligible"],
            "agent_version_state": event["agent_version_state"],
            "reasons": list(event.get("reasons") or []),
            "policy_revision": event["policy_revision"],
        }

    cursor_at = window_start
    state: dict[str, Any] | None = None
    remaining_events = window_events
    coverage_start: datetime | None = None

    if prior_events:
        state = event_state(prior_events[-1])
        coverage_start = window_start
    elif window_events:
        first_event = window_events[0]
        first_observed_at = min(max(first_event["observed_at"], window_start), window_end)
        if first_observed_at > window_start:
            append_segment(
                {
                    "readiness_status": "unknown",
                    "rollout_eligible": None,
                    "agent_version_state": None,
                    "reasons": [],
                    "policy_revision": None,
                },
                window_start,
                first_observed_at,
            )
        cursor_at = first_observed_at
        coverage_start = first_observed_at
        state = event_state(first_event)
        remaining_events = window_events[1:]
    elif current_state.get("readiness_status") is not None:
        first_observed_at = current_state.get("first_observed_at")
        state_changed_at = current_state.get("state_changed_at")
        known_since = state_changed_at or first_observed_at or window_end
        if first_observed_at is not None:
            known_since = max(known_since, first_observed_at)
        known_since = min(max(known_since, window_start), window_end)
        if known_since > window_start:
            append_segment(
                {
                    "readiness_status": "unknown",
                    "rollout_eligible": None,
                    "agent_version_state": None,
                    "reasons": [],
                    "policy_revision": None,
                },
                window_start,
                known_since,
            )
        cursor_at = known_since
        coverage_start = known_since
        state = {
            "readiness_status": current_state["readiness_status"],
            "rollout_eligible": current_state.get("rollout_eligible"),
            "agent_version_state": current_state.get("agent_version_state"),
            "reasons": list(current_state.get("reasons") or []),
            "policy_revision": current_state.get("policy_revision"),
        }

    for event in remaining_events:
        event_at = min(max(event["observed_at"], window_start), window_end)
        if state is not None:
            append_segment(state, cursor_at, event_at)
        state = event_state(event)
        cursor_at = max(cursor_at, event_at)

    if state is not None:
        append_segment(state, cursor_at, window_end)
    elif not timeline and window_end > window_start:
        append_segment(
            {
                "readiness_status": "unknown",
                "rollout_eligible": None,
                "agent_version_state": None,
                "reasons": [],
                "policy_revision": None,
            },
            window_start,
            window_end,
        )

    durations = {
        "ready": 0.0,
        "attention": 0.0,
        "blocked": 0.0,
        "excluded": 0.0,
        "unknown": 0.0,
    }
    for segment in timeline:
        status = segment["readiness_status"]
        durations[status if status in durations else "unknown"] += segment[
            "duration_seconds"
        ]

    assessed_seconds = (
        durations["ready"] + durations["attention"] + durations["blocked"]
    )
    ready_percent = None
    if assessed_seconds > 0:
        ready_percent = round(100 * durations["ready"] / assessed_seconds, 2)

    return {
        "coverage_start": coverage_start,
        "coverage_end": window_end,
        "coverage_seconds": round(
            durations["ready"]
            + durations["attention"]
            + durations["blocked"]
            + durations["excluded"],
            3,
        ),
        "window_seconds": max(
            0.0,
            round((window_end - window_start).total_seconds(), 3),
        ),
        "summary": {
            "ready_percent": ready_percent,
            "ready_seconds": round(durations["ready"], 3),
            "attention_seconds": round(durations["attention"], 3),
            "blocked_seconds": round(durations["blocked"], 3),
            "excluded_seconds": round(durations["excluded"], 3),
            "unknown_seconds": round(durations["unknown"], 3),
            "transition_count": sum(
                1
                for event in window_events
                if event.get("change_type") == "changed"
            ),
            "readiness_change_count": sum(
                1
                for event in window_events
                if event.get("change_type") == "changed"
                and event.get("previous_readiness_status")
                != event.get("readiness_status")
            ),
        },
        "timeline": timeline,
    }


def get_sensor_fleet_readiness_timeline(
    sensor_id: UUID,
    hours: int,
) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                sensor.id,
                sensor.sensor_key AS sensor_id,
                sensor.display_name,
                state.policy_revision,
                state.readiness_status,
                state.rollout_eligible,
                state.agent_version_state,
                state.reasons,
                state.first_observed_at,
                state.state_changed_at,
                state.last_evaluated_at,
                NOW() AS generated_at
            FROM sensors AS sensor
            LEFT JOIN sensor_fleet_readiness_state AS state
              ON state.sensor_id = sensor.id
            WHERE sensor.id = %s
              AND sensor.deleted_at IS NULL
            """,
            (sensor_id,),
        )
        sensor = cursor.fetchone()
        if sensor is None:
            return None

        current_state = dict(sensor)
        window_end = current_state["generated_at"]
        window_start = window_end - timedelta(hours=hours)
        cursor.execute(
            """
            WITH prior_event AS (
                SELECT
                    id,
                    policy_revision,
                    change_type,
                    previous_readiness_status,
                    readiness_status,
                    rollout_eligible,
                    agent_version_state,
                    reasons,
                    observed_at
                FROM sensor_fleet_readiness_history
                WHERE sensor_id = %(sensor_id)s
                  AND observed_at < %(window_start)s
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
            ),
            window_events AS (
                SELECT
                    id,
                    policy_revision,
                    change_type,
                    previous_readiness_status,
                    readiness_status,
                    rollout_eligible,
                    agent_version_state,
                    reasons,
                    observed_at
                FROM sensor_fleet_readiness_history
                WHERE sensor_id = %(sensor_id)s
                  AND observed_at >= %(window_start)s
                  AND observed_at <= %(window_end)s
            )
            SELECT * FROM prior_event
            UNION ALL
            SELECT * FROM window_events
            ORDER BY observed_at, id
            """,
            {
                "sensor_id": sensor_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        events = [dict(row) for row in cursor.fetchall()]

    timeline = _readiness_timeline_summary(
        current_state=current_state,
        events=events,
        window_start=window_start,
        window_end=window_end,
    )
    return {
        "sensor_id": current_state["sensor_id"],
        "display_name": current_state["display_name"],
        "window_hours": hours,
        "current": {
            "policy_revision": current_state.get("policy_revision"),
            "readiness_status": current_state.get("readiness_status"),
            "rollout_eligible": current_state.get("rollout_eligible"),
            "agent_version_state": current_state.get("agent_version_state"),
            "reasons": list(current_state.get("reasons") or []),
            "first_observed_at": current_state.get("first_observed_at"),
            "state_changed_at": current_state.get("state_changed_at"),
            "last_evaluated_at": current_state.get("last_evaluated_at"),
        },
        **timeline,
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

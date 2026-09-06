from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.database import connection


RELEASE_COLUMNS = """
    release.id,
    release.version,
    release.channel,
    release.status,
    release.minimum_agent_version,
    release.protocol_version,
    release.published_at,
    release.withdrawn_at
"""


SENSOR_COLUMNS = """
    sensor.id,
    sensor.sensor_key,
    sensor.display_name,
    sensor.status,
    sensor.agent_version,
    sensor.last_heartbeat_received_at AS last_heartbeat_at
"""


def _parse_version(value: str | None) -> tuple[int, int, int] | None:
    if value is None or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value) is None:
        return None
    return tuple(int(part) for part in value.split("."))


def _release_reference(release: dict[str, Any] | None) -> dict[str, Any] | None:
    if release is None:
        return None
    return {
        "id": release["id"],
        "version": release["version"],
        "channel": release["channel"],
        "status": release["status"],
        "minimum_agent_version": release["minimum_agent_version"],
        "protocol_version": release["protocol_version"],
        "published_at": release["published_at"],
        "withdrawn_at": release["withdrawn_at"],
    }


def _latest_published_release(
    releases: list[dict[str, Any]],
    channel: str,
) -> dict[str, Any] | None:
    candidates = [
        release
        for release in releases
        if release["status"] == "published"
        and release["channel"] == channel
        and _parse_version(release["version"]) is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda release: _parse_version(release["version"]))


def _assess_sensor_release(
    sensor: dict[str, Any],
    *,
    release_by_version: dict[str, dict[str, Any]],
    latest_stable: dict[str, Any] | None,
) -> dict[str, Any]:
    result = dict(sensor)
    current_version = _parse_version(sensor["agent_version"])
    current_release = (
        release_by_version.get(sensor["agent_version"])
        if sensor["agent_version"] is not None
        else None
    )
    reasons: list[str] = []
    update_eligible = False

    if current_version is None:
        state = "unreported"
        reasons.append("agent_version_unreported")
    elif current_release is not None and current_release["status"] == "withdrawn":
        state = "withdrawn"
        reasons.append("installed_release_withdrawn")
    elif latest_stable is None:
        state = "no_stable_release"
        reasons.append("no_published_stable_release")
    else:
        stable_version = _parse_version(latest_stable["version"])
        minimum_version = _parse_version(latest_stable["minimum_agent_version"])
        if stable_version is None or minimum_version is None:
            raise RuntimeError("catalog contains an invalid semantic version")
        if current_version == stable_version:
            state = "current"
        elif current_version < stable_version:
            if current_version < minimum_version:
                state = "upgrade_blocked"
                reasons.append("agent_version_below_release_minimum")
            else:
                state = "upgrade_available"
                update_eligible = True
                reasons.append("newer_stable_release_available")
        elif (
            current_release is not None
            and current_release["status"] == "published"
            and current_release["channel"] == "candidate"
        ):
            state = "candidate"
            reasons.append("published_candidate_installed")
        else:
            state = "ahead"
            reasons.append("agent_version_ahead_of_stable_catalog")

    if current_version is not None and latest_stable is not None:
        stable_version = _parse_version(latest_stable["version"])
        minimum_version = _parse_version(latest_stable["minimum_agent_version"])
        update_eligible = bool(
            stable_version is not None
            and minimum_version is not None
            and minimum_version <= current_version < stable_version
        )
    if update_eligible and sensor["status"] not in {"online", "degraded"}:
        update_eligible = False
        reasons.append("sensor_not_online")

    result.update(
        release_state=state,
        update_eligible=update_eligible,
        reason_codes=reasons,
        current_release=_release_reference(current_release),
        recommended_release=_release_reference(latest_stable),
    )
    return result


def get_sensor_agent_release_compliance() -> dict[str, Any]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {RELEASE_COLUMNS}
            FROM sensor_agent_releases AS release
            ORDER BY release.created_at, release.id
            """
        )
        releases = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            f"""
            SELECT {SENSOR_COLUMNS}
            FROM sensors AS sensor
            WHERE sensor.deleted_at IS NULL
            ORDER BY sensor.sensor_key
            """
        )
        sensors = [dict(row) for row in cursor.fetchall()]

    release_by_version = {release["version"]: release for release in releases}
    latest_stable = _latest_published_release(releases, "stable")
    latest_candidate = _latest_published_release(releases, "candidate")
    assessed = [
        _assess_sensor_release(
            sensor,
            release_by_version=release_by_version,
            latest_stable=latest_stable,
        )
        for sensor in sensors
    ]
    counts = Counter(sensor["release_state"] for sensor in assessed)
    return {
        "catalog": {
            "release_count": len(releases),
            "draft_count": sum(release["status"] == "draft" for release in releases),
            "published_count": sum(
                release["status"] == "published" for release in releases
            ),
            "withdrawn_count": sum(
                release["status"] == "withdrawn" for release in releases
            ),
            "latest_stable": _release_reference(latest_stable),
            "latest_candidate": _release_reference(latest_candidate),
        },
        "summary": {
            "sensor_count": len(assessed),
            "current_count": counts["current"],
            "upgrade_available_count": counts["upgrade_available"],
            "upgrade_blocked_count": counts["upgrade_blocked"],
            "candidate_count": counts["candidate"],
            "ahead_count": counts["ahead"],
            "withdrawn_count": counts["withdrawn"],
            "unreported_count": counts["unreported"],
            "no_stable_release_count": counts["no_stable_release"],
            "update_eligible_count": sum(
                sensor["update_eligible"] for sensor in assessed
            ),
        },
        "sensors": assessed,
    }

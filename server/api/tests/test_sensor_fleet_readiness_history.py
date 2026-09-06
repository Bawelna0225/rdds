from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4


REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import fleet_readiness_store
    from app import main as api_main


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "database/migrations/027_sensor_fleet_readiness_history.sql"
).read_text(encoding="utf-8")
STORE = (ROOT / "server/api/app/fleet_readiness_store.py").read_text(
    encoding="utf-8"
)
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "server/api/app/config.py").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


class FakeCursor:
    def __init__(self, *, rows_sequence=None, row_sequence=None):
        self.queries: list[str] = []
        self.parameters: list[object] = []
        self._rows_sequence = list(rows_sequence or [])
        self._row_sequence = list(row_sequence or [])
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, parameters=None):
        self.queries.append(query)
        self.parameters.append(parameters)

    def fetchall(self):
        if not self._rows_sequence:
            return []
        return self._rows_sequence.pop(0)

    def fetchone(self):
        if not self._row_sequence:
            return None
        return self._row_sequence.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def fake_connection_for(cursor: FakeCursor):
    @contextmanager
    def fake_connection():
        yield FakeConnection(cursor)

    return fake_connection


def readiness_sensor(
    *,
    sensor_id: UUID | None = None,
    readiness_status: str = "ready",
    agent_version_state: str = "compliant",
    reasons: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "id": sensor_id or uuid4(),
        "readiness_status": readiness_status,
        "rollout_eligible": readiness_status == "ready",
        "agent_version_state": agent_version_state,
        "reasons": reasons or [],
    }


def recorded_state(
    sensor: dict[str, object],
    *,
    policy_revision: int = 6,
    last_evaluated_at: datetime,
    state_changed_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "sensor_id": sensor["id"],
        "policy_revision": policy_revision,
        "readiness_status": sensor["readiness_status"],
        "rollout_eligible": sensor["rollout_eligible"],
        "agent_version_state": sensor["agent_version_state"],
        "reasons": sensor["reasons"],
        "first_observed_at": last_evaluated_at - timedelta(hours=1),
        "state_changed_at": state_changed_at or last_evaluated_at - timedelta(hours=1),
        "last_evaluated_at": last_evaluated_at,
    }


class FleetReadinessHistoryMigrationTests(unittest.TestCase):
    def test_current_state_and_immutable_history_are_separate(self) -> None:
        self.assertIn("CREATE TABLE sensor_fleet_readiness_state", MIGRATION)
        self.assertIn("sensor_id UUID PRIMARY KEY", MIGRATION)
        self.assertIn("CREATE TABLE sensor_fleet_readiness_history", MIGRATION)
        self.assertIn("id BIGSERIAL PRIMARY KEY", MIGRATION)

    def test_state_and_history_use_bounded_readiness_values(self) -> None:
        self.assertGreaterEqual(
            MIGRATION.count(
                "readiness_status IN ('ready', 'attention', 'blocked', 'excluded')"
            ),
            2,
        )
        self.assertGreaterEqual(
            MIGRATION.count("rollout_eligible = (readiness_status = 'ready')"),
            2,
        )
        self.assertIn("jsonb_typeof(reasons) = 'array'", MIGRATION)

    def test_initial_and_changed_history_have_consistent_previous_values(self) -> None:
        self.assertIn("change_type IN ('initial', 'changed')", MIGRATION)
        self.assertIn("change_type = 'initial'", MIGRATION)
        self.assertIn("previous_readiness_status IS NULL", MIGRATION)
        self.assertIn("change_type = 'changed'", MIGRATION)
        self.assertIn("previous_readiness_status IS NOT NULL", MIGRATION)
        self.assertIn("previous_reasons IS DISTINCT FROM reasons", MIGRATION)

    def test_history_has_sensor_and_global_time_indexes(self) -> None:
        self.assertIn(
            "idx_sensor_fleet_readiness_history_sensor_time",
            MIGRATION,
        )
        self.assertIn("idx_sensor_fleet_readiness_history_time", MIGRATION)


class FleetReadinessHistoryReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        self.settings = SimpleNamespace(
            fleet_readiness_state_refresh_seconds=300
        )

    def reconcile(
        self,
        cursor: FakeCursor,
        sensors: list[dict[str, object]],
        *,
        policy_revision: int = 6,
    ) -> dict[str, int]:
        with (
            patch.object(
                fleet_readiness_store,
                "connection",
                fake_connection_for(cursor),
            ),
            patch.object(
                fleet_readiness_store,
                "assess_sensor_fleet_readiness",
                return_value=({"revision": policy_revision}, sensors),
            ),
            patch.object(fleet_readiness_store, "settings", self.settings),
        ):
            return fleet_readiness_store.reconcile_sensor_fleet_readiness(
                observed_at=self.now
            )

    def test_first_assessment_creates_state_and_one_history_event(self) -> None:
        sensor = readiness_sensor()
        cursor = FakeCursor(rows_sequence=[[]])

        result = self.reconcile(cursor, [sensor])

        self.assertEqual(1, result["initial_states"])
        self.assertEqual(1, result["history_events"])
        combined = "\n".join(cursor.queries)
        self.assertIn("INSERT INTO sensor_fleet_readiness_state", combined)
        self.assertIn("INSERT INTO sensor_fleet_readiness_history", combined)
        history_index = next(
            index
            for index, query in enumerate(cursor.queries)
            if "INSERT INTO sensor_fleet_readiness_history" in query
        )
        parameters = cursor.parameters[history_index]
        assert isinstance(parameters, dict)
        self.assertEqual("initial", parameters["change_type"])
        self.assertIsNone(parameters["previous_readiness_status"])

    def test_unchanged_fresh_assessment_performs_no_write(self) -> None:
        sensor = readiness_sensor()
        before = recorded_state(sensor, last_evaluated_at=self.now)
        cursor = FakeCursor(rows_sequence=[[before]])

        result = self.reconcile(cursor, [sensor])

        self.assertEqual(0, result["history_events"])
        self.assertEqual(0, result["refreshed_states"])
        combined = "\n".join(cursor.queries)
        self.assertNotIn("UPDATE sensor_fleet_readiness_state", combined)
        self.assertNotIn("INSERT INTO sensor_fleet_readiness_history", combined)

    def test_reason_order_does_not_create_a_false_transition(self) -> None:
        sensor = readiness_sensor(
            readiness_status="blocked",
            agent_version_state="below_minimum",
            reasons=[
                {"code": "source_disconnected", "severity": "blocked"},
                {"code": "agent_version_below_minimum", "severity": "blocked"},
            ],
        )
        before = recorded_state(sensor, last_evaluated_at=self.now)
        before["reasons"] = list(reversed(before["reasons"]))
        cursor = FakeCursor(rows_sequence=[[before]])

        result = self.reconcile(cursor, [sensor])

        self.assertEqual(0, result["history_events"])
        self.assertNotIn(
            "INSERT INTO sensor_fleet_readiness_history",
            "\n".join(cursor.queries),
        )

    def test_control_refresh_updates_state_without_appending_history(self) -> None:
        sensor = readiness_sensor()
        before = recorded_state(
            sensor,
            last_evaluated_at=self.now - timedelta(seconds=301),
        )
        cursor = FakeCursor(rows_sequence=[[before]])

        result = self.reconcile(cursor, [sensor])

        self.assertEqual(1, result["refreshed_states"])
        self.assertEqual(0, result["history_events"])
        combined = "\n".join(cursor.queries)
        self.assertIn("UPDATE sensor_fleet_readiness_state", combined)
        self.assertNotIn("INSERT INTO sensor_fleet_readiness_history", combined)

    def test_policy_revision_refresh_without_result_change_adds_no_history(self) -> None:
        sensor = readiness_sensor()
        before = recorded_state(
            sensor,
            policy_revision=5,
            last_evaluated_at=self.now,
        )
        cursor = FakeCursor(rows_sequence=[[before]])

        result = self.reconcile(cursor, [sensor], policy_revision=6)

        self.assertEqual(1, result["refreshed_states"])
        self.assertEqual(0, result["history_events"])

    def test_material_change_updates_state_and_appends_previous_values(self) -> None:
        sensor_id = uuid4()
        previous_sensor = readiness_sensor(sensor_id=sensor_id)
        current_sensor = readiness_sensor(
            sensor_id=sensor_id,
            readiness_status="blocked",
            agent_version_state="below_minimum",
            reasons=[
                {"code": "agent_version_below_minimum", "severity": "blocked"}
            ],
        )
        before = recorded_state(
            previous_sensor,
            last_evaluated_at=self.now,
            state_changed_at=self.now - timedelta(hours=2),
        )
        cursor = FakeCursor(rows_sequence=[[before]])

        result = self.reconcile(cursor, [current_sensor])

        self.assertEqual(1, result["changed_states"])
        self.assertEqual(1, result["history_events"])
        history_index = next(
            index
            for index, query in enumerate(cursor.queries)
            if "INSERT INTO sensor_fleet_readiness_history" in query
        )
        parameters = cursor.parameters[history_index]
        assert isinstance(parameters, dict)
        self.assertEqual("changed", parameters["change_type"])
        self.assertEqual("ready", parameters["previous_readiness_status"])
        self.assertEqual("blocked", parameters["readiness_status"])
        self.assertEqual(self.now, parameters["observed_at"])

    def test_reconciliation_is_serialized_and_locks_state_rows_in_order(self) -> None:
        self.assertIn("pg_advisory_xact_lock", STORE)
        self.assertIn("ORDER BY sensor_id\n                FOR UPDATE", STORE)
        self.assertIn("key=lambda item: str(item[\"id\"])", STORE)


class FleetReadinessHistoryApiTests(unittest.TestCase):
    def test_history_store_is_filtered_paginated_and_newest_first(self) -> None:
        sensor_id = uuid4()
        event = {
            "id": 11,
            "sensor_id": sensor_id,
            "readiness_status": "blocked",
        }
        cursor = FakeCursor(
            row_sequence=[{"total": 1}],
            rows_sequence=[[event]],
        )
        with patch.object(
            fleet_readiness_store,
            "connection",
            fake_connection_for(cursor),
        ):
            events, total = (
                fleet_readiness_store.list_sensor_fleet_readiness_history(
                    sensor_id=sensor_id,
                    hours=168,
                    limit=50,
                    offset=10,
                )
            )

        self.assertEqual(1, total)
        self.assertEqual([event], events)
        query = cursor.queries[1]
        self.assertIn("history.sensor_id = %(sensor_id)s", query)
        self.assertIn("ORDER BY history.observed_at DESC, history.id DESC", query)
        self.assertIn("LIMIT %(limit)s", query)
        self.assertIn("OFFSET %(offset)s", query)
        self.assertEqual(168, cursor.parameters[1]["hours"])

    def test_history_endpoint_is_viewer_accessible_and_bounded(self) -> None:
        route = MAIN.split("def get_sensor_fleet_readiness_history_view", 1)[0]
        self.assertIn(
            '"/api/v1/sensor-fleet/readiness-history"',
            route[-500:],
        )
        self.assertIn("dependencies=[Depends(require_viewer)]", route[-500:])
        body = MAIN.split("def get_sensor_fleet_readiness_history_view", 1)[1].split(
            "@app.put(", 1
        )[0]
        self.assertIn("ge=1, le=2160", body)
        self.assertIn("ge=1, le=1000", body)
        self.assertIn("offset: int = Query(default=0, ge=0)", body)

    def test_history_route_returns_pagination_metadata(self) -> None:
        sensor_id = uuid4()
        with patch.object(
            api_main,
            "list_sensor_fleet_readiness_history",
            return_value=([{"id": 1}], 7),
        ) as list_history:
            response = api_main.get_sensor_fleet_readiness_history_view(
                sensor_id=sensor_id,
                hours=24,
                limit=50,
                offset=0,
            )

        self.assertEqual(7, response["total"])
        self.assertEqual([{"id": 1}], response["events"])
        list_history.assert_called_once_with(
            sensor_id=sensor_id,
            hours=24,
            limit=50,
            offset=0,
        )

    def test_monitor_records_readiness_after_health_before_rollout_safety(self) -> None:
        body = MAIN.split("async def sensor_status_monitor", 1)[1].split(
            "@asynccontextmanager", 1
        )[0]
        health_position = body.index("mark_stale_sensors")
        history_position = body.index("reconcile_sensor_fleet_readiness")
        rollout_position = body.index("monitor_active_sensor_configuration_rollouts")
        self.assertLess(health_position, history_position)
        self.assertLess(history_position, rollout_position)

    def test_refresh_interval_is_bounded_and_passed_only_to_api(self) -> None:
        self.assertIn("fleet_readiness_state_refresh_seconds", CONFIG)
        self.assertIn(
            "RDDS_FLEET_READINESS_STATE_REFRESH_SECONDS must be between 30 and 3600",
            CONFIG,
        )
        self.assertIn(
            "RDDS_FLEET_READINESS_STATE_REFRESH_SECONDS: "
            "${RDDS_FLEET_READINESS_STATE_REFRESH_SECONDS:-300}",
            COMPOSE,
        )
        self.assertEqual(
            1,
            sum(
                line.lstrip().startswith(
                    "RDDS_FLEET_READINESS_STATE_REFRESH_SECONDS:"
                )
                for line in COMPOSE.splitlines()
            ),
        )
        self.assertIn("RDDS_FLEET_READINESS_STATE_REFRESH_SECONDS=300", ENV_EXAMPLE)


if __name__ == "__main__":
    unittest.main()

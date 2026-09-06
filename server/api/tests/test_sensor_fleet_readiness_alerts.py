from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import sensor_alert_store


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "database/migrations/028_sensor_fleet_readiness_alerts.sql"
).read_text(encoding="utf-8")
STORE = (ROOT / "server/api/app/sensor_alert_store.py").read_text(encoding="utf-8")
PROCESSOR = (ROOT / "server/api/app/alert_processor.py").read_text(
    encoding="utf-8"
)
CONFIG = (ROOT / "server/api/app/config.py").read_text(encoding="utf-8")
AUDIT_STORE = (ROOT / "server/api/app/audit_store.py").read_text(
    encoding="utf-8"
)
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
WEB = (ROOT / "web/src/main.js").read_text(encoding="utf-8")


class FakeCursor:
    def __init__(self, rowcounts: list[int]) -> None:
        self.queries: list[str] = []
        self.parameters: list[object] = []
        self._rowcounts = iter(rowcounts)
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, parameters=None):
        self.queries.append(query)
        self.parameters.append(parameters)
        self.rowcount = next(self._rowcounts)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


def fake_connection_for(cursor: FakeCursor):
    @contextmanager
    def fake_connection():
        yield FakeConnection(cursor)

    return fake_connection


def compose_key_count(key: str) -> int:
    prefix = f"{key}:"
    return sum(line.lstrip().startswith(prefix) for line in COMPOSE.splitlines())


class FleetReadinessAlertTests(unittest.TestCase):
    def test_migration_adds_typed_alert_kind_and_json_context(self) -> None:
        self.assertIn("ADD COLUMN alert_kind TEXT NOT NULL DEFAULT 'health'", MIGRATION)
        self.assertIn("CHECK (alert_kind IN ('health', 'readiness'))", MIGRATION)
        self.assertIn("ADD COLUMN condition_details JSONB", MIGRATION)
        self.assertIn("jsonb_typeof(condition_details) = 'object'", MIGRATION)

    def test_migration_replaces_global_open_alert_uniqueness(self) -> None:
        self.assertIn("DROP INDEX IF EXISTS uq_sensor_alerts_open_sensor", MIGRATION)
        self.assertIn("uq_sensor_alerts_open_sensor_kind", MIGRATION)
        self.assertIn("ON sensor_alerts (sensor_id, alert_kind)", MIGRATION)
        self.assertIn("state IN ('active', 'acknowledged')", MIGRATION)

    def test_migration_preserves_alert_audit_with_kind_and_context(self) -> None:
        self.assertIn("CREATE OR REPLACE FUNCTION record_sensor_alert_audit_event", MIGRATION)
        self.assertIn("'alert_kind', NEW.alert_kind", MIGRATION)
        self.assertIn("'condition_details', NEW.condition_details", MIGRATION)
        self.assertIn("EXECUTE FUNCTION record_sensor_alert_audit_event()", MIGRATION)

    def test_health_alert_evaluator_is_scoped_to_health_kind(self) -> None:
        body = STORE.split("def evaluate_sensor_alerts", 1)[1].split(
            "def evaluate_sensor_readiness_alerts", 1
        )[0]
        self.assertIn("'health'", body)
        self.assertIn("existing.alert_kind = 'health'", body)
        self.assertIn("alert.alert_kind = 'health'", body)
        self.assertIn("ON CONFLICT (sensor_id, alert_kind)", body)

    def test_readiness_evaluator_uses_delays_and_composite_deduplication(self) -> None:
        cursor = FakeCursor([3, 2])
        with patch.object(
            sensor_alert_store,
            "connection",
            fake_connection_for(cursor),
        ):
            opened, closed = sensor_alert_store.evaluate_sensor_readiness_alerts()

        self.assertEqual((3, 2), (opened, closed))
        upsert = cursor.queries[0]
        self.assertIn("readiness_status IN ('attention', 'blocked')", upsert)
        self.assertIn("existing.alert_kind = 'readiness'", upsert)
        self.assertIn("%(blocked_delay)s", upsert)
        self.assertIn("%(attention_delay)s", upsert)
        self.assertIn("ON CONFLICT (sensor_id, alert_kind)", upsert)
        self.assertEqual(120, cursor.parameters[0]["blocked_delay"])
        self.assertEqual(600, cursor.parameters[0]["attention_delay"])

    def test_readiness_alert_retains_complete_condition_context(self) -> None:
        body = STORE.split("def evaluate_sensor_readiness_alerts", 1)[1].split(
            "def list_sensor_alerts", 1
        )[0]
        for field in (
            "readiness_status",
            "policy_revision",
            "rollout_eligible",
            "agent_version_state",
            "reasons",
        ):
            self.assertIn(f"'{field}'", body)
        self.assertIn("condition_details - 'policy_revision'", body)

    def test_readiness_alert_closes_after_recovery_or_exclusion(self) -> None:
        cursor = FakeCursor([0, 4])
        with patch.object(
            sensor_alert_store,
            "connection",
            fake_connection_for(cursor),
        ):
            sensor_alert_store.evaluate_sensor_readiness_alerts()

        close_query = cursor.queries[1]
        self.assertIn("alert.alert_kind = 'readiness'", close_query)
        self.assertIn("NOT IN ('attention', 'blocked')", close_query)
        self.assertIn("'readiness_restored'", close_query)
        self.assertIn("'sensor_excluded'", close_query)
        self.assertIn("'readiness_state_unavailable'", close_query)

    def test_alert_list_exposes_kind_context_and_current_readiness(self) -> None:
        self.assertIn("alert.alert_kind", STORE)
        self.assertIn("alert.condition_details", STORE)
        self.assertIn("fleet_readiness_policy_revision", STORE)
        self.assertIn("fleet_readiness_status", STORE)
        self.assertIn("fleet_readiness_reasons", STORE)

    def test_alert_processor_runs_both_sensor_alert_evaluators(self) -> None:
        self.assertIn("evaluate_sensor_alerts()", PROCESSOR)
        self.assertIn("evaluate_sensor_readiness_alerts()", PROCESSOR)
        self.assertIn("readiness_alerts=%s readiness_alerts_closed=%s", PROCESSOR)

    def test_alert_delay_configuration_has_safe_defaults_and_bounds(self) -> None:
        self.assertIn("sensor_readiness_alert_blocked_after_seconds", CONFIG)
        self.assertIn("sensor_readiness_alert_attention_after_seconds", CONFIG)
        self.assertIn(
            'os.getenv("RDDS_SENSOR_READINESS_ALERT_BLOCKED_AFTER_SECONDS", "120")',
            CONFIG,
        )
        self.assertIn(
            'os.getenv("RDDS_SENSOR_READINESS_ALERT_ATTENTION_AFTER_SECONDS", "600")',
            CONFIG,
        )
        self.assertIn("must be between", CONFIG)

    def test_delay_environment_is_passed_only_to_alert_processor(self) -> None:
        alert_processor = COMPOSE.split("  alert-processor:", 1)[1].split(
            "  maintenance:", 1
        )[0]
        for key in (
            "RDDS_SENSOR_READINESS_ALERT_BLOCKED_AFTER_SECONDS",
            "RDDS_SENSOR_READINESS_ALERT_ATTENTION_AFTER_SECONDS",
        ):
            self.assertEqual(1, compose_key_count(key))
            self.assertIn(f"{key}:", alert_processor)

    def test_environment_example_documents_both_delays(self) -> None:
        self.assertIn("RDDS_SENSOR_READINESS_ALERT_BLOCKED_AFTER_SECONDS=120", ENV_EXAMPLE)
        self.assertIn(
            "RDDS_SENSOR_READINESS_ALERT_ATTENTION_AFTER_SECONDS=600",
            ENV_EXAMPLE,
        )

    def test_web_labels_readiness_alert_kind_and_reasons(self) -> None:
        self.assertIn('readiness: "gotowość floty"', WEB)
        self.assertIn(
            'fleet_readiness_blocked: "gotowość operacyjna zablokowana"',
            WEB,
        )
        self.assertIn(
            'fleet_readiness_attention: "gotowość operacyjna wymaga uwagi"',
            WEB,
        )

    def test_web_alert_details_show_snapshot_and_current_readiness(self) -> None:
        self.assertIn('detailItem("Rodzaj", sensorAlertKindLabel', WEB)
        self.assertIn('"Zarejestrowana gotowość"', WEB)
        self.assertIn('"Zarejestrowane przyczyny"', WEB)
        self.assertIn('"Aktualne przyczyny gotowości"', WEB)

    def test_audit_list_exposes_sensor_alert_kind_and_context(self) -> None:
        self.assertIn("sensor_alert.alert_kind AS sensor_alert_kind", AUDIT_STORE)
        self.assertIn(
            "sensor_alert.condition_details AS sensor_alert_condition_details",
            AUDIT_STORE,
        )


if __name__ == "__main__":
    unittest.main()

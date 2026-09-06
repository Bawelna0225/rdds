from __future__ import annotations

import os
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError


REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app.models import SensorAgentUpdatePlanAction, SensorAgentUpdatePlanCreate


ROOT = Path(__file__).resolve().parents[3]
STORE_PATH = ROOT / "server/api/app/agent_update_plan_store.py"
STORE = STORE_PATH.read_text(encoding="utf-8")
MIGRATION = (
    ROOT / "database/migrations/030_sensor_agent_update_plans.sql"
).read_text(encoding="utf-8")
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/src/styles.css").read_text(encoding="utf-8")
DOC = (ROOT / "docs/RDDS_STAGE27C.md").read_text(encoding="utf-8")

fake_database = types.ModuleType("app.database")
fake_database.connection = object()
with patch.dict(sys.modules, {"app.database": fake_database}):
    NAMESPACE = runpy.run_path(str(STORE_PATH))

parse_version = NAMESPACE["_parse_version"]
assess_target = NAMESPACE["_assess_target"]


def release(
    version: str = "0.27.0",
    *,
    minimum: str = "0.23.0",
) -> dict[str, object]:
    return {
        "id": uuid4(),
        "version": version,
        "minimum_agent_version": minimum,
    }


def sensor(
    version: str | None = "0.26.0",
    *,
    status: str = "online",
) -> dict[str, object]:
    return {
        "id": uuid4(),
        "sensor_key": "sensor-01",
        "status": status,
        "agent_version": version,
    }


class AgentUpdatePlanModelTests(unittest.TestCase):
    def test_create_trims_note_and_preserves_target_order(self) -> None:
        first, second = uuid4(), uuid4()
        payload = SensorAgentUpdatePlanCreate(
            release_id=uuid4(),
            sensor_ids=[second, first],
            change_note="  Kontrolowany plan aktualizacji  ",
        )
        self.assertEqual([second, first], payload.sensor_ids)
        self.assertEqual("Kontrolowany plan aktualizacji", payload.change_note)

    def test_create_rejects_duplicate_empty_and_oversized_target_sets(self) -> None:
        duplicate = uuid4()
        for sensor_ids in ([], [duplicate, duplicate], [uuid4() for _ in range(101)]):
            with self.subTest(count=len(sensor_ids)), self.assertRaises(ValidationError):
                SensorAgentUpdatePlanCreate(
                    release_id=uuid4(),
                    sensor_ids=sensor_ids,
                    change_note="Niepoprawny zestaw",
                )

    def test_cancel_action_requires_revision_and_nonblank_note(self) -> None:
        action = SensorAgentUpdatePlanAction(
            expected_revision=4,
            change_note="  Rezygnacja z planu  ",
        )
        self.assertEqual(4, action.expected_revision)
        self.assertEqual("Rezygnacja z planu", action.change_note)
        with self.assertRaises(ValidationError):
            SensorAgentUpdatePlanAction(expected_revision=0, change_note="   ")


class AgentUpdatePlanAssessmentTests(unittest.TestCase):
    def test_parser_is_strict_numeric_semver(self) -> None:
        self.assertEqual((0, 27, 0), parse_version("0.27.0"))
        for value in (None, "0.27", "v0.27.0", "0.27.0-rc1"):
            with self.subTest(value=value):
                self.assertIsNone(parse_version(value))

    def test_compatible_older_online_agent_is_eligible(self) -> None:
        result = assess_target(sensor("0.26.0"), release("0.27.0"))
        self.assertEqual("eligible", result["eligibility_status"])
        self.assertTrue(result["update_eligible"])
        self.assertEqual([], result["reason_codes"])

    def test_current_agent_is_snapshotted_as_already_current(self) -> None:
        result = assess_target(sensor("0.27.0"), release("0.27.0"))
        self.assertEqual("already_current", result["eligibility_status"])
        self.assertFalse(result["update_eligible"])
        self.assertIn("target_release_already_installed", result["reason_codes"])

    def test_agent_below_release_minimum_is_not_eligible(self) -> None:
        result = assess_target(
            sensor("0.22.1"),
            release("0.27.0", minimum="0.23.0"),
        )
        self.assertEqual("below_minimum", result["eligibility_status"])
        self.assertIn("agent_version_below_release_minimum", result["reason_codes"])

    def test_agent_ahead_of_target_is_not_eligible(self) -> None:
        result = assess_target(sensor("0.28.0"), release("0.27.0"))
        self.assertEqual("ahead", result["eligibility_status"])
        self.assertIn("target_release_is_older", result["reason_codes"])

    def test_unreported_version_is_visible(self) -> None:
        for version in (None, "development"):
            with self.subTest(version=version):
                result = assess_target(sensor(version), release())
                self.assertEqual("unreported", result["eligibility_status"])

    def test_inactive_sensor_is_not_eligible_even_with_compatible_version(self) -> None:
        for status in ("offline", "maintenance", "disabled"):
            with self.subTest(status=status):
                result = assess_target(sensor(status=status), release())
                self.assertEqual("inactive", result["eligibility_status"])
                self.assertIn("sensor_not_online", result["reason_codes"])


class AgentUpdatePlanMigrationTests(unittest.TestCase):
    def test_plan_lifecycle_is_limited_to_draft_and_cancelled(self) -> None:
        self.assertIn("CREATE TABLE sensor_agent_update_plans", MIGRATION)
        self.assertIn("status IN ('draft', 'cancelled')", MIGRATION)
        self.assertIn("revision BIGINT NOT NULL DEFAULT 1", MIGRATION)
        self.assertNotIn("'active'", MIGRATION)
        self.assertNotIn("'approved'", MIGRATION)

    def test_release_identity_is_snapshotted_on_the_plan(self) -> None:
        for column in (
            "release_version",
            "release_channel",
            "release_artifact_sha256",
            "release_minimum_agent_version",
            "release_protocol_version",
        ):
            self.assertIn(column, MIGRATION)

    def test_target_assessment_is_an_ordered_immutable_snapshot(self) -> None:
        self.assertIn("CREATE TABLE sensor_agent_update_plan_targets", MIGRATION)
        self.assertIn("UNIQUE (plan_id, sequence)", MIGRATION)
        self.assertIn("reported_agent_version", MIGRATION)
        self.assertIn("eligibility_status", MIGRATION)
        self.assertIn("reason_codes JSONB", MIGRATION)
        self.assertNotIn("updated_at", MIGRATION)

    def test_database_constrains_counts_and_cancellation_metadata(self) -> None:
        self.assertIn("target_count BETWEEN 1 AND 100", MIGRATION)
        self.assertIn("eligible_count BETWEEN 0 AND target_count", MIGRATION)
        self.assertIn("status = 'cancelled'", MIGRATION)
        self.assertIn("cancellation_reason IS NOT NULL", MIGRATION)

    def test_plan_audit_events_are_allow_listed(self) -> None:
        for event_type in (
            "sensor_agent_update_plan_created",
            "sensor_agent_update_plan_cancelled",
        ):
            self.assertIn(f"'{event_type}'", MIGRATION)


class AgentUpdatePlanStoreTests(unittest.TestCase):
    def test_creation_locks_and_accepts_only_a_published_release(self) -> None:
        create = STORE.split("def create_sensor_agent_update_plan", 1)[1].split(
            "def cancel_sensor_agent_update_plan", 1
        )[0]
        self.assertIn("FOR SHARE", create)
        self.assertIn('release["status"] != "published"', create)

    def test_creation_rejects_missing_or_deleted_target_sensors(self) -> None:
        create = STORE.split("def create_sensor_agent_update_plan", 1)[1].split(
            "def cancel_sensor_agent_update_plan", 1
        )[0]
        self.assertIn("deleted_at IS NULL", create)
        self.assertIn("if missing:", create)

    def test_creation_persists_ordered_target_and_audit_snapshots(self) -> None:
        self.assertIn("enumerate(targets, start=1)", STORE)
        self.assertIn("INSERT INTO sensor_agent_update_plan_targets", STORE)
        self.assertIn("'targets', %(targets)s::jsonb", STORE)
        self.assertIn("'sensor_agent_update_plan_created'", STORE)

    def test_cancel_uses_row_lock_and_optimistic_revision(self) -> None:
        cancel = STORE.split("def cancel_sensor_agent_update_plan", 1)[1]
        self.assertIn("for_update=True", cancel)
        self.assertIn('before["status"] != "draft"', cancel)
        self.assertIn("AND revision = %(expected_revision)s", cancel)
        self.assertIn("revision = revision + 1", cancel)

    def test_store_has_no_sensor_assignment_or_execution_write(self) -> None:
        for forbidden in (
            "UPDATE sensors",
            "UPDATE sensor_configuration_state",
            "desired_agent_version",
            "download_url",
            "subprocess",
        ):
            self.assertNotIn(forbidden, STORE)


class AgentUpdatePlanApiTests(unittest.TestCase):
    def test_list_and_detail_are_viewer_routes(self) -> None:
        for function in (
            "get_sensor_agent_update_plans",
            "get_sensor_agent_update_plan_view",
        ):
            prefix = MAIN.split(f"def {function}", 1)[0][-650:]
            self.assertIn("dependencies=[Depends(require_viewer)]", prefix)

    def test_create_and_cancel_require_administrator_write(self) -> None:
        for function in (
            "post_sensor_agent_update_plan",
            "post_sensor_agent_update_plan_cancel",
        ):
            prefix = MAIN.split(f"def {function}", 1)[0][-650:]
            self.assertIn("dependencies=[Depends(require_administrator_write)]", prefix)

    def test_listing_is_bounded_and_cancelled_is_opt_in(self) -> None:
        body = MAIN.split("def get_sensor_agent_update_plans", 1)[1].split(
            "@app.post", 1
        )[0]
        self.assertIn("include_cancelled: bool = Query(default=False)", body)
        self.assertIn("limit: int = Query(default=100, ge=1, le=500)", body)
        self.assertIn("offset: int = Query(default=0, ge=0)", body)

    def test_conflicts_and_missing_objects_have_distinct_statuses(self) -> None:
        routes = MAIN.split('"/api/v1/sensor-agent-update-plans"', 1)[1].split(
            '"/api/v1/sensor-fleet/agent-release-compliance"', 1
        )[0]
        self.assertGreaterEqual(routes.count("except AgentUpdatePlanConflict as exc:"), 2)
        self.assertIn("status_code=409", routes)
        self.assertIn("status_code=404", routes)


class AgentUpdatePlanWebTests(unittest.TestCase):
    def test_planning_ui_is_inside_the_agent_release_panel(self) -> None:
        release_panel = INDEX.split('id="fleet-panel-releases"', 1)[1].split(
            'id="sensor-token-panel"', 1
        )[0]
        self.assertIn('id="agent-update-plan-list"', release_panel)
        self.assertIn('id="agent-update-plan-create-form"', release_panel)

    def test_ui_exposes_only_create_draft_and_cancel_actions(self) -> None:
        self.assertIn("async function createFleetAgentUpdatePlan", MAIN_JS)
        self.assertIn("async function cancelFleetAgentUpdatePlan", MAIN_JS)
        section = INDEX.split('class="fleet-detail agent-update-plans"', 1)[1].split(
            "</section>", 1
        )[0]
        for forbidden in ("Uruchom", "Zatwierdź", "Pobierz", "Zainstaluj"):
            self.assertNotIn(forbidden, section)

    def test_ui_requires_confirmation_and_states_no_sensor_change(self) -> None:
        create = MAIN_JS.split("async function createFleetAgentUpdatePlan", 1)[1].split(
            "async function cancelFleetAgentUpdatePlan", 1
        )[0]
        cancel = MAIN_JS.split("async function cancelFleetAgentUpdatePlan", 1)[1].split(
            "async function loadFleetConfigurationConsole", 1
        )[0]
        self.assertIn("window.confirm", create)
        self.assertIn("Nie uruchomi to aktualizacji", create)
        self.assertIn("window.confirm", cancel)
        self.assertIn("Sensory pozostaną bez zmian", cancel)

    def test_ui_renders_every_snapshot_eligibility_state(self) -> None:
        for status in (
            "eligible",
            "already_current",
            "below_minimum",
            "ahead",
            "unreported",
            "inactive",
        ):
            self.assertIn(f'{status}: "', MAIN_JS)
        self.assertIn("agent-update-plan-eligibility-eligible", STYLES)

    def test_documentation_preserves_draft_only_boundary(self) -> None:
        self.assertIn("draft-only", DOC)
        self.assertIn("does not download or install", DOC)
        self.assertIn("does not modify sensor configuration", DOC)


if __name__ == "__main__":
    unittest.main()

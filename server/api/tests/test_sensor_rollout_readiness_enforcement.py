from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
READINESS_STORE = (
    ROOT / "server/api/app/fleet_readiness_store.py"
).read_text(encoding="utf-8")
ROLLOUT_STORE = (
    ROOT / "server/api/app/configuration_rollout_store.py"
).read_text(encoding="utf-8")
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/src/styles.css").read_text(encoding="utf-8")
DOC = (ROOT / "docs/RDDS_STAGE25B.md").read_text(encoding="utf-8")


class RolloutReadinessAssessmentTests(unittest.TestCase):
    def test_readiness_assessment_is_reusable_inside_rollout_transaction(self) -> None:
        self.assertIn("def assess_sensor_fleet_readiness(", READINESS_STORE)
        self.assertIn("sensor_ids: list[UUID] | None = None", READINESS_STORE)
        self.assertIn("lock: bool = False", READINESS_STORE)

    def test_authoritative_assessment_locks_policy_sensors_and_configuration(self) -> None:
        body = READINESS_STORE.split("def assess_sensor_fleet_readiness", 1)[1].split(
            "def get_sensor_fleet_readiness", 1
        )[0]
        self.assertIn("_read_policy(cursor, for_update=lock)", body)
        self.assertGreaterEqual(body.count("FOR UPDATE"), 2)
        self.assertIn("FROM sensor_configuration_state", body)

    def test_inventory_uses_the_same_assessment_logic_as_rollouts(self) -> None:
        body = READINESS_STORE.split("def get_sensor_fleet_readiness", 1)[1]
        self.assertIn("assess_sensor_fleet_readiness(cursor)", body)


class RolloutReadinessBoundaryTests(unittest.TestCase):
    def test_draft_creation_does_not_enforce_readiness(self) -> None:
        body = ROLLOUT_STORE.split(
            "def create_sensor_configuration_rollout", 1
        )[1].split("def _get_locked_rollout", 1)[0]
        self.assertNotIn("RolloutReadinessConflict", body)
        self.assertIn("VALUES (%s, %s, 'draft'", body)

    def test_deployment_checks_only_the_bounded_next_batch(self) -> None:
        body = ROLLOUT_STORE.split("def _deploy_next_batch", 1)[1].split(
            "def start_sensor_configuration_rollout", 1
        )[0]
        limit_position = body.index("LIMIT %(batch_size)s")
        readiness_position = body.index("_next_batch_readiness")
        write_position = body.index("UPDATE sensor_configuration_state")
        self.assertLess(limit_position, readiness_position)
        self.assertLess(readiness_position, write_position)

    def test_every_noneligible_state_blocks_the_whole_batch(self) -> None:
        body = ROLLOUT_STORE.split("def _next_batch_readiness", 1)[1].split(
            "def _read_rollout_details", 1
        )[0]
        self.assertIn('if not item["rollout_eligible"]', body)
        self.assertIn('"eligible": not blockers', body)

    def test_structured_conflict_contains_policy_and_reasoned_blockers(self) -> None:
        body = ROLLOUT_STORE.split("class RolloutReadinessConflict", 1)[1].split(
            "ROLLOUT_SELECT", 1
        )[0]
        for field in (
            '"code": "rollout_readiness_blocked"',
            '"policy_revision"',
            '"blockers"',
        ):
            self.assertIn(field, body)
        self.assertIn('"reasons": sensor["reasons"]', ROLLOUT_STORE)

    def test_missing_sensor_is_a_blocker(self) -> None:
        self.assertIn('{"code": "sensor_missing", "severity": "blocked"}', ROLLOUT_STORE)

    def test_start_and_advance_share_the_authoritative_gate(self) -> None:
        self.assertEqual(ROLLOUT_STORE.count("_deploy_next_batch("), 3)
        body = ROLLOUT_STORE.split("def _deploy_next_batch", 1)[1].split(
            "def start_sensor_configuration_rollout", 1
        )[0]
        self.assertIn("raise RolloutReadinessConflict(", body)

    def test_fully_deployed_rollout_can_still_complete(self) -> None:
        body = ROLLOUT_STORE.split(
            "def advance_sensor_configuration_rollout", 1
        )[1].split("def cancel_sensor_configuration_rollout", 1)[0]
        completion = body.index("if pending_count == 0:")
        next_deploy = body.index("_deploy_next_batch(", completion)
        self.assertLess(completion, next_deploy)

    def test_rollout_detail_exposes_live_target_and_next_batch_readiness(self) -> None:
        for field in (
            'target["readiness_status"]',
            'target["rollout_eligible"]',
            'target["readiness_reasons"]',
            'rollout["next_batch_readiness"]',
        ):
            self.assertIn(field, ROLLOUT_STORE)

    def test_can_start_and_advance_include_the_readiness_gate(self) -> None:
        body = ROLLOUT_STORE.split("def _read_rollout_details", 1)[1].split(
            "def list_sensor_configuration_rollouts", 1
        )[0]
        self.assertIn("next_batch_eligible", body)
        self.assertGreaterEqual(body.count("and next_batch_eligible"), 2)

    def test_no_override_path_is_added(self) -> None:
        self.assertNotIn("readiness_override", ROLLOUT_STORE)
        self.assertNotIn("readiness_override", MAIN)
        self.assertIn("There is no administrator override", DOC)


class RolloutReadinessApiAndWebTests(unittest.TestCase):
    def test_start_and_advance_return_structured_http_409(self) -> None:
        self.assertGreaterEqual(
            MAIN.count("except RolloutReadinessConflict as exc:"),
            2,
        )
        self.assertGreaterEqual(MAIN.count("detail=jsonable_encoder(exc.api_detail())"), 2)

    def test_api_error_preserves_structured_detail(self) -> None:
        self.assertIn("constructor(message, status, detail = null)", MAIN_JS)
        self.assertIn("this.detail = detail", MAIN_JS)
        self.assertIn("responseDetail.message ?? responseDetail.code", MAIN_JS)

    def test_rollout_detail_has_visible_readiness_gate(self) -> None:
        self.assertIn('id="configuration-rollout-readiness-gate"', INDEX)
        self.assertIn(
            "Polityka gotowości jest egzekwowana przed każdą partią rolloutu.",
            INDEX,
        )
        self.assertNotIn("Stage 25A nie blokuje jeszcze rolloutów", INDEX)
        self.assertIn("rollout.next_batch_readiness", MAIN_JS)
        self.assertIn("Następna partia jest zablokowana", MAIN_JS)
        self.assertIn(".fleet-rollout-readiness-gate.blocked", STYLES)

    def test_buttons_follow_backend_can_start_and_can_advance(self) -> None:
        self.assertIn("elements.rolloutStart.disabled = !rollout.can_start", MAIN_JS)
        self.assertIn("elements.rolloutAdvance.disabled = !rollout.can_advance", MAIN_JS)
        self.assertIn("Następna partia nie spełnia polityki gotowości", MAIN_JS)

    def test_runtime_conflict_refreshes_state_and_names_blockers(self) -> None:
        body = MAIN_JS.split("async function runFleetRolloutAction", 1)[1].split(
            "function setSensorConfigurationFormDisabled", 1
        )[0]
        self.assertIn('error.detail?.code === "rollout_readiness_blocked"', body)
        self.assertIn("await loadFleetConfigurationConsole()", body)
        self.assertIn("Partia zablokowana przez gotowość", body)

    def test_stage_does_not_require_migration_or_agent_change(self) -> None:
        self.assertIn("does not change the sensor agent", DOC)
        self.assertIn("No migration command is required", DOC)


if __name__ == "__main__":
    unittest.main()

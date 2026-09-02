from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "database/migrations/026_sensor_configuration_rollout_pause.sql"
).read_text(encoding="utf-8")
ROLLOUT_STORE = (
    ROOT / "server/api/app/configuration_rollout_store.py"
).read_text(encoding="utf-8")
READINESS_STORE = (
    ROOT / "server/api/app/fleet_readiness_store.py"
).read_text(encoding="utf-8")
MODELS = (ROOT / "server/api/app/models.py").read_text(encoding="utf-8")
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/src/styles.css").read_text(encoding="utf-8")
DOC = (ROOT / "docs/RDDS_STAGE25C.md").read_text(encoding="utf-8")


class RolloutPauseMigrationTests(unittest.TestCase):
    def test_policy_has_bounded_application_timeout(self) -> None:
        self.assertIn(
            "rollout_application_timeout_seconds INTEGER NOT NULL DEFAULT 120",
            MIGRATION,
        )
        self.assertIn("BETWEEN 30 AND 3600", MIGRATION)

    def test_rollout_has_structured_pause_metadata(self) -> None:
        for field in (
            "paused_at TIMESTAMPTZ",
            "paused_by TEXT",
            "pause_reason JSONB",
            "pause_policy_revision BIGINT",
            "resume_count INTEGER NOT NULL DEFAULT 0",
        ):
            self.assertIn(field, MIGRATION)

    def test_lifecycle_allows_paused_as_nonterminal(self) -> None:
        self.assertIn(
            "status IN ('draft', 'active', 'paused', 'completed', 'cancelled')",
            MIGRATION,
        )
        paused = MIGRATION.split("status = 'paused'", 1)[1].split(
            "status = 'completed'", 1
        )[0]
        self.assertIn("started_at IS NOT NULL", paused)
        self.assertIn("completed_at IS NULL", paused)
        self.assertIn("cancelled_at IS NULL", paused)
        self.assertIn("pause_reason IS NOT NULL", paused)

    def test_migration_replaces_only_status_constraints_that_know_draft(self) -> None:
        self.assertIn("pg_get_constraintdef", MIGRATION)
        self.assertIn("LIKE '%draft%'", MIGRATION)

    def test_pause_and_resume_events_are_allow_listed(self) -> None:
        self.assertIn("'sensor_configuration_rollout_paused'", MIGRATION)
        self.assertIn("'sensor_configuration_rollout_resumed'", MIGRATION)


class RolloutAutomaticPauseTests(unittest.TestCase):
    def test_monitor_inspects_only_active_rollouts(self) -> None:
        body = ROLLOUT_STORE.split(
            "def monitor_active_sensor_configuration_rollouts", 1
        )[1].split("def resume_sensor_configuration_rollout", 1)[0]
        self.assertIn("WHERE status = 'active'", body)
        self.assertIn('rollout["status"] != "active"', body)

    def test_monitor_locks_authoritative_readiness_state(self) -> None:
        body = ROLLOUT_STORE.split(
            "def monitor_active_sensor_configuration_rollouts", 1
        )[1].split("def resume_sensor_configuration_rollout", 1)[0]
        self.assertIn("_get_locked_rollout", body)
        self.assertIn("lock=True", body)
        self.assertGreaterEqual(body.count("_read_rollout_targets"), 2)

    def test_deployment_and_monitor_use_policy_before_sensor_lock_order(self) -> None:
        deploy = ROLLOUT_STORE.split("def _deploy_next_batch", 1)[1].split(
            "def start_sensor_configuration_rollout", 1
        )[0]
        self.assertIn("FOR UPDATE OF target", deploy)
        self.assertNotIn("FOR UPDATE OF target, sensor", deploy)
        self.assertIn("_next_batch_readiness(cursor, targets, lock=True)", deploy)

    def test_apply_error_and_superseded_revision_pause_immediately(self) -> None:
        body = ROLLOUT_STORE.split("def _rollout_recovery_result", 1)[1].split(
            "def _read_rollout_details", 1
        )[0]
        self.assertIn('"code": "configuration_error"', body)
        self.assertIn('"code": "configuration_superseded"', body)

    def test_pending_configuration_has_a_grace_period(self) -> None:
        body = ROLLOUT_STORE.split("def _rollout_recovery_result", 1)[1].split(
            "def _read_rollout_details", 1
        )[0]
        timeout_check = body.index("if elapsed_seconds >= timeout_seconds:")
        timeout_blocker = body.index('"code": "configuration_application_timeout"')
        self.assertLess(timeout_check, timeout_blocker)
        self.assertIn('startswith("configuration_")', body)

    def test_nonconfiguration_readiness_loss_is_not_hidden_by_grace(self) -> None:
        body = ROLLOUT_STORE.split("def _rollout_recovery_result", 1)[1].split(
            "def _read_rollout_details", 1
        )[0]
        readiness_position = body.index("if non_configuration_reasons:")
        timeout_position = body.index("if elapsed_seconds >= timeout_seconds:")
        self.assertLess(readiness_position, timeout_position)
        self.assertIn('"code": "sensor_not_ready"', body)

    def test_automatic_pause_is_a_single_conditional_update(self) -> None:
        body = ROLLOUT_STORE.split(
            "def monitor_active_sensor_configuration_rollouts", 1
        )[1].split("def resume_sensor_configuration_rollout", 1)[0]
        self.assertIn("status = 'paused'", body)
        self.assertIn("AND status = 'active'", body)
        self.assertIn("if cursor.rowcount != 1:", body)

    def test_monitor_never_resumes_or_deploys(self) -> None:
        body = ROLLOUT_STORE.split(
            "def monitor_active_sensor_configuration_rollouts", 1
        )[1].split("def resume_sensor_configuration_rollout", 1)[0]
        self.assertNotIn("_deploy_next_batch", body)
        self.assertNotIn("status = 'active',", body.split("UPDATE", 1)[-1])

    def test_api_lifespan_runs_monitor_after_health_refresh(self) -> None:
        body = MAIN.split("async def sensor_status_monitor", 1)[1].split(
            "@asynccontextmanager", 1
        )[0]
        stale_position = body.index("mark_stale_sensors")
        rollout_position = body.index("monitor_active_sensor_configuration_rollouts")
        self.assertLess(stale_position, rollout_position)


class RolloutRecoveryTests(unittest.TestCase):
    def test_resume_requires_paused_state_and_current_safe_assessment(self) -> None:
        body = ROLLOUT_STORE.split(
            "def resume_sensor_configuration_rollout", 1
        )[1].split("def advance_sensor_configuration_rollout", 1)[0]
        self.assertIn('rollout["status"] != "paused"', body)
        self.assertIn("lock=True", body)
        self.assertIn('if not recovery["safe_to_resume"]:', body)

    def test_resume_returns_structured_conflict(self) -> None:
        conflict = ROLLOUT_STORE.split("class RolloutRecoveryConflict", 1)[1].split(
            "ROLLOUT_SELECT", 1
        )[0]
        self.assertIn('"code": "rollout_resume_blocked"', conflict)
        self.assertIn('"policy_revision"', conflict)
        self.assertIn('"blockers"', conflict)

    def test_resume_does_not_deploy_a_batch(self) -> None:
        body = ROLLOUT_STORE.split(
            "def resume_sensor_configuration_rollout", 1
        )[1].split("def advance_sensor_configuration_rollout", 1)[0]
        self.assertIn("resume_count = resume_count + 1", body)
        self.assertNotIn("_deploy_next_batch", body)

    def test_paused_rollout_can_be_cancelled(self) -> None:
        body = ROLLOUT_STORE.split(
            "def cancel_sensor_configuration_rollout", 1
        )[1].split("def _is_complete_managed_configuration", 1)[0]
        self.assertIn('{"draft", "active", "paused"}', body)
        self.assertIn("pause_reason = NULL", body)

    def test_direct_rollback_from_pause_terminates_before_restore(self) -> None:
        body = ROLLOUT_STORE.split(
            "def rollback_sensor_configuration_rollout", 1
        )[1]
        paused_position = body.index('if rollout["status"] == "paused":')
        cancelled_position = body.index("status = 'cancelled'", paused_position)
        restore_position = body.index("UPDATE sensor_configuration_state", paused_position)
        self.assertLess(cancelled_position, restore_position)

    def test_pause_and_resume_are_audited(self) -> None:
        self.assertIn(
            'event_type="sensor_configuration_rollout_paused"', ROLLOUT_STORE
        )
        self.assertIn(
            'event_type="sensor_configuration_rollout_resumed"', ROLLOUT_STORE
        )


class RolloutPauseApiAndWebTests(unittest.TestCase):
    def test_resume_endpoint_requires_administrator_write(self) -> None:
        route = MAIN.split("def post_sensor_configuration_rollout_resume", 1)[0]
        self.assertIn(
            '"/api/v1/sensor-configuration-rollouts/{rollout_id}/resume"',
            route[-400:],
        )
        self.assertIn("Depends(require_administrator_write)", route[-400:])

    def test_resume_conflict_is_structured_http_409(self) -> None:
        body = MAIN.split("def post_sensor_configuration_rollout_resume", 1)[1].split(
            "@app.post(", 1
        )[0]
        self.assertIn("except RolloutRecoveryConflict as exc:", body)
        self.assertIn("detail=jsonable_encoder(exc.api_detail())", body)

    def test_policy_model_store_and_form_expose_timeout(self) -> None:
        self.assertIn("rollout_application_timeout_seconds", MODELS)
        self.assertIn("rollout_application_timeout_seconds", READINESS_STORE)
        self.assertIn('id="fleet-policy-application-timeout"', INDEX)
        self.assertIn("fleetPolicyApplicationTimeout", MAIN_JS)

    def test_paused_rollout_is_visible_and_has_resume_button(self) -> None:
        self.assertIn("'draft', 'active', 'paused'", ROLLOUT_STORE)
        self.assertIn('id="configuration-rollout-resume"', INDEX)
        self.assertIn('paused: "wstrzymany"', MAIN_JS)
        self.assertIn(".fleet-status.rollout-paused", STYLES)

    def test_ui_shows_pause_blockers_and_never_implies_auto_resume(self) -> None:
        self.assertIn("rollout.pause_policy_revision", MAIN_JS)
        self.assertIn("rolloutRecoveryReasonLabels", MAIN_JS)
        self.assertIn("administrator może go jawnie wznowić", MAIN_JS)
        self.assertIn("Kolejna partia nie zostanie wdrożona automatycznie", MAIN_JS)

    def test_resume_button_follows_backend_capability(self) -> None:
        self.assertIn("elements.rolloutResume.disabled = !rollout.can_resume", MAIN_JS)
        self.assertIn("rollout.status !== \"paused\"", MAIN_JS)

    def test_agent_protocol_is_unchanged(self) -> None:
        self.assertIn("sensor agent protocol", DOC)
        self.assertIn("do not change", DOC)


if __name__ == "__main__":
    unittest.main()

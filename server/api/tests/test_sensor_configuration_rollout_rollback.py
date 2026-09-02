from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "database/migrations/024_sensor_configuration_rollout_rollback.sql"
).read_text(encoding="utf-8")
STORE = (
    ROOT / "server/api/app/configuration_rollout_store.py"
).read_text(encoding="utf-8")
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")


class ConfigurationRolloutRollbackMigrationTests(unittest.TestCase):
    def test_migration_records_rollout_and_target_rollback_state(self) -> None:
        for column in (
            "rolled_back_at",
            "rolled_back_by",
            "rollback_note",
            "rollback_revision",
        ):
            self.assertIn(column, MIGRATION)

    def test_migration_requires_terminal_rollout_and_monotonic_revision(self) -> None:
        self.assertIn("status IN ('completed', 'cancelled')", MIGRATION)
        self.assertIn("rollback_revision > desired_revision", MIGRATION)

    def test_rollback_audit_event_is_allow_listed(self) -> None:
        self.assertIn("'sensor_configuration_rollout_rolled_back'", MIGRATION)


class ConfigurationRolloutRollbackStoreTests(unittest.TestCase):
    def test_only_terminal_rollouts_can_be_rolled_back(self) -> None:
        self.assertIn(
            'if rollout["status"] not in {"completed", "cancelled"}:',
            STORE,
        )
        self.assertIn("configuration rollout was already rolled back", STORE)

    def test_rollback_is_all_or_nothing_and_locks_targets(self) -> None:
        body = STORE.split("def rollback_sensor_configuration_rollout", 1)[1]
        self.assertIn("with connection() as conn, conn.cursor() as cursor:", body)
        self.assertIn("FOR UPDATE OF target, sensor", body)
        self.assertIn("FOR UPDATE", body)
        self.assertLess(body.index("if blockers:"), body.index("for item in prepared:"))

    def test_rollback_blocks_superseded_assignments_and_unsafe_snapshots(self) -> None:
        for blocker in (
            "superseded",
            "assignment_changed",
            "no_safe_snapshot",
        ):
            self.assertIn(blocker, STORE)

    def test_rollback_creates_a_new_monotonic_desired_revision(self) -> None:
        self.assertIn(
            'rollback_revision = int(configuration["desired_revision"]) + 1',
            STORE,
        )
        self.assertIn("desired_revision = %(rollback_revision)s", STORE)

    def test_rollback_restores_snapshot_and_previous_assignment(self) -> None:
        self.assertIn('target["previous_desired_config"]', STORE)
        self.assertIn('target["previous_profile_id"]', STORE)
        self.assertIn('target["previous_profile_version"]', STORE)
        self.assertIn('target["previous_rollout_id"]', STORE)
        self.assertIn("ON CONFLICT (sensor_id) DO UPDATE", STORE)

    def test_rollback_without_previous_profile_returns_to_manual_configuration(self) -> None:
        self.assertRegex(
            STORE,
            re.compile(
                r'if target\["previous_profile_id"\] is None:[\s\S]*?'
                r"DELETE FROM sensor_configuration_profile_assignments",
            ),
        )
        self.assertIn('"reason": "rollout_rollback"', STORE)

    def test_target_status_tracks_agent_rollback_application(self) -> None:
        for status in (
            "rollback_pending",
            "rolled_back",
            "rollback_error",
            "rollback_superseded",
        ):
            self.assertIn(f'return "{status}"', STORE)

    def test_api_exposes_explicit_administrator_rollback_endpoint(self) -> None:
        self.assertIn(
            '"/api/v1/sensor-configuration-rollouts/{rollout_id}/rollback"',
            MAIN,
        )
        route = MAIN.split("def post_sensor_configuration_rollout_rollback", 1)[1]
        self.assertIn("rollback_sensor_configuration_rollout(", route)
        self.assertIn("except RolloutConflict as exc:", route)
        self.assertIn("status_code=409", route)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
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
    from app.models import (
        SensorConfigurationRolloutAction,
        SensorConfigurationRolloutCreate,
    )


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "database/migrations/023_sensor_configuration_rollouts.sql"
).read_text(encoding="utf-8")
STORE = (
    ROOT / "server/api/app/configuration_rollout_store.py"
).read_text(encoding="utf-8")
SENSOR_STORE = (
    ROOT / "server/api/app/sensor_store.py"
).read_text(encoding="utf-8")
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")


class ConfigurationRolloutModelTests(unittest.TestCase):
    def test_rollout_create_normalizes_note(self) -> None:
        payload = SensorConfigurationRolloutCreate(
            profile_id=uuid4(),
            profile_version=2,
            sensor_ids=[uuid4(), uuid4()],
            batch_size=1,
            change_note="  Pierwsza partia  ",
        )
        self.assertEqual(payload.change_note, "Pierwsza partia")

    def test_rollout_rejects_duplicate_targets(self) -> None:
        sensor_id = uuid4()
        with self.assertRaises(ValidationError):
            SensorConfigurationRolloutCreate(
                profile_id=uuid4(),
                profile_version=1,
                sensor_ids=[sensor_id, sensor_id],
                batch_size=1,
                change_note="Nieprawidłowy rollout",
            )

    def test_rollout_batch_and_target_limits_are_bounded(self) -> None:
        with self.assertRaises(ValidationError):
            SensorConfigurationRolloutCreate(
                profile_id=uuid4(),
                profile_version=1,
                sensor_ids=[uuid4()],
                batch_size=26,
                change_note="Zbyt duża partia",
            )

    def test_rollout_action_requires_operator_note(self) -> None:
        with self.assertRaises(ValidationError):
            SensorConfigurationRolloutAction(change_note="   ")


class ConfigurationRolloutMigrationTests(unittest.TestCase):
    def test_rollout_assignment_and_target_tables_are_separate(self) -> None:
        self.assertIn("CREATE TABLE sensor_configuration_rollouts", MIGRATION)
        self.assertIn("CREATE TABLE sensor_configuration_rollout_targets", MIGRATION)
        self.assertIn("CREATE TABLE sensor_configuration_profile_assignments", MIGRATION)

    def test_rollout_is_pinned_to_immutable_profile_version(self) -> None:
        self.assertIn("FOREIGN KEY (profile_id, profile_version)", MIGRATION)
        self.assertIn(
            "REFERENCES sensor_configuration_profile_versions(profile_id, version)",
            MIGRATION,
        )

    def test_targets_keep_rollback_snapshots(self) -> None:
        for column in (
            "previous_desired_revision",
            "previous_desired_config",
            "previous_profile_id",
            "previous_profile_version",
            "previous_rollout_id",
        ):
            self.assertIn(column, MIGRATION)

    def test_rollout_audit_events_are_allow_listed(self) -> None:
        for event_type in (
            "sensor_configuration_profile_assigned",
            "sensor_configuration_profile_unassigned",
            "sensor_configuration_rollout_created",
            "sensor_configuration_rollout_started",
            "sensor_configuration_rollout_batch_deployed",
            "sensor_configuration_rollout_completed",
            "sensor_configuration_rollout_cancelled",
        ):
            self.assertIn(f"'{event_type}'", MIGRATION)


class ConfigurationRolloutStoreBoundaryTests(unittest.TestCase):
    def test_creation_is_draft_and_locks_target_sensors(self) -> None:
        self.assertIn("VALUES (%s, %s, 'draft'", STORE)
        self.assertIn("ORDER BY id\n            FOR UPDATE", STORE)

    def test_start_deploys_only_one_bounded_batch(self) -> None:
        self.assertIn("LIMIT %(batch_size)s", STORE)
        self.assertIn("target.desired_revision IS NULL", STORE)
        self.assertIn("status = 'active'", STORE)

    def test_advance_requires_previous_targets_to_be_compliant(self) -> None:
        self.assertIn("def _deployed_blockers", STORE)
        self.assertIn("deployed targets are not compliant", STORE)
        self.assertIn("current_applied_revision", STORE)

    def test_deployment_increments_revision_and_pins_assignment(self) -> None:
        self.assertIn(
            'desired_revision = int(configuration["desired_revision"]) + 1',
            STORE,
        )
        self.assertIn("INSERT INTO sensor_configuration_profile_assignments", STORE)
        self.assertIn("rollout[\"profile_version\"]", STORE)

    def test_manual_configuration_removes_profile_assignment(self) -> None:
        self.assertIn(
            "DELETE FROM sensor_configuration_profile_assignments",
            SENSOR_STORE,
        )
        self.assertIn(
            "sensor_configuration_profile_unassigned",
            SENSOR_STORE,
        )

    def test_cancel_requires_a_separate_explicit_rollback(self) -> None:
        self.assertIn('"deployed_targets_rolled_back": False', STORE)
        self.assertIn("def rollback_sensor_configuration_rollout", STORE)

    def test_api_exposes_viewer_reads_and_admin_actions(self) -> None:
        self.assertIn('"/api/v1/sensor-configuration-rollouts"', MAIN)
        for action in ("start", "advance", "cancel", "rollback"):
            self.assertIn(
                f'"/api/v1/sensor-configuration-rollouts/{{rollout_id}}/{action}"',
                MAIN,
            )
        self.assertGreaterEqual(MAIN.count("Depends(require_administrator_write)"), 7)


if __name__ == "__main__":
    unittest.main()

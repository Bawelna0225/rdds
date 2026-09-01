import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app.models import SensorManagedConfiguration


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SENSOR_STORE = PROJECT_ROOT / "server" / "api" / "app" / "sensor_store.py"
MAIN = PROJECT_ROOT / "server" / "api" / "app" / "main.py"
MIGRATION = PROJECT_ROOT / "database" / "migrations" / "020_sensor_configuration.sql"


class SensorManagedConfigurationValidationTests(unittest.TestCase):
    def test_allowed_configuration_is_strictly_bounded(self) -> None:
        config = SensorManagedConfiguration(
            heartbeat_seconds=10,
            reconnect_seconds=3,
            request_timeout_seconds=5,
            replay_messages_per_second=2,
        )
        self.assertEqual(10, config.heartbeat_seconds)

        with self.assertRaises(ValidationError):
            SensorManagedConfiguration(
                heartbeat_seconds=1,
                reconnect_seconds=3,
                request_timeout_seconds=5,
                replay_messages_per_second=2,
            )

        with self.assertRaises(ValidationError):
            SensorManagedConfiguration(
                heartbeat_seconds=10,
                reconnect_seconds=3,
                request_timeout_seconds=5,
                replay_messages_per_second=101,
            )


class SensorConfigurationSourceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sensor_store = SENSOR_STORE.read_text(encoding="utf-8")
        cls.main = MAIN.read_text(encoding="utf-8")
        cls.migration = MIGRATION.read_text(encoding="utf-8")

    def test_configuration_is_separate_one_to_one_state(self) -> None:
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS sensor_configuration_state",
            self.migration,
        )
        self.assertIn("sensor_id UUID PRIMARY KEY", self.migration)
        self.assertIn(
            "desired_revision BIGINT NOT NULL DEFAULT 0",
            self.migration,
        )

    def test_agent_configuration_requires_individual_credential(self) -> None:
        self.assertIn('"/api/v1/agent/configuration"', self.main)
        self.assertIn('principal.mode != "sensor"', self.main)
        self.assertIn("individual sensor credential required", self.main)

    def test_configuration_change_is_audited(self) -> None:
        self.assertIn("'sensor_configuration_changed'", self.sensor_store)
        self.assertIn("desired_revision", self.sensor_store)
        self.assertIn("desired_config", self.sensor_store)

    def test_sensor_list_exposes_compliance_without_raw_configuration(self) -> None:
        self.assertIn("configuration_compliance", self.sensor_store)
        self.assertIn("configuration_desired_revision", self.sensor_store)
        self.assertNotIn(
            "configuration.desired_config AS configuration_",
            self.sensor_store,
        )


if __name__ == "__main__":
    unittest.main()

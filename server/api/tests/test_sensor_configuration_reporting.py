from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.database import _record_sensor_configuration_report
from app.models import HeartbeatEnvelope, SensorConfigurationReport


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_PATH = PROJECT_ROOT / "sensor-agent" / "rdds_agent.py"
SPEC = importlib.util.spec_from_file_location("rdds_agent_stage23b", AGENT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load the sensor agent module")
AGENT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AGENT
SPEC.loader.exec_module(AGENT)


MANAGED = {
    "heartbeat_seconds": 10.0,
    "reconnect_seconds": 3.0,
    "request_timeout_seconds": 5.0,
    "replay_messages_per_second": 2.0,
}


def heartbeat(configuration_report=None) -> HeartbeatEnvelope:
    raw = {
        "protocol_version": "rdds/1.0",
        "message_type": "heartbeat",
        "sensor": {
            "sensor_id": "sensor-stage23b",
            "display_name": "Stage 23B sensor",
            "boot_id": str(uuid4()),
            "sequence": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "status": {},
    }
    if configuration_report is not None:
        raw["configuration_report"] = configuration_report
    return HeartbeatEnvelope.model_validate(raw)


class ConfigurationReportModelTests(unittest.TestCase):
    def test_legacy_heartbeat_remains_valid(self) -> None:
        self.assertIsNone(heartbeat().configuration_report)

    def test_applied_report_is_valid(self) -> None:
        report = heartbeat(
            {
                "desired_revision": 4,
                "applied_revision": 4,
                "applied_config": MANAGED,
                "apply_status": "applied",
                "apply_error": None,
            }
        ).configuration_report
        self.assertEqual(report.applied_revision, 4)

    def test_applied_report_must_match_desired_revision(self) -> None:
        with self.assertRaises(ValidationError):
            heartbeat(
                {
                    "desired_revision": 4,
                    "applied_revision": 3,
                    "applied_config": MANAGED,
                    "apply_status": "applied",
                    "apply_error": None,
                }
            )

    def test_error_report_requires_message(self) -> None:
        with self.assertRaises(ValidationError):
            heartbeat(
                {
                    "desired_revision": 4,
                    "applied_revision": 3,
                    "applied_config": MANAGED,
                    "apply_status": "error",
                    "apply_error": None,
                }
            )


class ManagedConfigurationValidationTests(unittest.TestCase):
    def test_valid_configuration_is_normalized(self) -> None:
        result = AGENT.validate_managed_configuration(MANAGED)
        self.assertEqual(result, MANAGED)

    def test_missing_field_is_rejected(self) -> None:
        raw = dict(MANAGED)
        raw.pop("heartbeat_seconds")
        with self.assertRaises(AGENT.ConfigurationError):
            AGENT.validate_managed_configuration(raw)

    def test_unknown_field_is_rejected(self) -> None:
        with self.assertRaises(AGENT.ConfigurationError):
            AGENT.validate_managed_configuration({**MANAGED, "source": "/tmp/x"})

    def test_boolean_value_is_rejected(self) -> None:
        with self.assertRaises(AGENT.ConfigurationError):
            AGENT.validate_managed_configuration(
                {**MANAGED, "heartbeat_seconds": True}
            )

    def test_out_of_range_value_is_rejected(self) -> None:
        with self.assertRaises(AGENT.ConfigurationError):
            AGENT.validate_managed_configuration(
                {**MANAGED, "replay_messages_per_second": 1000}
            )


class FakeCursor:
    def __init__(self, state):
        self.state = state
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))

    def fetchone(self):
        return self.state


class ConfigurationReportPersistenceTests(unittest.TestCase):
    def test_stale_revision_is_ignored(self) -> None:
        payload = heartbeat(
            {
                "desired_revision": 2,
                "applied_revision": 2,
                "applied_config": MANAGED,
                "apply_status": "applied",
                "apply_error": None,
            }
        )
        cursor = FakeCursor(
            {
                "desired_revision": 3,
                "applied_revision": 2,
                "applied_config": MANAGED,
                "apply_status": "pending",
                "apply_error": None,
                "reported_at": None,
            }
        )
        _record_sensor_configuration_report(cursor, uuid4(), payload)
        self.assertEqual(len(cursor.statements), 2)

    def test_changed_report_is_updated_and_audited(self) -> None:
        payload = heartbeat(
            {
                "desired_revision": 2,
                "applied_revision": 2,
                "applied_config": MANAGED,
                "apply_status": "applied",
                "apply_error": None,
            }
        )
        cursor = FakeCursor(
            {
                "desired_revision": 2,
                "applied_revision": 1,
                "applied_config": MANAGED,
                "apply_status": "pending",
                "apply_error": None,
                "reported_at": None,
            }
        )
        _record_sensor_configuration_report(cursor, uuid4(), payload)
        self.assertEqual(len(cursor.statements), 4)
        self.assertIn("UPDATE sensor_configuration_state", cursor.statements[2][0])
        self.assertIn("INSERT INTO audit_events", cursor.statements[3][0])

    def test_unchanged_report_refreshes_time_without_duplicate_audit(self) -> None:
        payload = heartbeat(
            {
                "desired_revision": 2,
                "applied_revision": 2,
                "applied_config": MANAGED,
                "apply_status": "applied",
                "apply_error": None,
            }
        )
        cursor = FakeCursor(
            {
                "desired_revision": 2,
                "applied_revision": 2,
                "applied_config": MANAGED,
                "apply_status": "applied",
                "apply_error": None,
                "reported_at": None,
            }
        )
        _record_sensor_configuration_report(cursor, uuid4(), payload)
        self.assertEqual(len(cursor.statements), 3)


class SensorConfigurationAuditMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            PROJECT_ROOT
            / "database"
            / "migrations"
            / "021_sensor_configuration_audit_events.sql"
        ).read_text(encoding="utf-8")

    def test_changed_event_is_allowed(self) -> None:
        self.assertIn("'sensor_configuration_changed'", self.source)

    def test_applied_event_is_allowed(self) -> None:
        self.assertIn("'sensor_configuration_applied'", self.source)

    def test_failed_event_is_allowed(self) -> None:
        self.assertIn("'sensor_configuration_failed'", self.source)


if __name__ == "__main__":
    unittest.main()

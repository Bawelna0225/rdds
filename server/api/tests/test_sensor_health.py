import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from pydantic import ValidationError

REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import database, sensor_store
    from app.models import HeartbeatEnvelope, HeartbeatStatus, SensorMaintenance
    from app.sensor_health import assess_heartbeat


class FakeCursor:
    def __init__(
        self,
        *,
        rows: list[dict[str, object]] | None = None,
        rowcounts: list[int] | None = None,
    ) -> None:
        self.queries: list[str] = []
        self.parameters: list[object] = []
        self._rows = iter(rows or [])
        self._rowcounts = iter(rowcounts or [])
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, parameters: object = None) -> None:
        self.queries.append(query)
        self.parameters.append(parameters)
        try:
            self.rowcount = next(self._rowcounts)
        except StopIteration:
            pass

    def fetchone(self) -> dict[str, object] | None:
        try:
            return next(self._rows)
        except StopIteration:
            return None


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


class HealthAssessmentTests(unittest.TestCase):
    reported_at = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    def test_healthy_source_is_online(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(
                source_connected=True,
                queue_depth=2,
                dead_letter_depth=0,
            ),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
        )
        self.assertEqual(("online", "healthy"), (result.state, result.reason))

    def test_disconnected_source_is_degraded(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(source_connected=False),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
        )
        self.assertEqual("source_unavailable", result.reason)

    def test_dead_letter_is_degraded_before_queue_threshold(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(
                source_connected=True,
                queue_depth=1,
                dead_letter_depth=1,
            ),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
        )
        self.assertEqual("dead_letter", result.reason)

    def test_queue_threshold_is_inclusive(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(source_connected=True, queue_depth=100),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
        )
        self.assertEqual("queue_backlog", result.reason)

    def test_open_but_silent_source_is_degraded_after_grace_period(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(
                source_connected=True,
                uptime_seconds=120,
                source_last_message_at=self.reported_at - timedelta(seconds=91),
            ),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
        )
        self.assertEqual("source_silent", result.reason)


class HealthModelTests(unittest.TestCase):
    def test_maintenance_requires_reason(self) -> None:
        with self.assertRaises(ValidationError):
            SensorMaintenance(enabled=True, reason="  ")

    def test_maintenance_deadline_must_be_future_and_timezone_aware(self) -> None:
        with self.assertRaises(ValidationError):
            SensorMaintenance(
                enabled=True,
                reason="service",
                until=datetime.now(),
            )
        accepted = SensorMaintenance(
            enabled=True,
            reason="service",
            until=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        self.assertTrue(accepted.enabled)


class HealthPersistenceTests(unittest.TestCase):
    def test_newest_heartbeat_controls_current_health_snapshot(self) -> None:
        sensor_id = uuid4()
        cursor = FakeCursor(rows=[{"id": sensor_id}, {"id": 17}])
        payload = HeartbeatEnvelope.model_validate(
            {
                "protocol_version": "rdds/1.0",
                "message_type": "heartbeat",
                "sensor": {
                    "sensor_id": "sensor-test-01",
                    "display_name": "Test sensor",
                    "boot_id": str(uuid4()),
                    "sequence": 5,
                    "timestamp": "2026-08-26T12:00:00+00:00",
                },
                "status": {
                    "agent_version": "0.17.0",
                    "source_connected": False,
                    "queue_depth": 3,
                    "dead_letter_depth": 0,
                },
            }
        )
        fake_settings = SimpleNamespace(
            sensor_queue_warning_messages=100,
            sensor_source_silent_after_seconds=90,
        )

        with (
            patch.object(database, "connection", fake_connection_for(cursor)),
            patch.object(database, "settings", fake_settings),
        ):
            stored_sensor, record_id = database.insert_heartbeat(payload, {})

        self.assertEqual(sensor_id, stored_sensor)
        self.assertEqual(17, record_id)
        heartbeat_insert = cursor.queries[1]
        health_update = cursor.queries[2]
        self.assertIn("dead_letter_depth", heartbeat_insert)
        self.assertIn("source_connected", heartbeat_insert)
        self.assertIn("last_heartbeat_reported_at < %(reported_at)s", health_update)
        self.assertIn("status IN ('disabled', 'maintenance')", health_update)
        self.assertEqual("degraded", cursor.parameters[2]["health_state"])

    def test_monitor_expires_maintenance_and_marks_stale_once(self) -> None:
        cursor = FakeCursor(rowcounts=[1, 2])
        fake_settings = SimpleNamespace(
            sensor_offline_after_seconds=30,
            sensor_queue_warning_messages=100,
            sensor_source_silent_after_seconds=90,
        )
        with (
            patch.object(database, "connection", fake_connection_for(cursor)),
            patch.object(database, "settings", fake_settings),
        ):
            changed = database.mark_stale_sensors()

        self.assertEqual(3, changed)
        self.assertIn("status = 'maintenance'", cursor.queries[0])
        self.assertIn("status IN ('online', 'degraded')", cursor.queries[1])
        self.assertIn("health_issue_started_at = COALESCE(", cursor.queries[1])

    def test_maintenance_is_admin_owned_and_does_not_disable_ingest(self) -> None:
        sensor_id = uuid4()
        cursor = FakeCursor(
            rows=[
                {"id": sensor_id},
                {"id": sensor_id, "status": "maintenance"},
            ]
        )
        payload = SensorMaintenance(
            enabled=True,
            reason="antenna service",
            until=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        with patch.object(
            sensor_store,
            "connection",
            fake_connection_for(cursor),
        ):
            stored = sensor_store.set_sensor_maintenance(
                sensor_id,
                payload,
                "admin-test",
            )

        self.assertEqual("maintenance", stored["status"])
        update_query = cursor.queries[0]
        self.assertIn("maintenance_started_by", update_query)
        self.assertIn("status <> 'disabled'", update_query)
        self.assertIn("(%(enabled)s OR status = 'maintenance')", update_query)
        self.assertEqual(
            3,
            update_query.count(
                "(%(source_silent_after)s * INTERVAL '1 second')"
            ),
        )
        self.assertEqual("admin-test", cursor.parameters[0]["actor"])

    def test_delete_clears_health_issue_and_maintenance_metadata(self) -> None:
        sensor_id = uuid4()
        cursor = FakeCursor(
            rows=[
                {"id": sensor_id},
                {"id": sensor_id},
                {"id": sensor_id, "status": "disabled"},
            ]
        )
        with patch.object(
            sensor_store,
            "connection",
            fake_connection_for(cursor),
        ):
            stored = sensor_store.delete_sensor(sensor_id, "admin-test")

        self.assertEqual("disabled", stored["status"])
        delete_query = cursor.queries[2]
        self.assertIn("health_issue_started_at = NULL", delete_query)
        self.assertIn("maintenance_reason = NULL", delete_query)
        self.assertIn("maintenance_until = NULL", delete_query)


if __name__ == "__main__":
    unittest.main()

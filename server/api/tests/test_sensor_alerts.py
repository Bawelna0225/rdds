import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import main as api_main
    from app import sensor_alert_store


class FakeCursor:
    def __init__(self, *, rowcounts=None, rows=None, row=None):
        self.queries = []
        self.parameters = []
        self._rowcounts = iter(rowcounts or [])
        self._rows = rows or []
        self._row = row
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, parameters=None):
        self.queries.append(query)
        self.parameters.append(parameters)
        try:
            self.rowcount = next(self._rowcounts)
        except StopIteration:
            pass

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def fake_connection_for(cursor):
    @contextmanager
    def fake_connection():
        yield FakeConnection(cursor)
    return fake_connection


class SensorAlertPersistenceTests(unittest.TestCase):
    def test_evaluator_deduplicates_one_open_alert_per_sensor(self):
        cursor = FakeCursor(rowcounts=[4, 2])
        with patch.object(sensor_alert_store, "connection", fake_connection_for(cursor)):
            opened, closed = sensor_alert_store.evaluate_sensor_alerts()

        self.assertEqual(4, opened)
        self.assertEqual(2, closed)
        upsert = cursor.queries[0]
        self.assertIn("ON CONFLICT (sensor_id, alert_kind)", upsert)
        self.assertIn("FROM sensor_alerts AS existing", upsert)
        self.assertIn("existing.alert_kind = 'health'", upsert)
        self.assertIn("'health'", upsert)
        self.assertIn("state IN ('active', 'acknowledged')", upsert)
        self.assertIn("sensor.health_issue_started_at", upsert)
        self.assertIn("sensor.health_changed_at <=", upsert)
        self.assertIn("WHEN sensor.status = 'offline' THEN sensor.health_changed_at", upsert)
        self.assertIn("%(offline_delay)s", upsert)
        self.assertIn("%(degraded_delay)s", upsert)
        self.assertIn("sensor_alerts.occurrence_count + CASE", upsert)
        self.assertEqual(60, cursor.parameters[0]["offline_delay"])
        self.assertEqual(120, cursor.parameters[0]["degraded_delay"])

    def test_evaluator_closes_on_recovery_maintenance_or_disable(self):
        cursor = FakeCursor(rowcounts=[0, 3])
        with patch.object(sensor_alert_store, "connection", fake_connection_for(cursor)):
            sensor_alert_store.evaluate_sensor_alerts()

        close_query = cursor.queries[1]
        self.assertIn("alert.alert_kind = 'health'", close_query)
        self.assertIn("sensor.status NOT IN ('degraded', 'offline')", close_query)
        self.assertIn("WHEN sensor.status = 'maintenance' THEN 'maintenance'", close_query)
        self.assertIn("WHEN sensor.status = 'disabled' THEN 'disabled'", close_query)
        self.assertIn("ELSE 'recovered'", close_query)
        self.assertIn("closed_by = 'system'", close_query)

    def test_listing_is_sensor_scoped_and_supports_closed_archive(self):
        cursor = FakeCursor(rows=[])
        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        end = datetime(2026, 9, 1, tzinfo=timezone.utc)
        with patch.object(sensor_alert_store, "connection", fake_connection_for(cursor)):
            rows = sensor_alert_store.list_sensor_alerts(
                closed_only=True,
                closed_from=start,
                closed_before=end,
                alert_id=uuid4(),
                limit=500,
            )
        self.assertEqual([], rows)
        query = cursor.queries[0]
        self.assertIn("JOIN sensors AS sensor ON sensor.id = alert.sensor_id", query)
        self.assertIn("alert.closed_at >= %(closed_from)s", query)
        self.assertIn("alert.closed_at < %(closed_before)s", query)
        self.assertIn("sensor.reported_dead_letter_depth AS dead_letter_depth", query)
        self.assertIn("alert.alert_kind", query)
        self.assertIn("alert.condition_details", query)
        self.assertIn("readiness.readiness_status AS fleet_readiness_status", query)
        self.assertIn("sensor.fixed_position::geometry", query)
        self.assertIn("alert.id = %(alert_id)s", query)
        self.assertIsNotNone(cursor.parameters[0]["alert_id"])
        self.assertTrue(cursor.parameters[0]["closed_only"])

    def test_acknowledgement_only_changes_active_alert(self):
        alert_id = uuid4()
        cursor = FakeCursor(row={"id": alert_id, "state": "acknowledged"})
        with patch.object(sensor_alert_store, "connection", fake_connection_for(cursor)):
            result = sensor_alert_store.acknowledge_sensor_alert(alert_id, "operator:test")
        self.assertEqual("acknowledged", result["state"])
        self.assertIn("WHERE id = %s AND state = 'active'", cursor.queries[0])
        self.assertEqual(("operator:test", alert_id), cursor.parameters[0])

    def test_list_route_passes_exact_alert_filter_to_store(self):
        alert_id = uuid4()
        with patch.object(api_main, "list_sensor_alerts", return_value=[]) as list_alerts:
            payload = api_main.get_sensor_alerts(
                include_closed=True,
                closed_only=False,
                closed_from=None,
                closed_before=None,
                alert_id=alert_id,
                limit=1,
            )
        self.assertEqual([], payload["alerts"])
        list_alerts.assert_called_once_with(
            include_closed=True,
            closed_only=False,
            closed_from=None,
            closed_before=None,
            alert_id=alert_id,
            limit=1,
        )


if __name__ == "__main__":
    unittest.main()

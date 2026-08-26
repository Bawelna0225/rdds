import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import alert_store


class FakeCursor:
    def __init__(
        self,
        *,
        rowcounts: list[int] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.queries: list[str] = []
        self.parameters: list[object] = []
        self._rowcounts = iter(rowcounts or [])
        self._rows = rows or []
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

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


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


class IncidentPersistenceTests(unittest.TestCase):
    def test_new_incident_captures_entry_snapshot(self) -> None:
        cursor = FakeCursor(rowcounts=[3, 1, 0])
        with patch.object(
            alert_store,
            "connection",
            fake_connection_for(cursor),
        ):
            detected, presence_changes = alert_store.evaluate_intrusions()

        self.assertEqual(3, detected)
        self.assertEqual(1, presence_changes)
        insert_query = cursor.queries[0]
        self.assertIn("entry_zone_name", insert_query)
        self.assertIn("entry_position", insert_query)
        self.assertIn("entry_altitude_m", insert_query)
        self.assertIn("entry_sensor_key", insert_query)
        conflict_update = insert_query.split("DO UPDATE SET", 1)[1]
        self.assertNotIn("entry_zone_name =", conflict_update)
        self.assertNotIn("entry_position =", conflict_update)
        self.assertNotIn("severity = EXCLUDED.severity", conflict_update)

    def test_leaving_zone_changes_presence_without_closing_incident(self) -> None:
        cursor = FakeCursor(rowcounts=[0, 2, 0])
        with patch.object(
            alert_store,
            "connection",
            fake_connection_for(cursor),
        ):
            alert_store.evaluate_intrusions()

        presence_query = cursor.queries[1]
        self.assertIn("presence_state = presence.next_presence", presence_query)
        self.assertIn("THEN 'lost'", presence_query)
        self.assertIn("ELSE 'left'", presence_query)
        self.assertNotIn("state = 'closed'", presence_query)

    def test_closed_inside_incident_blocks_reopen_until_definite_exit(self) -> None:
        cursor = FakeCursor(rowcounts=[0, 0, 1])
        with patch.object(
            alert_store,
            "connection",
            fake_connection_for(cursor),
        ):
            detected, presence_changes = alert_store.evaluate_intrusions()

        self.assertEqual(0, detected)
        self.assertEqual(1, presence_changes)
        detection_query = cursor.queries[0]
        self.assertIn("open_alert.state IN ('active', 'acknowledged')", detection_query)
        self.assertIn("previous.state = 'closed'", detection_query)
        self.assertIn(") <> 'inside'", detection_query)

        closed_departure_query = cursor.queries[2]
        self.assertIn("latest.presence_state = 'inside'", closed_departure_query)
        self.assertIn("NOT ST_Intersects(zone.area, track.last_position)", closed_departure_query)
        self.assertNotIn("track.state IN ('stale', 'ended')", closed_departure_query)
        self.assertIn("presence_state = 'left'", closed_departure_query)

    def test_alert_list_separates_entry_and_live_fields(self) -> None:
        cursor = FakeCursor(rows=[])
        with patch.object(
            alert_store,
            "connection",
            fake_connection_for(cursor),
        ):
            self.assertEqual([], alert_store.list_alerts())

        query = cursor.queries[0]
        self.assertIn("entry_altitude_m AS altitude_m", query)
        self.assertIn("last_altitude_m AS live_altitude_m", query)
        self.assertIn("entry_position::geometry", query)
        self.assertIn("track.last_position::geometry", query)


if __name__ == "__main__":
    unittest.main()

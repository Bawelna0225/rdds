import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
    from app import audit_store, track_store


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.queries: list[str] = []
        self.parameters: list[object] = []
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, parameters: object) -> None:
        self.queries.append(query)
        self.parameters.append(parameters)

    def fetchone(self) -> dict[str, int]:
        return {"total": 0}

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


class AuditFilterTests(unittest.TestCase):
    def test_category_percent_is_escaped_for_psycopg(self) -> None:
        for category, event_prefix in (
            ("detections", "track"),
            ("alerts", "alert"),
            ("zones", "zone"),
            ("sensors", "sensor"),
            ("operators", "operator"),
        ):
            with self.subTest(category=category):
                cursor = FakeCursor()

                @contextmanager
                def fake_connection(test_cursor: FakeCursor = cursor):
                    yield FakeConnection(test_cursor)

                with patch.object(audit_store, "connection", fake_connection):
                    events, total = audit_store.list_audit_events(category=category)

                self.assertEqual([], events)
                self.assertEqual(0, total)
                self.assertEqual(2, len(cursor.queries))
                self.assertTrue(
                    all(
                        f"LIKE '{event_prefix}_%%'" in query
                        for query in cursor.queries
                    )
                )

    def test_track_filter_is_parameterized(self) -> None:
        cursor = FakeCursor()

        @contextmanager
        def fake_connection():
            yield FakeConnection(cursor)

        track_id = uuid4()
        with patch.object(audit_store, "connection", fake_connection):
            events, total = audit_store.list_audit_events(track_id=track_id)

        self.assertEqual([], events)
        self.assertEqual(0, total)
        self.assertTrue(
            all("event.track_id = %(track_id)s" in query for query in cursor.queries)
        )
        self.assertTrue(
            all(parameters["track_id"] == track_id for parameters in cursor.parameters)
        )


class LiveObservationTests(unittest.TestCase):
    def test_current_observation_is_live(self) -> None:
        now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
        message_time = now - timedelta(
            seconds=track_store.settings.track_ended_after_seconds - 1
        )
        self.assertTrue(track_store.is_live_observation(message_time, now))

    def test_queued_observation_is_not_live(self) -> None:
        now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
        message_time = now - timedelta(
            seconds=track_store.settings.track_ended_after_seconds + 1
        )
        self.assertFalse(track_store.is_live_observation(message_time, now))

    def test_future_observation_is_not_live(self) -> None:
        now = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
        self.assertFalse(
            track_store.is_live_observation(now + timedelta(seconds=6), now)
        )

    def test_track_session_keys_are_unique_but_keep_entity_prefix(self) -> None:
        entity_key = "basic_id:0123456789abcdef01234567"

        first = track_store.new_track_session_key(entity_key)
        second = track_store.new_track_session_key(entity_key)

        self.assertTrue(first.startswith(f"{entity_key}:session:"))
        self.assertTrue(second.startswith(f"{entity_key}:session:"))
        self.assertNotEqual(first, second)


class TrackPriorityTests(unittest.TestCase):
    def test_live_observations_are_selected_before_replayed_rows(self) -> None:
        cursor = FakeCursor()

        @contextmanager
        def fake_connection():
            yield FakeConnection(cursor)

        with patch.object(track_store, "connection", fake_connection):
            linked, rejected = track_store.process_observation_batch(limit=25)

        self.assertEqual((0, 0), (linked, rejected))
        self.assertIn("CASE", cursor.queries[0])
        self.assertIn("o.message_time", cursor.queries[0])
        self.assertEqual(
            (track_store.settings.track_ended_after_seconds, 25),
            cursor.parameters[0],
        )


class TrackHistoryTests(unittest.TestCase):
    def test_history_is_sampled_and_contains_operator_position(self) -> None:
        cursor = FakeCursor(
            [
                {
                    "observation_id": 1,
                    "message_time": datetime(2026, 8, 20, tzinfo=timezone.utc),
                    "total_observations": 24000,
                    "history_row": 1,
                    "sample_bucket": 0,
                }
            ]
        )

        @contextmanager
        def fake_connection():
            yield FakeConnection(cursor)

        track_id = uuid4()
        with patch.object(track_store, "connection", fake_connection):
            observations, total = track_store.get_track_history(track_id, 10000)

        self.assertEqual(24000, total)
        self.assertNotIn("history_row", observations[0])
        self.assertNotIn("sample_bucket", observations[0])
        self.assertNotIn("total_observations", observations[0])
        self.assertIn("pilot_latitude", cursor.queries[0])
        self.assertIn("pilot_longitude", cursor.queries[0])
        self.assertEqual(
            (
                track_store.settings.track_ended_after_seconds,
                track_id,
                10000,
            ),
            cursor.parameters[0],
        )


class LiveTrackTrailTests(unittest.TestCase):
    def test_recent_points_are_grouped_by_track(self) -> None:
        first_track_id = uuid4()
        second_track_id = uuid4()
        cursor = FakeCursor(
            [
                {
                    "track_id": first_track_id,
                    "observation_id": 1,
                    "message_time": datetime(2026, 8, 20, tzinfo=timezone.utc),
                    "latitude": 52.1,
                    "longitude": 21.0,
                    "recent_row": 2,
                },
                {
                    "track_id": first_track_id,
                    "observation_id": 2,
                    "message_time": datetime(2026, 8, 20, 0, 0, 1, tzinfo=timezone.utc),
                    "latitude": 52.2,
                    "longitude": 21.1,
                    "recent_row": 1,
                },
                {
                    "track_id": second_track_id,
                    "observation_id": 3,
                    "message_time": datetime(2026, 8, 20, tzinfo=timezone.utc),
                    "latitude": 52.3,
                    "longitude": 21.2,
                    "recent_row": 1,
                },
            ]
        )

        @contextmanager
        def fake_connection():
            yield FakeConnection(cursor)

        with patch.object(track_store, "connection", fake_connection):
            trails = track_store.get_live_track_trails(20, 100)

        self.assertEqual([first_track_id, second_track_id], [
            trail["track_id"] for trail in trails
        ])
        self.assertEqual(2, len(trails[0]["points"]))
        self.assertNotIn("recent_row", trails[0]["points"][0])
        self.assertEqual((20, 20, 100), cursor.parameters[0])
        self.assertIn("DATE_TRUNC('second'", cursor.queries[0])
        self.assertIn("DISTINCT ON (track_id, sample_time)", cursor.queries[0])
        self.assertIn("PARTITION BY track_id", cursor.queries[0])
        self.assertIn("track.state <> 'ended'", cursor.queries[0])
        self.assertIn("observation.received_at", cursor.queries[0])


if __name__ == "__main__":
    unittest.main()

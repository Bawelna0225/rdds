import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import track_store


class FakeCursor:
    def __init__(self, *, rows: list[dict[str, object]] | None = None) -> None:
        self.queries: list[str] = []
        self.parameters: list[object] = []
        self._rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, parameters: object = None) -> None:
        self.queries.append(query)
        self.parameters.append(parameters)

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


class TrackArchiveBoundedQueryTests(unittest.TestCase):
    def test_live_query_has_no_limit_and_no_date_bounds(self) -> None:
        cursor = FakeCursor(rows=[])
        with patch.object(track_store, "connection", fake_connection_for(cursor)):
            self.assertEqual([], track_store.list_tracks())

        parameters = cursor.parameters[0]
        self.assertFalse(parameters["include_ended"])
        self.assertIsNone(parameters["limit"])
        self.assertIsNone(parameters["ended_from"])
        self.assertIsNone(parameters["ended_before"])

    def test_archive_query_filters_by_closure_window_and_caps_rows(self) -> None:
        cursor = FakeCursor(rows=[])
        ended_from = datetime(2026, 8, 1, tzinfo=timezone.utc)
        ended_before = datetime(2026, 9, 1, tzinfo=timezone.utc)
        with patch.object(track_store, "connection", fake_connection_for(cursor)):
            self.assertEqual(
                [],
                track_store.list_tracks(
                    include_ended=True,
                    limit=200,
                    ended_from=ended_from,
                    ended_before=ended_before,
                ),
            )

        query = cursor.queries[0]
        parameters = cursor.parameters[0]
        self.assertIn("track.ended_at >= %(ended_from)s", query)
        self.assertIn("track.ended_at < %(ended_before)s", query)
        self.assertIn("track.ended_at END DESC NULLS LAST", query)
        self.assertIn("LIMIT %(limit)s", query)
        self.assertTrue(parameters["include_ended"])
        self.assertEqual(200, parameters["limit"])
        self.assertEqual(ended_from, parameters["ended_from"])
        self.assertEqual(ended_before, parameters["ended_before"])

    def test_archive_calendar_groups_ended_tracks_by_utc_day(self) -> None:
        cursor = FakeCursor(rows=[])
        month_start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        month_end = datetime(2026, 10, 1, tzinfo=timezone.utc)
        with patch.object(track_store, "connection", fake_connection_for(cursor)):
            self.assertEqual(
                [],
                track_store.get_track_archive_calendar(
                    month_start=month_start,
                    month_end=month_end,
                ),
            )

        query = cursor.queries[0]
        parameters = cursor.parameters[0]
        self.assertIn("state = 'ended'", query)
        self.assertIn("DATE_TRUNC('day', track.ended_at AT TIME ZONE 'UTC')", query)
        self.assertIn("GROUP BY 1", query)
        self.assertEqual(month_start, parameters["month_start"])
        self.assertEqual(month_end, parameters["month_end"])

    def test_archive_calendar_endpoint_computes_utc_month_bounds(self) -> None:
        main_source = (
            __import__("pathlib")
            .Path(__file__)
            .resolve()
            .parents[1]
            .joinpath("app", "main.py")
            .read_text(encoding="utf-8")
        )
        start = main_source.index("def get_tracks_archive_calendar(")
        end = main_source.index("\n@app.", start)
        source = main_source[start:end]
        self.assertIn('pattern=r"^\\d{4}-(0[1-9]|1[0-2])$"', source)
        self.assertIn("month_number == 12", source)


if __name__ == "__main__":
    unittest.main()

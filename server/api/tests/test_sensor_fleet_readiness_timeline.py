from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import HTTPException


REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import fleet_readiness_store
    from app import main as api_main


ROOT = Path(__file__).resolve().parents[3]
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/src/styles.css").read_text(encoding="utf-8")


class FakeCursor:
    def __init__(self, *, row_sequence=None, rows_sequence=None):
        self.queries: list[str] = []
        self.parameters: list[object] = []
        self._row_sequence = list(row_sequence or [])
        self._rows_sequence = list(rows_sequence or [])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, parameters=None):
        self.queries.append(query)
        self.parameters.append(parameters)

    def fetchone(self):
        if not self._row_sequence:
            return None
        return self._row_sequence.pop(0)

    def fetchall(self):
        if not self._rows_sequence:
            return []
        return self._rows_sequence.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def fake_connection_for(cursor: FakeCursor):
    @contextmanager
    def fake_connection():
        yield FakeConnection(cursor)

    return fake_connection


def event(
    observed_at: datetime,
    status: str,
    *,
    event_id: int = 1,
    change_type: str = "changed",
    previous_status: str | None = "ready",
    reasons: list[dict[str, str]] | None = None,
    policy_revision: int = 8,
) -> dict[str, object]:
    return {
        "id": event_id,
        "policy_revision": policy_revision,
        "change_type": change_type,
        "previous_readiness_status": previous_status,
        "readiness_status": status,
        "rollout_eligible": status == "ready",
        "agent_version_state": "compliant",
        "reasons": reasons or [],
        "observed_at": observed_at,
    }


def current_state(
    now: datetime,
    status: str = "ready",
    *,
    first_observed_at: datetime | None = None,
    state_changed_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "policy_revision": 8,
        "readiness_status": status,
        "rollout_eligible": status == "ready",
        "agent_version_state": "compliant",
        "reasons": [],
        "first_observed_at": first_observed_at or now - timedelta(days=1),
        "state_changed_at": state_changed_at or now - timedelta(days=1),
        "last_evaluated_at": now,
    }


class FleetReadinessTimelineSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.end = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        self.start = self.end - timedelta(hours=2)

    def build(self, events, state=None):
        return fleet_readiness_store._readiness_timeline_summary(
            current_state=(
                current_state(self.end) if state is None else state
            ),
            events=events,
            window_start=self.start,
            window_end=self.end,
        )

    def test_prior_event_anchors_the_full_requested_window(self) -> None:
        result = self.build(
            [
                event(self.start - timedelta(minutes=5), "ready", event_id=1),
                event(self.start + timedelta(minutes=30), "blocked", event_id=2),
                event(self.start + timedelta(hours=1), "ready", event_id=3),
            ]
        )

        self.assertEqual(["ready", "blocked", "ready"], [
            segment["readiness_status"] for segment in result["timeline"]
        ])
        self.assertEqual(5400, result["summary"]["ready_seconds"])
        self.assertEqual(1800, result["summary"]["blocked_seconds"])
        self.assertEqual(0, result["summary"]["unknown_seconds"])
        self.assertEqual(2, result["summary"]["transition_count"])

    def test_initial_event_inside_window_leaves_an_explicit_unknown_gap(self) -> None:
        initial_at = self.start + timedelta(minutes=20)
        result = self.build([
            event(
                initial_at,
                "ready",
                change_type="initial",
                previous_status=None,
            )
        ])

        self.assertEqual(["unknown", "ready"], [
            segment["readiness_status"] for segment in result["timeline"]
        ])
        self.assertEqual(1200, result["summary"]["unknown_seconds"])
        self.assertEqual(6000, result["summary"]["ready_seconds"])
        self.assertEqual(initial_at, result["coverage_start"])

    def test_current_state_fallback_never_backfills_before_known_state(self) -> None:
        known_at = self.start + timedelta(minutes=45)
        result = self.build(
            [],
            current_state(
                self.end,
                "attention",
                first_observed_at=known_at,
                state_changed_at=known_at,
            ),
        )

        self.assertEqual(2700, result["summary"]["unknown_seconds"])
        self.assertEqual(4500, result["summary"]["attention_seconds"])

    def test_missing_state_is_unknown_for_the_entire_window(self) -> None:
        result = self.build([], {})

        self.assertEqual(7200, result["summary"]["unknown_seconds"])
        self.assertEqual(0, result["coverage_seconds"])
        self.assertIsNone(result["coverage_start"])

    def test_excluded_time_is_not_part_of_ready_percentage(self) -> None:
        result = self.build([
            event(self.start - timedelta(minutes=1), "excluded", event_id=1),
            event(self.start + timedelta(hours=1), "ready", event_id=2),
        ])

        self.assertEqual(3600, result["summary"]["excluded_seconds"])
        self.assertEqual(3600, result["summary"]["ready_seconds"])
        self.assertEqual(100.0, result["summary"]["ready_percent"])

    def test_reason_only_change_is_a_transition_not_a_readiness_change(self) -> None:
        result = self.build([
            event(self.start - timedelta(minutes=1), "ready", event_id=1),
            event(
                self.start + timedelta(hours=1),
                "ready",
                event_id=2,
                reasons=[{"code": "test", "severity": "attention"}],
            ),
        ])

        self.assertEqual(2, len(result["timeline"]))
        self.assertEqual(1, result["summary"]["transition_count"])
        self.assertEqual(0, result["summary"]["readiness_change_count"])

    def test_segment_durations_cover_the_exact_window(self) -> None:
        result = self.build([
            event(self.start + timedelta(minutes=15), "ready", change_type="initial"),
            event(self.start + timedelta(minutes=75), "blocked", event_id=2),
        ])

        self.assertEqual(
            result["window_seconds"],
            sum(segment["duration_seconds"] for segment in result["timeline"]),
        )


class FleetReadinessTimelineStoreTests(unittest.TestCase):
    def test_missing_sensor_returns_none_without_history_query(self) -> None:
        cursor = FakeCursor(row_sequence=[None])
        with patch.object(
            fleet_readiness_store,
            "connection",
            fake_connection_for(cursor),
        ):
            result = fleet_readiness_store.get_sensor_fleet_readiness_timeline(
                uuid4(), 24
            )

        self.assertIsNone(result)
        self.assertEqual(1, len(cursor.queries))

    def test_store_reads_one_boundary_event_and_window_events_in_order(self) -> None:
        sensor_id = uuid4()
        now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        sensor = {
            "id": sensor_id,
            "sensor_id": "skyspy-sensor-01",
            "display_name": "Sky-Spy",
            "generated_at": now,
            **current_state(now),
        }
        cursor = FakeCursor(
            row_sequence=[sensor],
            rows_sequence=[[event(now - timedelta(hours=25), "ready")]],
        )
        with patch.object(
            fleet_readiness_store,
            "connection",
            fake_connection_for(cursor),
        ):
            result = fleet_readiness_store.get_sensor_fleet_readiness_timeline(
                sensor_id, 24
            )

        assert result is not None
        self.assertEqual("skyspy-sensor-01", result["sensor_id"])
        history_query = cursor.queries[1]
        self.assertIn("WITH prior_event AS", history_query)
        self.assertIn("ORDER BY observed_at DESC, id DESC", history_query)
        self.assertIn("ORDER BY observed_at, id", history_query)
        self.assertEqual(now - timedelta(hours=24), cursor.parameters[1]["window_start"])


class FleetReadinessTimelineApiTests(unittest.TestCase):
    def test_endpoint_is_viewer_only_and_has_bounded_windows(self) -> None:
        route = MAIN.split("def get_sensor_fleet_readiness_timeline_view", 1)[0][-700:]
        body = MAIN.split("def get_sensor_fleet_readiness_timeline_view", 1)[1].split(
            "@app.put(", 1
        )[0]
        self.assertIn('"/api/v1/sensors/{sensor_id}/readiness-history"', route)
        self.assertIn("dependencies=[Depends(require_viewer)]", route)
        self.assertIn("hours: SensorHealthHistoryWindow", body)

    def test_endpoint_returns_timeline_payload(self) -> None:
        sensor_id = uuid4()
        with patch.object(
            api_main,
            "get_sensor_fleet_readiness_timeline",
            return_value={"sensor_id": "skyspy-sensor-01", "timeline": []},
        ) as get_timeline:
            result = api_main.get_sensor_fleet_readiness_timeline_view(
                sensor_id,
                api_main.SensorHealthHistoryWindow.ONE_DAY,
            )

        self.assertEqual("skyspy-sensor-01", result["sensor_id"])
        get_timeline.assert_called_once_with(sensor_id, 24)

    def test_endpoint_returns_404_for_deleted_or_missing_sensor(self) -> None:
        with patch.object(
            api_main,
            "get_sensor_fleet_readiness_timeline",
            return_value=None,
        ):
            with self.assertRaises(HTTPException) as raised:
                api_main.get_sensor_fleet_readiness_timeline_view(
                    uuid4(),
                    api_main.SensorHealthHistoryWindow.ONE_HOUR,
                )
        self.assertEqual(404, raised.exception.status_code)


class FleetReadinessTimelineUiTests(unittest.TestCase):
    def test_fleet_panel_has_sensor_history_and_four_bounded_windows(self) -> None:
        self.assertIn('id="fleet-readiness-history-content"', INDEX)
        for hours in (1, 6, 24, 168):
            self.assertIn(f'data-readiness-hours="{hours}"', INDEX)

    def test_sensor_rows_are_selectable_and_fetch_only_the_selected_timeline(self) -> None:
        self.assertIn('row.addEventListener("click", () => selectFleetReadinessSensor(sensor.id))', MAIN_JS)
        self.assertIn(
            '`/readiness-history?hours=${requestedHours}`',
            MAIN_JS,
        )
        self.assertIn("fleetReadinessTimelineRequestSequence", MAIN_JS)

    def test_timeline_displays_all_durations_transitions_and_unknown_coverage(self) -> None:
        for field in (
            "ready_seconds",
            "attention_seconds",
            "blocked_seconds",
            "excluded_seconds",
            "unknown_seconds",
            "transition_count",
        ):
            self.assertIn(f"summary.{field}", MAIN_JS)
        self.assertIn("fleet-readiness-history-segment readiness-${status}", MAIN_JS)
        self.assertIn("repeating-linear-gradient", STYLES)
        self.assertIn('unknown: "brak danych"', MAIN_JS)


if __name__ == "__main__":
    unittest.main()

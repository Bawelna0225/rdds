import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import config, database, main as api_main, sensor_store
    from app.models import HeartbeatEnvelope, HeartbeatStatus, SensorMaintenance
    from app.sensor_health import SourceQuality, assess_heartbeat, measure_source_quality


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

    def fetchall(self) -> list[dict[str, object]]:
        return list(self._rows)


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

    def test_latest_delivery_error_marks_api_path_degraded(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(
                source_connected=True,
                last_delivery_success_at=self.reported_at - timedelta(minutes=2),
                last_delivery_error_at=self.reported_at - timedelta(minutes=1),
                last_delivery_error_reason="connection_failed",
            ),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
        )
        self.assertEqual(("degraded", "api_delivery_failed"), (result.state, result.reason))

    def test_recovery_after_delivery_error_is_healthy(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(
                source_connected=True,
                last_delivery_success_at=self.reported_at - timedelta(seconds=10),
                last_delivery_error_at=self.reported_at - timedelta(minutes=1),
                last_delivery_error_reason="connection_failed",
            ),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
        )
        self.assertEqual(("online", "healthy"), (result.state, result.reason))

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

    def test_malformed_stream_is_degraded_after_quality_grace(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(source_connected=True),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
            source_quality=SourceQuality(40, 42, 0, 42, 0, 1.0),
            quality_min_window_seconds=30,
            quality_min_input_lines=20,
            quality_max_ignored_ratio=0.8,
            reconnect_warning_count=3,
        )
        self.assertEqual("source_data_invalid", result.reason)

    def test_quality_sample_does_not_degrade_during_warmup(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(source_connected=True),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
            source_quality=SourceQuality(20, 30, 0, 30, 4, 1.0),
            quality_min_window_seconds=30,
            quality_min_input_lines=20,
            quality_max_ignored_ratio=0.8,
            reconnect_warning_count=3,
        )
        self.assertEqual(("online", "healthy"), (result.state, result.reason))

    def test_frequent_reconnects_are_degraded(self) -> None:
        result = assess_heartbeat(
            HeartbeatStatus(source_connected=True),
            queue_warning_messages=100,
            source_silent_after_seconds=90,
            reported_at=self.reported_at,
            source_quality=SourceQuality(45, 45, 40, 5, 3, 5 / 45),
            quality_min_window_seconds=30,
            quality_min_input_lines=20,
            quality_max_ignored_ratio=0.8,
            reconnect_warning_count=3,
        )
        self.assertEqual("source_unstable", result.reason)

    def test_counter_deltas_form_quality_sample(self) -> None:
        sample = measure_source_quality(
            reported_at=self.reported_at,
            baseline_at=self.reported_at - timedelta(seconds=40),
            input_lines_total=150,
            parsed_detections_total=110,
            ignored_lines_total=40,
            source_connections_total=7,
            baseline_input_lines_total=100,
            baseline_parsed_detections_total=80,
            baseline_ignored_lines_total=20,
            baseline_source_connections_total=4,
        )
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual((40, 50, 30, 20, 3), (
            sample.window_seconds,
            sample.input_lines,
            sample.parsed_detections,
            sample.ignored_lines,
            sample.reconnects,
        ))
        self.assertAlmostEqual(0.4, sample.ignored_ratio)

    def test_counter_reset_discards_quality_sample(self) -> None:
        sample = measure_source_quality(
            reported_at=self.reported_at,
            baseline_at=self.reported_at - timedelta(seconds=40),
            input_lines_total=2,
            parsed_detections_total=1,
            ignored_lines_total=1,
            source_connections_total=1,
            baseline_input_lines_total=100,
            baseline_parsed_detections_total=80,
            baseline_ignored_lines_total=20,
            baseline_source_connections_total=4,
        )
        self.assertIsNone(sample)

    def test_inconsistent_counter_deltas_discard_quality_sample(self) -> None:
        sample = measure_source_quality(
            reported_at=self.reported_at,
            baseline_at=self.reported_at - timedelta(seconds=40),
            input_lines_total=110,
            parsed_detections_total=120,
            ignored_lines_total=30,
            source_connections_total=2,
            baseline_input_lines_total=100,
            baseline_parsed_detections_total=80,
            baseline_ignored_lines_total=20,
            baseline_source_connections_total=1,
        )
        self.assertIsNone(sample)


class HealthModelTests(unittest.TestCase):
    def test_quality_warmup_cannot_exceed_rolling_window(self) -> None:
        with patch.dict(
            os.environ,
            {
                **REQUIRED_ENVIRONMENT,
                "RDDS_SENSOR_QUALITY_WINDOW_SECONDS": "60",
                "RDDS_SENSOR_QUALITY_MIN_WINDOW_SECONDS": "61",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                config.load_settings()

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


class HealthHistoryTests(unittest.TestCase):
    def test_history_calculates_availability_and_excludes_maintenance(self) -> None:
        window_start = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        window_end = window_start + timedelta(hours=24)
        sensor = {
            "created_at": window_start - timedelta(days=1),
            "status": "online",
            "health_reason": "healthy",
        }
        events = [
            {
                "occurred_at": window_start - timedelta(hours=1),
                "event_type": "sensor_online",
                "details": {"from_status": "provisioning", "to_status": "online", "reason": "healthy"},
            },
            {
                "occurred_at": window_start + timedelta(hours=10),
                "event_type": "sensor_degraded",
                "details": {"from_status": "online", "to_status": "degraded", "reason": "source_unavailable"},
            },
            {
                "occurred_at": window_start + timedelta(hours=11),
                "event_type": "sensor_health_changed",
                "details": {"from_status": "degraded", "to_status": "degraded", "from_reason": "source_unavailable", "reason": "source_unstable"},
            },
            {
                "occurred_at": window_start + timedelta(hours=12),
                "event_type": "sensor_health_changed",
                "details": {"from_status": "degraded", "to_status": "offline", "from_reason": "source_unstable", "reason": "heartbeat_timeout"},
            },
            {
                "occurred_at": window_start + timedelta(hours=13),
                "event_type": "sensor_recovered",
                "details": {"from_status": "offline", "to_status": "online", "from_reason": "heartbeat_timeout", "reason": "healthy"},
            },
            {
                "occurred_at": window_start + timedelta(hours=20),
                "event_type": "sensor_maintenance_started",
                "details": {"from_status": "online", "to_status": "maintenance", "reason": "service"},
            },
            {
                "occurred_at": window_start + timedelta(hours=22),
                "event_type": "sensor_maintenance_ended",
                "details": {"from_status": "maintenance", "to_status": "online"},
            },
        ]

        history = sensor_store._health_history_summary(
            sensor=sensor,
            events=events,
            window_start=window_start,
            window_end=window_end,
        )

        summary = history["summary"]
        self.assertEqual(19 * 3600, summary["online_seconds"])
        self.assertEqual(2 * 3600, summary["degraded_seconds"])
        self.assertEqual(1 * 3600, summary["offline_seconds"])
        self.assertEqual(2 * 3600, summary["excluded_seconds"])
        self.assertEqual(1, summary["issue_count"])
        self.assertEqual(1, summary["recovery_count"])
        self.assertEqual(95.45, summary["availability_percent"])
        self.assertEqual(86.36, summary["healthy_percent"])
        self.assertEqual(7, len(history["timeline"]))

    def test_duplicate_transition_events_do_not_double_count_issue(self) -> None:
        window_start = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        window_end = window_start + timedelta(hours=1)
        transition_at = window_start + timedelta(minutes=30)
        sensor = {
            "created_at": window_start - timedelta(days=1),
            "status": "offline",
            "health_reason": "heartbeat_timeout",
        }
        events = [
            {
                "occurred_at": window_start - timedelta(minutes=1),
                "event_type": "sensor_disabled",
                "details": {"status": "disabled"},
            },
            {
                "occurred_at": transition_at,
                "event_type": "sensor_enabled",
                "details": {"status": "offline"},
            },
            {
                "occurred_at": transition_at,
                "event_type": "sensor_offline",
                "details": {"from_status": "disabled", "to_status": "offline", "reason": "heartbeat_timeout"},
            },
        ]

        history = sensor_store._health_history_summary(
            sensor=sensor,
            events=events,
            window_start=window_start,
            window_end=window_end,
        )

        self.assertEqual(1, history["summary"]["issue_count"])
        self.assertEqual(2, len(history["timeline"]))
        self.assertEqual("disabled", history["timeline"][0]["state"])
        self.assertEqual("offline", history["timeline"][1]["state"])



class HealthPersistenceTests(unittest.TestCase):
    def test_health_history_reads_prior_transition_and_window_events(self) -> None:
        sensor_id = uuid4()
        generated_at = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        cursor = FakeCursor(
            rows=[
                {
                    "id": sensor_id,
                    "sensor_id": "skyspy-sensor-01",
                    "display_name": "Sensor 01",
                    "status": "online",
                    "health_reason": "healthy",
                    "created_at": generated_at - timedelta(days=10),
                    "generated_at": generated_at,
                },
                {
                    "id": uuid4(),
                    "occurred_at": generated_at - timedelta(hours=25),
                    "event_type": "sensor_online",
                    "details": {"to_status": "online", "reason": "healthy"},
                },
                {
                    "id": uuid4(),
                    "occurred_at": generated_at - timedelta(hours=2),
                    "event_type": "sensor_degraded",
                    "details": {
                        "from_status": "online",
                        "to_status": "degraded",
                        "reason": "source_unstable",
                    },
                },
                {
                    "id": uuid4(),
                    "occurred_at": generated_at - timedelta(hours=1),
                    "event_type": "sensor_recovered",
                    "details": {
                        "from_status": "degraded",
                        "to_status": "online",
                        "reason": "healthy",
                    },
                },
            ]
        )
        with patch.object(
            sensor_store,
            "connection",
            fake_connection_for(cursor),
        ):
            history = sensor_store.get_sensor_health_history(sensor_id, 24)

        self.assertIsNotNone(history)
        assert history is not None
        self.assertEqual(24, history["window_hours"])
        self.assertEqual(1, history["summary"]["issue_count"])
        self.assertEqual(1, history["summary"]["recovery_count"])
        self.assertIn("WITH prior_event AS", cursor.queries[1])
        self.assertIn("event_type = ANY", cursor.queries[1])
        parameters = cursor.parameters[1]
        assert isinstance(parameters, dict)
        self.assertIn("sensor_health_changed", parameters["event_types"])
        self.assertIn("sensor_maintenance_started", parameters["event_types"])

    def test_health_overview_aggregates_audit_events_for_last_24_hours(self) -> None:
        sensor_id = uuid4()
        cursor = FakeCursor(
            rows=[
                {
                    "id": sensor_id,
                    "sensor_id": "skyspy-sensor-01",
                    "status": "degraded",
                    "issue_starts_24h": 2,
                    "health_changes_24h": 1,
                    "recoveries_24h": 1,
                }
            ]
        )
        with patch.object(
            sensor_store,
            "connection",
            fake_connection_for(cursor),
        ):
            overview = sensor_store.list_sensor_health_overview()

        self.assertEqual(2, overview[0]["issue_starts_24h"])
        query = cursor.queries[0]
        self.assertIn("INTERVAL '24 hours'", query)
        self.assertIn("sensor_degraded", query)
        self.assertIn("sensor_health_changed", query)
        self.assertIn("sensor_recovered", query)
        self.assertIn("sensor.deleted_at IS NULL", query)

    def test_quality_history_is_scoped_and_classified_by_server_thresholds(self) -> None:
        sensor_id = uuid4()
        cursor = FakeCursor(
            rows=[
                {"id": sensor_id},
                {
                    "measured_at": datetime(
                        2026, 8, 26, 12, 0, tzinfo=timezone.utc
                    ),
                    "window_seconds": 40,
                    "input_lines": 40,
                    "parsed_detections": 0,
                    "ignored_lines": 40,
                    "reconnects": 0,
                    "ignored_ratio": 1.0,
                    "reason": "source_data_invalid",
                },
            ]
        )
        fake_settings = SimpleNamespace(
            sensor_quality_min_window_seconds=30,
            sensor_quality_min_input_lines=20,
            sensor_quality_max_ignored_percent=80,
            sensor_reconnect_warning_count=3,
        )
        with (
            patch.object(sensor_store, "connection", fake_connection_for(cursor)),
            patch.object(sensor_store, "settings", fake_settings),
        ):
            history = sensor_store.get_sensor_quality_history(sensor_id, 18)

        self.assertIsNotNone(history)
        assert history is not None
        self.assertEqual("source_data_invalid", history[0]["reason"])
        self.assertIn("quality_ignored_ratio", cursor.queries[1])
        self.assertEqual(18, cursor.parameters[1]["limit"])

    def test_newest_heartbeat_controls_current_health_snapshot(self) -> None:
        sensor_id = uuid4()
        cursor = FakeCursor(
            rows=[
                {"id": sensor_id},
                {
                    "measured_at": datetime(
                        2026, 8, 26, 11, 59, 20, tzinfo=timezone.utc
                    ),
                    "input_lines_total": 60,
                    "parsed_detections_total": 50,
                    "ignored_lines_total": 10,
                    "source_connections_total": 1,
                },
                {"id": 17},
            ]
        )
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
                    "agent_version": "0.18.0",
                    "source_connected": False,
                    "source_kind": "serial",
                    "queue_depth": 3,
                    "queue_capacity": 250000,
                    "queue_oldest_age_seconds": 12,
                    "dead_letter_depth": 0,
                    "input_lines_total": 100,
                    "parsed_detections_total": 80,
                    "enqueued_observations_total": 79,
                    "ignored_lines_total": 20,
                    "source_connections_total": 2,
                    "delivery_success_total": 75,
                    "delivery_retry_total": 4,
                    "delivery_discard_total": 0,
                    "delivery_dead_letter_total": 0,
                    "last_delivery_success_at": "2026-08-26T11:59:50+00:00",
                },
            }
        )
        fake_settings = SimpleNamespace(
            sensor_queue_warning_messages=100,
            sensor_source_silent_after_seconds=90,
            sensor_quality_window_seconds=60,
            sensor_quality_min_window_seconds=30,
            sensor_quality_min_input_lines=20,
            sensor_quality_max_ignored_percent=80,
            sensor_reconnect_warning_count=3,
        )

        with (
            patch.object(database, "connection", fake_connection_for(cursor)),
            patch.object(database, "settings", fake_settings),
        ):
            stored_sensor, record_id = database.insert_heartbeat(payload, {})

        self.assertEqual(sensor_id, stored_sensor)
        self.assertEqual(17, record_id)
        quality_query = cursor.queries[1]
        heartbeat_insert = cursor.queries[2]
        health_update = cursor.queries[3]
        self.assertIn("sensor_boot_id = %(boot_id)s", quality_query)
        self.assertIn("dead_letter_depth", heartbeat_insert)
        self.assertIn("source_connected", heartbeat_insert)
        self.assertIn("parsed_detections_total", heartbeat_insert)
        self.assertIn("delivery_success_total", heartbeat_insert)
        self.assertIn("queue_oldest_age_seconds", heartbeat_insert)
        self.assertIn("last_heartbeat_reported_at < %(reported_at)s", health_update)
        self.assertIn("status IN ('disabled', 'maintenance')", health_update)
        self.assertIn("quality_ignored_ratio", heartbeat_insert)
        self.assertEqual("degraded", cursor.parameters[3]["health_state"])

    def test_monitor_expires_maintenance_and_marks_stale_once(self) -> None:
        cursor = FakeCursor(rowcounts=[1, 2])
        fake_settings = SimpleNamespace(
            sensor_offline_after_seconds=30,
            sensor_queue_warning_messages=100,
            sensor_source_silent_after_seconds=90,
            sensor_quality_min_window_seconds=30,
            sensor_quality_min_input_lines=20,
            sensor_quality_max_ignored_percent=80,
            sensor_reconnect_warning_count=3,
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


class HealthHistoryRouteTests(unittest.TestCase):
    def test_query_string_windows_are_coerced_to_allowed_integer_enum(self) -> None:
        adapter = TypeAdapter(api_main.SensorHealthHistoryWindow)
        for hours in (1, 6, 24, 168):
            with self.subTest(hours=hours):
                parsed = adapter.validate_python(str(hours))
                self.assertEqual(hours, int(parsed))

    def test_unknown_history_window_is_rejected_by_query_type(self) -> None:
        adapter = TypeAdapter(api_main.SensorHealthHistoryWindow)
        with self.assertRaises(ValidationError):
            adapter.validate_python("2")

if __name__ == "__main__":
    unittest.main()

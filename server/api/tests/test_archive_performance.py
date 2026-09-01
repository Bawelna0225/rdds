from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALERT_STORE = PROJECT_ROOT / "server" / "api" / "app" / "alert_store.py"
TRACK_STORE = PROJECT_ROOT / "server" / "api" / "app" / "track_store.py"
WEB_SOURCE = PROJECT_ROOT / "web" / "src" / "main.js"


class ArchivePerformanceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.alert_store = ALERT_STORE.read_text(encoding="utf-8")
        cls.track_store = TRACK_STORE.read_text(encoding="utf-8")
        cls.web_source = WEB_SOURCE.read_text(encoding="utf-8")

    def test_closed_alert_archive_skips_historical_sensor_aggregation(self) -> None:
        start = self.alert_store.index("def list_alerts(")
        end = self.alert_store.index("\ndef acknowledge_alert(", start)
        source = self.alert_store[start:end]
        self.assertIn("AND NOT %(closed_only)s", source)
        self.assertIn("LEFT JOIN LATERAL", source)

    def test_track_archive_skips_raw_observation_joins(self) -> None:
        start = self.track_store.index("def list_tracks(")
        end = self.track_store.index("\ndef get_live_track_trails(", start)
        source = self.track_store[start:end]
        self.assertIn("WHEN %s THEN NULL", source)
        self.assertIn("AND NOT %s", source)
        self.assertIn(
            "(include_ended, include_ended, include_ended)",
            source,
        )

    def test_archived_track_sensor_count_has_unknown_fallback(self) -> None:
        self.assertIn("track.contributing_sensors == null", self.web_source)
        self.assertIn('"sensory: —"', self.web_source)


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_SOURCE = PROJECT_ROOT / "web" / "src" / "main.js"


class WebRefreshBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WEB_SOURCE.read_text(encoding="utf-8")
        match = re.search(
            r"async function refresh\(.*?\n}\n\nelements\.showEnded",
            cls.source,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError("Could not isolate the live refresh function")
        cls.live_refresh = match.group(0)

    def test_periodic_refresh_only_fetches_live_operational_data(self) -> None:
        expected_live_paths = (
            '/api/v1/sensors',
            '/api/v1/tracks?include_ended=false',
            '/api/v1/tracks/trails?seconds=',
            '/api/v1/alerts?include_closed=false',
        )
        for path in expected_live_paths:
            with self.subTest(path=path):
                self.assertIn(path, self.live_refresh)

        stored_paths = (
            '/api/v1/zones',
            '/api/v1/audit/events',
            '/api/v1/security/events',
            '/api/v1/security/sessions',
            'include_ended=true',
            'include_closed=true',
        )
        for path in stored_paths:
            with self.subTest(path=path):
                self.assertNotIn(path, self.live_refresh)

    def test_stored_views_have_dedicated_on_demand_loaders(self) -> None:
        for function_name in (
            "loadArchivedTracks",
            "loadClosedAlerts",
            "loadZones",
            "loadAuditEvents",
        ):
            with self.subTest(function=function_name):
                self.assertIn(f"async function {function_name}", self.source)

    def test_global_telemetry_loader_is_not_present(self) -> None:
        self.assertNotIn("global-loading", self.source)
        self.assertNotIn("setDashboardLoading", self.source)

    def test_security_event_log_is_loaded_only_on_demand(self) -> None:
        self.assertIn("async function loadSecurityCenter", self.source)
        self.assertIn('fetchJson("/api/v1/security/sessions")', self.source)
        self.assertIn("/api/v1/security/events?", self.source)
        self.assertNotIn("/api/v1/security/events?", self.live_refresh)


if __name__ == "__main__":
    unittest.main()

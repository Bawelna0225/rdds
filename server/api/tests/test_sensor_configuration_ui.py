from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/src/styles.css").read_text(encoding="utf-8")


class SensorConfigurationUiTests(unittest.TestCase):
    def test_configuration_form_contains_only_managed_fields(self) -> None:
        expected = {
            "sensor-configuration-heartbeat": ("2", "3600"),
            "sensor-configuration-reconnect": ("0.5", "300"),
            "sensor-configuration-timeout": ("1", "120"),
            "sensor-configuration-replay-rate": ("0.1", "100"),
        }
        for field_id, (minimum, maximum) in expected.items():
            pattern = (
                rf'id="{re.escape(field_id)}"[\s\S]*?'
                rf'min="{re.escape(minimum)}"[\s\S]*?'
                rf'max="{re.escape(maximum)}"'
            )
            self.assertRegex(INDEX, pattern)
        for forbidden in (
            "RDDS_API_URL",
            "RDDS_AGENT_SENSOR_TOKEN",
            "RDDS_SKYSPY_SOURCE",
            "baud_rate",
        ):
            self.assertNotIn(forbidden, INDEX)

    def test_configuration_write_uses_admin_request(self) -> None:
        self.assertRegex(
            MAIN_JS,
            re.compile(
                r"adminRequest\([\s\S]*?/configuration`?[\s\S]*?"
                r'"PUT"[\s\S]*?payload',
            ),
        )
        self.assertIn('headers["X-RDDS-CSRF-Token"] = csrfToken;', MAIN_JS)

    def test_every_compliance_state_has_a_polish_label(self) -> None:
        for state in ("unmanaged", "unreported", "pending", "compliant", "error"):
            self.assertRegex(MAIN_JS, rf'{state}: "[^"]+"')
            self.assertIn(f"configuration-{state}", STYLES)

    def test_fleet_view_exposes_configuration_status(self) -> None:
        self.assertIn('id="sensor-overview-configuration"', INDEX)
        self.assertIn('<option value="configuration">Niezgodna konfiguracja</option>', INDEX)
        self.assertIn('<span>Konfiguracja</span>', INDEX)
        self.assertIn("sensorConfigurationPriority", MAIN_JS)

    def test_release_version_is_0271(self) -> None:
        package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], "0.27.1")
        api_main = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
        self.assertIn('version="0.27.1"', api_main)


if __name__ == "__main__":
    unittest.main()

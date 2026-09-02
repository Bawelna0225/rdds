from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/src/styles.css").read_text(encoding="utf-8")


class SensorConfigurationFleetUiTests(unittest.TestCase):
    def test_administrator_has_dedicated_fleet_console(self) -> None:
        self.assertIn('id="fleet-configuration-open"', INDEX)
        self.assertIn('id="fleet-configuration-editor"', INDEX)
        self.assertIn('data-fleet-tab="profiles"', INDEX)
        self.assertIn('data-fleet-tab="rollouts"', INDEX)
        self.assertIn(
            'elements.fleetConfigurationOpen.classList.toggle("hidden", !canAdminister());',
            MAIN_JS,
        )

    def test_profile_create_form_contains_only_managed_agent_fields(self) -> None:
        for field in (
            "profile-create-heartbeat",
            "profile-create-reconnect",
            "profile-create-timeout",
            "profile-create-replay",
        ):
            self.assertIn(f'id="{field}"', INDEX)
        for forbidden in (
            "RDDS_API_URL",
            "RDDS_AGENT_SENSOR_TOKEN",
            "RDDS_SKYSPY_SOURCE",
            "baud_rate",
        ):
            self.assertNotIn(forbidden, INDEX)

    def test_profile_metadata_and_versions_are_separate_operations(self) -> None:
        self.assertIn('id="configuration-profile-metadata-form"', INDEX)
        self.assertIn('id="configuration-profile-version-form"', INDEX)
        self.assertRegex(
            MAIN_JS,
            re.compile(
                r"async function updateFleetProfileMetadata[\s\S]*?"
                r'"PUT"[\s\S]*?async function createFleetProfileVersion',
            ),
        )
        self.assertRegex(
            MAIN_JS,
            re.compile(
                r"async function createFleetProfileVersion[\s\S]*?"
                r'/versions`[\s\S]*?"POST"',
            ),
        )

    def test_profile_history_is_loaded_from_immutable_versions_endpoint(self) -> None:
        self.assertIn('id="configuration-profile-version-list"', INDEX)
        self.assertIn(
            '`/api/v1/sensor-configuration-profiles/${encodeURIComponent(profileId)}`',
            MAIN_JS,
        )
        self.assertIn('"/versions?limit=500&offset=0"', MAIN_JS)
        self.assertIn("Wersje profilu są niemodyfikowalne.", INDEX)

    def test_rollout_form_exposes_profile_version_batch_and_targets(self) -> None:
        for field in (
            "rollout-create-profile",
            "rollout-create-version",
            "rollout-create-batch-size",
            "rollout-create-sensors",
            "rollout-create-note",
        ):
            self.assertIn(f'id="{field}"', INDEX)
        self.assertRegex(
            INDEX,
            r'id="rollout-create-batch-size"[^>]*min="1"[^>]*max="25"',
        )
        self.assertIn("sensorIds.length < 1 || sensorIds.length > 100", MAIN_JS)

    def test_rollout_creation_is_explicitly_draft_only(self) -> None:
        self.assertIn("najpierw powstanie draft", INDEX)
        self.assertIn("Utworzenie rollout'u nie zmienia konfiguracji", INDEX)
        body = MAIN_JS.split("async function createFleetRollout", 1)[1].split(
            "async function runFleetRolloutAction", 1
        )[0]
        self.assertIn('adminRequest("/api/v1/sensor-configuration-rollouts", "POST"', body)
        self.assertNotIn("/start", body)
        self.assertIn("Żaden sensor nie został jeszcze zmieniony", body)

    def test_start_advance_and_cancel_are_separate_actions(self) -> None:
        for action in ("start", "advance", "cancel", "rollback"):
            self.assertIn(f'id="configuration-rollout-{action}"', INDEX)
            self.assertIn(
                f'runFleetRolloutAction("{action}")',
                MAIN_JS,
            )
        self.assertIn(
            "`/api/v1/sensor-configuration-rollouts/${encodeURIComponent(rollout.id)}/${action}`",
            MAIN_JS,
        )

    def test_rollout_writes_use_authenticated_csrf_admin_request(self) -> None:
        self.assertIn('headers["X-RDDS-CSRF-Token"] = csrfToken;', MAIN_JS)
        for endpoint in (
            "/api/v1/sensor-configuration-profiles",
            "/api/v1/sensor-configuration-rollouts",
        ):
            self.assertIn(f'adminRequest("{endpoint}"', MAIN_JS)

    def test_dangerous_rollout_actions_require_confirmation_and_notes(self) -> None:
        self.assertIn("if (!window.confirm(prompts[action])) return;", MAIN_JS)
        self.assertIn("changeNote.length < 3", MAIN_JS)
        self.assertIn(
            "Już wdrożone konfiguracje nie zostaną automatycznie cofnięte",
            MAIN_JS,
        )

    def test_advance_is_disabled_until_server_reports_it_safe(self) -> None:
        self.assertIn(
            "elements.rolloutAdvance.disabled = !rollout.can_advance;",
            MAIN_JS,
        )
        self.assertIn("Poprzednia partia musi być w pełni zgodna", MAIN_JS)

    def test_every_rollout_status_has_a_polish_label(self) -> None:
        for status in ("draft", "active", "completed", "cancelled"):
            self.assertRegex(MAIN_JS, rf'{status}: "[^"]+"')
            self.assertIn(f"rollout-{status}", STYLES)

    def test_every_target_status_has_a_polish_label(self) -> None:
        for status in (
            "pending",
            "awaiting_application",
            "compliant",
            "error",
            "superseded",
            "cancelled",
            "rollback_pending",
            "rolled_back",
            "rollback_error",
            "rollback_superseded",
        ):
            self.assertRegex(MAIN_JS, rf'{status}: "[^"]+"')

    def test_sensor_configuration_shows_profile_assignment(self) -> None:
        self.assertIn('id="sensor-configuration-profile"', INDEX)
        self.assertIn("configuration.assigned_profile_key", MAIN_JS)
        self.assertIn("zapis ręczny odłączy to przypisanie", MAIN_JS)

    def test_profile_and_rollout_audit_events_have_labels(self) -> None:
        for event_type in (
            "sensor_configuration_profile_created",
            "sensor_configuration_profile_version_created",
            "sensor_configuration_profile_assigned",
            "sensor_configuration_rollout_created",
            "sensor_configuration_rollout_started",
            "sensor_configuration_rollout_batch_deployed",
            "sensor_configuration_rollout_completed",
            "sensor_configuration_rollout_cancelled",
            "sensor_configuration_rollout_rolled_back",
        ):
            self.assertRegex(MAIN_JS, rf'{event_type}: "[^"]+"')

    def test_fleet_console_is_closed_when_session_is_cleared(self) -> None:
        clear_session = MAIN_JS.split("function clearSession", 1)[1].split(
            "async function logout", 1
        )[0]
        self.assertIn("closeFleetConfigurationEditor();", clear_session)
        self.assertIn(
            'event.key === "Escape" &&\n    !elements.fleetConfigurationEditor',
            MAIN_JS,
        )

    def test_fleet_console_has_wide_and_responsive_layout(self) -> None:
        self.assertIn(".fleet-configuration-editor", STYLES)
        self.assertIn("width: min(1120px", STYLES)
        self.assertIn("@media (max-width: 900px)", STYLES)

    def test_release_version_is_0240(self) -> None:
        package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], "0.24.0")
        api_main = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
        self.assertIn('version="0.24.0"', api_main)


if __name__ == "__main__":
    unittest.main()

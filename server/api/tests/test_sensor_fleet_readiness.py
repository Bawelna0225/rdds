from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "database/migrations/025_sensor_fleet_readiness.sql"
).read_text(encoding="utf-8")
STORE = (ROOT / "server/api/app/fleet_readiness_store.py").read_text(
    encoding="utf-8"
)
MODELS = (ROOT / "server/api/app/models.py").read_text(encoding="utf-8")
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
DOC = (ROOT / "docs/RDDS_STAGE25A.md").read_text(encoding="utf-8")


class FleetReadinessMigrationTests(unittest.TestCase):
    def test_policy_is_a_revisioned_singleton(self) -> None:
        self.assertIn("CREATE TABLE sensor_fleet_readiness_policy", MIGRATION)
        self.assertIn("CHECK (id = 1)", MIGRATION)
        self.assertIn("revision BIGINT NOT NULL DEFAULT 1", MIGRATION)

    def test_policy_defaults_match_the_managed_agent_baseline(self) -> None:
        self.assertIn("DEFAULT '0.23.0'", MIGRATION)
        self.assertIn("require_source_connected BOOLEAN NOT NULL DEFAULT TRUE", MIGRATION)
        self.assertIn(
            "require_configuration_compliance BOOLEAN NOT NULL DEFAULT TRUE",
            MIGRATION,
        )

    def test_policy_versions_are_strict_numeric_semver(self) -> None:
        self.assertGreaterEqual(
            MIGRATION.count("~ '^[0-9]+\\.[0-9]+\\.[0-9]+$'"),
            2,
        )

    def test_policy_change_event_is_allow_listed(self) -> None:
        self.assertIn("'sensor_fleet_readiness_policy_changed'", MIGRATION)


class FleetReadinessModelAndApiTests(unittest.TestCase):
    def test_policy_update_has_revision_requirements_and_note(self) -> None:
        body = MODELS.split("class SensorFleetReadinessPolicyUpdate", 1)[1].split(
            "class SensorConfigurationReport", 1
        )[0]
        for field in (
            "expected_revision",
            "minimum_agent_version",
            "recommended_agent_version",
            "require_source_connected",
            "require_configuration_compliance",
            "change_note",
        ):
            self.assertIn(field, body)

    def test_model_rejects_recommended_version_older_than_minimum(self) -> None:
        self.assertIn("if recommended < minimum:", MODELS)
        self.assertIn(
            "recommended_agent_version cannot be older than",
            MODELS,
        )

    def test_readiness_endpoint_is_viewer_accessible(self) -> None:
        self.assertIn('"/api/v1/sensor-fleet/readiness"', MAIN)
        route = MAIN.split("def get_sensor_fleet_readiness_view", 1)[0]
        self.assertIn("dependencies=[Depends(require_viewer)]", route[-400:])

    def test_policy_endpoint_requires_administrator_write(self) -> None:
        self.assertIn('"/api/v1/sensor-fleet/readiness-policy"', MAIN)
        route = MAIN.split("def put_sensor_fleet_readiness_policy", 1)[0]
        self.assertIn("dependencies=[Depends(require_administrator_write)]", route[-500:])

    def test_policy_conflict_is_reported_as_http_409(self) -> None:
        body = MAIN.split("def put_sensor_fleet_readiness_policy", 1)[1].split(
            "@app.get(", 1
        )[0]
        self.assertIn("except FleetReadinessPolicyConflict as exc:", body)
        self.assertIn("status_code=409", body)


class FleetReadinessStoreTests(unittest.TestCase):
    def test_agent_version_parser_is_strict_and_numeric(self) -> None:
        self.assertIn('re.fullmatch(r"[0-9]+\\.[0-9]+\\.[0-9]+", value)', STORE)
        self.assertIn("return int(major), int(minor), int(patch)", STORE)

    def test_disabled_and_maintenance_sensors_are_excluded(self) -> None:
        body = STORE.split("def _evaluate_sensor", 1)[1].split(
            "def _read_policy", 1
        )[0]
        self.assertIn('if status == "disabled":', body)
        self.assertIn('if status == "maintenance":', body)
        self.assertGreaterEqual(body.count('readiness_status="excluded"'), 2)

    def test_health_state_distinguishes_blocked_and_attention(self) -> None:
        self.assertIn('_reason("sensor_offline", "blocked")', STORE)
        self.assertIn('_reason("sensor_degraded", "attention")', STORE)
        self.assertIn('_reason("heartbeat_missing", "blocked")', STORE)

    def test_agent_policy_distinguishes_minimum_and_recommended(self) -> None:
        self.assertIn('version_state = "below_minimum"', STORE)
        self.assertIn('_reason("agent_version_below_minimum", "blocked")', STORE)
        self.assertIn('version_state = "below_recommended"', STORE)
        self.assertIn(
            '_reason("agent_version_below_recommended", "attention")',
            STORE,
        )

    def test_source_and_configuration_requirements_are_policy_controlled(self) -> None:
        self.assertIn('policy["require_source_connected"]', STORE)
        self.assertIn('_reason("source_disconnected", "blocked")', STORE)
        self.assertIn('policy["require_configuration_compliance"]', STORE)
        self.assertIn('f"configuration_{compliance}"', STORE)

    def test_summary_excludes_intentionally_inactive_sensors(self) -> None:
        self.assertRegex(
            STORE,
            re.compile(
                r"assessed = \[[\s\S]*?"
                r'if sensor\["readiness_status"\] != "excluded"'
            ),
        )
        self.assertIn('"excluded_count": counts["excluded"]', STORE)

    def test_policy_update_uses_optimistic_revision_lock(self) -> None:
        self.assertIn("for_update=True", STORE)
        self.assertIn('before["revision"] != payload.expected_revision', STORE)
        self.assertIn("revision = revision + 1", STORE)
        self.assertIn("AND revision = %(expected_revision)s", STORE)

    def test_policy_update_is_audited_with_before_after_and_note(self) -> None:
        body = STORE.split("def update_sensor_fleet_readiness_policy", 1)[1]
        self.assertIn("'sensor_fleet_readiness_policy_changed'", body)
        self.assertIn("'before', %(before)s::jsonb", body)
        self.assertIn("'after', %(after)s::jsonb", body)
        self.assertIn("'change_note', %(change_note)s::text", body)


class FleetReadinessWebTests(unittest.TestCase):
    def test_fleet_console_has_readiness_tab_summary_and_policy(self) -> None:
        self.assertIn('data-fleet-tab="readiness"', INDEX)
        self.assertIn('id="fleet-readiness-summary"', INDEX)
        self.assertIn('id="fleet-readiness-sensor-list"', INDEX)
        self.assertIn('id="fleet-readiness-policy-form"', INDEX)

    def test_web_has_polish_labels_for_all_readiness_states(self) -> None:
        for state in ("ready", "attention", "blocked", "excluded"):
            self.assertRegex(MAIN_JS, rf'{state}: "[^"]+"')

    def test_policy_write_uses_authenticated_admin_request(self) -> None:
        self.assertIn(
            'adminRequest("/api/v1/sensor-fleet/readiness-policy", "PUT"',
            MAIN_JS,
        )
        self.assertIn("expected_revision: fleetReadiness.policy.revision", MAIN_JS)
        self.assertIn("window.confirm", MAIN_JS)

    def test_rollout_picker_displays_readiness_without_enforcement(self) -> None:
        body = MAIN_JS.split("function renderRolloutSensorTargets", 1)[1].split(
            "function appendFleetMetric", 1
        )[0]
        self.assertIn("gotowość:", body)
        self.assertNotIn("input.disabled", body)
        self.assertIn("does not disable any target", DOC)


if __name__ == "__main__":
    unittest.main()

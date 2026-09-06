from __future__ import annotations

import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
STORE_PATH = ROOT / "server/api/app/agent_release_compliance_store.py"
STORE = STORE_PATH.read_text(encoding="utf-8")
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
DOC = (ROOT / "docs/RDDS_STAGE27B.md").read_text(encoding="utf-8")

fake_database = types.ModuleType("app.database")
fake_database.connection = object()
with patch.dict(sys.modules, {"app.database": fake_database}):
    NAMESPACE = runpy.run_path(str(STORE_PATH))

parse_version = NAMESPACE["_parse_version"]
latest_release = NAMESPACE["_latest_published_release"]
assess = NAMESPACE["_assess_sensor_release"]


def release(
    version: str,
    *,
    channel: str = "stable",
    status: str = "published",
    minimum: str = "0.23.0",
) -> dict[str, object]:
    return {
        "id": uuid4(),
        "version": version,
        "channel": channel,
        "status": status,
        "minimum_agent_version": minimum,
        "protocol_version": "rdds/1.0",
        "published_at": None,
        "withdrawn_at": None,
    }


def sensor(version: str | None, *, status: str = "online") -> dict[str, object]:
    return {
        "id": uuid4(),
        "sensor_key": "sensor-01",
        "display_name": "Sensor 01",
        "status": status,
        "agent_version": version,
        "last_heartbeat_at": None,
    }


class AgentReleaseVersionTests(unittest.TestCase):
    def test_parser_accepts_only_strict_numeric_semver(self) -> None:
        self.assertEqual((0, 27, 0), parse_version("0.27.0"))
        for value in (None, "0.27", "v0.27.0", "0.27.0-rc1"):
            with self.subTest(value=value):
                self.assertIsNone(parse_version(value))

    def test_latest_release_uses_numeric_not_lexicographic_order(self) -> None:
        releases = [release("0.9.0"), release("0.10.0")]
        self.assertEqual("0.10.0", latest_release(releases, "stable")["version"])

    def test_latest_release_ignores_drafts_withdrawn_and_other_channels(self) -> None:
        releases = [
            release("0.26.0"),
            release("0.30.0", status="draft"),
            release("0.29.0", status="withdrawn"),
            release("0.28.0", channel="candidate"),
        ]
        self.assertEqual("0.26.0", latest_release(releases, "stable")["version"])


class AgentReleaseAssessmentTests(unittest.TestCase):
    def assess_version(
        self,
        version: str | None,
        *,
        stable: dict[str, object] | None = None,
        catalog: list[dict[str, object]] | None = None,
        status: str = "online",
    ) -> dict[str, object]:
        stable = stable or release("0.26.0")
        entries = catalog if catalog is not None else [stable]
        return assess(
            sensor(version, status=status),
            release_by_version={item["version"]: item for item in entries},
            latest_stable=stable,
        )

    def test_current_stable_version_is_current(self) -> None:
        result = self.assess_version("0.26.0")
        self.assertEqual("current", result["release_state"])
        self.assertFalse(result["update_eligible"])

    def test_older_compatible_version_has_update_available(self) -> None:
        result = self.assess_version("0.23.0")
        self.assertEqual("upgrade_available", result["release_state"])
        self.assertTrue(result["update_eligible"])

    def test_version_below_release_minimum_is_blocked(self) -> None:
        result = self.assess_version("0.22.1")
        self.assertEqual("upgrade_blocked", result["release_state"])
        self.assertFalse(result["update_eligible"])

    def test_unreported_and_invalid_versions_are_distinctly_visible(self) -> None:
        for version in (None, "development"):
            with self.subTest(version=version):
                result = self.assess_version(version)
                self.assertEqual("unreported", result["release_state"])

    def test_withdrawn_release_keeps_risk_state_and_can_be_eligible(self) -> None:
        stable = release("0.27.0", minimum="0.23.0")
        withdrawn = release("0.26.0", status="withdrawn")
        result = self.assess_version(
            "0.26.0",
            stable=stable,
            catalog=[stable, withdrawn],
        )
        self.assertEqual("withdrawn", result["release_state"])
        self.assertTrue(result["update_eligible"])

    def test_offline_sensor_is_not_eligible_for_future_update(self) -> None:
        result = self.assess_version("0.23.0", status="offline")
        self.assertEqual("upgrade_available", result["release_state"])
        self.assertFalse(result["update_eligible"])
        self.assertIn("sensor_not_online", result["reason_codes"])

    def test_newer_published_candidate_is_recognized(self) -> None:
        stable = release("0.26.0")
        candidate = release("0.27.0", channel="candidate")
        result = self.assess_version(
            "0.27.0",
            stable=stable,
            catalog=[stable, candidate],
        )
        self.assertEqual("candidate", result["release_state"])

    def test_uncatalogued_newer_version_is_ahead(self) -> None:
        result = self.assess_version("0.28.0")
        self.assertEqual("ahead", result["release_state"])


class AgentReleaseComplianceBoundaryTests(unittest.TestCase):
    def test_store_is_read_only_and_excludes_deleted_sensors(self) -> None:
        self.assertIn("WHERE sensor.deleted_at IS NULL", STORE)
        self.assertNotIn("INSERT INTO", STORE)
        self.assertNotIn("UPDATE ", STORE)
        self.assertNotIn("DELETE FROM", STORE)

    def test_endpoint_is_viewer_only(self) -> None:
        prefix = MAIN.split("def get_sensor_agent_release_compliance_view", 1)[0][-600:]
        self.assertIn(
            '"/api/v1/sensor-fleet/agent-release-compliance"',
            prefix,
        )
        self.assertIn("dependencies=[Depends(require_viewer)]", prefix)

    def test_endpoint_has_no_write_or_agent_command_payload(self) -> None:
        body = MAIN.split("def get_sensor_agent_release_compliance_view", 1)[1].split(
            "@app.get", 1
        )[0]
        self.assertNotIn("require_administrator_write", body)
        for forbidden in ("download_url", "artifact_data", "desired_agent_version"):
            self.assertNotIn(forbidden, STORE + body)

    def test_ui_shows_summary_and_sensor_assessment(self) -> None:
        self.assertIn('id="agent-release-compliance-summary"', INDEX)
        self.assertIn('id="agent-release-compliance-list"', INDEX)
        self.assertIn("function renderFleetAgentReleaseCompliance", MAIN_JS)
        self.assertIn(
            'fetchJson("/api/v1/sensor-fleet/agent-release-compliance")',
            MAIN_JS,
        )

    def test_ui_has_labels_for_every_release_state(self) -> None:
        for state in (
            "current",
            "upgrade_available",
            "upgrade_blocked",
            "candidate",
            "ahead",
            "withdrawn",
            "unreported",
            "no_stable_release",
        ):
            self.assertIn(f'{state}: "', MAIN_JS)

    def test_stage_is_explicitly_informational(self) -> None:
        self.assertIn("Kwalifikacja jest wyłącznie informacyjna", INDEX)
        self.assertIn("read-only assessment layer", DOC)
        self.assertIn("does not expose any update or assignment action", DOC)


if __name__ == "__main__":
    unittest.main()

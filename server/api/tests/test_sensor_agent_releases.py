from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError


REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app.models import (
        SensorAgentReleaseAction,
        SensorAgentReleaseCreate,
        SensorAgentReleaseUpdate,
    )


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (ROOT / "database/migrations/029_sensor_agent_releases.sql").read_text(
    encoding="utf-8"
)
STORE = (ROOT / "server/api/app/agent_release_store.py").read_text(
    encoding="utf-8"
)
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web/src/styles.css").read_text(encoding="utf-8")
DOC = (ROOT / "docs/RDDS_STAGE27A.md").read_text(encoding="utf-8")


VALID_METADATA = {
    "version": "0.27.0",
    "channel": "candidate",
    "artifact_filename": "rdds-agent-0.27.0.tar.gz",
    "artifact_sha256": "AB" * 32,
    "artifact_size_bytes": 1048576,
    "minimum_agent_version": "0.23.0",
    "protocol_version": "rdds/1.0",
    "release_notes": "  Pierwsze wydanie katalogowe.  ",
}


class SensorAgentReleaseModelTests(unittest.TestCase):
    def test_create_normalizes_hash_notes_and_change_note(self) -> None:
        release = SensorAgentReleaseCreate(
            **VALID_METADATA,
            change_note="  Rejestracja artefaktu  ",
        )
        self.assertEqual("ab" * 32, release.artifact_sha256)
        self.assertEqual("Pierwsze wydanie katalogowe.", release.release_notes)
        self.assertEqual("Rejestracja artefaktu", release.change_note)

    def test_minimum_agent_version_cannot_exceed_release(self) -> None:
        with self.assertRaises(ValidationError):
            SensorAgentReleaseCreate(
                **{**VALID_METADATA, "minimum_agent_version": "0.28.0"},
                change_note="Niepoprawna zależność",
            )

    def test_filename_must_be_a_safe_basename(self) -> None:
        for filename in ("../agent.tar.gz", "/tmp/agent.tar.gz", "agent/package"):
            with self.subTest(filename=filename), self.assertRaises(ValidationError):
                SensorAgentReleaseCreate(
                    **{**VALID_METADATA, "artifact_filename": filename},
                    change_note="Niepoprawna nazwa",
                )

    def test_update_and_actions_require_optimistic_revision(self) -> None:
        updated = SensorAgentReleaseUpdate(
            **VALID_METADATA,
            expected_revision=3,
            change_note="Nowe metadane",
        )
        action = SensorAgentReleaseAction(
            expected_revision=4,
            change_note="  Publikacja po kontroli  ",
        )
        self.assertEqual(3, updated.expected_revision)
        self.assertEqual("Publikacja po kontroli", action.change_note)


class SensorAgentReleaseMigrationTests(unittest.TestCase):
    def test_catalog_has_revisioned_lifecycle_and_unique_version(self) -> None:
        self.assertIn("CREATE TABLE sensor_agent_releases", MIGRATION)
        self.assertIn("version TEXT NOT NULL UNIQUE", MIGRATION)
        self.assertIn("revision BIGINT NOT NULL DEFAULT 1", MIGRATION)
        self.assertIn("status IN ('draft', 'published', 'withdrawn')", MIGRATION)

    def test_artifact_identity_is_bounded_and_has_no_location(self) -> None:
        self.assertIn("artifact_filename", MIGRATION)
        self.assertIn("artifact_sha256", MIGRATION)
        self.assertIn("artifact_size_bytes", MIGRATION)
        self.assertNotRegex(MIGRATION, r"(?i)(download|artifact)_url")
        self.assertNotIn("artifact_data", MIGRATION)

    def test_lifecycle_timestamps_are_database_constrained(self) -> None:
        for field in (
            "published_at",
            "published_by",
            "withdrawn_at",
            "withdrawn_by",
            "withdrawal_reason",
        ):
            self.assertIn(field, MIGRATION)
        self.assertIn("published_at <= withdrawn_at", MIGRATION)

    def test_all_catalog_events_are_allow_listed(self) -> None:
        for event_type in (
            "sensor_agent_release_created",
            "sensor_agent_release_updated",
            "sensor_agent_release_published",
            "sensor_agent_release_withdrawn",
        ):
            self.assertIn(f"'{event_type}'", MIGRATION)


class SensorAgentReleaseStoreTests(unittest.TestCase):
    def test_every_mutation_locks_and_uses_expected_revision(self) -> None:
        self.assertGreaterEqual(STORE.count("for_update=True"), 3)
        self.assertGreaterEqual(STORE.count("payload.expected_revision"), 6)
        self.assertGreaterEqual(
            STORE.count("AND revision = %(expected_revision)s"),
            3,
        )

    def test_only_drafts_can_be_edited_or_published(self) -> None:
        update_body = STORE.split("def update_sensor_agent_release", 1)[1].split(
            "def publish_sensor_agent_release", 1
        )[0]
        publish_body = STORE.split("def publish_sensor_agent_release", 1)[1].split(
            "def withdraw_sensor_agent_release", 1
        )[0]
        self.assertIn('before["status"] != "draft"', update_body)
        self.assertIn("status = 'draft'", update_body)
        self.assertIn('before["status"] != "draft"', publish_body)

    def test_only_published_releases_can_be_withdrawn(self) -> None:
        body = STORE.split("def withdraw_sensor_agent_release", 1)[1]
        self.assertIn('before["status"] != "published"', body)
        self.assertIn("status = 'published'", body)

    def test_all_mutations_are_audited_with_operator_note(self) -> None:
        for event_type in (
            "sensor_agent_release_created",
            "sensor_agent_release_updated",
            "sensor_agent_release_published",
            "sensor_agent_release_withdrawn",
        ):
            self.assertIn(f"'{event_type}'", STORE)
        self.assertGreaterEqual(STORE.count("'change_note', %(change_note)s::text"), 4)

    def test_catalog_store_cannot_change_sensor_or_agent_runtime(self) -> None:
        for forbidden in (
            "sensor_configuration_state",
            "desired_config",
            "assigned_rollout_id",
            "subprocess",
            "download_url",
        ):
            self.assertNotIn(forbidden, STORE)


class SensorAgentReleaseApiTests(unittest.TestCase):
    def test_list_and_detail_are_viewer_routes(self) -> None:
        for function in (
            "get_sensor_agent_releases",
            "get_sensor_agent_release_view",
        ):
            prefix = MAIN.split(f"def {function}", 1)[0][-500:]
            self.assertIn("dependencies=[Depends(require_viewer)]", prefix)

    def test_create_update_publish_and_withdraw_require_admin_write(self) -> None:
        for function in (
            "post_sensor_agent_release",
            "put_sensor_agent_release",
            "post_sensor_agent_release_publish",
            "post_sensor_agent_release_withdraw",
        ):
            prefix = MAIN.split(f"def {function}", 1)[0][-550:]
            self.assertIn("dependencies=[Depends(require_administrator_write)]", prefix)

    def test_conflicts_are_http_409_and_missing_releases_are_404(self) -> None:
        self.assertGreaterEqual(MAIN.count("except AgentReleaseConflict as exc:"), 3)
        self.assertGreaterEqual(
            MAIN.count('status_code=404, detail="agent release not found"'),
            4,
        )
        self.assertIn("detail=\"agent release version already exists\"", MAIN)

    def test_listing_is_bounded_and_withdrawn_is_opt_in(self) -> None:
        body = MAIN.split("def get_sensor_agent_releases", 1)[1].split("@app.post", 1)[0]
        self.assertIn("include_withdrawn: bool = Query(default=False)", body)
        self.assertIn("limit: int = Query(default=100, ge=1, le=500)", body)
        self.assertIn("offset: int = Query(default=0, ge=0)", body)


class SensorAgentReleaseWebTests(unittest.TestCase):
    def test_fleet_console_has_a_release_catalog_tab(self) -> None:
        self.assertIn('data-fleet-tab="releases"', INDEX)
        self.assertIn('data-fleet-panel="releases"', INDEX)
        self.assertIn('id="agent-release-list"', INDEX)
        self.assertIn("Wydania agentów", INDEX)

    def test_form_separates_catalog_metadata_from_controlled_binary_upload(self) -> None:
        for field in (
            "agent-release-create-filename",
            "agent-release-create-sha256",
            "agent-release-create-size",
            "agent-release-create-protocol",
        ):
            self.assertIn(f'id="{field}"', INDEX)
        self.assertIn('id="agent-release-artifact-file" type="file"', INDEX)
        create_form = INDEX.split('id="agent-release-create-form"', 1)[1].split(
            "</form>", 1
        )[0]
        self.assertNotRegex(create_form, r'<input[^>]+type="file"')
        self.assertNotIn("download_url", INDEX + MAIN_JS)

    def test_create_update_and_lifecycle_are_separate_confirmed_writes(self) -> None:
        for function in (
            "createFleetAgentRelease",
            "updateFleetAgentRelease",
            "runFleetAgentReleaseAction",
        ):
            self.assertIn(f"async function {function}", MAIN_JS)
        lifecycle = MAIN_JS.split("async function runFleetAgentReleaseAction", 1)[1].split(
            "async function loadFleetConfigurationConsole", 1
        )[0]
        self.assertIn("window.confirm(prompt)", lifecycle)
        self.assertIn("expected_revision: release.revision", lifecycle)

    def test_published_metadata_is_read_only_in_the_ui(self) -> None:
        render = MAIN_JS.split("function renderFleetAgentReleases", 1)[1].split(
            "async function createFleetAgentRelease", 1
        )[0]
        self.assertIn('const editable = release.status === "draft";', render)
        self.assertIn("field.disabled = !editable", render)
        self.assertIn("agent-release-published", STYLES)

    def test_ui_and_documentation_state_the_safety_boundary(self) -> None:
        self.assertIn("nie uruchamia aktualizacji agentów", INDEX)
        self.assertIn("metadata-only", DOC)
        self.assertIn("does not modify", DOC)


if __name__ == "__main__":
    unittest.main()

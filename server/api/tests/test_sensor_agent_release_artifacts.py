from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app.agent_artifact_store import (
        AgentArtifactRejected,
        store_verified_agent_artifact,
    )


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (ROOT / "database/migrations/031_sensor_agent_release_artifacts.sql").read_text(
    encoding="utf-8"
)
STORE = (ROOT / "server/api/app/agent_release_store.py").read_text(encoding="utf-8")
ARTIFACT_STORE = (ROOT / "server/api/app/agent_artifact_store.py").read_text(
    encoding="utf-8"
)
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")
INDEX = (ROOT / "web/index.html").read_text(encoding="utf-8")
MAIN_JS = (ROOT / "web/src/main.js").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
NGINX = (ROOT / "web/nginx.conf").read_text(encoding="utf-8")
GATEWAY_NGINX = (ROOT / "gateway/nginx.conf").read_text(encoding="utf-8")
DOC = (ROOT / "docs/RDDS_STAGE28A.md").read_text(encoding="utf-8")


async def chunks(*values: bytes):
    for value in values:
        yield value


class AgentArtifactStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_matching_stream_is_atomically_stored_by_digest(self) -> None:
        payload = b"trusted agent artifact\n" * 4
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            stored = await store_verified_agent_artifact(
                chunks=chunks(payload[:9], payload[9:]),
                root_directory=directory,
                expected_sha256=digest,
                expected_size_bytes=len(payload),
            )
            path = Path(directory) / stored.storage_key
            self.assertEqual(payload, path.read_bytes())
            self.assertEqual(0o440, path.stat().st_mode & 0o777)
            self.assertTrue(stored.created)
            self.assertEqual([], list((Path(directory) / ".staging").iterdir()))

    async def test_hash_mismatch_is_rejected_and_temporary_file_removed(self) -> None:
        payload = b"tampered"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AgentArtifactRejected, "SHA-256"):
                await store_verified_agent_artifact(
                    chunks=chunks(payload),
                    root_directory=directory,
                    expected_sha256="0" * 64,
                    expected_size_bytes=len(payload),
                )
            self.assertEqual([], list((Path(directory) / ".staging").iterdir()))

    async def test_short_and_oversized_streams_are_rejected(self) -> None:
        payload = b"12345"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AgentArtifactRejected, "size mismatch"):
                await store_verified_agent_artifact(
                    chunks=chunks(payload[:-1]),
                    root_directory=directory,
                    expected_sha256=digest,
                    expected_size_bytes=len(payload),
                )
            with self.assertRaisesRegex(AgentArtifactRejected, "larger"):
                await store_verified_agent_artifact(
                    chunks=chunks(payload, b"6"),
                    root_directory=directory,
                    expected_sha256=digest,
                    expected_size_bytes=len(payload),
                )

    async def test_existing_identical_object_is_verified_and_reused(self) -> None:
        payload = b"same content"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            first = await store_verified_agent_artifact(
                chunks=chunks(payload),
                root_directory=directory,
                expected_sha256=digest,
                expected_size_bytes=len(payload),
            )
            second = await store_verified_agent_artifact(
                chunks=chunks(payload),
                root_directory=directory,
                expected_sha256=digest,
                expected_size_bytes=len(payload),
            )
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(first.storage_key, second.storage_key)

    async def test_storage_prefix_symlink_is_rejected(self) -> None:
        payload = b"safe"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            (Path(directory) / digest[:2]).symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(OSError, "unsafe directory"):
                await store_verified_agent_artifact(
                    chunks=chunks(payload),
                    root_directory=directory,
                    expected_sha256=digest,
                    expected_size_bytes=len(payload),
                )


class AgentArtifactMigrationAndStoreTests(unittest.TestCase):
    def test_migration_records_verified_identity_without_a_url_or_blob(self) -> None:
        self.assertIn("CREATE TABLE sensor_agent_release_artifacts", MIGRATION)
        self.assertIn("release_revision BIGINT", MIGRATION)
        self.assertIn("storage_key TEXT NOT NULL", MIGRATION)
        self.assertIn("verified_at TIMESTAMPTZ", MIGRATION)
        self.assertNotRegex(MIGRATION, r"(?i)download_url|artifact_data|bytea")

    def test_storage_key_is_content_addressed_and_user_filename_is_not_a_path(self) -> None:
        self.assertIn('f"{expected_sha256[:2]}/{expected_sha256}"', ARTIFACT_STORE)
        self.assertNotIn("artifact_filename", ARTIFACT_STORE)
        self.assertIn("tempfile.mkstemp", ARTIFACT_STORE)
        self.assertIn("os.replace", ARTIFACT_STORE)
        self.assertIn("os.fsync", ARTIFACT_STORE)

    def test_release_view_derives_missing_stale_or_verified_state(self) -> None:
        for state in ("missing", "stale", "verified"):
            self.assertIn(f"'{state}'", STORE)
        self.assertIn("LEFT JOIN sensor_agent_release_artifacts", STORE)
        self.assertIn("artifact.release_revision = release.revision - 1", STORE)
        self.assertIn("release.status = 'published'", STORE)

    def test_registration_rechecks_locked_catalog_metadata(self) -> None:
        body = STORE.split("def register_verified_sensor_agent_artifact", 1)[1].split(
            "def create_sensor_agent_release", 1
        )[0]
        self.assertIn("for_update=True", body)
        self.assertIn('release["revision"] != expected_revision', body)
        self.assertIn('release["artifact_sha256"] != artifact_sha256', body)
        self.assertIn("ON CONFLICT (release_id) DO UPDATE", body)

    def test_new_draft_requires_verified_artifact_before_publication(self) -> None:
        body = STORE.split("def publish_sensor_agent_release", 1)[1].split(
            "def withdraw_sensor_agent_release", 1
        )[0]
        self.assertIn('before["artifact_storage_status"] != "verified"', body)

    def test_successful_verification_is_audited(self) -> None:
        self.assertIn("sensor_agent_release_artifact_verified", MIGRATION)
        self.assertIn("'sensor_agent_release_artifact_verified'", STORE)


class AgentArtifactApiAndDeploymentTests(unittest.TestCase):
    def test_upload_is_an_administrator_only_octet_stream_route(self) -> None:
        body = MAIN.split("async def put_sensor_agent_release_artifact", 1)[1].split(
            "@app.post", 1
        )[0]
        prefix = MAIN.split("async def put_sensor_agent_release_artifact", 1)[0][-700:]
        self.assertIn('"/api/v1/sensor-agent-releases/{release_id}/artifact"', prefix)
        self.assertIn("Depends(require_administrator_write)", prefix)
        self.assertIn("application/octet-stream", body)
        self.assertIn("request.stream()", body)

    def test_upload_is_revisioned_and_content_length_is_checked_early(self) -> None:
        body = MAIN.split("async def put_sensor_agent_release_artifact", 1)[1].split(
            "@app.post", 1
        )[0]
        self.assertIn("expected_revision: int = Query(ge=1)", body)
        self.assertIn('request.headers.get("content-length")', body)
        self.assertIn('release["revision"] != expected_revision', body)

    def test_api_has_no_artifact_download_or_sensor_distribution_route(self) -> None:
        self.assertNotIn("StreamingResponse", MAIN)
        self.assertNotRegex(MAIN, r'@app\.get\([^)]*artifact')
        self.assertNotIn("desired_agent_artifact", MAIN)

    def test_compose_uses_a_dedicated_persistent_bind_mount(self) -> None:
        self.assertIn("RDDS_AGENT_ARTIFACT_PATH", COMPOSE)
        self.assertIn("RDDS_AGENT_ARTIFACT_PATH:-/opt/rdds/agent-artifacts", COMPOSE)
        self.assertIn("/var/lib/rdds/agent-artifacts", COMPOSE)
        self.assertIn("read_only: true", COMPOSE)
        self.assertIn("client_max_body_size 513m", NGINX)
        self.assertIn("proxy_request_buffering off", NGINX)
        self.assertIn("client_max_body_size 513m", GATEWAY_NGINX)
        self.assertIn("proxy_request_buffering off", GATEWAY_NGINX)


class AgentArtifactWebAndBoundaryTests(unittest.TestCase):
    def test_ui_has_a_separate_binary_verification_form(self) -> None:
        self.assertIn('id="agent-release-artifact-form"', INDEX)
        self.assertIn('id="agent-release-artifact-file" type="file"', INDEX)
        self.assertIn("async function adminBinaryRequest", MAIN_JS)
        self.assertIn("async function uploadFleetAgentReleaseArtifact", MAIN_JS)

    def test_ui_requires_filename_and_size_to_match_before_upload(self) -> None:
        upload = MAIN_JS.split("async function uploadFleetAgentReleaseArtifact", 1)[1].split(
            "async function runFleetAgentReleaseAction", 1
        )[0]
        self.assertIn("file.name !== release.artifact_filename", upload)
        self.assertIn("file.size !== release.artifact_size_bytes", upload)
        self.assertIn("window.confirm", upload)

    def test_stage_does_not_distribute_or_install_artifacts(self) -> None:
        self.assertIn("no sensor download endpoint", DOC)
        self.assertIn("does not install", DOC)
        self.assertNotIn("subprocess", ARTIFACT_STORE + STORE + MAIN)


if __name__ == "__main__":
    unittest.main()

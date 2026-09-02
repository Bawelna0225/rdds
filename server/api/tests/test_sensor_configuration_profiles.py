from __future__ import annotations

import os
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
        SensorConfigurationProfileCreate,
        SensorConfigurationProfileUpdate,
        SensorConfigurationProfileVersionCreate,
    )


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT / "database/migrations/022_sensor_configuration_profiles.sql"
).read_text(encoding="utf-8")
STORE = (
    ROOT / "server/api/app/configuration_profile_store.py"
).read_text(encoding="utf-8")
MAIN = (ROOT / "server/api/app/main.py").read_text(encoding="utf-8")

MANAGED = {
    "heartbeat_seconds": 10.0,
    "reconnect_seconds": 3.0,
    "request_timeout_seconds": 5.0,
    "replay_messages_per_second": 2.0,
}


class ConfigurationProfileModelTests(unittest.TestCase):
    def test_create_profile_normalizes_operator_text(self) -> None:
        profile = SensorConfigurationProfileCreate(
            profile_key="standard",
            display_name="  Standardowy  ",
            description="  Profil podstawowy  ",
            configuration=MANAGED,
            change_note="  Pierwsza wersja  ",
        )
        self.assertEqual(profile.display_name, "Standardowy")
        self.assertEqual(profile.description, "Profil podstawowy")
        self.assertEqual(profile.change_note, "Pierwsza wersja")

    def test_profile_key_is_strict_and_lowercase(self) -> None:
        with self.assertRaises(ValidationError):
            SensorConfigurationProfileCreate(
                profile_key="Standard",
                display_name="Standardowy",
                configuration=MANAGED,
                change_note="Pierwsza wersja",
            )

    def test_profile_reuses_managed_configuration_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            SensorConfigurationProfileVersionCreate(
                configuration={**MANAGED, "heartbeat_seconds": 1},
                change_note="Nieprawidłowa wersja",
            )

    def test_metadata_update_is_strict(self) -> None:
        updated = SensorConfigurationProfileUpdate(
            display_name="  Tryb terenowy ",
            description=" ",
            enabled=False,
        )
        self.assertEqual(updated.display_name, "Tryb terenowy")
        self.assertIsNone(updated.description)
        with self.assertRaises(ValidationError):
            SensorConfigurationProfileUpdate(
                display_name="Tryb terenowy",
                enabled=True,
                configuration=MANAGED,
            )


class ConfigurationProfileMigrationTests(unittest.TestCase):
    def test_profile_and_immutable_version_tables_are_separate(self) -> None:
        self.assertIn("CREATE TABLE sensor_configuration_profiles", MIGRATION)
        self.assertIn("CREATE TABLE sensor_configuration_profile_versions", MIGRATION)
        self.assertIn("UNIQUE (profile_id, version)", MIGRATION)

    def test_current_version_reference_is_deferred_and_exact(self) -> None:
        self.assertIn("FOREIGN KEY (id, current_version)", MIGRATION)
        self.assertIn(
            "REFERENCES sensor_configuration_profile_versions(profile_id, version)",
            MIGRATION,
        )
        self.assertIn("DEFERRABLE INITIALLY DEFERRED", MIGRATION)

    def test_profile_audit_events_are_allow_listed(self) -> None:
        for event_type in (
            "sensor_configuration_profile_created",
            "sensor_configuration_profile_updated",
            "sensor_configuration_profile_version_created",
        ):
            self.assertIn(f"'{event_type}'", MIGRATION)


class ConfigurationProfileStoreBoundaryTests(unittest.TestCase):
    def test_version_creation_serializes_on_profile_row(self) -> None:
        self.assertIn("SELECT profile_key, current_version", STORE)
        self.assertIn("FOR UPDATE", STORE)
        self.assertIn('next_version = int(profile["current_version"]) + 1', STORE)

    def test_version_history_is_never_updated(self) -> None:
        self.assertNotIn("UPDATE sensor_configuration_profile_versions", STORE)
        self.assertNotIn("sensor_configuration_state", STORE)

    def test_audit_json_parameters_have_explicit_postgresql_types(self) -> None:
        for marker in (
            "%(profile_id)s::uuid",
            "%(profile_key)s::text",
            "%(change_note)s::text",
            "%(old_description)s::text",
            "%(description)s::text",
            "%(enabled)s::boolean",
            "%(previous_version)s::bigint",
            "%(version)s::bigint",
        ):
            self.assertIn(marker, STORE)

    def test_api_exposes_read_and_csrf_protected_write_routes(self) -> None:
        self.assertIn('"/api/v1/sensor-configuration-profiles"', MAIN)
        self.assertIn(
            '"/api/v1/sensor-configuration-profiles/{profile_id}/versions"',
            MAIN,
        )
        self.assertGreaterEqual(MAIN.count("Depends(require_viewer)"), 2)
        self.assertGreaterEqual(
            MAIN.count("Depends(require_administrator_write)"),
            3,
        )


if __name__ == "__main__":
    unittest.main()

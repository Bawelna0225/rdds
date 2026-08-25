import os
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import config, main, operations_store


class FakeCursor:
    def __init__(
        self,
        database_size_bytes: int,
        tables: list[dict[str, object]] | None = None,
    ) -> None:
        self.database_size_bytes = database_size_bytes
        self.tables = tables or []
        self.queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> None:
        self.queries.append(query)

    def fetchone(self) -> dict[str, object]:
        return {
            "database_name": "rdds",
            "database_size_bytes": self.database_size_bytes,
        }

    def fetchall(self) -> list[dict[str, object]]:
        return self.tables


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


def fake_settings(capacity_gb: float) -> SimpleNamespace:
    return SimpleNamespace(
        database_capacity_gb=capacity_gb,
        database_warning_percent=70.0,
        database_critical_percent=85.0,
    )


class DatabaseStorageTests(unittest.TestCase):
    def test_configured_budget_returns_percentage_and_largest_tables(self) -> None:
        gibibyte = 1024**3
        cursor = FakeCursor(
            database_size_bytes=8 * gibibyte,
            tables=[
                {
                    "schemaname": "public",
                    "table_name": "observations",
                    "size_bytes": 6 * gibibyte,
                    "estimated_rows": 125000,
                }
            ],
        )

        @contextmanager
        def fake_connection():
            yield FakeConnection(cursor)

        with (
            patch.object(operations_store, "connection", fake_connection),
            patch.object(operations_store, "settings", fake_settings(10)),
        ):
            storage = operations_store.get_database_storage()

        self.assertEqual("rdds", storage["database_name"])
        self.assertEqual(10 * gibibyte, storage["capacity_bytes"])
        self.assertEqual(80.0, storage["used_percent"])
        self.assertEqual("warning", storage["status"])
        self.assertEqual("observations", storage["largest_tables"][0]["table_name"])
        self.assertIn("pg_database_size", cursor.queries[0])
        self.assertIn("pg_total_relation_size", cursor.queries[1])

    def test_zero_budget_reports_size_without_percentage(self) -> None:
        cursor = FakeCursor(database_size_bytes=512 * 1024**2)

        @contextmanager
        def fake_connection():
            yield FakeConnection(cursor)

        with (
            patch.object(operations_store, "connection", fake_connection),
            patch.object(operations_store, "settings", fake_settings(0)),
        ):
            storage = operations_store.get_database_storage()

        self.assertIsNone(storage["capacity_bytes"])
        self.assertIsNone(storage["used_percent"])
        self.assertEqual("unconfigured", storage["status"])


class StorageConfigurationTests(unittest.TestCase):
    def test_threshold_order_is_validated(self) -> None:
        environment = {
            **REQUIRED_ENVIRONMENT,
            "RDDS_DATABASE_CAPACITY_GB": "20",
            "RDDS_DATABASE_WARNING_PERCENT": "90",
            "RDDS_DATABASE_CRITICAL_PERCENT": "80",
        }
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(RuntimeError, "warning < critical"):
                config.load_settings()


class StorageRouteTests(unittest.TestCase):
    def test_storage_endpoint_requires_administrator_dependency(self) -> None:
        route = next(
            route
            for route in main.app.routes
            if getattr(route, "path", None) == "/api/v1/system/storage"
        )
        dependency_calls = {
            dependency.call for dependency in route.dependant.dependencies
        }

        self.assertIn(main.require_administrator, dependency_calls)


if __name__ == "__main__":
    unittest.main()

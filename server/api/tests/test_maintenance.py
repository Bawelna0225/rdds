import os
import unittest
from unittest.mock import patch

REQUIRED_ENVIRONMENT = {
    "RDDS_DB_HOST": "database",
    "RDDS_DB_NAME": "rdds",
    "RDDS_DB_USER": "rdds",
    "RDDS_DB_PASSWORD": "test-only",
    "RDDS_INGEST_TOKEN": "test-only",
}

with patch.dict(os.environ, REQUIRED_ENVIRONMENT, clear=False):
    from app import maintenance


class FakeCursor:
    def __init__(self, rowcounts: list[int]) -> None:
        self._rowcounts = iter(rowcounts)
        self.rowcount = 0
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> None:
        self.executions.append((query, parameters))
        self.rowcount = next(self._rowcounts)


class MaintenanceBatchTests(unittest.TestCase):
    def test_delete_stops_after_short_batch(self) -> None:
        cursor = FakeCursor([maintenance.settings.retention_batch_size, 7])

        deleted = maintenance._delete_in_batches(
            cursor,
            table="observations",
            id_column="id",
            predicate="received_at < NOW() - make_interval(days => %s)",
            parameters=(90,),
        )

        self.assertEqual(maintenance.settings.retention_batch_size + 7, deleted)
        self.assertEqual(2, len(cursor.executions))
        self.assertEqual(
            (90, maintenance.settings.retention_batch_size),
            cursor.executions[0][1],
        )

    def test_delete_does_not_interpolate_parameters(self) -> None:
        cursor = FakeCursor([0])

        maintenance._delete_in_batches(
            cursor,
            table="sensor_heartbeats",
            id_column="id",
            predicate="received_at < NOW() - make_interval(days => %s)",
            parameters=(30,),
        )

        query, parameters = cursor.executions[0]
        self.assertIn("make_interval(days => %s)", query)
        self.assertEqual((30, maintenance.settings.retention_batch_size), parameters)


if __name__ == "__main__":
    unittest.main()

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
    from app import auth_store, main, security_store


class FakeCursor:
    def __init__(
        self,
        fetchone_rows: list[dict[str, object] | None] | None = None,
        fetchall_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.queries: list[str] = []
        self.parameters: list[object] = []
        self._fetchone_rows = iter(fetchone_rows or [])
        self._fetchall_rows = fetchall_rows or []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, parameters: object = None) -> None:
        self.queries.append(query)
        self.parameters.append(parameters)

    def fetchone(self):
        return next(self._fetchone_rows)

    def fetchall(self) -> list[dict[str, object]]:
        return self._fetchall_rows


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


def fake_connection_for(cursor: FakeCursor):
    @contextmanager
    def fake_connection():
        yield FakeConnection(cursor)

    return fake_connection


class LoginSecurityEventTests(unittest.TestCase):
    def test_unknown_account_is_logged_without_password_or_token(self) -> None:
        cursor = FakeCursor(fetchone_rows=[None])
        with (
            patch.object(auth_store, "connection", fake_connection_for(cursor)),
            patch.object(auth_store, "verify_password", return_value=False),
        ):
            result = auth_store.authenticate_login(
                username="missing-user",
                password="never-log-this-password",
                user_agent="Test Browser",
                remote_address="192.0.2.10",
            )

        self.assertIsNone(result)
        security_query_index = next(
            index
            for index, query in enumerate(cursor.queries)
            if "INSERT INTO operator_security_events" in query
        )
        event_parameters = cursor.parameters[security_query_index]
        self.assertIn("missing-user", event_parameters)
        self.assertNotIn("never-log-this-password", event_parameters)
        self.assertTrue(all("never-log-this-password" not in query for query in cursor.queries))


class SecurityEventFilterTests(unittest.TestCase):
    def test_username_filter_is_parameterized_and_escapes_wildcards(self) -> None:
        cursor = FakeCursor(fetchone_rows=[{"total": 0}])
        with patch.object(
            security_store,
            "connection",
            fake_connection_for(cursor),
        ):
            events, total = security_store.list_security_events(username="adm%_in")

        self.assertEqual([], events)
        self.assertEqual(0, total)
        for query in cursor.queries:
            self.assertIn("ILIKE %(username)s", query)
            self.assertNotIn("adm%_in", query)
        for parameters in cursor.parameters:
            self.assertEqual("%adm\\%\\_in%", parameters["username"])

    def test_failure_threshold_activates_administrator_warning(self) -> None:
        cursor = FakeCursor(
            fetchone_rows=[
                {
                    "active_sessions": 3,
                    "recent_failures": 5,
                    "affected_usernames": 2,
                    "source_addresses": 2,
                    "locked_accounts": 1,
                }
            ]
        )
        fake_settings = SimpleNamespace(
            security_failure_window_minutes=15,
            security_failure_alert_count=5,
        )
        with (
            patch.object(security_store, "connection", fake_connection_for(cursor)),
            patch.object(security_store, "settings", fake_settings),
        ):
            summary = security_store.get_security_summary()

        self.assertTrue(summary["alert_active"])
        self.assertEqual(15, summary["failure_window_minutes"])
        self.assertEqual(5, summary["failure_alert_count"])


class SecurityRouteTests(unittest.TestCase):
    def test_read_routes_require_administrator(self) -> None:
        for path in (
            "/api/v1/security/summary",
            "/api/v1/security/sessions",
            "/api/v1/security/events",
            "/api/v1/security/export",
        ):
            with self.subTest(path=path):
                route = next(
                    route
                    for route in main.app.routes
                    if getattr(route, "path", None) == path
                )
                dependency_calls = {
                    dependency.call for dependency in route.dependant.dependencies
                }
                self.assertIn(main.require_administrator, dependency_calls)

    def test_revocation_routes_require_administrator_write(self) -> None:
        for path in (
            "/api/v1/security/sessions/{session_id}",
            "/api/v1/security/operators/{operator_id}/sessions/revoke",
        ):
            with self.subTest(path=path):
                route = next(
                    route
                    for route in main.app.routes
                    if getattr(route, "path", None) == path
                )
                dependency_calls = {
                    dependency.call for dependency in route.dependant.dependencies
                }
                self.assertIn(main.require_administrator_write, dependency_calls)


if __name__ == "__main__":
    unittest.main()

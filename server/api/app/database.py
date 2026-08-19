from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from app.config import settings


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
        connect_timeout=3,
        application_name="rdds-api",
        autocommit=True,
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        conn.close()


def readiness() -> dict[str, str]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_database() AS database,
                current_user AS database_user,
                postgis_version() AS postgis_version
            """
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Database readiness query returned no row")
    return dict(row)


def system_summary() -> dict[str, int]:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM sensors) AS sensors,
                (SELECT COUNT(*) FROM observations) AS observations,
                (SELECT COUNT(*) FROM tracks) AS tracks
            """
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("System summary query returned no row")
    return {key: int(value) for key, value in row.items()}

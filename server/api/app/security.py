import secrets
from dataclasses import dataclass
from typing import Literal

import psycopg
from fastapi import Header, HTTPException, status

from app.config import settings
from app.sensor_store import authenticate_sensor_token, legacy_sensor_access


@dataclass(frozen=True)
class IngestPrincipal:
    mode: Literal["legacy", "sensor"]
    sensor_key: str | None = None


def require_ingest_token(
    x_rdds_ingest_token: str | None = Header(default=None),
) -> IngestPrincipal:
    if x_rdds_ingest_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid sensor ingest token",
        )

    if secrets.compare_digest(x_rdds_ingest_token, settings.ingest_token):
        if not settings.allow_legacy_ingest:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="legacy sensor ingest is disabled",
            )
        return IngestPrincipal(mode="legacy")

    try:
        sensor = authenticate_sensor_token(x_rdds_ingest_token)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sensor authentication unavailable",
        ) from exc

    if sensor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid sensor ingest token",
        )
    if sensor["status"] == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="sensor is disabled",
        )
    return IngestPrincipal(mode="sensor", sensor_key=sensor["sensor_key"])


def authorize_sensor_identity(
    principal: IngestPrincipal,
    sensor_key: str,
) -> None:
    if principal.mode == "sensor":
        if principal.sensor_key is None or not secrets.compare_digest(
            principal.sensor_key,
            sensor_key,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="sensor token does not match payload sensor_id",
            )
        return

    try:
        access = legacy_sensor_access(sensor_key)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sensor authorization unavailable",
        ) from exc

    if access == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="sensor is disabled",
        )
    if access == "individual_required":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="sensor requires its individual ingest token",
        )


def require_admin_token(
    x_rdds_admin_token: str | None = Header(default=None),
) -> None:
    if x_rdds_admin_token is None or not secrets.compare_digest(
        x_rdds_admin_token,
        settings.admin_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid RDDS administrator token",
        )

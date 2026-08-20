import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import Cookie, Depends, Header, HTTPException, status

from app.auth_store import read_session
from app.config import settings
from app.sensor_store import authenticate_sensor_token, legacy_sensor_access

SESSION_COOKIE_NAME = "rdds_session"
OperatorRole = Literal["viewer", "operator", "administrator"]
ROLE_RANK = {"viewer": 0, "operator": 1, "administrator": 2}


@dataclass(frozen=True)
class IngestPrincipal:
    mode: Literal["legacy", "sensor"]
    sensor_key: str | None = None


@dataclass(frozen=True)
class OperatorPrincipal:
    id: UUID
    session_id: UUID
    username: str
    display_name: str
    role: OperatorRole
    enabled: bool
    must_change_password: bool
    csrf_token: str
    expires_at: datetime

    @property
    def actor(self) -> str:
        return self.username


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


def require_operator_session(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> OperatorPrincipal:
    if session_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    try:
        account = read_session(session_token)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator authentication unavailable",
        ) from exc
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session is invalid or expired",
        )
    return OperatorPrincipal(
        id=account["id"],
        session_id=account["session_id"],
        username=account["username"],
        display_name=account["display_name"],
        role=account["role"],
        enabled=account["enabled"],
        must_change_password=account["must_change_password"],
        csrf_token=account["csrf_token"],
        expires_at=account["expires_at"],
    )


def require_csrf(
    principal: OperatorPrincipal = Depends(require_operator_session),
    x_rdds_csrf_token: str | None = Header(default=None),
) -> OperatorPrincipal:
    if x_rdds_csrf_token is None or not secrets.compare_digest(
        x_rdds_csrf_token,
        principal.csrf_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid CSRF token",
        )
    return principal


def require_role(
    minimum_role: OperatorRole,
    *,
    csrf: bool = False,
) -> Callable[..., OperatorPrincipal]:
    dependency = require_csrf if csrf else require_operator_session

    def check_role(
        principal: OperatorPrincipal = Depends(dependency),
    ) -> OperatorPrincipal:
        if principal.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="password change required",
            )
        if ROLE_RANK[principal.role] < ROLE_RANK[minimum_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{minimum_role} role required",
            )
        return principal

    return check_role


require_viewer = require_role("viewer")
require_operator_write = require_role("operator", csrf=True)
require_administrator = require_role("administrator")
require_administrator_write = require_role("administrator", csrf=True)

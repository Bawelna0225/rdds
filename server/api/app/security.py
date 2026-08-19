import secrets

from fastapi import Header, HTTPException, status

from app.config import settings


def require_ingest_token(
    x_rdds_ingest_token: str | None = Header(default=None),
) -> None:
    if x_rdds_ingest_token is None or not secrets.compare_digest(
        x_rdds_ingest_token,
        settings.ingest_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid sensor ingest token",
        )

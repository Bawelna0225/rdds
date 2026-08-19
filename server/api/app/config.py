import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    environment: str
    log_level: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    ingest_token: str
    admin_token: str
    allow_legacy_ingest: bool
    sensor_offline_after_seconds: int
    track_poll_seconds: float
    track_stale_after_seconds: int
    track_ended_after_seconds: int
    track_batch_size: int
    alert_poll_seconds: float


def load_settings() -> Settings:
    settings = Settings(
        environment=os.getenv("RDDS_ENVIRONMENT", "development"),
        log_level=os.getenv("RDDS_LOG_LEVEL", "INFO").upper(),
        db_host=_required("RDDS_DB_HOST"),
        db_port=int(os.getenv("RDDS_DB_PORT", "5432")),
        db_name=_required("RDDS_DB_NAME"),
        db_user=_required("RDDS_DB_USER"),
        db_password=_required("RDDS_DB_PASSWORD"),
        ingest_token=_required("RDDS_INGEST_TOKEN"),
        admin_token=_required("RDDS_ADMIN_TOKEN"),
        allow_legacy_ingest=_boolean("RDDS_ALLOW_LEGACY_INGEST", True),
        sensor_offline_after_seconds=int(
            os.getenv("RDDS_SENSOR_OFFLINE_AFTER_SECONDS", "30")
        ),
        track_poll_seconds=float(os.getenv("RDDS_TRACK_POLL_SECONDS", "1")),
        track_stale_after_seconds=int(
            os.getenv("RDDS_TRACK_STALE_AFTER_SECONDS", "15")
        ),
        track_ended_after_seconds=int(
            os.getenv("RDDS_TRACK_ENDED_AFTER_SECONDS", "60")
        ),
        track_batch_size=int(os.getenv("RDDS_TRACK_BATCH_SIZE", "500")),
        alert_poll_seconds=float(os.getenv("RDDS_ALERT_POLL_SECONDS", "1")),
    )

    if settings.track_poll_seconds <= 0:
        raise RuntimeError("RDDS_TRACK_POLL_SECONDS must be greater than zero")
    if settings.track_stale_after_seconds <= 0:
        raise RuntimeError("RDDS_TRACK_STALE_AFTER_SECONDS must be greater than zero")
    if settings.track_ended_after_seconds <= settings.track_stale_after_seconds:
        raise RuntimeError(
            "RDDS_TRACK_ENDED_AFTER_SECONDS must be greater than "
            "RDDS_TRACK_STALE_AFTER_SECONDS"
        )
    if not 1 <= settings.track_batch_size <= 5000:
        raise RuntimeError("RDDS_TRACK_BATCH_SIZE must be between 1 and 5000")
    if settings.alert_poll_seconds <= 0:
        raise RuntimeError("RDDS_ALERT_POLL_SECONDS must be greater than zero")
    if len(settings.admin_token) < 32:
        raise RuntimeError("RDDS_ADMIN_TOKEN must contain at least 32 characters")
    if settings.admin_token == settings.ingest_token:
        raise RuntimeError("RDDS_ADMIN_TOKEN must differ from RDDS_INGEST_TOKEN")

    return settings


settings = load_settings()

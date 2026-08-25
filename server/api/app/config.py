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
    allow_legacy_ingest: bool
    session_cookie_secure: bool
    session_absolute_seconds: int
    session_idle_seconds: int
    login_max_failures: int
    login_lock_seconds: int
    sensor_offline_after_seconds: int
    track_poll_seconds: float
    track_stale_after_seconds: int
    track_ended_after_seconds: int
    track_batch_size: int
    alert_poll_seconds: float
    retention_enabled: bool
    maintenance_interval_seconds: int
    retention_batch_size: int
    retention_sessions_days: int
    retention_heartbeats_days: int
    retention_observations_days: int
    retention_audit_days: int
    retention_alerts_days: int
    retention_tracks_days: int


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
        allow_legacy_ingest=_boolean("RDDS_ALLOW_LEGACY_INGEST", True),
        session_cookie_secure=_boolean("RDDS_SESSION_COOKIE_SECURE", False),
        session_absolute_seconds=int(
            os.getenv("RDDS_SESSION_ABSOLUTE_SECONDS", "28800")
        ),
        session_idle_seconds=int(os.getenv("RDDS_SESSION_IDLE_SECONDS", "1800")),
        login_max_failures=int(os.getenv("RDDS_LOGIN_MAX_FAILURES", "5")),
        login_lock_seconds=int(os.getenv("RDDS_LOGIN_LOCK_SECONDS", "900")),
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
        retention_enabled=_boolean("RDDS_RETENTION_ENABLED", False),
        maintenance_interval_seconds=int(
            os.getenv("RDDS_MAINTENANCE_INTERVAL_SECONDS", "86400")
        ),
        retention_batch_size=int(
            os.getenv("RDDS_RETENTION_BATCH_SIZE", "10000")
        ),
        retention_sessions_days=int(
            os.getenv("RDDS_RETENTION_SESSIONS_DAYS", "30")
        ),
        retention_heartbeats_days=int(
            os.getenv("RDDS_RETENTION_HEARTBEATS_DAYS", "30")
        ),
        retention_observations_days=int(
            os.getenv("RDDS_RETENTION_OBSERVATIONS_DAYS", "90")
        ),
        retention_audit_days=int(
            os.getenv("RDDS_RETENTION_AUDIT_DAYS", "365")
        ),
        retention_alerts_days=int(
            os.getenv("RDDS_RETENTION_ALERTS_DAYS", "365")
        ),
        retention_tracks_days=int(
            os.getenv("RDDS_RETENTION_TRACKS_DAYS", "365")
        ),
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
    if settings.session_idle_seconds < 60:
        raise RuntimeError("RDDS_SESSION_IDLE_SECONDS must be at least 60")
    if settings.session_absolute_seconds < settings.session_idle_seconds:
        raise RuntimeError(
            "RDDS_SESSION_ABSOLUTE_SECONDS must be at least RDDS_SESSION_IDLE_SECONDS"
        )
    if not 3 <= settings.login_max_failures <= 20:
        raise RuntimeError("RDDS_LOGIN_MAX_FAILURES must be between 3 and 20")
    if settings.login_lock_seconds < 60:
        raise RuntimeError("RDDS_LOGIN_LOCK_SECONDS must be at least 60")
    if settings.maintenance_interval_seconds < 300:
        raise RuntimeError(
            "RDDS_MAINTENANCE_INTERVAL_SECONDS must be at least 300"
        )
    if not 100 <= settings.retention_batch_size <= 100000:
        raise RuntimeError("RDDS_RETENTION_BATCH_SIZE must be between 100 and 100000")
    retention_periods = {
        "RDDS_RETENTION_SESSIONS_DAYS": settings.retention_sessions_days,
        "RDDS_RETENTION_HEARTBEATS_DAYS": settings.retention_heartbeats_days,
        "RDDS_RETENTION_OBSERVATIONS_DAYS": settings.retention_observations_days,
        "RDDS_RETENTION_AUDIT_DAYS": settings.retention_audit_days,
        "RDDS_RETENTION_ALERTS_DAYS": settings.retention_alerts_days,
        "RDDS_RETENTION_TRACKS_DAYS": settings.retention_tracks_days,
    }
    for name, days in retention_periods.items():
        if not 1 <= days <= 36500:
            raise RuntimeError(f"{name} must be between 1 and 36500")

    return settings


settings = load_settings()

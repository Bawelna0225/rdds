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
    security_failure_window_minutes: int
    security_failure_alert_count: int
    sensor_offline_after_seconds: int
    sensor_queue_warning_messages: int
    sensor_source_silent_after_seconds: int
    sensor_quality_window_seconds: int
    sensor_quality_min_window_seconds: int
    sensor_quality_min_input_lines: int
    sensor_quality_max_ignored_percent: float
    sensor_reconnect_warning_count: int
    track_poll_seconds: float
    track_stale_after_seconds: int
    track_ended_after_seconds: int
    track_batch_size: int
    alert_poll_seconds: float
    retention_enabled: bool
    maintenance_interval_seconds: int
    retention_batch_size: int
    retention_sessions_days: int
    retention_security_events_days: int
    retention_heartbeats_days: int
    retention_observations_days: int
    retention_audit_days: int
    retention_alerts_days: int
    retention_tracks_days: int
    database_capacity_gb: float
    database_warning_percent: float
    database_critical_percent: float


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
        security_failure_window_minutes=int(
            os.getenv("RDDS_SECURITY_FAILURE_WINDOW_MINUTES", "15")
        ),
        security_failure_alert_count=int(
            os.getenv("RDDS_SECURITY_FAILURE_ALERT_COUNT", "5")
        ),
        sensor_offline_after_seconds=int(
            os.getenv("RDDS_SENSOR_OFFLINE_AFTER_SECONDS", "30")
        ),
        sensor_queue_warning_messages=int(
            os.getenv("RDDS_SENSOR_QUEUE_WARNING_MESSAGES", "100")
        ),
        sensor_source_silent_after_seconds=int(
            os.getenv("RDDS_SENSOR_SOURCE_SILENT_AFTER_SECONDS", "90")
        ),
        sensor_quality_window_seconds=int(
            os.getenv("RDDS_SENSOR_QUALITY_WINDOW_SECONDS", "60")
        ),
        sensor_quality_min_window_seconds=int(
            os.getenv("RDDS_SENSOR_QUALITY_MIN_WINDOW_SECONDS", "30")
        ),
        sensor_quality_min_input_lines=int(
            os.getenv("RDDS_SENSOR_QUALITY_MIN_INPUT_LINES", "20")
        ),
        sensor_quality_max_ignored_percent=float(
            os.getenv("RDDS_SENSOR_QUALITY_MAX_IGNORED_PERCENT", "80")
        ),
        sensor_reconnect_warning_count=int(
            os.getenv("RDDS_SENSOR_RECONNECT_WARNING_COUNT", "3")
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
        retention_security_events_days=int(
            os.getenv("RDDS_RETENTION_SECURITY_EVENTS_DAYS", "180")
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
        database_capacity_gb=float(
            os.getenv("RDDS_DATABASE_CAPACITY_GB", "0")
        ),
        database_warning_percent=float(
            os.getenv("RDDS_DATABASE_WARNING_PERCENT", "70")
        ),
        database_critical_percent=float(
            os.getenv("RDDS_DATABASE_CRITICAL_PERCENT", "85")
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
    if not 1 <= settings.security_failure_window_minutes <= 1440:
        raise RuntimeError(
            "RDDS_SECURITY_FAILURE_WINDOW_MINUTES must be between 1 and 1440"
        )
    if not 1 <= settings.security_failure_alert_count <= 10000:
        raise RuntimeError(
            "RDDS_SECURITY_FAILURE_ALERT_COUNT must be between 1 and 10000"
        )
    if settings.sensor_offline_after_seconds < 10:
        raise RuntimeError(
            "RDDS_SENSOR_OFFLINE_AFTER_SECONDS must be at least 10"
        )
    if not 1 <= settings.sensor_queue_warning_messages <= 1000000:
        raise RuntimeError(
            "RDDS_SENSOR_QUEUE_WARNING_MESSAGES must be between 1 and 1000000"
        )
    if not 30 <= settings.sensor_source_silent_after_seconds <= 3600:
        raise RuntimeError(
            "RDDS_SENSOR_SOURCE_SILENT_AFTER_SECONDS must be between 30 and 3600"
        )
    if not 30 <= settings.sensor_quality_window_seconds <= 3600:
        raise RuntimeError(
            "RDDS_SENSOR_QUALITY_WINDOW_SECONDS must be between 30 and 3600"
        )
    if not (
        10
        <= settings.sensor_quality_min_window_seconds
        <= settings.sensor_quality_window_seconds
    ):
        raise RuntimeError(
            "RDDS_SENSOR_QUALITY_MIN_WINDOW_SECONDS must be between 10 and "
            "RDDS_SENSOR_QUALITY_WINDOW_SECONDS"
        )
    if not 1 <= settings.sensor_quality_min_input_lines <= 1000000:
        raise RuntimeError(
            "RDDS_SENSOR_QUALITY_MIN_INPUT_LINES must be between 1 and 1000000"
        )
    if not 0 < settings.sensor_quality_max_ignored_percent <= 100:
        raise RuntimeError(
            "RDDS_SENSOR_QUALITY_MAX_IGNORED_PERCENT must be greater than 0 "
            "and at most 100"
        )
    if not 1 <= settings.sensor_reconnect_warning_count <= 10000:
        raise RuntimeError(
            "RDDS_SENSOR_RECONNECT_WARNING_COUNT must be between 1 and 10000"
        )
    if settings.maintenance_interval_seconds < 300:
        raise RuntimeError(
            "RDDS_MAINTENANCE_INTERVAL_SECONDS must be at least 300"
        )
    if not 100 <= settings.retention_batch_size <= 100000:
        raise RuntimeError("RDDS_RETENTION_BATCH_SIZE must be between 100 and 100000")
    retention_periods = {
        "RDDS_RETENTION_SESSIONS_DAYS": settings.retention_sessions_days,
        "RDDS_RETENTION_SECURITY_EVENTS_DAYS": (
            settings.retention_security_events_days
        ),
        "RDDS_RETENTION_HEARTBEATS_DAYS": settings.retention_heartbeats_days,
        "RDDS_RETENTION_OBSERVATIONS_DAYS": settings.retention_observations_days,
        "RDDS_RETENTION_AUDIT_DAYS": settings.retention_audit_days,
        "RDDS_RETENTION_ALERTS_DAYS": settings.retention_alerts_days,
        "RDDS_RETENTION_TRACKS_DAYS": settings.retention_tracks_days,
    }
    for name, days in retention_periods.items():
        if not 1 <= days <= 36500:
            raise RuntimeError(f"{name} must be between 1 and 36500")
    if not 0 <= settings.database_capacity_gb <= 1000000:
        raise RuntimeError(
            "RDDS_DATABASE_CAPACITY_GB must be between 0 and 1000000"
        )
    if not (
        0 < settings.database_warning_percent
        < settings.database_critical_percent
        <= 100
    ):
        raise RuntimeError(
            "RDDS database warning and critical percentages must satisfy "
            "0 < warning < critical <= 100"
        )

    return settings


settings = load_settings()

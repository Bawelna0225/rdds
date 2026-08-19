from dataclasses import dataclass
import os


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    environment: str
    log_level: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str


def load_settings() -> Settings:
    return Settings(
        environment=os.getenv("RDDS_ENVIRONMENT", "development"),
        log_level=os.getenv("RDDS_LOG_LEVEL", "INFO").upper(),
        db_host=_required("RDDS_DB_HOST"),
        db_port=int(os.getenv("RDDS_DB_PORT", "5432")),
        db_name=_required("RDDS_DB_NAME"),
        db_user=_required("RDDS_DB_USER"),
        db_password=_required("RDDS_DB_PASSWORD"),
    )


settings = load_settings()

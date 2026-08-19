from datetime import datetime, timezone
import logging

from fastapi import FastAPI, HTTPException
import psycopg

from app.config import settings
from app.database import readiness, system_summary


logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("rdds.api")

app = FastAPI(
    title="RDDS API",
    description="Standalone Remote Drone Detection System API",
    version="0.1.0",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/", tags=["service"])
def root() -> dict[str, str]:
    return {
        "service": "rdds-api",
        "version": app.version,
        "environment": settings.environment,
        "documentation": "/docs",
    }


@app.get("/api/v1/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "rdds-api",
        "time": utc_now(),
    }


@app.get("/api/v1/health/ready", tags=["health"])
def health_ready() -> dict[str, object]:
    try:
        database = readiness()
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "status": "ready",
        "service": "rdds-api",
        "time": utc_now(),
        "database": database,
    }


@app.get("/api/v1/system/summary", tags=["system"])
def get_system_summary() -> dict[str, object]:
    try:
        counts = system_summary()
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("System summary query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "counts": counts,
    }

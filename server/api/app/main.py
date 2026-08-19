import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, status

from app.config import settings
from app.database import (
    insert_heartbeat,
    insert_observation,
    list_sensors,
    mark_stale_sensors,
    readiness,
    system_summary,
)
from app.models import HeartbeatEnvelope, IngestResult, ObservationEnvelope
from app.security import require_ingest_token
from app.track_store import get_track_history, list_tracks

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("rdds.api")


async def sensor_status_monitor() -> None:
    interval = max(5, min(settings.sensor_offline_after_seconds // 2, 30))
    while True:
        await asyncio.sleep(interval)
        try:
            changed = await asyncio.to_thread(mark_stale_sensors)
            if changed:
                logger.info("Marked %s sensor(s) offline", changed)
        except psycopg.Error:
            logger.exception("Sensor status monitor could not reach the database")


@asynccontextmanager
async def lifespan(_: FastAPI):
    monitor = asyncio.create_task(sensor_status_monitor())
    try:
        yield
    finally:
        monitor.cancel()
        with suppress(asyncio.CancelledError):
            await monitor


app = FastAPI(
    title="RDDS API",
    description="Standalone Remote Drone Detection System API",
    version="0.3.0",
    lifespan=lifespan,
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


@app.get("/api/v1/protocol/schema", tags=["protocol"])
def get_protocol_schema() -> dict[str, object]:
    return {
        "protocol_version": "rdds/1.0",
        "heartbeat": HeartbeatEnvelope.model_json_schema(),
        "observation": ObservationEnvelope.model_json_schema(),
    }


@app.post(
    "/api/v1/ingest/heartbeat",
    response_model=IngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["ingest"],
    dependencies=[Depends(require_ingest_token)],
)
def ingest_heartbeat(payload: HeartbeatEnvelope) -> IngestResult:
    try:
        sensor_uuid, record_id = insert_heartbeat(
            payload,
            payload.model_dump(mode="json"),
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Heartbeat ingestion failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return IngestResult(
        accepted=True,
        duplicate=record_id is None,
        record_id=record_id,
        sensor_uuid=sensor_uuid,
    )


@app.post(
    "/api/v1/ingest/observation",
    response_model=IngestResult,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["ingest"],
    dependencies=[Depends(require_ingest_token)],
)
def ingest_observation(payload: ObservationEnvelope) -> IngestResult:
    try:
        sensor_uuid, record_id = insert_observation(
            payload,
            payload.model_dump(mode="json"),
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Observation ingestion failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return IngestResult(
        accepted=True,
        duplicate=record_id is None,
        record_id=record_id,
        sensor_uuid=sensor_uuid,
    )


@app.get("/api/v1/sensors", tags=["sensors"])
def get_sensors() -> dict[str, object]:
    try:
        sensors = list_sensors()
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Sensor list query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "sensors": sensors,
    }


@app.get("/api/v1/tracks", tags=["tracks"])
def get_tracks(
    include_ended: bool = Query(default=False),
) -> dict[str, object]:
    try:
        tracks = list_tracks(include_ended=include_ended)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Track list query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "tracks": tracks,
    }


@app.get("/api/v1/tracks/{track_id}/history", tags=["tracks"])
def get_track_observation_history(
    track_id: UUID,
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, object]:
    try:
        observations = get_track_history(track_id=track_id, limit=limit)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Track history query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "track_id": track_id,
        "observations": observations,
    }

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, status

from app.alert_store import (
    acknowledge_alert,
    close_alert,
    create_zone,
    list_alerts,
    list_zones,
    set_zone_active,
)
from app.config import settings
from app.database import (
    insert_heartbeat,
    insert_observation,
    list_sensors,
    mark_stale_sensors,
    readiness,
    system_summary,
)
from app.models import (
    AlertAction,
    HeartbeatEnvelope,
    IngestResult,
    ObservationEnvelope,
    ProtectedZoneCreate,
    ProtectedZoneState,
)
from app.security import require_admin_token, require_ingest_token
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
    version="0.6.0",
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


@app.get(
    "/api/v1/admin/verify",
    tags=["administration"],
    dependencies=[Depends(require_admin_token)],
)
def verify_admin_access() -> dict[str, object]:
    return {
        "time": utc_now(),
        "authorized": True,
    }


@app.get("/api/v1/zones", tags=["zones"])
def get_zones() -> dict[str, object]:
    try:
        zones = list_zones()
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Protected zone list query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "zones": zones,
    }


@app.post(
    "/api/v1/zones",
    status_code=status.HTTP_201_CREATED,
    tags=["zones"],
    dependencies=[Depends(require_admin_token)],
)
def post_zone(payload: ProtectedZoneCreate) -> dict[str, object]:
    try:
        zone = create_zone(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Protected zone creation failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "zone": zone,
    }


@app.patch(
    "/api/v1/zones/{zone_id}",
    tags=["zones"],
    dependencies=[Depends(require_admin_token)],
)
def patch_zone_state(
    zone_id: UUID,
    payload: ProtectedZoneState,
) -> dict[str, object]:
    try:
        zone = set_zone_active(zone_id=zone_id, active=payload.active)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Protected zone state update failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if zone is None:
        raise HTTPException(status_code=404, detail="protected zone not found")

    return {
        "time": utc_now(),
        "zone": zone,
    }


@app.get("/api/v1/alerts", tags=["alerts"])
def get_alerts(
    include_closed: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, object]:
    try:
        alerts = list_alerts(include_closed=include_closed, limit=limit)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Alert list query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "alerts": alerts,
    }


@app.post(
    "/api/v1/alerts/{alert_id}/acknowledge",
    tags=["alerts"],
    dependencies=[Depends(require_admin_token)],
)
def post_alert_acknowledgement(
    alert_id: UUID,
    payload: AlertAction,
) -> dict[str, object]:
    try:
        alert = acknowledge_alert(alert_id=alert_id, actor=payload.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Alert acknowledgement failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if alert is None:
        raise HTTPException(status_code=409, detail="alert is not active")

    return {
        "time": utc_now(),
        "alert": alert,
    }


@app.post(
    "/api/v1/alerts/{alert_id}/close",
    tags=["alerts"],
    dependencies=[Depends(require_admin_token)],
)
def post_alert_close(
    alert_id: UUID,
    payload: AlertAction,
) -> dict[str, object]:
    try:
        alert = close_alert(alert_id=alert_id, actor=payload.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Alert close failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if alert is None:
        raise HTTPException(status_code=409, detail="alert is not open")

    return {
        "time": utc_now(),
        "alert": alert,
    }

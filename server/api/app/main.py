import asyncio
import csv
import io
import json
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status

from app.alert_store import (
    acknowledge_alert,
    close_alert,
    create_zone,
    list_alerts,
    list_zones,
    set_zone_active,
)
from app.audit_store import AuditCategory, list_audit_events
from app.config import settings
from app.database import (
    insert_heartbeat,
    insert_observation,
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
    SensorRegistration,
    SensorState,
    SensorTokenRotation,
)
from app.security import (
    IngestPrincipal,
    authorize_sensor_identity,
    require_admin_token,
    require_ingest_token,
)
from app.sensor_store import (
    list_sensors,
    register_sensor,
    rotate_sensor_token,
    set_sensor_enabled,
)
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
    version="0.9.0",
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
)
def ingest_heartbeat(
    payload: HeartbeatEnvelope,
    principal: IngestPrincipal = Depends(require_ingest_token),
) -> IngestResult:
    authorize_sensor_identity(principal, payload.sensor.sensor_id)
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
)
def ingest_observation(
    payload: ObservationEnvelope,
    principal: IngestPrincipal = Depends(require_ingest_token),
) -> IngestResult:
    authorize_sensor_identity(principal, payload.sensor.sensor_id)
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


@app.post(
    "/api/v1/sensors",
    status_code=status.HTTP_201_CREATED,
    tags=["sensors"],
    dependencies=[Depends(require_admin_token)],
)
def post_sensor_registration(payload: SensorRegistration) -> dict[str, object]:
    try:
        sensor, ingest_token = register_sensor(payload)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail="sensor_key already exists",
        ) from exc
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Sensor registration failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "sensor": sensor,
        "credential": {
            "ingest_token": ingest_token,
            "token_prefix": sensor["token_prefix"],
            "shown_once": True,
        },
    }


@app.patch(
    "/api/v1/sensors/{sensor_id}",
    tags=["sensors"],
    dependencies=[Depends(require_admin_token)],
)
def patch_sensor_state(
    sensor_id: UUID,
    payload: SensorState,
) -> dict[str, object]:
    try:
        sensor = set_sensor_enabled(
            sensor_id=sensor_id,
            enabled=payload.enabled,
            actor=payload.actor,
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Sensor state update failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if sensor is None:
        raise HTTPException(status_code=404, detail="sensor not found")

    return {
        "time": utc_now(),
        "sensor": sensor,
    }


@app.post(
    "/api/v1/sensors/{sensor_id}/token/rotate",
    tags=["sensors"],
    dependencies=[Depends(require_admin_token)],
)
def post_sensor_token_rotation(
    sensor_id: UUID,
    payload: SensorTokenRotation,
) -> dict[str, object]:
    try:
        result = rotate_sensor_token(sensor_id=sensor_id, actor=payload.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Sensor token rotation failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="sensor not found")

    sensor, ingest_token = result
    return {
        "time": utc_now(),
        "sensor": sensor,
        "credential": {
            "ingest_token": ingest_token,
            "token_prefix": sensor["token_prefix"],
            "shown_once": True,
        },
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
        "legacy_ingest_enabled": settings.allow_legacy_ingest,
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
        zone = set_zone_active(
            zone_id=zone_id,
            active=payload.active,
            actor=payload.actor,
        )
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


AuditEventType = Literal[
    "alert_opened",
    "alert_acknowledged",
    "alert_closed",
    "zone_created",
    "zone_enabled",
    "zone_disabled",
    "sensor_registered",
    "sensor_enabled",
    "sensor_disabled",
    "sensor_token_issued",
    "sensor_token_rotated",
]


@app.get("/api/v1/audit/events", tags=["audit"])
def get_audit_events(
    category: AuditCategory = Query(default="all"),
    event_type: AuditEventType | None = Query(default=None),
    alert_id: UUID | None = Query(default=None),
    zone_id: UUID | None = Query(default=None),
    sensor_id: UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    try:
        events, total = list_audit_events(
            category=category,
            event_type=event_type,
            alert_id=alert_id,
            zone_id=zone_id,
            sensor_id=sensor_id,
            limit=limit,
            offset=offset,
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Audit event query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    return {
        "time": utc_now(),
        "total": total,
        "limit": limit,
        "offset": offset,
        "events": events,
    }


@app.get("/api/v1/audit/export", tags=["audit"])
def export_audit_events(
    format: Literal["csv", "json"] = Query(default="csv"),
    category: AuditCategory = Query(default="all"),
    event_type: AuditEventType | None = Query(default=None),
    alert_id: UUID | None = Query(default=None),
    zone_id: UUID | None = Query(default=None),
    sensor_id: UUID | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=5000),
) -> Response:
    try:
        events, total = list_audit_events(
            category=category,
            event_type=event_type,
            alert_id=alert_id,
            zone_id=zone_id,
            sensor_id=sensor_id,
            limit=limit,
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Audit export query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    headers = {
        "Content-Disposition": f'attachment; filename="rdds-audit-{timestamp}.{format}"',
    }

    if format == "json":
        payload = {
            "exported_at": utc_now(),
            "total": total,
            "exported": len(events),
            "events": events,
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False, default=str, indent=2),
            media_type="application/json",
            headers=headers,
        )

    output = io.StringIO()
    fieldnames = [
        "id",
        "occurred_at",
        "event_type",
        "actor",
        "alert_id",
        "alert_state",
        "alert_severity",
        "zone_id",
        "zone_name",
        "track_id",
        "basic_id",
        "identity_key",
        "operator_id",
        "sensor_id",
        "sensor_key",
        "sensor_name",
        "details",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for event in events:
        row = dict(event)
        row["details"] = json.dumps(
            event.get("details") or {},
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
        writer.writerow(row)

    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv",
        headers=headers,
    )

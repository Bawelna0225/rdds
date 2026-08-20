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
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.alert_store import (
    acknowledge_alert,
    close_alert,
    create_zone,
    delete_zone,
    list_alerts,
    list_zones,
    set_zone_active,
    update_zone,
)
from app.audit_store import AuditCategory, list_audit_events
from app.auth_store import (
    authenticate_login,
    change_password,
    create_account,
    delete_account,
    list_accounts,
    reset_account_password,
    revoke_session,
    set_account_enabled,
    update_account,
)
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
    EntityDelete,
    HeartbeatEnvelope,
    IngestResult,
    LoginRequest,
    ObservationEnvelope,
    OperatorCreate,
    OperatorPasswordReset,
    OperatorState,
    OperatorUpdate,
    PasswordChange,
    ProtectedZoneCreate,
    ProtectedZoneState,
    ProtectedZoneUpdate,
    SensorRegistration,
    SensorState,
    SensorTokenRotation,
    SensorUpdate,
)
from app.security import (
    SESSION_COOKIE_NAME,
    IngestPrincipal,
    OperatorPrincipal,
    authorize_sensor_identity,
    require_administrator,
    require_administrator_write,
    require_csrf,
    require_ingest_token,
    require_operator_session,
    require_operator_write,
    require_viewer,
)
from app.sensor_store import (
    delete_sensor,
    list_sensors,
    register_sensor,
    rotate_sensor_token,
    set_sensor_enabled,
    update_sensor,
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
    version="0.12.0",
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


def _session_payload(principal: OperatorPrincipal) -> dict[str, object]:
    return {
        "time": utc_now(),
        "user": {
            "id": principal.id,
            "username": principal.username,
            "display_name": principal.display_name,
            "role": principal.role,
            "enabled": principal.enabled,
            "must_change_password": principal.must_change_password,
        },
        "csrf_token": principal.csrf_token,
        "expires_at": principal.expires_at,
    }


@app.post("/api/v1/auth/login", tags=["authentication"])
def login(payload: LoginRequest, request: Request) -> JSONResponse:
    try:
        result = authenticate_login(
            username=payload.username,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            remote_address=request.client.host if request.client else None,
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator login failed because authentication is unavailable")
        raise HTTPException(
            status_code=503, detail="authentication unavailable"
        ) from exc
    if result is None:
        raise HTTPException(status_code=401, detail="invalid username or password")

    account, raw_token, csrf_token, expires_at = result
    response = JSONResponse(
        jsonable_encoder(
            {
                "time": utc_now(),
                "user": account,
                "csrf_token": csrf_token,
                "expires_at": expires_at.isoformat(),
            }
        )
    )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.session_absolute_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    return response


@app.get("/api/v1/auth/me", tags=["authentication"])
def get_current_session(
    principal: OperatorPrincipal = Depends(require_operator_session),
) -> dict[str, object]:
    return _session_payload(principal)


@app.post("/api/v1/auth/logout", tags=["authentication"])
def logout(
    principal: OperatorPrincipal = Depends(require_csrf),
) -> JSONResponse:
    try:
        revoke_session(principal.session_id, principal.actor, principal.id)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator logout failed")
        raise HTTPException(
            status_code=503, detail="authentication unavailable"
        ) from exc
    response = JSONResponse({"time": utc_now(), "logged_out": True})
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return response


@app.post("/api/v1/auth/password", tags=["authentication"])
def post_password_change(
    payload: PasswordChange,
    principal: OperatorPrincipal = Depends(require_csrf),
) -> dict[str, object]:
    try:
        changed = change_password(
            account_id=principal.id,
            session_id=principal.session_id,
            actor=principal.actor,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator password change failed")
        raise HTTPException(
            status_code=503, detail="authentication unavailable"
        ) from exc
    if not changed:
        raise HTTPException(status_code=400, detail="current password is invalid")
    return {"time": utc_now(), "password_changed": True}


@app.get(
    "/api/v1/system/summary",
    tags=["system"],
    dependencies=[Depends(require_viewer)],
)
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


@app.get(
    "/api/v1/protocol/schema",
    tags=["protocol"],
    dependencies=[Depends(require_viewer)],
)
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


@app.get(
    "/api/v1/sensors",
    tags=["sensors"],
    dependencies=[Depends(require_viewer)],
)
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
    dependencies=[Depends(require_administrator_write)],
)
def post_sensor_registration(
    payload: SensorRegistration,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        sensor, ingest_token = register_sensor(payload, principal.actor)
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
    dependencies=[Depends(require_administrator_write)],
)
def patch_sensor_state(
    sensor_id: UUID,
    payload: SensorState,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        sensor = set_sensor_enabled(
            sensor_id=sensor_id,
            enabled=payload.enabled,
            actor=principal.actor,
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


@app.put(
    "/api/v1/sensors/{sensor_id}",
    tags=["sensors"],
    dependencies=[Depends(require_administrator_write)],
)
def put_sensor(
    sensor_id: UUID,
    payload: SensorUpdate,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        sensor = update_sensor(
            sensor_id=sensor_id,
            payload=payload,
            actor=principal.actor,
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Sensor update failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if sensor is None:
        raise HTTPException(status_code=404, detail="sensor not found")

    return {
        "time": utc_now(),
        "sensor": sensor,
    }


@app.delete(
    "/api/v1/sensors/{sensor_id}",
    tags=["sensors"],
    dependencies=[Depends(require_administrator_write)],
)
def delete_sensor_registration(
    sensor_id: UUID,
    payload: EntityDelete,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        sensor = delete_sensor(sensor_id=sensor_id, actor=principal.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Sensor deletion failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if sensor is None:
        raise HTTPException(status_code=404, detail="sensor not found")

    return {
        "time": utc_now(),
        "sensor": sensor,
        "deleted": True,
    }


@app.post(
    "/api/v1/sensors/{sensor_id}/token/rotate",
    tags=["sensors"],
    dependencies=[Depends(require_administrator_write)],
)
def post_sensor_token_rotation(
    sensor_id: UUID,
    payload: SensorTokenRotation,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        result = rotate_sensor_token(sensor_id=sensor_id, actor=principal.actor)
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


@app.get(
    "/api/v1/tracks",
    tags=["tracks"],
    dependencies=[Depends(require_viewer)],
)
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


@app.get(
    "/api/v1/tracks/{track_id}/history",
    tags=["tracks"],
    dependencies=[Depends(require_viewer)],
)
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
    dependencies=[Depends(require_administrator)],
)
def verify_admin_access(
    principal: OperatorPrincipal = Depends(require_administrator),
) -> dict[str, object]:
    return {
        "time": utc_now(),
        "authorized": True,
        "user": {
            "username": principal.username,
            "display_name": principal.display_name,
            "role": principal.role,
        },
        "legacy_ingest_enabled": settings.allow_legacy_ingest,
    }


@app.get(
    "/api/v1/zones",
    tags=["zones"],
    dependencies=[Depends(require_viewer)],
)
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
    dependencies=[Depends(require_operator_write)],
)
def post_zone(
    payload: ProtectedZoneCreate,
    principal: OperatorPrincipal = Depends(require_operator_write),
) -> dict[str, object]:
    try:
        zone = create_zone(payload, principal.actor)
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
    dependencies=[Depends(require_operator_write)],
)
def patch_zone_state(
    zone_id: UUID,
    payload: ProtectedZoneState,
    principal: OperatorPrincipal = Depends(require_operator_write),
) -> dict[str, object]:
    try:
        zone = set_zone_active(
            zone_id=zone_id,
            active=payload.active,
            actor=principal.actor,
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


@app.put(
    "/api/v1/zones/{zone_id}",
    tags=["zones"],
    dependencies=[Depends(require_operator_write)],
)
def put_zone(
    zone_id: UUID,
    payload: ProtectedZoneUpdate,
    principal: OperatorPrincipal = Depends(require_operator_write),
) -> dict[str, object]:
    try:
        zone = update_zone(
            zone_id=zone_id,
            payload=payload,
            actor=principal.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Protected zone update failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if zone is None:
        raise HTTPException(status_code=404, detail="protected zone not found")

    return {
        "time": utc_now(),
        "zone": zone,
    }


@app.delete(
    "/api/v1/zones/{zone_id}",
    tags=["zones"],
    dependencies=[Depends(require_administrator_write)],
)
def delete_protected_zone(
    zone_id: UUID,
    payload: EntityDelete,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        zone = delete_zone(zone_id=zone_id, actor=principal.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Protected zone deletion failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if zone is None:
        raise HTTPException(status_code=404, detail="protected zone not found")

    return {
        "time": utc_now(),
        "zone": zone,
        "deleted": True,
    }


@app.get(
    "/api/v1/alerts",
    tags=["alerts"],
    dependencies=[Depends(require_viewer)],
)
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
    dependencies=[Depends(require_operator_write)],
)
def post_alert_acknowledgement(
    alert_id: UUID,
    payload: AlertAction,
    principal: OperatorPrincipal = Depends(require_operator_write),
) -> dict[str, object]:
    try:
        alert = acknowledge_alert(alert_id=alert_id, actor=principal.actor)
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
    dependencies=[Depends(require_operator_write)],
)
def post_alert_close(
    alert_id: UUID,
    payload: AlertAction,
    principal: OperatorPrincipal = Depends(require_operator_write),
) -> dict[str, object]:
    try:
        alert = close_alert(alert_id=alert_id, actor=principal.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Alert close failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if alert is None:
        raise HTTPException(status_code=409, detail="alert is not open")

    return {
        "time": utc_now(),
        "alert": alert,
    }


@app.get("/api/v1/operators", tags=["operators"])
def get_operator_accounts(
    _: OperatorPrincipal = Depends(require_administrator),
) -> dict[str, object]:
    try:
        accounts = list_accounts()
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator account list query failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"time": utc_now(), "operators": accounts}


@app.post(
    "/api/v1/operators",
    status_code=status.HTTP_201_CREATED,
    tags=["operators"],
)
def post_operator_account(
    payload: OperatorCreate,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        account = create_account(payload, principal.actor)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="username already exists") from exc
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator account creation failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"time": utc_now(), "operator": account}


@app.put("/api/v1/operators/{operator_id}", tags=["operators"])
def put_operator_account(
    operator_id: UUID,
    payload: OperatorUpdate,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        result = update_account(operator_id, payload, principal.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator account update failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="operator account not found")
    if result == "last_administrator":
        raise HTTPException(
            status_code=409, detail="last administrator must be preserved"
        )
    return {"time": utc_now(), "operator": result}


@app.patch("/api/v1/operators/{operator_id}", tags=["operators"])
def patch_operator_account_state(
    operator_id: UUID,
    payload: OperatorState,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    if operator_id == principal.id and not payload.enabled:
        raise HTTPException(status_code=409, detail="cannot disable your own account")
    try:
        result = set_account_enabled(
            operator_id,
            payload.enabled,
            principal.actor,
        )
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator account state update failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="operator account not found")
    if result == "last_administrator":
        raise HTTPException(
            status_code=409, detail="last administrator must be preserved"
        )
    return {"time": utc_now(), "operator": result}


@app.post("/api/v1/operators/{operator_id}/password/reset", tags=["operators"])
def post_operator_password_reset(
    operator_id: UUID,
    payload: OperatorPasswordReset,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    try:
        account = reset_account_password(operator_id, payload, principal.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator password reset failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if account is None:
        raise HTTPException(status_code=404, detail="operator account not found")
    return {"time": utc_now(), "operator": account}


@app.delete("/api/v1/operators/{operator_id}", tags=["operators"])
def delete_operator_account(
    operator_id: UUID,
    payload: EntityDelete,
    principal: OperatorPrincipal = Depends(require_administrator_write),
) -> dict[str, object]:
    if operator_id == principal.id:
        raise HTTPException(status_code=409, detail="cannot delete your own account")
    try:
        result = delete_account(operator_id, principal.actor)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Operator account deletion failed")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="operator account not found")
    if result == "last_administrator":
        raise HTTPException(
            status_code=409, detail="last administrator must be preserved"
        )
    return {"time": utc_now(), "operator": result, "deleted": True}


AuditEventType = Literal[
    "alert_opened",
    "alert_acknowledged",
    "alert_closed",
    "zone_created",
    "zone_enabled",
    "zone_disabled",
    "zone_updated",
    "zone_deleted",
    "sensor_registered",
    "sensor_enabled",
    "sensor_disabled",
    "sensor_updated",
    "sensor_deleted",
    "sensor_token_issued",
    "sensor_token_rotated",
    "operator_created",
    "operator_updated",
    "operator_enabled",
    "operator_disabled",
    "operator_deleted",
    "operator_password_changed",
    "operator_logged_in",
    "operator_logged_out",
]


@app.get(
    "/api/v1/audit/events",
    tags=["audit"],
    dependencies=[Depends(require_viewer)],
)
def get_audit_events(
    category: AuditCategory = Query(default="all"),
    event_type: AuditEventType | None = Query(default=None),
    alert_id: UUID | None = Query(default=None),
    zone_id: UUID | None = Query(default=None),
    sensor_id: UUID | None = Query(default=None),
    operator_account_id: UUID | None = Query(default=None),
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
            operator_account_id=operator_account_id,
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


@app.get(
    "/api/v1/audit/export",
    tags=["audit"],
    dependencies=[Depends(require_viewer)],
)
def export_audit_events(
    format: Literal["csv", "json"] = Query(default="csv"),
    category: AuditCategory = Query(default="all"),
    event_type: AuditEventType | None = Query(default=None),
    alert_id: UUID | None = Query(default=None),
    zone_id: UUID | None = Query(default=None),
    sensor_id: UUID | None = Query(default=None),
    operator_account_id: UUID | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=5000),
) -> Response:
    try:
        events, total = list_audit_events(
            category=category,
            event_type=event_type,
            alert_id=alert_id,
            zone_id=zone_id,
            sensor_id=sensor_id,
            operator_account_id=operator_account_id,
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
        "operator_account_id",
        "account_username",
        "account_display_name",
        "account_role",
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

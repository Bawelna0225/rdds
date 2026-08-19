from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(StrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SensorContext(StrictModel):
    sensor_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    boot_id: UUID
    sequence: int = Field(ge=0)
    timestamp: datetime
    position: Position | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value


class HeartbeatStatus(StrictModel):
    uptime_seconds: int | None = Field(default=None, ge=0)
    free_heap_bytes: int | None = Field(default=None, ge=0)
    queue_depth: int | None = Field(default=None, ge=0)
    cellular_rssi: int | None = Field(default=None, ge=-150, le=0)


class HeartbeatEnvelope(StrictModel):
    protocol_version: Literal["rdds/1.0"]
    message_type: Literal["heartbeat"]
    sensor: SensorContext
    status: HeartbeatStatus


class RadioObservation(StrictModel):
    transport: Literal["ble", "wifi_nan", "wifi_beacon", "simulator", "unknown"]
    channel: int | None = Field(default=None, ge=0, le=255)
    rssi: int | None = Field(default=None, ge=-150, le=20)


class DroneObservation(StrictModel):
    mac: str | None = Field(
        default=None,
        pattern=r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$",
    )
    basic_id: str | None = Field(default=None, max_length=255)
    operator_id: str | None = Field(default=None, max_length=255)
    session_id: str | None = Field(default=None, max_length=255)
    position: Position | None = None
    altitude_m: float | None = None
    height_agl_m: float | None = None
    speed_mps: float | None = Field(default=None, ge=0)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    emergency_status: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_identity_or_position(self) -> "DroneObservation":
        if not any(
            (
                self.mac,
                self.basic_id,
                self.operator_id,
                self.session_id,
                self.position,
            )
        ):
            raise ValueError("drone requires an identity field or position")
        return self


class ObservationEnvelope(StrictModel):
    protocol_version: Literal["rdds/1.0"]
    message_type: Literal["observation"]
    sensor: SensorContext
    radio: RadioObservation
    drone: DroneObservation
    pilot_position: Position | None = None
    raw_remote_id: dict[str, Any] | None = None


class IngestResult(StrictModel):
    accepted: bool
    duplicate: bool
    record_id: int | None
    sensor_uuid: UUID


class SensorRegistration(StrictModel):
    sensor_key: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    display_name: str = Field(min_length=1, max_length=160)
    position: Position | None = None
    actor: str = Field(default="api-admin", min_length=1, max_length=160)


class SensorState(StrictModel):
    enabled: bool
    actor: str = Field(default="api-admin", min_length=1, max_length=160)


class SensorTokenRotation(StrictModel):
    actor: str = Field(default="api-admin", min_length=1, max_length=160)


class PolygonGeometry(StrictModel):
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]]

    @field_validator("coordinates")
    @classmethod
    def validate_polygon(
        cls,
        value: list[list[tuple[float, float]]],
    ) -> list[list[tuple[float, float]]]:
        if len(value) != 1:
            raise ValueError("only a single exterior polygon ring is supported")

        ring = value[0]
        if len(ring) < 4:
            raise ValueError("polygon ring requires at least four positions")
        if len(ring) > 501:
            raise ValueError("polygon ring cannot exceed 500 positions")
        if ring[0] != ring[-1]:
            raise ValueError("polygon ring must be closed")

        for longitude, latitude in ring:
            if not -180 <= longitude <= 180:
                raise ValueError("polygon longitude must be between -180 and 180")
            if not -90 <= latitude <= 90:
                raise ValueError("polygon latitude must be between -90 and 90")

        if len(set(ring[:-1])) < 3:
            raise ValueError("polygon requires at least three distinct positions")
        return value


class ProtectedZoneCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    severity: Literal["low", "medium", "high", "critical"] = "high"
    active: bool = True
    actor: str = Field(default="api-admin", min_length=1, max_length=160)
    geometry: PolygonGeometry


class ProtectedZoneState(StrictModel):
    active: bool
    actor: str = Field(default="api-admin", min_length=1, max_length=160)


class AlertAction(StrictModel):
    actor: str = Field(min_length=1, max_length=160)

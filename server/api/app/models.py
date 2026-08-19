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

from datetime import datetime, timezone
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
    queue_capacity: int | None = Field(default=None, ge=1)
    queue_oldest_age_seconds: int | None = Field(default=None, ge=0)
    dead_letter_depth: int | None = Field(default=None, ge=0)
    cellular_rssi: int | None = Field(default=None, ge=-150, le=0)
    agent_version: str | None = Field(default=None, min_length=1, max_length=64)
    source_kind: Literal["serial", "socket", "loopback", "unknown"] | None = None
    source_connected: bool | None = None
    source_connected_at: datetime | None = None
    source_last_message_at: datetime | None = None
    source_last_error_at: datetime | None = None
    source_last_error_reason: str | None = Field(default=None, min_length=1, max_length=64)
    input_lines_total: int | None = Field(default=None, ge=0)
    parsed_detections_total: int | None = Field(default=None, ge=0)
    enqueued_observations_total: int | None = Field(default=None, ge=0)
    ignored_lines_total: int | None = Field(default=None, ge=0)
    source_connections_total: int | None = Field(default=None, ge=0)
    delivery_success_total: int | None = Field(default=None, ge=0)
    delivery_retry_total: int | None = Field(default=None, ge=0)
    delivery_discard_total: int | None = Field(default=None, ge=0)
    delivery_dead_letter_total: int | None = Field(default=None, ge=0)
    last_delivery_success_at: datetime | None = None
    last_delivery_error_at: datetime | None = None
    last_delivery_error_reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )

    @field_validator(
        "source_connected_at",
        "source_last_message_at",
        "source_last_error_at",
        "last_delivery_success_at",
        "last_delivery_error_at",
    )
    @classmethod
    def diagnostic_timestamp_must_include_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("diagnostic timestamps must include a UTC offset")
        return value


class SensorManagedConfiguration(StrictModel):
    heartbeat_seconds: float = Field(ge=2.0, le=3600.0)
    reconnect_seconds: float = Field(ge=0.5, le=300.0)
    request_timeout_seconds: float = Field(ge=1.0, le=120.0)
    replay_messages_per_second: float = Field(ge=0.1, le=100.0)


class SensorConfigurationProfileCreate(StrictModel):
    profile_key: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$",
    )
    display_name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    configuration: SensorManagedConfiguration
    change_note: str = Field(min_length=3, max_length=500)

    @field_validator("display_name", "change_note")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank")
        return stripped

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SensorConfigurationProfileUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool

    @field_validator("display_name")
    @classmethod
    def display_name_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("display_name cannot be blank")
        return stripped

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SensorConfigurationProfileVersionCreate(StrictModel):
    configuration: SensorManagedConfiguration
    change_note: str = Field(min_length=3, max_length=500)

    @field_validator("change_note")
    @classmethod
    def change_note_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("change_note cannot be blank")
        return stripped


class SensorConfigurationRolloutCreate(StrictModel):
    profile_id: UUID
    profile_version: int = Field(ge=1)
    sensor_ids: list[UUID] = Field(min_length=1, max_length=100)
    batch_size: int = Field(default=1, ge=1, le=25)
    change_note: str = Field(min_length=3, max_length=500)

    @field_validator("sensor_ids")
    @classmethod
    def sensor_ids_must_be_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("sensor_ids must be unique")
        return value

    @field_validator("change_note")
    @classmethod
    def change_note_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("change_note cannot be blank")
        return stripped


class SensorConfigurationRolloutAction(StrictModel):
    change_note: str = Field(min_length=3, max_length=500)

    @field_validator("change_note")
    @classmethod
    def change_note_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("change_note cannot be blank")
        return stripped


class SensorFleetReadinessPolicyUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    minimum_agent_version: str = Field(
        min_length=5,
        max_length=32,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$",
    )
    recommended_agent_version: str = Field(
        min_length=5,
        max_length=32,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$",
    )
    require_source_connected: bool = True
    require_configuration_compliance: bool = True
    rollout_application_timeout_seconds: int | None = Field(
        default=None,
        ge=30,
        le=3600,
    )
    change_note: str = Field(min_length=3, max_length=500)

    @field_validator("change_note")
    @classmethod
    def change_note_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("change_note cannot be blank")
        return stripped

    @model_validator(mode="after")
    def recommended_version_cannot_be_older(
        self,
    ) -> "SensorFleetReadinessPolicyUpdate":
        minimum = tuple(int(part) for part in self.minimum_agent_version.split("."))
        recommended = tuple(
            int(part) for part in self.recommended_agent_version.split(".")
        )
        if recommended < minimum:
            raise ValueError(
                "recommended_agent_version cannot be older than "
                "minimum_agent_version"
            )
        return self


class SensorConfigurationReport(StrictModel):
    desired_revision: int = Field(ge=0)
    applied_revision: int | None = Field(default=None, ge=0)
    applied_config: SensorManagedConfiguration | None = None
    apply_status: Literal["applied", "error"]
    apply_error: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_configuration_report(self) -> "SensorConfigurationReport":
        if (self.applied_revision is None) != (self.applied_config is None):
            raise ValueError(
                "applied_revision and applied_config must be reported together"
            )
        if (
            self.applied_revision is not None
            and self.applied_revision > self.desired_revision
        ):
            raise ValueError("applied_revision cannot exceed desired_revision")
        if self.apply_status == "applied":
            if self.applied_revision != self.desired_revision:
                raise ValueError(
                    "an applied report must match the desired revision"
                )
            if self.applied_config is None:
                raise ValueError("an applied report requires applied_config")
            if self.apply_error is not None:
                raise ValueError("an applied report cannot contain apply_error")
        elif not (self.apply_error or "").strip():
            raise ValueError("an error report requires apply_error")
        return self


class HeartbeatEnvelope(StrictModel):
    protocol_version: Literal["rdds/1.0"]
    message_type: Literal["heartbeat"]
    sensor: SensorContext
    status: HeartbeatStatus
    configuration_report: SensorConfigurationReport | None = None


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


class SensorState(StrictModel):
    enabled: bool


class SensorUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    position: Position | None = None


class SensorMaintenance(StrictModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)
    until: datetime | None = None

    @model_validator(mode="after")
    def validate_maintenance(self) -> "SensorMaintenance":
        if self.enabled and not (self.reason or "").strip():
            raise ValueError("reason is required when maintenance is enabled")
        if self.until is not None:
            if self.until.tzinfo is None or self.until.utcoffset() is None:
                raise ValueError("until must include a UTC offset")
            if not self.enabled:
                raise ValueError("until is only valid when maintenance is enabled")
            if self.until <= datetime.now(timezone.utc):
                raise ValueError("until must be in the future")
        return self


class SensorTokenRotation(StrictModel):
    pass


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
    geometry: PolygonGeometry


class ProtectedZoneState(StrictModel):
    active: bool


class ProtectedZoneUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    severity: Literal["low", "medium", "high", "critical"]
    active: bool
    geometry: PolygonGeometry


class EntityDelete(StrictModel):
    pass


class AlertAction(StrictModel):
    pass


OperatorRole = Literal["viewer", "operator", "administrator"]


class LoginRequest(StrictModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(StrictModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def passwords_must_differ(self) -> "PasswordChange":
        if self.current_password == self.new_password:
            raise ValueError("new password must differ from current password")
        return self


class OperatorCreate(StrictModel):
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$",
    )
    display_name: str = Field(min_length=1, max_length=160)
    role: OperatorRole
    temporary_password: str = Field(min_length=12, max_length=128)

    @field_validator("username")
    @classmethod
    def username_must_be_lowercase(cls, value: str) -> str:
        return value.strip().lower()


class OperatorUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    role: OperatorRole


class OperatorState(StrictModel):
    enabled: bool


class OperatorPasswordReset(StrictModel):
    temporary_password: str = Field(min_length=12, max_length=128)

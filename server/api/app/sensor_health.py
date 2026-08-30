from dataclasses import dataclass
from datetime import datetime

from app.models import HeartbeatStatus


@dataclass(frozen=True)
class HealthAssessment:
    state: str
    reason: str


def assess_heartbeat(
    status: HeartbeatStatus,
    queue_warning_messages: int,
    source_silent_after_seconds: int,
    reported_at: datetime,
) -> HealthAssessment:
    """Turn one current agent snapshot into an operational sensor state."""
    if status.source_connected is False:
        return HealthAssessment("degraded", "source_unavailable")
    if status.source_connected is True:
        source_is_old = (
            status.source_last_message_at is not None
            and (
                reported_at - status.source_last_message_at
            ).total_seconds() >= source_silent_after_seconds
        )
        source_never_reported = (
            status.source_last_message_at is None
            and (status.uptime_seconds or 0) >= source_silent_after_seconds
        )
        if source_is_old or source_never_reported:
            return HealthAssessment("degraded", "source_silent")
    latest_delivery_failed = (
        status.last_delivery_error_reason not in (None, "sensor_disabled")
        and status.last_delivery_error_at is not None
        and (
            status.last_delivery_success_at is None
            or status.last_delivery_error_at > status.last_delivery_success_at
        )
    )
    if latest_delivery_failed:
        return HealthAssessment("degraded", "api_delivery_failed")
    if (status.dead_letter_depth or 0) > 0:
        return HealthAssessment("degraded", "dead_letter")
    if (status.queue_depth or 0) >= queue_warning_messages:
        return HealthAssessment("degraded", "queue_backlog")
    return HealthAssessment("online", "healthy")

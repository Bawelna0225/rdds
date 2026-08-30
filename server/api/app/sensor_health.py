from dataclasses import dataclass
from datetime import datetime

from app.models import HeartbeatStatus


@dataclass(frozen=True)
class HealthAssessment:
    state: str
    reason: str


@dataclass(frozen=True)
class SourceQuality:
    window_seconds: int
    input_lines: int
    parsed_detections: int
    ignored_lines: int
    reconnects: int
    ignored_ratio: float


def measure_source_quality(
    *,
    reported_at: datetime,
    baseline_at: datetime,
    input_lines_total: int | None,
    parsed_detections_total: int | None,
    ignored_lines_total: int | None,
    source_connections_total: int | None,
    baseline_input_lines_total: int | None,
    baseline_parsed_detections_total: int | None,
    baseline_ignored_lines_total: int | None,
    baseline_source_connections_total: int | None,
) -> SourceQuality | None:
    """Build a rolling quality sample from monotonic agent counters."""
    current = (
        input_lines_total,
        parsed_detections_total,
        ignored_lines_total,
        source_connections_total,
    )
    baseline = (
        baseline_input_lines_total,
        baseline_parsed_detections_total,
        baseline_ignored_lines_total,
        baseline_source_connections_total,
    )
    if any(value is None for value in (*current, *baseline)):
        return None

    elapsed = int((reported_at - baseline_at).total_seconds())
    deltas = tuple(
        int(current_value) - int(baseline_value)
        for current_value, baseline_value in zip(current, baseline, strict=True)
    )
    if elapsed <= 0 or any(value < 0 for value in deltas):
        return None

    input_lines, parsed_detections, ignored_lines, reconnects = deltas
    if parsed_detections > input_lines or ignored_lines > input_lines:
        return None
    ignored_ratio = ignored_lines / input_lines if input_lines else 0.0
    return SourceQuality(
        window_seconds=elapsed,
        input_lines=input_lines,
        parsed_detections=parsed_detections,
        ignored_lines=ignored_lines,
        reconnects=reconnects,
        ignored_ratio=ignored_ratio,
    )


def assess_heartbeat(
    status: HeartbeatStatus,
    queue_warning_messages: int,
    source_silent_after_seconds: int,
    reported_at: datetime,
    source_quality: SourceQuality | None = None,
    quality_min_window_seconds: int = 30,
    quality_min_input_lines: int = 20,
    quality_max_ignored_ratio: float = 0.8,
    reconnect_warning_count: int = 3,
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
    quality_is_ready = (
        source_quality is not None
        and source_quality.window_seconds >= quality_min_window_seconds
    )
    if (
        quality_is_ready
        and source_quality.input_lines >= quality_min_input_lines
        and source_quality.ignored_ratio >= quality_max_ignored_ratio
    ):
        return HealthAssessment("degraded", "source_data_invalid")
    if (
        quality_is_ready
        and source_quality.reconnects >= reconnect_warning_count
    ):
        return HealthAssessment("degraded", "source_unstable")
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

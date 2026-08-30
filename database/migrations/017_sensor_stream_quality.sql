BEGIN;

ALTER TABLE sensor_heartbeats
    ADD COLUMN IF NOT EXISTS quality_window_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS quality_input_lines BIGINT,
    ADD COLUMN IF NOT EXISTS quality_parsed_detections BIGINT,
    ADD COLUMN IF NOT EXISTS quality_ignored_lines BIGINT,
    ADD COLUMN IF NOT EXISTS quality_reconnects BIGINT,
    ADD COLUMN IF NOT EXISTS quality_ignored_ratio DOUBLE PRECISION;

ALTER TABLE sensor_heartbeats
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_quality_window_check,
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_quality_counters_check,
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_quality_ratio_check;

ALTER TABLE sensor_heartbeats
    ADD CONSTRAINT sensor_heartbeats_quality_window_check CHECK (
        quality_window_seconds IS NULL OR quality_window_seconds > 0
    ),
    ADD CONSTRAINT sensor_heartbeats_quality_counters_check CHECK (
        (quality_input_lines IS NULL OR quality_input_lines >= 0)
        AND (
            quality_parsed_detections IS NULL
            OR quality_parsed_detections >= 0
        )
        AND (quality_ignored_lines IS NULL OR quality_ignored_lines >= 0)
        AND (quality_reconnects IS NULL OR quality_reconnects >= 0)
    ),
    ADD CONSTRAINT sensor_heartbeats_quality_ratio_check CHECK (
        quality_ignored_ratio IS NULL
        OR quality_ignored_ratio BETWEEN 0 AND 1
    );

ALTER TABLE sensors
    ADD COLUMN IF NOT EXISTS reported_quality_window_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS reported_quality_input_lines BIGINT,
    ADD COLUMN IF NOT EXISTS reported_quality_parsed_detections BIGINT,
    ADD COLUMN IF NOT EXISTS reported_quality_ignored_lines BIGINT,
    ADD COLUMN IF NOT EXISTS reported_quality_reconnects BIGINT,
    ADD COLUMN IF NOT EXISTS reported_quality_ignored_ratio DOUBLE PRECISION;

ALTER TABLE sensors
    DROP CONSTRAINT IF EXISTS sensors_reported_quality_window_check,
    DROP CONSTRAINT IF EXISTS sensors_reported_quality_counters_check,
    DROP CONSTRAINT IF EXISTS sensors_reported_quality_ratio_check;

ALTER TABLE sensors
    ADD CONSTRAINT sensors_reported_quality_window_check CHECK (
        reported_quality_window_seconds IS NULL
        OR reported_quality_window_seconds > 0
    ),
    ADD CONSTRAINT sensors_reported_quality_counters_check CHECK (
        (
            reported_quality_input_lines IS NULL
            OR reported_quality_input_lines >= 0
        )
        AND (
            reported_quality_parsed_detections IS NULL
            OR reported_quality_parsed_detections >= 0
        )
        AND (
            reported_quality_ignored_lines IS NULL
            OR reported_quality_ignored_lines >= 0
        )
        AND (
            reported_quality_reconnects IS NULL
            OR reported_quality_reconnects >= 0
        )
    ),
    ADD CONSTRAINT sensors_reported_quality_ratio_check CHECK (
        reported_quality_ignored_ratio IS NULL
        OR reported_quality_ignored_ratio BETWEEN 0 AND 1
    );

CREATE INDEX IF NOT EXISTS idx_sensor_heartbeats_quality_history
    ON sensor_heartbeats (sensor_id, measured_at DESC)
    WHERE quality_window_seconds IS NOT NULL;

CREATE OR REPLACE FUNCTION record_sensor_health_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    audit_type TEXT;
BEGIN
    IF NEW.status = 'maintenance' AND OLD.status IS DISTINCT FROM 'maintenance' THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, sensor_id, details
        )
        VALUES (
            NOW(),
            'sensor_maintenance_started',
            NEW.updated_by,
            NEW.id,
            jsonb_strip_nulls(jsonb_build_object(
                'from_status', OLD.status,
                'to_status', NEW.status,
                'reason', NEW.maintenance_reason,
                'until', NEW.maintenance_until
            ))
        );
        RETURN NEW;
    END IF;

    IF OLD.status = 'maintenance' AND NEW.status IS DISTINCT FROM 'maintenance' THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, sensor_id, details
        )
        VALUES (
            NOW(),
            'sensor_maintenance_ended',
            NEW.updated_by,
            NEW.id,
            jsonb_build_object(
                'from_status', OLD.status,
                'to_status', NEW.status
            )
        );
    END IF;

    IF NEW.health_issue_started_at IS NOT NULL
       AND OLD.health_issue_started_at IS NULL
    THEN
        audit_type := CASE
            WHEN NEW.status = 'offline' THEN 'sensor_offline'
            ELSE 'sensor_degraded'
        END;
    ELSIF NEW.health_issue_started_at IS NOT NULL
       AND OLD.health_issue_started_at IS NOT NULL
       AND (
           NEW.status IS DISTINCT FROM OLD.status
           OR NEW.health_reason IS DISTINCT FROM OLD.health_reason
       )
    THEN
        audit_type := 'sensor_health_changed';
    ELSIF OLD.health_issue_started_at IS NOT NULL
       AND NEW.health_issue_started_at IS NULL
       AND NEW.status = 'online'
    THEN
        audit_type := 'sensor_recovered';
    ELSIF OLD.status = 'provisioning' AND NEW.status = 'online' THEN
        audit_type := 'sensor_online';
    ELSE
        audit_type := NULL;
    END IF;

    IF audit_type IS NOT NULL THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, sensor_id, details
        )
        VALUES (
            NOW(),
            audit_type,
            'system',
            NEW.id,
            jsonb_strip_nulls(jsonb_build_object(
                'from_status', OLD.status,
                'to_status', NEW.status,
                'from_reason', OLD.health_reason,
                'reason', NEW.health_reason,
                'issue_started_at', NEW.health_issue_started_at,
                'source_connected', NEW.source_connected,
                'queue_depth', NEW.reported_queue_depth,
                'dead_letter_depth', NEW.reported_dead_letter_depth,
                'quality_window_seconds', NEW.reported_quality_window_seconds,
                'quality_input_lines', NEW.reported_quality_input_lines,
                'quality_ignored_ratio', NEW.reported_quality_ignored_ratio,
                'quality_reconnects', NEW.reported_quality_reconnects,
                'agent_version', NEW.agent_version
            ))
        );
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_health_audit ON sensors;
CREATE TRIGGER trg_sensor_health_audit
AFTER UPDATE OF status, health_reason, health_issue_started_at ON sensors
FOR EACH ROW
WHEN (
    OLD.status IS DISTINCT FROM NEW.status
    OR OLD.health_reason IS DISTINCT FROM NEW.health_reason
    OR OLD.health_issue_started_at IS DISTINCT FROM NEW.health_issue_started_at
)
EXECUTE FUNCTION record_sensor_health_audit_event();

COMMIT;

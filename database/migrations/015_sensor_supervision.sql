BEGIN;

ALTER TABLE sensor_heartbeats
    ADD COLUMN IF NOT EXISTS dead_letter_depth INTEGER,
    ADD COLUMN IF NOT EXISTS agent_version TEXT,
    ADD COLUMN IF NOT EXISTS source_connected BOOLEAN,
    ADD COLUMN IF NOT EXISTS source_last_message_at TIMESTAMPTZ;

ALTER TABLE sensor_heartbeats
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_dead_letter_depth_check,
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_agent_version_length_check;

ALTER TABLE sensor_heartbeats
    ADD CONSTRAINT sensor_heartbeats_dead_letter_depth_check
        CHECK (dead_letter_depth IS NULL OR dead_letter_depth >= 0),
    ADD CONSTRAINT sensor_heartbeats_agent_version_length_check
        CHECK (agent_version IS NULL OR char_length(agent_version) BETWEEN 1 AND 64);

ALTER TABLE sensors
    ADD COLUMN IF NOT EXISTS health_reason TEXT NOT NULL DEFAULT 'awaiting_heartbeat',
    ADD COLUMN IF NOT EXISTS health_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS health_issue_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_heartbeat_received_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_heartbeat_reported_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_observation_received_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS agent_version TEXT,
    ADD COLUMN IF NOT EXISTS source_connected BOOLEAN,
    ADD COLUMN IF NOT EXISTS source_last_message_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reported_queue_depth INTEGER,
    ADD COLUMN IF NOT EXISTS reported_dead_letter_depth INTEGER,
    ADD COLUMN IF NOT EXISTS maintenance_reason TEXT,
    ADD COLUMN IF NOT EXISTS maintenance_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS maintenance_started_by TEXT,
    ADD COLUMN IF NOT EXISTS maintenance_until TIMESTAMPTZ;

ALTER TABLE sensors
    DROP CONSTRAINT IF EXISTS sensors_status_check,
    DROP CONSTRAINT IF EXISTS sensors_health_reason_length_check,
    DROP CONSTRAINT IF EXISTS sensors_agent_version_length_check,
    DROP CONSTRAINT IF EXISTS sensors_reported_queue_depth_check,
    DROP CONSTRAINT IF EXISTS sensors_reported_dead_letter_depth_check,
    DROP CONSTRAINT IF EXISTS sensors_maintenance_metadata_check;

ALTER TABLE sensors
    ADD CONSTRAINT sensors_status_check CHECK (
        status IN (
            'provisioning',
            'online',
            'degraded',
            'offline',
            'maintenance',
            'disabled'
        )
    ),
    ADD CONSTRAINT sensors_health_reason_length_check
        CHECK (char_length(health_reason) BETWEEN 1 AND 128),
    ADD CONSTRAINT sensors_agent_version_length_check
        CHECK (agent_version IS NULL OR char_length(agent_version) BETWEEN 1 AND 64),
    ADD CONSTRAINT sensors_reported_queue_depth_check
        CHECK (reported_queue_depth IS NULL OR reported_queue_depth >= 0),
    ADD CONSTRAINT sensors_reported_dead_letter_depth_check
        CHECK (
            reported_dead_letter_depth IS NULL
            OR reported_dead_letter_depth >= 0
        ),
    ADD CONSTRAINT sensors_maintenance_metadata_check CHECK (
        (
            status = 'maintenance'
            AND maintenance_reason IS NOT NULL
            AND char_length(maintenance_reason) BETWEEN 1 AND 500
            AND maintenance_started_at IS NOT NULL
            AND maintenance_started_by IS NOT NULL
            AND char_length(maintenance_started_by) BETWEEN 1 AND 160
        )
        OR (
            status <> 'maintenance'
            AND maintenance_reason IS NULL
            AND maintenance_started_at IS NULL
            AND maintenance_started_by IS NULL
            AND maintenance_until IS NULL
        )
    );

WITH latest_heartbeat AS (
    SELECT DISTINCT ON (heartbeat.sensor_id)
        heartbeat.sensor_id,
        heartbeat.received_at,
        heartbeat.measured_at,
        heartbeat.queue_depth
    FROM sensor_heartbeats AS heartbeat
    ORDER BY
        heartbeat.sensor_id,
        heartbeat.measured_at DESC,
        heartbeat.received_at DESC
),
latest_observation AS (
    SELECT
        observation.sensor_id,
        MAX(observation.received_at) AS received_at
    FROM observations AS observation
    GROUP BY observation.sensor_id
)
UPDATE sensors AS sensor
SET
    health_reason = CASE sensor.status
        WHEN 'online' THEN 'healthy'
        WHEN 'offline' THEN 'heartbeat_timeout'
        WHEN 'disabled' THEN 'disabled'
        ELSE 'awaiting_heartbeat'
    END,
    health_changed_at = sensor.updated_at,
    health_issue_started_at = CASE
        WHEN sensor.status = 'offline' THEN sensor.updated_at
        ELSE NULL
    END,
    last_heartbeat_received_at = heartbeat.received_at,
    last_heartbeat_reported_at = heartbeat.measured_at,
    last_observation_received_at = observation.received_at,
    reported_queue_depth = heartbeat.queue_depth
FROM latest_heartbeat AS heartbeat
LEFT JOIN latest_observation AS observation
    ON observation.sensor_id = heartbeat.sensor_id
WHERE sensor.id = heartbeat.sensor_id;

UPDATE sensors
SET
    status = CASE
        WHEN status = 'online' THEN 'provisioning'
        ELSE status
    END,
    health_reason = CASE
        WHEN status = 'disabled' THEN 'disabled'
        WHEN status = 'offline' THEN 'heartbeat_timeout'
        ELSE 'awaiting_heartbeat'
    END,
    health_changed_at = updated_at,
    health_issue_started_at = CASE
        WHEN status = 'offline' THEN updated_at
        ELSE NULL
    END
WHERE last_heartbeat_received_at IS NULL;

UPDATE sensors AS sensor
SET last_observation_received_at = observation.received_at
FROM (
    SELECT sensor_id, MAX(received_at) AS received_at
    FROM observations
    GROUP BY sensor_id
) AS observation
WHERE sensor.id = observation.sensor_id
  AND sensor.last_observation_received_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_sensors_health_status
    ON sensors (status, health_changed_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_sensors_health_issue
    ON sensors (health_issue_started_at DESC)
    WHERE health_issue_started_at IS NOT NULL AND deleted_at IS NULL;

CREATE OR REPLACE FUNCTION update_sensor_last_observation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE sensors
    SET last_observation_received_at = GREATEST(
        COALESCE(last_observation_received_at, NEW.received_at),
        NEW.received_at
    )
    WHERE id = NEW.sensor_id;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_last_observation ON observations;
CREATE TRIGGER trg_sensor_last_observation
AFTER INSERT ON observations
FOR EACH ROW
EXECUTE FUNCTION update_sensor_last_observation();

ALTER TABLE audit_events
    DROP CONSTRAINT IF EXISTS audit_events_event_type_check;

ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_event_type_check CHECK (
        event_type IN (
            'track_detected',
            'alert_opened',
            'alert_acknowledged',
            'alert_closed',
            'alert_presence_changed',
            'zone_created',
            'zone_enabled',
            'zone_disabled',
            'zone_updated',
            'zone_deleted',
            'sensor_registered',
            'sensor_enabled',
            'sensor_disabled',
            'sensor_updated',
            'sensor_deleted',
            'sensor_token_issued',
            'sensor_token_rotated',
            'sensor_online',
            'sensor_degraded',
            'sensor_offline',
            'sensor_health_changed',
            'sensor_recovered',
            'sensor_maintenance_started',
            'sensor_maintenance_ended',
            'operator_created',
            'operator_updated',
            'operator_enabled',
            'operator_disabled',
            'operator_deleted',
            'operator_password_changed',
            'operator_logged_in',
            'operator_logged_out',
            'operator_session_revoked',
            'operator_sessions_revoked',
            'operator_security_exported'
        )
    );

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
       AND NEW.status IS DISTINCT FROM OLD.status
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
                'reason', NEW.health_reason,
                'issue_started_at', NEW.health_issue_started_at,
                'source_connected', NEW.source_connected,
                'queue_depth', NEW.reported_queue_depth,
                'dead_letter_depth', NEW.reported_dead_letter_depth,
                'agent_version', NEW.agent_version
            ))
        );
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_health_audit ON sensors;
CREATE TRIGGER trg_sensor_health_audit
AFTER UPDATE OF status, health_issue_started_at ON sensors
FOR EACH ROW
WHEN (
    OLD.status IS DISTINCT FROM NEW.status
    OR OLD.health_issue_started_at IS DISTINCT FROM NEW.health_issue_started_at
)
EXECUTE FUNCTION record_sensor_health_audit_event();

COMMIT;

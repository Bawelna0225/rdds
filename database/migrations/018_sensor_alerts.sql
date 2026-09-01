BEGIN;

CREATE TABLE IF NOT EXISTS sensor_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sensor_id UUID NOT NULL REFERENCES sensors(id) ON DELETE RESTRICT,
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'acknowledged', 'closed')),
    severity TEXT NOT NULL
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    reason TEXT NOT NULL,
    condition_started_at TIMESTAMPTZ NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    occurrence_count BIGINT NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    closed_at TIMESTAMPTZ,
    closed_by TEXT,
    resolution TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (char_length(reason) BETWEEN 1 AND 128),
    CHECK (resolution IS NULL OR char_length(resolution) <= 128),
    CHECK (acknowledged_by IS NULL OR char_length(acknowledged_by) <= 160),
    CHECK (closed_by IS NULL OR char_length(closed_by) <= 160)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sensor_alerts_open_sensor
    ON sensor_alerts (sensor_id)
    WHERE state IN ('active', 'acknowledged');

CREATE INDEX IF NOT EXISTS idx_sensor_alerts_state_severity
    ON sensor_alerts (state, severity, opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_sensor_alerts_sensor_time
    ON sensor_alerts (sensor_id, opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_sensor_alerts_reason_state
    ON sensor_alerts (reason, state, opened_at DESC);

ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS sensor_alert_id UUID
        REFERENCES sensor_alerts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_audit_events_sensor_alert_time
    ON audit_events (sensor_alert_id, occurred_at, id)
    WHERE sensor_alert_id IS NOT NULL;

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
            'sensor_alert_opened',
            'sensor_alert_acknowledged',
            'sensor_alert_reason_changed',
            'sensor_alert_closed',
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

CREATE OR REPLACE FUNCTION record_sensor_alert_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    audit_type TEXT;
    audit_actor TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_events (
            occurred_at,
            event_type,
            actor,
            sensor_id,
            sensor_alert_id,
            details
        )
        VALUES (
            NEW.opened_at,
            'sensor_alert_opened',
            'system',
            NEW.sensor_id,
            NEW.id,
            jsonb_build_object(
                'state', NEW.state,
                'severity', NEW.severity,
                'reason', NEW.reason,
                'condition_started_at', NEW.condition_started_at
            )
        );
        RETURN NEW;
    END IF;

    IF NEW.state IS DISTINCT FROM OLD.state THEN
        IF NEW.state = 'acknowledged' THEN
            audit_type := 'sensor_alert_acknowledged';
            audit_actor := COALESCE(NEW.acknowledged_by, 'system');
        ELSIF NEW.state = 'closed' THEN
            audit_type := 'sensor_alert_closed';
            audit_actor := COALESCE(NEW.closed_by, 'system');
        ELSE
            audit_type := NULL;
        END IF;

        IF audit_type IS NOT NULL THEN
            INSERT INTO audit_events (
                occurred_at,
                event_type,
                actor,
                sensor_id,
                sensor_alert_id,
                details
            )
            VALUES (
                NOW(),
                audit_type,
                audit_actor,
                NEW.sensor_id,
                NEW.id,
                jsonb_strip_nulls(jsonb_build_object(
                    'from_state', OLD.state,
                    'to_state', NEW.state,
                    'severity', NEW.severity,
                    'reason', NEW.reason,
                    'resolution', NEW.resolution
                ))
            );
        END IF;
    END IF;

    IF NEW.reason IS DISTINCT FROM OLD.reason
       AND NEW.state IN ('active', 'acknowledged')
    THEN
        INSERT INTO audit_events (
            occurred_at,
            event_type,
            actor,
            sensor_id,
            sensor_alert_id,
            details
        )
        VALUES (
            NOW(),
            'sensor_alert_reason_changed',
            'system',
            NEW.sensor_id,
            NEW.id,
            jsonb_build_object(
                'from_reason', OLD.reason,
                'reason', NEW.reason,
                'severity', NEW.severity
            )
        );
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_alert_audit ON sensor_alerts;
CREATE TRIGGER trg_sensor_alert_audit
AFTER INSERT OR UPDATE OF state, reason ON sensor_alerts
FOR EACH ROW
EXECUTE FUNCTION record_sensor_alert_audit_event();

COMMIT;

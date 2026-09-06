BEGIN;

ALTER TABLE sensor_alerts
    ADD COLUMN alert_kind TEXT NOT NULL DEFAULT 'health',
    ADD COLUMN condition_details JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE sensor_alerts
    ADD CONSTRAINT sensor_alerts_alert_kind_check
        CHECK (alert_kind IN ('health', 'readiness')),
    ADD CONSTRAINT sensor_alerts_condition_details_check
        CHECK (jsonb_typeof(condition_details) = 'object');

DROP INDEX IF EXISTS uq_sensor_alerts_open_sensor;

CREATE UNIQUE INDEX uq_sensor_alerts_open_sensor_kind
    ON sensor_alerts (sensor_id, alert_kind)
    WHERE state IN ('active', 'acknowledged');

CREATE INDEX idx_sensor_alerts_kind_state
    ON sensor_alerts (alert_kind, state, severity, opened_at DESC);

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
                'alert_kind', NEW.alert_kind,
                'state', NEW.state,
                'severity', NEW.severity,
                'reason', NEW.reason,
                'condition_started_at', NEW.condition_started_at,
                'condition_details', NEW.condition_details
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
                    'alert_kind', NEW.alert_kind,
                    'from_state', OLD.state,
                    'to_state', NEW.state,
                    'severity', NEW.severity,
                    'reason', NEW.reason,
                    'resolution', NEW.resolution,
                    'condition_details', NEW.condition_details
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
                'alert_kind', NEW.alert_kind,
                'from_reason', OLD.reason,
                'reason', NEW.reason,
                'severity', NEW.severity,
                'condition_details', NEW.condition_details
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

BEGIN;

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

CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_events_track_detected
    ON audit_events (track_id)
    WHERE event_type = 'track_detected' AND track_id IS NOT NULL;

CREATE OR REPLACE FUNCTION record_track_detection_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    detection_sensor_id UUID;
BEGIN
    SELECT observation.sensor_id
    INTO detection_sensor_id
    FROM observations AS observation
    WHERE observation.id = NEW.last_observation_id;

    INSERT INTO audit_events (
        occurred_at,
        event_type,
        actor,
        track_id,
        sensor_id,
        details
    )
    VALUES (
        NEW.first_seen_at,
        'track_detected',
        'system',
        NEW.id,
        detection_sensor_id,
        jsonb_strip_nulls(
            jsonb_build_object(
                'track_key', NEW.track_key,
                'entity_key', NEW.entity_key,
                'identity_key', NEW.identity_key,
                'identity_type', NEW.identity_type,
                'basic_id', NEW.last_basic_id,
                'operator_id', NEW.last_operator_id,
                'drone_mac', NEW.last_drone_mac,
                'initial_state', NEW.state
            )
        )
    )
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_track_detection_audit ON tracks;
CREATE TRIGGER trg_track_detection_audit
AFTER INSERT ON tracks
FOR EACH ROW
EXECUTE FUNCTION record_track_detection_audit_event();

COMMIT;

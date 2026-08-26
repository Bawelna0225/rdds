BEGIN;

ALTER TABLE intrusion_alerts
    ADD COLUMN IF NOT EXISTS presence_state TEXT,
    ADD COLUMN IF NOT EXISTS presence_changed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS exited_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS entry_zone_name TEXT,
    ADD COLUMN IF NOT EXISTS entry_zone_description TEXT,
    ADD COLUMN IF NOT EXISTS entry_track_key TEXT,
    ADD COLUMN IF NOT EXISTS entry_identity_key TEXT,
    ADD COLUMN IF NOT EXISTS entry_basic_id TEXT,
    ADD COLUMN IF NOT EXISTS entry_operator_id TEXT,
    ADD COLUMN IF NOT EXISTS entry_drone_mac TEXT,
    ADD COLUMN IF NOT EXISTS entry_sensor_key TEXT,
    ADD COLUMN IF NOT EXISTS entry_position GEOGRAPHY(POINT, 4326),
    ADD COLUMN IF NOT EXISTS entry_pilot_position GEOGRAPHY(POINT, 4326),
    ADD COLUMN IF NOT EXISTS entry_altitude_m DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_speed_mps DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_heading_deg DOUBLE PRECISION;

UPDATE intrusion_alerts AS alert
SET
    presence_state = CASE
        WHEN alert.state <> 'closed'
         AND zone.active
         AND zone.deleted_at IS NULL
         AND track.state IN ('new', 'active', 'anomalous')
         AND track.last_position IS NOT NULL
         AND ST_Intersects(zone.area, track.last_position)
            THEN 'inside'
        WHEN track.state IN ('stale', 'ended') OR track.last_position IS NULL
            THEN 'lost'
        ELSE 'left'
    END,
    presence_changed_at = COALESCE(alert.updated_at, alert.last_detected_at),
    exited_at = CASE
        WHEN alert.state <> 'closed'
         AND zone.active
         AND zone.deleted_at IS NULL
         AND track.state IN ('new', 'active', 'anomalous')
         AND track.last_position IS NOT NULL
         AND ST_Intersects(zone.area, track.last_position)
            THEN NULL
        ELSE alert.last_detected_at
    END,
    entry_zone_name = zone.name,
    entry_zone_description = zone.description,
    entry_track_key = track.track_key,
    entry_identity_key = track.identity_key,
    entry_basic_id = track.last_basic_id,
    entry_operator_id = track.last_operator_id,
    entry_drone_mac = track.last_drone_mac,
    entry_sensor_key = sensor.sensor_key,
    entry_position = COALESCE(alert.last_position, track.last_position),
    entry_pilot_position = track.last_pilot_position,
    entry_altitude_m = track.last_altitude_m,
    entry_speed_mps = track.last_speed_mps,
    entry_heading_deg = track.last_heading_deg
FROM protected_zones AS zone,
tracks AS track
LEFT JOIN observations AS observation ON observation.id = track.last_observation_id
LEFT JOIN sensors AS sensor ON sensor.id = observation.sensor_id
WHERE zone.id = alert.zone_id
  AND track.id = alert.track_id
  AND alert.presence_state IS NULL;

ALTER TABLE intrusion_alerts
    ALTER COLUMN presence_state SET DEFAULT 'inside',
    ALTER COLUMN presence_state SET NOT NULL,
    ALTER COLUMN presence_changed_at SET DEFAULT NOW(),
    ALTER COLUMN presence_changed_at SET NOT NULL;

ALTER TABLE intrusion_alerts
    DROP CONSTRAINT IF EXISTS intrusion_alerts_presence_state_check,
    DROP CONSTRAINT IF EXISTS intrusion_alerts_entry_zone_name_length_check,
    DROP CONSTRAINT IF EXISTS intrusion_alerts_entry_heading_check,
    DROP CONSTRAINT IF EXISTS intrusion_alerts_entry_speed_check;

ALTER TABLE intrusion_alerts
    ADD CONSTRAINT intrusion_alerts_presence_state_check
        CHECK (presence_state IN ('inside', 'left', 'lost')),
    ADD CONSTRAINT intrusion_alerts_entry_zone_name_length_check
        CHECK (entry_zone_name IS NULL OR char_length(entry_zone_name) <= 160),
    ADD CONSTRAINT intrusion_alerts_entry_heading_check
        CHECK (
            entry_heading_deg IS NULL
            OR (entry_heading_deg >= 0 AND entry_heading_deg < 360)
        ),
    ADD CONSTRAINT intrusion_alerts_entry_speed_check
        CHECK (entry_speed_mps IS NULL OR entry_speed_mps >= 0);

CREATE INDEX IF NOT EXISTS idx_intrusion_alerts_presence
    ON intrusion_alerts (presence_state, presence_changed_at DESC)
    WHERE state IN ('active', 'acknowledged');

CREATE INDEX IF NOT EXISTS idx_intrusion_alerts_entry_position
    ON intrusion_alerts USING GIST (entry_position);

ALTER TABLE audit_events
    DROP CONSTRAINT IF EXISTS audit_events_event_type_check;

ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_event_type_check CHECK (
        event_type IN (
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

CREATE OR REPLACE FUNCTION record_alert_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    audit_type TEXT;
    audit_actor TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, alert_id, zone_id, track_id, details
        )
        VALUES (
            NEW.first_detected_at,
            'alert_opened',
            'system',
            NEW.id,
            NEW.zone_id,
            NEW.track_id,
            jsonb_build_object(
                'severity', NEW.severity,
                'state', NEW.state,
                'presence_state', NEW.presence_state
            )
        );
        RETURN NEW;
    END IF;

    IF NEW.state IS DISTINCT FROM OLD.state THEN
        IF NEW.state = 'acknowledged' THEN
            audit_type := 'alert_acknowledged';
            audit_actor := COALESCE(NEW.acknowledged_by, 'system');
        ELSIF NEW.state = 'closed' THEN
            audit_type := 'alert_closed';
            audit_actor := COALESCE(NEW.closed_by, 'system');
        ELSE
            audit_type := NULL;
        END IF;

        IF audit_type IS NOT NULL THEN
            INSERT INTO audit_events (
                occurred_at, event_type, actor, alert_id, zone_id, track_id, details
            )
            VALUES (
                NOW(),
                audit_type,
                audit_actor,
                NEW.id,
                NEW.zone_id,
                NEW.track_id,
                jsonb_build_object(
                    'from_state', OLD.state,
                    'to_state', NEW.state,
                    'severity', NEW.severity,
                    'presence_state', NEW.presence_state
                )
            );
        END IF;
    END IF;

    IF NEW.presence_state IS DISTINCT FROM OLD.presence_state THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, alert_id, zone_id, track_id, details
        )
        VALUES (
            NEW.presence_changed_at,
            'alert_presence_changed',
            'system',
            NEW.id,
            NEW.zone_id,
            NEW.track_id,
            jsonb_build_object(
                'from_presence', OLD.presence_state,
                'to_presence', NEW.presence_state,
                'severity', NEW.severity
            )
        );
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_intrusion_alert_audit ON intrusion_alerts;
CREATE TRIGGER trg_intrusion_alert_audit
AFTER INSERT OR UPDATE OF state, presence_state ON intrusion_alerts
FOR EACH ROW
EXECUTE FUNCTION record_alert_audit_event();

COMMIT;

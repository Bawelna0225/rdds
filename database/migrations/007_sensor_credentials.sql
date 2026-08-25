BEGIN;

ALTER TABLE sensors
    ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT 'system',
    ADD COLUMN IF NOT EXISTS updated_by TEXT NOT NULL DEFAULT 'system',
    ADD COLUMN IF NOT EXISTS heartbeat_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS observation_count BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS sensor_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sensor_id UUID NOT NULL REFERENCES sensors(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    token_prefix TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    CHECK (char_length(token_hash) = 64),
    CHECK (char_length(token_prefix) BETWEEN 8 AND 16),
    CHECK (char_length(created_by) BETWEEN 1 AND 160),
    CHECK (revoked_by IS NULL OR char_length(revoked_by) BETWEEN 1 AND 160),
    CHECK (
        (revoked_at IS NULL AND revoked_by IS NULL)
        OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sensor_credentials_active
    ON sensor_credentials (sensor_id)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_sensor_credentials_sensor_time
    ON sensor_credentials (sensor_id, created_at DESC);

ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS sensor_id UUID
        REFERENCES sensors(id) ON DELETE SET NULL;

ALTER TABLE audit_events
    DROP CONSTRAINT IF EXISTS audit_events_event_type_check;

ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_event_type_check CHECK (
        event_type IN (
            'alert_opened',
            'alert_acknowledged',
            'alert_closed',
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
            'operator_logged_out'
        )
    );

CREATE INDEX IF NOT EXISTS idx_audit_events_sensor_time
    ON audit_events (sensor_id, occurred_at, id)
    WHERE sensor_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS rdds_migration_markers (
    migration_key TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (char_length(migration_key) BETWEEN 1 AND 160)
);

CREATE OR REPLACE FUNCTION increment_sensor_heartbeat_count()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE sensors
    SET heartbeat_count = heartbeat_count + 1
    WHERE id = NEW.sensor_id;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_heartbeat_count ON sensor_heartbeats;
CREATE TRIGGER trg_sensor_heartbeat_count
AFTER INSERT ON sensor_heartbeats
FOR EACH ROW
EXECUTE FUNCTION increment_sensor_heartbeat_count();

CREATE OR REPLACE FUNCTION increment_sensor_observation_count()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE sensors
    SET observation_count = observation_count + 1
    WHERE id = NEW.sensor_id;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_observation_count ON observations;
CREATE TRIGGER trg_sensor_observation_count
AFTER INSERT ON observations
FOR EACH ROW
EXECUTE FUNCTION increment_sensor_observation_count();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM rdds_migration_markers
        WHERE migration_key = '007_sensor_message_counter_triggers'
    ) THEN
        UPDATE sensors AS sensor
        SET
            heartbeat_count = (
                SELECT COUNT(*)
                FROM sensor_heartbeats AS heartbeat
                WHERE heartbeat.sensor_id = sensor.id
            ),
            observation_count = (
                SELECT COUNT(*)
                FROM observations AS observation
                WHERE observation.sensor_id = sensor.id
            );

        INSERT INTO rdds_migration_markers (migration_key)
        VALUES ('007_sensor_message_counter_triggers');
    END IF;
END;
$$;

INSERT INTO audit_events (
    occurred_at,
    event_type,
    actor,
    sensor_id,
    details
)
SELECT
    sensor.created_at,
    'sensor_registered',
    sensor.created_by,
    sensor.id,
    jsonb_build_object(
        'sensor_key', sensor.sensor_key,
        'display_name', sensor.display_name,
        'authentication', 'legacy'
    )
FROM sensors AS sensor
WHERE NOT EXISTS (
    SELECT 1
    FROM audit_events AS event
    WHERE event.sensor_id = sensor.id
      AND event.event_type = 'sensor_registered'
);

CREATE OR REPLACE FUNCTION record_sensor_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    audit_type TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        audit_type := 'sensor_registered';
    ELSIF NEW.status = 'disabled' AND OLD.status IS DISTINCT FROM 'disabled' THEN
        audit_type := 'sensor_disabled';
    ELSIF OLD.status = 'disabled' AND NEW.status IS DISTINCT FROM 'disabled' THEN
        audit_type := 'sensor_enabled';
    ELSE
        RETURN NEW;
    END IF;

    INSERT INTO audit_events (
        occurred_at,
        event_type,
        actor,
        sensor_id,
        details
    )
    VALUES (
        NOW(),
        audit_type,
        CASE WHEN TG_OP = 'INSERT' THEN NEW.created_by ELSE NEW.updated_by END,
        NEW.id,
        jsonb_build_object(
            'sensor_key', NEW.sensor_key,
            'display_name', NEW.display_name,
            'status', NEW.status
        )
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_audit ON sensors;
CREATE TRIGGER trg_sensor_audit
AFTER INSERT OR UPDATE OF status ON sensors
FOR EACH ROW
EXECUTE FUNCTION record_sensor_audit_event();

CREATE OR REPLACE FUNCTION record_sensor_credential_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    audit_type TEXT;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM sensor_credentials AS credential
        WHERE credential.sensor_id = NEW.sensor_id
          AND credential.id <> NEW.id
    ) THEN
        audit_type := 'sensor_token_rotated';
    ELSE
        audit_type := 'sensor_token_issued';
    END IF;

    INSERT INTO audit_events (
        occurred_at,
        event_type,
        actor,
        sensor_id,
        details
    )
    VALUES (
        NEW.created_at,
        audit_type,
        NEW.created_by,
        NEW.sensor_id,
        jsonb_build_object('token_prefix', NEW.token_prefix)
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_credential_audit ON sensor_credentials;
CREATE TRIGGER trg_sensor_credential_audit
AFTER INSERT ON sensor_credentials
FOR EACH ROW
EXECUTE FUNCTION record_sensor_credential_audit_event();

COMMIT;

BEGIN;

ALTER TABLE protected_zones
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT;

ALTER TABLE sensors
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_by TEXT;

ALTER TABLE protected_zones
    DROP CONSTRAINT IF EXISTS protected_zones_deletion_metadata_check;

ALTER TABLE protected_zones
    ADD CONSTRAINT protected_zones_deletion_metadata_check CHECK (
        (deleted_at IS NULL AND deleted_by IS NULL)
        OR (
            deleted_at IS NOT NULL
            AND deleted_by IS NOT NULL
            AND char_length(deleted_by) BETWEEN 1 AND 160
        )
    );

ALTER TABLE sensors
    DROP CONSTRAINT IF EXISTS sensors_deletion_metadata_check;

ALTER TABLE sensors
    ADD CONSTRAINT sensors_deletion_metadata_check CHECK (
        (deleted_at IS NULL AND deleted_by IS NULL)
        OR (
            deleted_at IS NOT NULL
            AND deleted_by IS NOT NULL
            AND char_length(deleted_by) BETWEEN 1 AND 160
        )
    );

CREATE INDEX IF NOT EXISTS idx_protected_zones_visible
    ON protected_zones (active, severity)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_sensors_visible
    ON sensors (sensor_key)
    WHERE deleted_at IS NULL;

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

CREATE OR REPLACE FUNCTION record_zone_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, zone_id, details
        )
        VALUES (
            NOW(),
            'zone_created',
            NEW.created_by,
            NEW.id,
            jsonb_build_object(
                'name', NEW.name,
                'severity', NEW.severity,
                'active', NEW.active
            )
        );
        RETURN NEW;
    END IF;

    IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, zone_id, details
        )
        VALUES (
            NEW.deleted_at,
            'zone_deleted',
            COALESCE(NEW.deleted_by, NEW.updated_by),
            NEW.id,
            jsonb_build_object(
                'name', NEW.name,
                'severity', NEW.severity,
                'active', NEW.active
            )
        );
        RETURN NEW;
    END IF;

    IF NEW.active IS DISTINCT FROM OLD.active THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, zone_id, details
        )
        VALUES (
            NOW(),
            CASE WHEN NEW.active THEN 'zone_enabled' ELSE 'zone_disabled' END,
            NEW.updated_by,
            NEW.id,
            jsonb_build_object(
                'name', NEW.name,
                'severity', NEW.severity,
                'active', NEW.active
            )
        );
    END IF;

    IF NEW.name IS DISTINCT FROM OLD.name
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.severity IS DISTINCT FROM OLD.severity
       OR NOT ST_Equals(NEW.area::geometry, OLD.area::geometry)
    THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, zone_id, details
        )
        VALUES (
            NOW(),
            'zone_updated',
            NEW.updated_by,
            NEW.id,
            jsonb_build_object(
                'name', NEW.name,
                'severity', NEW.severity,
                'active', NEW.active,
                'geometry_changed', NOT ST_Equals(
                    NEW.area::geometry,
                    OLD.area::geometry
                )
            )
        );
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_protected_zone_audit ON protected_zones;
CREATE TRIGGER trg_protected_zone_audit
AFTER INSERT OR UPDATE OF name, description, severity, active, area, deleted_at
ON protected_zones
FOR EACH ROW
EXECUTE FUNCTION record_zone_audit_event();

CREATE OR REPLACE FUNCTION record_sensor_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, sensor_id, details
        )
        VALUES (
            NOW(),
            'sensor_registered',
            NEW.created_by,
            NEW.id,
            jsonb_build_object(
                'sensor_key', NEW.sensor_key,
                'display_name', NEW.display_name,
                'status', NEW.status
            )
        );
        RETURN NEW;
    END IF;

    IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, sensor_id, details
        )
        VALUES (
            NEW.deleted_at,
            'sensor_deleted',
            COALESCE(NEW.deleted_by, NEW.updated_by),
            NEW.id,
            jsonb_build_object(
                'sensor_key', NEW.sensor_key,
                'display_name', NEW.display_name,
                'status', NEW.status
            )
        );
        RETURN NEW;
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status
       AND (NEW.status = 'disabled' OR OLD.status = 'disabled')
    THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, sensor_id, details
        )
        VALUES (
            NOW(),
            CASE
                WHEN NEW.status = 'disabled' THEN 'sensor_disabled'
                WHEN OLD.status = 'disabled' THEN 'sensor_enabled'
                ELSE NULL
            END,
            NEW.updated_by,
            NEW.id,
            jsonb_build_object(
                'sensor_key', NEW.sensor_key,
                'display_name', NEW.display_name,
                'status', NEW.status
            )
        );
    END IF;

    IF NEW.display_name IS DISTINCT FROM OLD.display_name
       OR (NEW.fixed_position IS NULL) IS DISTINCT FROM
          (OLD.fixed_position IS NULL)
       OR (
           NEW.fixed_position IS NOT NULL
           AND OLD.fixed_position IS NOT NULL
           AND NOT ST_Equals(
               NEW.fixed_position::geometry,
               OLD.fixed_position::geometry
           )
       )
    THEN
        INSERT INTO audit_events (
            occurred_at, event_type, actor, sensor_id, details
        )
        VALUES (
            NOW(),
            'sensor_updated',
            NEW.updated_by,
            NEW.id,
            jsonb_build_object(
                'sensor_key', NEW.sensor_key,
                'display_name', NEW.display_name,
                'position_changed',
                    (NEW.fixed_position IS NULL) IS DISTINCT FROM
                    (OLD.fixed_position IS NULL)
                    OR (
                        NEW.fixed_position IS NOT NULL
                        AND OLD.fixed_position IS NOT NULL
                        AND NOT ST_Equals(
                            NEW.fixed_position::geometry,
                            OLD.fixed_position::geometry
                        )
                    )
            )
        );
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_sensor_audit ON sensors;
CREATE TRIGGER trg_sensor_audit
AFTER INSERT OR UPDATE OF status, display_name, fixed_position, deleted_at
ON sensors
FOR EACH ROW
EXECUTE FUNCTION record_sensor_audit_event();

COMMIT;

BEGIN;

ALTER TABLE protected_zones
    ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT 'system',
    ADD COLUMN IF NOT EXISTS updated_by TEXT NOT NULL DEFAULT 'system';

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'alert_opened',
            'alert_acknowledged',
            'alert_closed',
            'zone_created',
            'zone_enabled',
            'zone_disabled'
        )
    ),
    actor TEXT NOT NULL DEFAULT 'system',
    alert_id UUID REFERENCES intrusion_alerts(id) ON DELETE SET NULL,
    zone_id UUID REFERENCES protected_zones(id) ON DELETE SET NULL,
    track_id UUID REFERENCES tracks(id) ON DELETE SET NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (char_length(actor) BETWEEN 1 AND 160)
);

CREATE INDEX IF NOT EXISTS idx_audit_events_time
    ON audit_events (occurred_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_audit_events_type_time
    ON audit_events (event_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_events_alert_time
    ON audit_events (alert_id, occurred_at, id)
    WHERE alert_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_events_zone_time
    ON audit_events (zone_id, occurred_at, id)
    WHERE zone_id IS NOT NULL;

INSERT INTO audit_events (
    occurred_at,
    event_type,
    actor,
    alert_id,
    zone_id,
    track_id,
    details
)
SELECT
    alert.first_detected_at,
    'alert_opened',
    'system',
    alert.id,
    alert.zone_id,
    alert.track_id,
    jsonb_build_object('severity', alert.severity, 'state', 'active')
FROM intrusion_alerts AS alert
WHERE NOT EXISTS (
    SELECT 1
    FROM audit_events AS event
    WHERE event.alert_id = alert.id
      AND event.event_type = 'alert_opened'
);

INSERT INTO audit_events (
    occurred_at,
    event_type,
    actor,
    alert_id,
    zone_id,
    track_id,
    details
)
SELECT
    alert.acknowledged_at,
    'alert_acknowledged',
    COALESCE(alert.acknowledged_by, 'system'),
    alert.id,
    alert.zone_id,
    alert.track_id,
    jsonb_build_object('from_state', 'active', 'to_state', 'acknowledged')
FROM intrusion_alerts AS alert
WHERE alert.acknowledged_at IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM audit_events AS event
      WHERE event.alert_id = alert.id
        AND event.event_type = 'alert_acknowledged'
  );

INSERT INTO audit_events (
    occurred_at,
    event_type,
    actor,
    alert_id,
    zone_id,
    track_id,
    details
)
SELECT
    alert.closed_at,
    'alert_closed',
    COALESCE(alert.closed_by, 'system'),
    alert.id,
    alert.zone_id,
    alert.track_id,
    jsonb_build_object(
        'from_state',
        CASE
            WHEN alert.acknowledged_at IS NOT NULL
             AND alert.acknowledged_at <= alert.closed_at
                THEN 'acknowledged'
            ELSE 'active'
        END,
        'to_state',
        'closed'
    )
FROM intrusion_alerts AS alert
WHERE alert.closed_at IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM audit_events AS event
      WHERE event.alert_id = alert.id
        AND event.event_type = 'alert_closed'
  );

INSERT INTO audit_events (
    occurred_at,
    event_type,
    actor,
    zone_id,
    details
)
SELECT
    zone.created_at,
    'zone_created',
    zone.created_by,
    zone.id,
    jsonb_build_object(
        'name', zone.name,
        'severity', zone.severity,
        'active', zone.active
    )
FROM protected_zones AS zone
WHERE NOT EXISTS (
    SELECT 1
    FROM audit_events AS event
    WHERE event.zone_id = zone.id
      AND event.event_type = 'zone_created'
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
            occurred_at,
            event_type,
            actor,
            alert_id,
            zone_id,
            track_id,
            details
        )
        VALUES (
            NEW.first_detected_at,
            'alert_opened',
            'system',
            NEW.id,
            NEW.zone_id,
            NEW.track_id,
            jsonb_build_object('severity', NEW.severity, 'state', NEW.state)
        );
        RETURN NEW;
    END IF;

    IF NEW.state IS NOT DISTINCT FROM OLD.state THEN
        RETURN NEW;
    END IF;

    IF NEW.state = 'acknowledged' THEN
        audit_type := 'alert_acknowledged';
        audit_actor := COALESCE(NEW.acknowledged_by, 'system');
    ELSIF NEW.state = 'closed' THEN
        audit_type := 'alert_closed';
        audit_actor := COALESCE(NEW.closed_by, 'system');
    ELSE
        RETURN NEW;
    END IF;

    INSERT INTO audit_events (
        occurred_at,
        event_type,
        actor,
        alert_id,
        zone_id,
        track_id,
        details
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
            'severity', NEW.severity
        )
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_intrusion_alert_audit ON intrusion_alerts;
CREATE TRIGGER trg_intrusion_alert_audit
AFTER INSERT OR UPDATE OF state ON intrusion_alerts
FOR EACH ROW
EXECUTE FUNCTION record_alert_audit_event();

CREATE OR REPLACE FUNCTION record_zone_audit_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    audit_type TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        audit_type := 'zone_created';
    ELSIF NEW.active IS DISTINCT FROM OLD.active THEN
        audit_type := CASE WHEN NEW.active THEN 'zone_enabled' ELSE 'zone_disabled' END;
    ELSE
        RETURN NEW;
    END IF;

    INSERT INTO audit_events (
        occurred_at,
        event_type,
        actor,
        zone_id,
        details
    )
    VALUES (
        NOW(),
        audit_type,
        CASE WHEN TG_OP = 'INSERT' THEN NEW.created_by ELSE NEW.updated_by END,
        NEW.id,
        jsonb_build_object(
            'name', NEW.name,
            'severity', NEW.severity,
            'active', NEW.active
        )
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_protected_zone_audit ON protected_zones;
CREATE TRIGGER trg_protected_zone_audit
AFTER INSERT OR UPDATE OF active ON protected_zones
FOR EACH ROW
EXECUTE FUNCTION record_zone_audit_event();

COMMIT;

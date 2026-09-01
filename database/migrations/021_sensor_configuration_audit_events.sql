BEGIN;

-- Stage 23 introduces configuration lifecycle audit events. The audit table
-- intentionally uses an allow-list, so every new event type must be added to
-- the constraint explicitly.
ALTER TABLE audit_events
    DROP CONSTRAINT audit_events_event_type_check;

ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_event_type_check
    CHECK (
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
            'operator_security_exported',
            'sensor_configuration_changed',
            'sensor_configuration_applied',
            'sensor_configuration_failed'
        )
    );

COMMIT;

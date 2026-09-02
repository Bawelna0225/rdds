BEGIN;

CREATE TABLE sensor_configuration_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_key TEXT NOT NULL UNIQUE
        CHECK (
            char_length(profile_key) BETWEEN 3 AND 64
            AND profile_key ~ '^[a-z0-9][a-z0-9._-]{2,63}$'
        ),
    display_name TEXT NOT NULL
        CHECK (char_length(display_name) BETWEEN 1 AND 160),
    description TEXT
        CHECK (description IS NULL OR char_length(description) <= 1000),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    current_version BIGINT NOT NULL DEFAULT 1
        CHECK (current_version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL
        CHECK (char_length(created_by) BETWEEN 1 AND 160),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT NOT NULL
        CHECK (char_length(updated_by) BETWEEN 1 AND 160),
    UNIQUE (id, current_version)
);

CREATE TABLE sensor_configuration_profile_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL
        REFERENCES sensor_configuration_profiles(id) ON DELETE CASCADE,
    version BIGINT NOT NULL CHECK (version >= 1),
    configuration JSONB NOT NULL
        CHECK (jsonb_typeof(configuration) = 'object'),
    change_note TEXT NOT NULL
        CHECK (char_length(change_note) BETWEEN 3 AND 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL
        CHECK (char_length(created_by) BETWEEN 1 AND 160),
    UNIQUE (profile_id, version)
);

ALTER TABLE sensor_configuration_profiles
    ADD CONSTRAINT sensor_configuration_profiles_current_version_fkey
    FOREIGN KEY (id, current_version)
    REFERENCES sensor_configuration_profile_versions(profile_id, version)
    DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX idx_sensor_configuration_profiles_enabled_name
    ON sensor_configuration_profiles (enabled, display_name, profile_key);

CREATE INDEX idx_sensor_configuration_profile_versions_history
    ON sensor_configuration_profile_versions (profile_id, version DESC);

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
            'sensor_configuration_failed',
            'sensor_configuration_profile_created',
            'sensor_configuration_profile_updated',
            'sensor_configuration_profile_version_created'
        )
    );

COMMIT;

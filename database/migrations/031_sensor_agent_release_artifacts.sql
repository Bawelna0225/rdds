BEGIN;

CREATE TABLE sensor_agent_release_artifacts (
    release_id UUID PRIMARY KEY
        REFERENCES sensor_agent_releases(id) ON DELETE CASCADE,
    release_revision BIGINT NOT NULL CHECK (release_revision >= 1),
    artifact_filename TEXT NOT NULL
        CHECK (artifact_filename ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$'),
    artifact_sha256 TEXT NOT NULL
        CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    artifact_size_bytes BIGINT NOT NULL
        CHECK (artifact_size_bytes BETWEEN 1 AND 536870912),
    storage_key TEXT NOT NULL
        CHECK (storage_key ~ '^[0-9a-f]{2}/[0-9a-f]{64}$'),
    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verified_by TEXT NOT NULL CHECK (char_length(verified_by) BETWEEN 1 AND 160)
);

CREATE INDEX idx_sensor_agent_release_artifacts_storage_key
    ON sensor_agent_release_artifacts (storage_key);

ALTER TABLE audit_events
    DROP CONSTRAINT audit_events_event_type_check;

ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_event_type_check
    CHECK (
        event_type IN (
            'track_detected', 'alert_opened', 'alert_acknowledged', 'alert_closed',
            'alert_presence_changed', 'zone_created', 'zone_enabled', 'zone_disabled',
            'zone_updated', 'zone_deleted', 'sensor_registered', 'sensor_enabled',
            'sensor_disabled', 'sensor_updated', 'sensor_deleted',
            'sensor_token_issued', 'sensor_token_rotated', 'sensor_online',
            'sensor_degraded', 'sensor_offline', 'sensor_health_changed',
            'sensor_recovered', 'sensor_maintenance_started',
            'sensor_maintenance_ended', 'sensor_alert_opened',
            'sensor_alert_acknowledged', 'sensor_alert_reason_changed',
            'sensor_alert_closed', 'operator_created', 'operator_updated',
            'operator_enabled', 'operator_disabled', 'operator_deleted',
            'operator_password_changed', 'operator_logged_in', 'operator_logged_out',
            'operator_session_revoked', 'operator_sessions_revoked',
            'operator_security_exported', 'sensor_configuration_changed',
            'sensor_configuration_applied', 'sensor_configuration_failed',
            'sensor_configuration_profile_created',
            'sensor_configuration_profile_updated',
            'sensor_configuration_profile_version_created',
            'sensor_configuration_profile_assigned',
            'sensor_configuration_profile_unassigned',
            'sensor_configuration_rollout_created',
            'sensor_configuration_rollout_started',
            'sensor_configuration_rollout_batch_deployed',
            'sensor_configuration_rollout_completed',
            'sensor_configuration_rollout_cancelled',
            'sensor_configuration_rollout_rolled_back',
            'sensor_configuration_rollout_paused',
            'sensor_configuration_rollout_resumed',
            'sensor_fleet_readiness_policy_changed',
            'sensor_agent_release_created', 'sensor_agent_release_updated',
            'sensor_agent_release_published', 'sensor_agent_release_withdrawn',
            'sensor_agent_update_plan_created', 'sensor_agent_update_plan_cancelled',
            'sensor_agent_release_artifact_verified'
        )
    );

COMMIT;

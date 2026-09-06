BEGIN;

CREATE TABLE sensor_agent_releases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version TEXT NOT NULL UNIQUE
        CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$')
        CHECK (char_length(version) BETWEEN 5 AND 32),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    channel TEXT NOT NULL CHECK (channel IN ('stable', 'candidate')),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'published', 'withdrawn')),
    artifact_filename TEXT NOT NULL
        CHECK (artifact_filename ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$'),
    artifact_sha256 TEXT NOT NULL
        CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    artifact_size_bytes BIGINT NOT NULL
        CHECK (artifact_size_bytes BETWEEN 1 AND 536870912),
    minimum_agent_version TEXT NOT NULL
        CHECK (minimum_agent_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$')
        CHECK (char_length(minimum_agent_version) BETWEEN 5 AND 32),
    protocol_version TEXT NOT NULL
        CHECK (protocol_version ~ '^rdds/[0-9]+\.[0-9]+$')
        CHECK (char_length(protocol_version) BETWEEN 8 AND 32),
    release_notes TEXT NOT NULL
        CHECK (char_length(release_notes) BETWEEN 3 AND 5000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 160),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT NOT NULL CHECK (char_length(updated_by) BETWEEN 1 AND 160),
    published_at TIMESTAMPTZ,
    published_by TEXT
        CHECK (published_by IS NULL OR char_length(published_by) BETWEEN 1 AND 160),
    withdrawn_at TIMESTAMPTZ,
    withdrawn_by TEXT
        CHECK (withdrawn_by IS NULL OR char_length(withdrawn_by) BETWEEN 1 AND 160),
    withdrawal_reason TEXT
        CHECK (
            withdrawal_reason IS NULL
            OR char_length(withdrawal_reason) BETWEEN 3 AND 500
        ),
    CHECK (created_at <= updated_at),
    CHECK (
        (
            status = 'draft'
            AND published_at IS NULL
            AND published_by IS NULL
            AND withdrawn_at IS NULL
            AND withdrawn_by IS NULL
            AND withdrawal_reason IS NULL
        )
        OR (
            status = 'published'
            AND published_at IS NOT NULL
            AND published_by IS NOT NULL
            AND withdrawn_at IS NULL
            AND withdrawn_by IS NULL
            AND withdrawal_reason IS NULL
        )
        OR (
            status = 'withdrawn'
            AND published_at IS NOT NULL
            AND published_by IS NOT NULL
            AND withdrawn_at IS NOT NULL
            AND withdrawn_by IS NOT NULL
            AND withdrawal_reason IS NOT NULL
            AND published_at <= withdrawn_at
        )
    )
);

CREATE INDEX idx_sensor_agent_releases_status_channel
    ON sensor_agent_releases (status, channel, created_at DESC);

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
            'sensor_agent_release_created',
            'sensor_agent_release_updated',
            'sensor_agent_release_published',
            'sensor_agent_release_withdrawn'
        )
    );

COMMIT;

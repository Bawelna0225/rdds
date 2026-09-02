BEGIN;

CREATE TABLE sensor_configuration_rollouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL,
    profile_version BIGINT NOT NULL CHECK (profile_version >= 1),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'completed', 'cancelled')),
    batch_size INTEGER NOT NULL CHECK (batch_size BETWEEN 1 AND 25),
    target_count INTEGER NOT NULL CHECK (target_count BETWEEN 1 AND 100),
    change_note TEXT NOT NULL
        CHECK (char_length(change_note) BETWEEN 3 AND 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL
        CHECK (char_length(created_by) BETWEEN 1 AND 160),
    started_at TIMESTAMPTZ,
    started_by TEXT
        CHECK (started_by IS NULL OR char_length(started_by) BETWEEN 1 AND 160),
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancelled_by TEXT
        CHECK (cancelled_by IS NULL OR char_length(cancelled_by) BETWEEN 1 AND 160),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (profile_id, profile_version)
        REFERENCES sensor_configuration_profile_versions(profile_id, version),
    CHECK (
        (status = 'draft' AND started_at IS NULL AND completed_at IS NULL
            AND cancelled_at IS NULL)
        OR (status = 'active' AND started_at IS NOT NULL AND completed_at IS NULL
            AND cancelled_at IS NULL)
        OR (status = 'completed' AND started_at IS NOT NULL
            AND completed_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'cancelled' AND completed_at IS NULL
            AND cancelled_at IS NOT NULL)
    ),
    CHECK ((started_at IS NULL) = (started_by IS NULL)),
    CHECK ((cancelled_at IS NULL) = (cancelled_by IS NULL))
);

CREATE TABLE sensor_configuration_rollout_targets (
    rollout_id UUID NOT NULL
        REFERENCES sensor_configuration_rollouts(id) ON DELETE CASCADE,
    sensor_id UUID NOT NULL
        REFERENCES sensors(id),
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    desired_revision BIGINT
        CHECK (desired_revision IS NULL OR desired_revision >= 1),
    previous_desired_revision BIGINT
        CHECK (
            previous_desired_revision IS NULL
            OR previous_desired_revision >= 0
        ),
    previous_desired_config JSONB
        CHECK (
            previous_desired_config IS NULL
            OR jsonb_typeof(previous_desired_config) = 'object'
        ),
    previous_profile_id UUID,
    previous_profile_version BIGINT,
    previous_rollout_id UUID,
    deployed_at TIMESTAMPTZ,
    deployed_by TEXT
        CHECK (deployed_by IS NULL OR char_length(deployed_by) BETWEEN 1 AND 160),
    PRIMARY KEY (rollout_id, sensor_id),
    UNIQUE (rollout_id, sequence),
    FOREIGN KEY (previous_profile_id, previous_profile_version)
        REFERENCES sensor_configuration_profile_versions(profile_id, version),
    FOREIGN KEY (previous_rollout_id)
        REFERENCES sensor_configuration_rollouts(id),
    CHECK (
        (desired_revision IS NULL
            AND previous_desired_revision IS NULL
            AND previous_desired_config IS NULL
            AND deployed_at IS NULL
            AND deployed_by IS NULL)
        OR (desired_revision IS NOT NULL
            AND previous_desired_revision IS NOT NULL
            AND previous_desired_config IS NOT NULL
            AND deployed_at IS NOT NULL
            AND deployed_by IS NOT NULL)
    ),
    CHECK (
        (previous_profile_id IS NULL
            AND previous_profile_version IS NULL
            AND previous_rollout_id IS NULL)
        OR (previous_profile_id IS NOT NULL
            AND previous_profile_version IS NOT NULL
            AND previous_rollout_id IS NOT NULL)
    )
);

CREATE TABLE sensor_configuration_profile_assignments (
    sensor_id UUID PRIMARY KEY
        REFERENCES sensors(id) ON DELETE CASCADE,
    profile_id UUID NOT NULL,
    profile_version BIGINT NOT NULL CHECK (profile_version >= 1),
    rollout_id UUID NOT NULL,
    desired_revision BIGINT NOT NULL CHECK (desired_revision >= 1),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by TEXT NOT NULL
        CHECK (char_length(assigned_by) BETWEEN 1 AND 160),
    FOREIGN KEY (profile_id, profile_version)
        REFERENCES sensor_configuration_profile_versions(profile_id, version),
    FOREIGN KEY (rollout_id, sensor_id)
        REFERENCES sensor_configuration_rollout_targets(rollout_id, sensor_id)
);

CREATE INDEX idx_sensor_configuration_rollouts_status_created
    ON sensor_configuration_rollouts (status, created_at DESC);

CREATE INDEX idx_sensor_configuration_rollout_targets_sensor
    ON sensor_configuration_rollout_targets (sensor_id, rollout_id);

CREATE INDEX idx_sensor_configuration_assignments_profile
    ON sensor_configuration_profile_assignments (profile_id, profile_version);

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
            'sensor_configuration_rollout_cancelled'
        )
    );

COMMIT;

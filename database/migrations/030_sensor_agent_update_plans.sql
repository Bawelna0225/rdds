BEGIN;

CREATE TABLE sensor_agent_update_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'cancelled')),
    release_id UUID NOT NULL
        REFERENCES sensor_agent_releases(id) ON DELETE RESTRICT,
    release_version TEXT NOT NULL
        CHECK (release_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    release_channel TEXT NOT NULL
        CHECK (release_channel IN ('stable', 'candidate')),
    release_artifact_sha256 TEXT NOT NULL
        CHECK (release_artifact_sha256 ~ '^[0-9a-f]{64}$'),
    release_minimum_agent_version TEXT NOT NULL
        CHECK (release_minimum_agent_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    release_protocol_version TEXT NOT NULL
        CHECK (release_protocol_version ~ '^rdds/[0-9]+\.[0-9]+$'),
    target_count INTEGER NOT NULL CHECK (target_count BETWEEN 1 AND 100),
    eligible_count INTEGER NOT NULL
        CHECK (eligible_count BETWEEN 0 AND target_count),
    change_note TEXT NOT NULL
        CHECK (char_length(change_note) BETWEEN 3 AND 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL CHECK (char_length(created_by) BETWEEN 1 AND 160),
    cancelled_at TIMESTAMPTZ,
    cancelled_by TEXT
        CHECK (cancelled_by IS NULL OR char_length(cancelled_by) BETWEEN 1 AND 160),
    cancellation_reason TEXT
        CHECK (
            cancellation_reason IS NULL
            OR char_length(cancellation_reason) BETWEEN 3 AND 500
        ),
    CHECK (
        (
            status = 'draft'
            AND cancelled_at IS NULL
            AND cancelled_by IS NULL
            AND cancellation_reason IS NULL
        )
        OR (
            status = 'cancelled'
            AND cancelled_at IS NOT NULL
            AND cancelled_by IS NOT NULL
            AND cancellation_reason IS NOT NULL
            AND created_at <= cancelled_at
        )
    )
);

CREATE TABLE sensor_agent_update_plan_targets (
    plan_id UUID NOT NULL
        REFERENCES sensor_agent_update_plans(id) ON DELETE CASCADE,
    sensor_id UUID NOT NULL REFERENCES sensors(id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence BETWEEN 1 AND 100),
    sensor_key TEXT NOT NULL CHECK (char_length(sensor_key) BETWEEN 3 AND 128),
    sensor_status TEXT NOT NULL
        CHECK (
            sensor_status IN (
                'provisioning',
                'online',
                'degraded',
                'offline',
                'maintenance',
                'disabled'
            )
        ),
    reported_agent_version TEXT
        CHECK (
            reported_agent_version IS NULL
            OR char_length(reported_agent_version) BETWEEN 1 AND 64
        ),
    eligibility_status TEXT NOT NULL
        CHECK (
            eligibility_status IN (
                'eligible',
                'already_current',
                'below_minimum',
                'ahead',
                'unreported',
                'inactive'
            )
        ),
    update_eligible BOOLEAN NOT NULL,
    reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reason_codes) = 'array'),
    assessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (plan_id, sensor_id),
    UNIQUE (plan_id, sequence)
);

CREATE INDEX idx_sensor_agent_update_plans_status_created
    ON sensor_agent_update_plans (status, created_at DESC);

CREATE INDEX idx_sensor_agent_update_plan_targets_sensor
    ON sensor_agent_update_plan_targets (sensor_id, assessed_at DESC);

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
            'sensor_agent_release_withdrawn',
            'sensor_agent_update_plan_created',
            'sensor_agent_update_plan_cancelled'
        )
    );

COMMIT;

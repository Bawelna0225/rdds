BEGIN;

ALTER TABLE sensor_fleet_readiness_policy
    ADD COLUMN rollout_application_timeout_seconds INTEGER NOT NULL DEFAULT 120
        CHECK (rollout_application_timeout_seconds BETWEEN 30 AND 3600);

ALTER TABLE sensor_configuration_rollouts
    ADD COLUMN paused_at TIMESTAMPTZ,
    ADD COLUMN paused_by TEXT
        CHECK (
            paused_by IS NULL
            OR char_length(paused_by) BETWEEN 1 AND 160
        ),
    ADD COLUMN pause_reason JSONB
        CHECK (
            pause_reason IS NULL
            OR jsonb_typeof(pause_reason) = 'object'
        ),
    ADD COLUMN pause_policy_revision BIGINT
        CHECK (
            pause_policy_revision IS NULL
            OR pause_policy_revision >= 1
        ),
    ADD COLUMN resume_count INTEGER NOT NULL DEFAULT 0
        CHECK (resume_count >= 0);

DO $$
DECLARE
    constraint_row RECORD;
BEGIN
    FOR constraint_row IN
        SELECT constraint_definition.conname
        FROM pg_constraint AS constraint_definition
        WHERE constraint_definition.conrelid =
                'sensor_configuration_rollouts'::REGCLASS
          AND constraint_definition.contype = 'c'
          AND pg_get_constraintdef(constraint_definition.oid) LIKE '%draft%'
    LOOP
        EXECUTE format(
            'ALTER TABLE sensor_configuration_rollouts DROP CONSTRAINT %I',
            constraint_row.conname
        );
    END LOOP;
END
$$;

ALTER TABLE sensor_configuration_rollouts
    ADD CONSTRAINT sensor_configuration_rollouts_status_check
        CHECK (
            status IN ('draft', 'active', 'paused', 'completed', 'cancelled')
        ),
    ADD CONSTRAINT sensor_configuration_rollouts_lifecycle_check
        CHECK (
            (
                status = 'draft'
                AND started_at IS NULL
                AND completed_at IS NULL
                AND cancelled_at IS NULL
                AND paused_at IS NULL
                AND paused_by IS NULL
                AND pause_reason IS NULL
                AND pause_policy_revision IS NULL
            )
            OR (
                status = 'active'
                AND started_at IS NOT NULL
                AND completed_at IS NULL
                AND cancelled_at IS NULL
                AND paused_at IS NULL
                AND paused_by IS NULL
                AND pause_reason IS NULL
                AND pause_policy_revision IS NULL
            )
            OR (
                status = 'paused'
                AND started_at IS NOT NULL
                AND completed_at IS NULL
                AND cancelled_at IS NULL
                AND paused_at IS NOT NULL
                AND paused_by IS NOT NULL
                AND pause_reason IS NOT NULL
                AND pause_policy_revision IS NOT NULL
            )
            OR (
                status = 'completed'
                AND started_at IS NOT NULL
                AND completed_at IS NOT NULL
                AND cancelled_at IS NULL
                AND paused_at IS NULL
                AND paused_by IS NULL
                AND pause_reason IS NULL
                AND pause_policy_revision IS NULL
            )
            OR (
                status = 'cancelled'
                AND completed_at IS NULL
                AND cancelled_at IS NOT NULL
                AND paused_at IS NULL
                AND paused_by IS NULL
                AND pause_reason IS NULL
                AND pause_policy_revision IS NULL
            )
        );

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
            'sensor_fleet_readiness_policy_changed'
        )
    );

COMMIT;

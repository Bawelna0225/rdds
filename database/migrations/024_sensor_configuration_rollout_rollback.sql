BEGIN;

ALTER TABLE sensor_configuration_rollouts
    ADD COLUMN rolled_back_at TIMESTAMPTZ,
    ADD COLUMN rolled_back_by TEXT
        CHECK (
            rolled_back_by IS NULL
            OR char_length(rolled_back_by) BETWEEN 1 AND 160
        ),
    ADD COLUMN rollback_note TEXT
        CHECK (
            rollback_note IS NULL
            OR char_length(rollback_note) BETWEEN 3 AND 500
        ),
    ADD CONSTRAINT sensor_configuration_rollouts_rollback_state_check
        CHECK (
            (
                rolled_back_at IS NULL
                AND rolled_back_by IS NULL
                AND rollback_note IS NULL
            )
            OR (
                rolled_back_at IS NOT NULL
                AND rolled_back_by IS NOT NULL
                AND rollback_note IS NOT NULL
                AND status IN ('completed', 'cancelled')
            )
        );

ALTER TABLE sensor_configuration_rollout_targets
    ADD COLUMN rollback_revision BIGINT
        CHECK (rollback_revision IS NULL OR rollback_revision >= 1),
    ADD COLUMN rolled_back_at TIMESTAMPTZ,
    ADD COLUMN rolled_back_by TEXT
        CHECK (
            rolled_back_by IS NULL
            OR char_length(rolled_back_by) BETWEEN 1 AND 160
        ),
    ADD CONSTRAINT sensor_configuration_rollout_targets_rollback_state_check
        CHECK (
            (
                rollback_revision IS NULL
                AND rolled_back_at IS NULL
                AND rolled_back_by IS NULL
            )
            OR (
                rollback_revision IS NOT NULL
                AND desired_revision IS NOT NULL
                AND rollback_revision > desired_revision
                AND rolled_back_at IS NOT NULL
                AND rolled_back_by IS NOT NULL
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
            'sensor_configuration_rollout_rolled_back'
        )
    );

COMMIT;

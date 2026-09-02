BEGIN;

CREATE TABLE sensor_fleet_readiness_policy (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
    minimum_agent_version TEXT NOT NULL DEFAULT '0.23.0'
        CHECK (
            char_length(minimum_agent_version) BETWEEN 5 AND 32
            AND minimum_agent_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'
        ),
    recommended_agent_version TEXT NOT NULL DEFAULT '0.23.0'
        CHECK (
            char_length(recommended_agent_version) BETWEEN 5 AND 32
            AND recommended_agent_version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'
        ),
    require_source_connected BOOLEAN NOT NULL DEFAULT TRUE,
    require_configuration_compliance BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by TEXT NOT NULL
        CHECK (char_length(updated_by) BETWEEN 1 AND 160),
    CHECK (
        (
            split_part(recommended_agent_version, '.', 1)::NUMERIC,
            split_part(recommended_agent_version, '.', 2)::NUMERIC,
            split_part(recommended_agent_version, '.', 3)::NUMERIC
        ) >= (
            split_part(minimum_agent_version, '.', 1)::NUMERIC,
            split_part(minimum_agent_version, '.', 2)::NUMERIC,
            split_part(minimum_agent_version, '.', 3)::NUMERIC
        )
    )
);

INSERT INTO sensor_fleet_readiness_policy (
    id,
    revision,
    minimum_agent_version,
    recommended_agent_version,
    require_source_connected,
    require_configuration_compliance,
    updated_by
)
VALUES (1, 1, '0.23.0', '0.23.0', TRUE, TRUE, 'migration:025');

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
            'sensor_fleet_readiness_policy_changed'
        )
    );

COMMIT;

BEGIN;

CREATE TABLE sensor_fleet_readiness_state (
    sensor_id UUID PRIMARY KEY REFERENCES sensors(id) ON DELETE RESTRICT,
    policy_revision BIGINT NOT NULL CHECK (policy_revision >= 1),
    readiness_status TEXT NOT NULL
        CHECK (readiness_status IN ('ready', 'attention', 'blocked', 'excluded')),
    rollout_eligible BOOLEAN NOT NULL,
    agent_version_state TEXT NOT NULL
        CHECK (
            agent_version_state IN (
                'not_assessed',
                'unknown',
                'below_minimum',
                'below_recommended',
                'compliant'
            )
        ),
    reasons JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reasons) = 'array'),
    first_observed_at TIMESTAMPTZ NOT NULL,
    state_changed_at TIMESTAMPTZ NOT NULL,
    last_evaluated_at TIMESTAMPTZ NOT NULL,
    CHECK (rollout_eligible = (readiness_status = 'ready')),
    CHECK (first_observed_at <= state_changed_at),
    CHECK (state_changed_at <= last_evaluated_at)
);

CREATE INDEX idx_sensor_fleet_readiness_state_status
    ON sensor_fleet_readiness_state (
        readiness_status,
        state_changed_at DESC
    );

CREATE TABLE sensor_fleet_readiness_history (
    id BIGSERIAL PRIMARY KEY,
    sensor_id UUID NOT NULL REFERENCES sensors(id) ON DELETE RESTRICT,
    policy_revision BIGINT NOT NULL CHECK (policy_revision >= 1),
    change_type TEXT NOT NULL CHECK (change_type IN ('initial', 'changed')),
    previous_readiness_status TEXT
        CHECK (
            previous_readiness_status IS NULL
            OR previous_readiness_status IN (
                'ready', 'attention', 'blocked', 'excluded'
            )
        ),
    readiness_status TEXT NOT NULL
        CHECK (readiness_status IN ('ready', 'attention', 'blocked', 'excluded')),
    previous_rollout_eligible BOOLEAN,
    rollout_eligible BOOLEAN NOT NULL,
    previous_agent_version_state TEXT
        CHECK (
            previous_agent_version_state IS NULL
            OR previous_agent_version_state IN (
                'not_assessed',
                'unknown',
                'below_minimum',
                'below_recommended',
                'compliant'
            )
        ),
    agent_version_state TEXT NOT NULL
        CHECK (
            agent_version_state IN (
                'not_assessed',
                'unknown',
                'below_minimum',
                'below_recommended',
                'compliant'
            )
        ),
    previous_reasons JSONB
        CHECK (
            previous_reasons IS NULL
            OR jsonb_typeof(previous_reasons) = 'array'
        ),
    reasons JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(reasons) = 'array'),
    observed_at TIMESTAMPTZ NOT NULL,
    CHECK (rollout_eligible = (readiness_status = 'ready')),
    CHECK (
        previous_rollout_eligible IS NULL
        OR previous_rollout_eligible = (
            previous_readiness_status = 'ready'
        )
    ),
    CHECK (
        (
            change_type = 'initial'
            AND previous_readiness_status IS NULL
            AND previous_rollout_eligible IS NULL
            AND previous_agent_version_state IS NULL
            AND previous_reasons IS NULL
        )
        OR (
            change_type = 'changed'
            AND previous_readiness_status IS NOT NULL
            AND previous_rollout_eligible IS NOT NULL
            AND previous_agent_version_state IS NOT NULL
            AND previous_reasons IS NOT NULL
            AND (
                previous_readiness_status IS DISTINCT FROM readiness_status
                OR previous_rollout_eligible IS DISTINCT FROM rollout_eligible
                OR previous_agent_version_state IS DISTINCT FROM agent_version_state
                OR previous_reasons IS DISTINCT FROM reasons
            )
        )
    )
);

CREATE INDEX idx_sensor_fleet_readiness_history_sensor_time
    ON sensor_fleet_readiness_history (
        sensor_id,
        observed_at DESC,
        id DESC
    );

CREATE INDEX idx_sensor_fleet_readiness_history_time
    ON sensor_fleet_readiness_history (observed_at DESC, id DESC);

COMMIT;

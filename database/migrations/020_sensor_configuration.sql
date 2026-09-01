BEGIN;

CREATE TABLE IF NOT EXISTS sensor_configuration_state (
    sensor_id UUID PRIMARY KEY
        REFERENCES sensors(id) ON DELETE CASCADE,

    desired_revision BIGINT NOT NULL DEFAULT 0
        CHECK (desired_revision >= 0),
    desired_config JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(desired_config) = 'object'),
    desired_updated_at TIMESTAMPTZ,
    desired_updated_by TEXT,

    applied_revision BIGINT
        CHECK (applied_revision IS NULL OR applied_revision >= 0),
    applied_config JSONB
        CHECK (
            applied_config IS NULL
            OR jsonb_typeof(applied_config) = 'object'
        ),
    apply_status TEXT NOT NULL DEFAULT 'unreported'
        CHECK (
            apply_status IN (
                'unreported',
                'pending',
                'applied',
                'error'
            )
        ),
    apply_error TEXT
        CHECK (
            apply_error IS NULL
            OR char_length(apply_error) BETWEEN 1 AND 500
        ),
    reported_at TIMESTAMPTZ,

    CHECK (
        (desired_updated_at IS NULL AND desired_updated_by IS NULL)
        OR (
            desired_updated_at IS NOT NULL
            AND desired_updated_by IS NOT NULL
            AND char_length(desired_updated_by) BETWEEN 1 AND 160
        )
    )
);

INSERT INTO sensor_configuration_state (sensor_id)
SELECT sensor.id
FROM sensors AS sensor
ON CONFLICT (sensor_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_sensor_configuration_compliance
    ON sensor_configuration_state (
        apply_status,
        desired_revision,
        applied_revision
    );

COMMIT;

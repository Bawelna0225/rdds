BEGIN;

ALTER TABLE sensor_heartbeats
    ADD COLUMN IF NOT EXISTS queue_capacity INTEGER,
    ADD COLUMN IF NOT EXISTS queue_oldest_age_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS source_kind TEXT,
    ADD COLUMN IF NOT EXISTS source_connected_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_last_error_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source_last_error_reason TEXT,
    ADD COLUMN IF NOT EXISTS input_lines_total BIGINT,
    ADD COLUMN IF NOT EXISTS parsed_detections_total BIGINT,
    ADD COLUMN IF NOT EXISTS enqueued_observations_total BIGINT,
    ADD COLUMN IF NOT EXISTS ignored_lines_total BIGINT,
    ADD COLUMN IF NOT EXISTS source_connections_total BIGINT,
    ADD COLUMN IF NOT EXISTS delivery_success_total BIGINT,
    ADD COLUMN IF NOT EXISTS delivery_retry_total BIGINT,
    ADD COLUMN IF NOT EXISTS delivery_discard_total BIGINT,
    ADD COLUMN IF NOT EXISTS delivery_dead_letter_total BIGINT,
    ADD COLUMN IF NOT EXISTS last_delivery_success_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_delivery_error_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_delivery_error_reason TEXT;

ALTER TABLE sensor_heartbeats
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_queue_capacity_check,
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_queue_oldest_age_check,
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_source_kind_check,
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_source_error_reason_length_check,
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_diagnostic_counters_check,
    DROP CONSTRAINT IF EXISTS sensor_heartbeats_delivery_error_reason_length_check;

ALTER TABLE sensor_heartbeats
    ADD CONSTRAINT sensor_heartbeats_queue_capacity_check
        CHECK (queue_capacity IS NULL OR queue_capacity >= 1),
    ADD CONSTRAINT sensor_heartbeats_queue_oldest_age_check
        CHECK (
            queue_oldest_age_seconds IS NULL
            OR queue_oldest_age_seconds >= 0
        ),
    ADD CONSTRAINT sensor_heartbeats_source_kind_check
        CHECK (
            source_kind IS NULL
            OR source_kind IN ('serial', 'socket', 'loopback', 'unknown')
        ),
    ADD CONSTRAINT sensor_heartbeats_source_error_reason_length_check
        CHECK (
            source_last_error_reason IS NULL
            OR char_length(source_last_error_reason) BETWEEN 1 AND 64
        ),
    ADD CONSTRAINT sensor_heartbeats_diagnostic_counters_check CHECK (
        (input_lines_total IS NULL OR input_lines_total >= 0)
        AND (parsed_detections_total IS NULL OR parsed_detections_total >= 0)
        AND (
            enqueued_observations_total IS NULL
            OR enqueued_observations_total >= 0
        )
        AND (ignored_lines_total IS NULL OR ignored_lines_total >= 0)
        AND (source_connections_total IS NULL OR source_connections_total >= 0)
        AND (delivery_success_total IS NULL OR delivery_success_total >= 0)
        AND (delivery_retry_total IS NULL OR delivery_retry_total >= 0)
        AND (delivery_discard_total IS NULL OR delivery_discard_total >= 0)
        AND (
            delivery_dead_letter_total IS NULL
            OR delivery_dead_letter_total >= 0
        )
    ),
    ADD CONSTRAINT sensor_heartbeats_delivery_error_reason_length_check
        CHECK (
            last_delivery_error_reason IS NULL
            OR char_length(last_delivery_error_reason) BETWEEN 1 AND 64
        );

COMMIT;

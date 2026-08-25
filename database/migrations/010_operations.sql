BEGIN;

CREATE TABLE IF NOT EXISTS maintenance_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL
        CHECK (status IN ('running', 'succeeded', 'failed', 'dry_run')),
    trigger_type TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (trigger_type IN ('scheduled', 'manual')),
    retention_settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    affected_rows JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status <> 'running' AND finished_at IS NOT NULL)
    ),
    CHECK (error_message IS NULL OR char_length(error_message) <= 4000)
);

CREATE INDEX IF NOT EXISTS idx_maintenance_runs_started
    ON maintenance_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_sessions_retention
    ON operator_sessions (
        (COALESCE(revoked_at, LEAST(expires_at, idle_expires_at)))
    );

CREATE INDEX IF NOT EXISTS idx_sensor_heartbeats_retention
    ON sensor_heartbeats (received_at, id);

CREATE INDEX IF NOT EXISTS idx_observations_retention
    ON observations (received_at, id);

CREATE INDEX IF NOT EXISTS idx_intrusion_alerts_retention
    ON intrusion_alerts (closed_at, id)
    WHERE state = 'closed';

CREATE INDEX IF NOT EXISTS idx_tracks_retention
    ON tracks (ended_at, id)
    WHERE state = 'ended';

COMMIT;

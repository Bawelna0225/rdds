BEGIN;

ALTER TABLE observations
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_error TEXT;

ALTER TABLE tracks
    ADD COLUMN IF NOT EXISTS identity_type TEXT,
    ADD COLUMN IF NOT EXISTS observation_count BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_pilot_position GEOGRAPHY(POINT, 4326),
    ADD COLUMN IF NOT EXISTS last_speed_mps DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS last_heading_deg DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS last_operator_id TEXT,
    ADD COLUMN IF NOT EXISTS last_basic_id TEXT,
    ADD COLUMN IF NOT EXISTS last_drone_mac TEXT,
    ADD COLUMN IF NOT EXISTS last_observation_id BIGINT
        REFERENCES observations(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS track_observations (
    observation_id BIGINT PRIMARY KEY
        REFERENCES observations(id) ON DELETE CASCADE,
    track_id UUID NOT NULL
        REFERENCES tracks(id) ON DELETE CASCADE,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_observations_unprocessed
    ON observations (received_at, id)
    WHERE processed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_track_observations_track
    ON track_observations (track_id, observation_id);

CREATE INDEX IF NOT EXISTS idx_tracks_last_pilot_position
    ON tracks USING GIST (last_pilot_position);

CREATE INDEX IF NOT EXISTS idx_tracks_identity
    ON tracks (identity_type, identity_key);

COMMIT;

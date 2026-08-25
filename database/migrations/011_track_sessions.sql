BEGIN;

ALTER TABLE tracks
    ADD COLUMN IF NOT EXISTS entity_key TEXT;

UPDATE tracks
SET entity_key = track_key
WHERE entity_key IS NULL;

ALTER TABLE tracks
    ALTER COLUMN entity_key SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tracks_entity_last_seen
    ON tracks (entity_key, last_seen_at DESC);

COMMIT;

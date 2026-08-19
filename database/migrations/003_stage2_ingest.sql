BEGIN;

ALTER TABLE observations
    ADD COLUMN IF NOT EXISTS drone_mac TEXT;

CREATE INDEX IF NOT EXISTS idx_observations_drone_mac_time
    ON observations (drone_mac, message_time DESC);

COMMIT;

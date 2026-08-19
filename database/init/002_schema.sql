BEGIN;

CREATE TABLE IF NOT EXISTS sensors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sensor_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'provisioning'
        CHECK (status IN ('provisioning', 'online', 'offline', 'disabled')),
    fixed_position GEOGRAPHY(POINT, 4326),
    firmware_version TEXT,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (char_length(sensor_key) BETWEEN 3 AND 128)
);

CREATE TABLE IF NOT EXISTS sensor_heartbeats (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id UUID NOT NULL REFERENCES sensors(id) ON DELETE RESTRICT,
    sensor_boot_id UUID NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence >= 0),
    measured_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    uptime_seconds BIGINT CHECK (uptime_seconds >= 0),
    free_heap_bytes BIGINT CHECK (free_heap_bytes >= 0),
    queue_depth INTEGER CHECK (queue_depth >= 0),
    cellular_rssi SMALLINT,
    raw_message JSONB NOT NULL,
    UNIQUE (sensor_id, sensor_boot_id, sequence)
);

CREATE TABLE IF NOT EXISTS observations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id UUID NOT NULL REFERENCES sensors(id) ON DELETE RESTRICT,
    sensor_boot_id UUID NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence >= 0),
    protocol_version TEXT NOT NULL DEFAULT 'rdds/1.0',
    message_time TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    transport TEXT NOT NULL
        CHECK (transport IN ('ble', 'wifi_nan', 'wifi_beacon', 'simulator', 'unknown')),
    channel SMALLINT,
    rssi SMALLINT,
    basic_id TEXT,
    operator_id TEXT,
    session_id TEXT,
    drone_position GEOGRAPHY(POINT, 4326),
    pilot_position GEOGRAPHY(POINT, 4326),
    altitude_m DOUBLE PRECISION,
    height_agl_m DOUBLE PRECISION,
    speed_mps DOUBLE PRECISION CHECK (speed_mps IS NULL OR speed_mps >= 0),
    heading_deg DOUBLE PRECISION
        CHECK (heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg < 360)),
    emergency_status TEXT,
    raw_message JSONB NOT NULL,
    UNIQUE (sensor_id, sensor_boot_id, sequence)
);

CREATE TABLE IF NOT EXISTS tracks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track_key TEXT NOT NULL UNIQUE,
    identity_key TEXT,
    state TEXT NOT NULL DEFAULT 'new'
        CHECK (state IN ('new', 'active', 'stale', 'ended', 'anomalous', 'no_gps')),
    last_position GEOGRAPHY(POINT, 4326),
    last_altitude_m DOUBLE PRECISION,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sensors_fixed_position
    ON sensors USING GIST (fixed_position);
CREATE INDEX IF NOT EXISTS idx_heartbeats_sensor_received
    ON sensor_heartbeats (sensor_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_observations_sensor_received
    ON observations (sensor_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_observations_basic_id_time
    ON observations (basic_id, message_time DESC);
CREATE INDEX IF NOT EXISTS idx_observations_drone_position
    ON observations USING GIST (drone_position);
CREATE INDEX IF NOT EXISTS idx_tracks_last_position
    ON tracks USING GIST (last_position);
CREATE INDEX IF NOT EXISTS idx_tracks_state_last_seen
    ON tracks (state, last_seen_at DESC);

COMMIT;

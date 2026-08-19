BEGIN;

CREATE TABLE IF NOT EXISTS protected_zones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    severity TEXT NOT NULL DEFAULT 'high'
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    area GEOGRAPHY(POLYGON, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (char_length(name) BETWEEN 1 AND 160),
    CHECK (description IS NULL OR char_length(description) <= 1000),
    CHECK (ST_IsValid(area::geometry))
);

CREATE TABLE IF NOT EXISTS intrusion_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_id UUID NOT NULL
        REFERENCES protected_zones(id) ON DELETE RESTRICT,
    track_id UUID NOT NULL
        REFERENCES tracks(id) ON DELETE RESTRICT,
    state TEXT NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'acknowledged', 'closed')),
    severity TEXT NOT NULL
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    first_detected_at TIMESTAMPTZ NOT NULL,
    last_detected_at TIMESTAMPTZ NOT NULL,
    last_position GEOGRAPHY(POINT, 4326),
    detection_count BIGINT NOT NULL DEFAULT 1
        CHECK (detection_count >= 1),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    closed_at TIMESTAMPTZ,
    closed_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_protected_zones_area
    ON protected_zones USING GIST (area);

CREATE INDEX IF NOT EXISTS idx_protected_zones_active
    ON protected_zones (active, severity);

CREATE INDEX IF NOT EXISTS idx_intrusion_alerts_state_time
    ON intrusion_alerts (state, last_detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_intrusion_alerts_zone
    ON intrusion_alerts (zone_id, last_detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_intrusion_alerts_track
    ON intrusion_alerts (track_id, last_detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_intrusion_alerts_last_position
    ON intrusion_alerts USING GIST (last_position);

CREATE UNIQUE INDEX IF NOT EXISTS uq_intrusion_alerts_open_pair
    ON intrusion_alerts (zone_id, track_id)
    WHERE state IN ('active', 'acknowledged');

COMMIT;

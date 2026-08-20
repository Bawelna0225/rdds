BEGIN;

CREATE TABLE IF NOT EXISTS operator_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'operator', 'administrator')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
    failed_login_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
    locked_until TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    password_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    deleted_by TEXT,
    CHECK (username = lower(username)),
    CHECK (username ~ '^[a-z0-9][a-z0-9._-]{2,63}$'),
    CHECK (char_length(display_name) BETWEEN 1 AND 160),
    CHECK (char_length(password_hash) BETWEEN 32 AND 512),
    CHECK (char_length(created_by) BETWEEN 1 AND 160),
    CHECK (char_length(updated_by) BETWEEN 1 AND 160),
    CHECK (
        (deleted_at IS NULL AND deleted_by IS NULL)
        OR (deleted_at IS NOT NULL AND deleted_by IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_operator_accounts_username
    ON operator_accounts (username);

CREATE INDEX IF NOT EXISTS idx_operator_accounts_active_role
    ON operator_accounts (role, enabled)
    WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS operator_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id UUID NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    idle_expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    user_agent TEXT,
    remote_address TEXT,
    CHECK (char_length(token_hash) = 64),
    CHECK (char_length(csrf_token) BETWEEN 32 AND 256),
    CHECK (remote_address IS NULL OR char_length(remote_address) <= 128),
    CHECK (expires_at > created_at),
    CHECK (idle_expires_at <= expires_at)
);

CREATE INDEX IF NOT EXISTS idx_operator_sessions_operator_active
    ON operator_sessions (operator_id, expires_at)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_operator_sessions_expiry
    ON operator_sessions (idle_expires_at, expires_at)
    WHERE revoked_at IS NULL;

ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS operator_account_id UUID
        REFERENCES operator_accounts(id) ON DELETE SET NULL;

ALTER TABLE audit_events
    DROP CONSTRAINT IF EXISTS audit_events_event_type_check;

ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_event_type_check CHECK (
        event_type IN (
            'alert_opened',
            'alert_acknowledged',
            'alert_closed',
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
            'operator_created',
            'operator_updated',
            'operator_enabled',
            'operator_disabled',
            'operator_deleted',
            'operator_password_changed',
            'operator_logged_in',
            'operator_logged_out'
        )
    );

CREATE INDEX IF NOT EXISTS idx_audit_events_operator_time
    ON audit_events (operator_account_id, occurred_at, id)
    WHERE operator_account_id IS NOT NULL;

COMMIT;

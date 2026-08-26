BEGIN;

ALTER TABLE operator_sessions
    ADD COLUMN IF NOT EXISTS revoked_by_account_id UUID
        REFERENCES operator_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS revoked_by TEXT,
    ADD COLUMN IF NOT EXISTS revoke_reason TEXT;

ALTER TABLE operator_sessions
    DROP CONSTRAINT IF EXISTS operator_sessions_revoked_by_length_check,
    DROP CONSTRAINT IF EXISTS operator_sessions_revoke_reason_length_check;

ALTER TABLE operator_sessions
    ADD CONSTRAINT operator_sessions_revoked_by_length_check
        CHECK (revoked_by IS NULL OR char_length(revoked_by) <= 160),
    ADD CONSTRAINT operator_sessions_revoke_reason_length_check
        CHECK (revoke_reason IS NULL OR char_length(revoke_reason) <= 160);

CREATE TABLE IF NOT EXISTS operator_security_events (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type TEXT NOT NULL CHECK (
        event_type IN (
            'login_succeeded',
            'login_failed',
            'account_locked',
            'session_logged_out',
            'session_revoked',
            'sessions_revoked'
        )
    ),
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'high')),
    operator_account_id UUID
        REFERENCES operator_accounts(id) ON DELETE SET NULL,
    session_id UUID
        REFERENCES operator_sessions(id) ON DELETE SET NULL,
    username TEXT,
    actor TEXT,
    remote_address TEXT,
    user_agent TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (username IS NULL OR char_length(username) <= 64),
    CHECK (actor IS NULL OR char_length(actor) <= 160),
    CHECK (remote_address IS NULL OR char_length(remote_address) <= 128),
    CHECK (user_agent IS NULL OR char_length(user_agent) <= 512),
    CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_operator_security_events_time
    ON operator_security_events (occurred_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_operator_security_events_type_time
    ON operator_security_events (event_type, occurred_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_operator_security_events_account_time
    ON operator_security_events (operator_account_id, occurred_at DESC, id DESC)
    WHERE operator_account_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_operator_security_events_failures
    ON operator_security_events (occurred_at DESC, username, remote_address)
    WHERE outcome = 'failure';

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
            'operator_logged_out',
            'operator_session_revoked',
            'operator_sessions_revoked',
            'operator_security_exported'
        )
    );

COMMIT;

BEGIN;

-- Keep deleted operator rows for audit/history, but allow the same login to be
-- assigned to a newly created account after the previous account was soft-deleted.
DROP INDEX IF EXISTS uq_operator_accounts_username;

CREATE UNIQUE INDEX uq_operator_accounts_username
    ON operator_accounts (username)
    WHERE deleted_at IS NULL;

COMMIT;

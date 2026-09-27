-- Security hardening (findings B-L3, B-L4). Idempotent; also applied at startup
-- by ensure_schema() in app.py. Safe to run more than once on PostgreSQL.

-- B-L3: token invalidation on password change / logout / block.
ALTER TABLE auth ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;

-- B-L4: OTPs stored as a SHA-256 hash; the plaintext column is no longer
-- written and is made nullable so new rows can omit it.
ALTER TABLE otp ADD COLUMN IF NOT EXISTS otp_hash VARCHAR(64);
ALTER TABLE otp ALTER COLUMN otp DROP NOT NULL;

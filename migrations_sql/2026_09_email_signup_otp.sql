-- E-mail signup with OTP verification. Idempotent; also applied at startup by
-- ensure_schema() in app.py. Safe to run more than once on PostgreSQL.

-- What a code was issued for ('signup' or 'password_reset'). A code is only
-- accepted for its own purpose. Rows from before this change have NULL and are
-- never accepted; they expired within minutes anyway.
ALTER TABLE otp ADD COLUMN IF NOT EXISTS purpose VARCHAR(20);

-- Wrong guesses against a code; it is destroyed after 5.
ALTER TABLE otp ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;

-- New self-registrations are keyed by their verified e-mail address:
-- auth.fin_kod = "User".fin_kod = "User".personal_email (lower-case, <= 100
-- characters). Existing accounts keep their FIN code as the key; no data is
-- rewritten.

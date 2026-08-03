-- =====================================================================
-- Archive editing unlock.
--
-- Projects that belong to a PREVIOUS (non-active) competition live in the
-- admin-only archive and are read-only for their owners. An admin can now
-- unlock a single archived project so its owner (layihə rəhbəri) may edit
-- everything except the smeta.
--
-- NOTE: the app also does this automatically on startup via ensure_schema()
-- in app.py. Running this SQL manually is safe (idempotent) and lets you
-- apply the change without a full app restart.
-- =====================================================================

ALTER TABLE project ADD COLUMN IF NOT EXISTS edit_unlocked    BOOLEAN DEFAULT FALSE;
ALTER TABLE project ADD COLUMN IF NOT EXISTS edit_unlocked_at TIMESTAMP;
ALTER TABLE project ADD COLUMN IF NOT EXISTS edit_unlocked_by VARCHAR(100);

-- Existing rows predate the column: make the "locked" default explicit.
UPDATE project SET edit_unlocked = FALSE WHERE edit_unlocked IS NULL;

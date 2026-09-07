-- =====================================================================
-- Returning a submitted proposal for corrections.
--
-- An administrator can move a project back out of the "submitted" state so its
-- lead can fix what is wrong and hand it in again. The note explaining what to
-- fix travels with it and is shown to the lead on their project page.
--
-- `revision_note` is deliberately kept after the resubmission — `submitted`
-- alone says whether anything is still outstanding.
--
-- NOTE: the app also applies this on startup via ensure_schema() in app.py.
-- Running this SQL manually is safe (idempotent).
-- =====================================================================

ALTER TABLE project ADD COLUMN IF NOT EXISTS revision_note TEXT;
ALTER TABLE project ADD COLUMN IF NOT EXISTS returned_at   TIMESTAMP;
ALTER TABLE project ADD COLUMN IF NOT EXISTS returned_by   VARCHAR(100);

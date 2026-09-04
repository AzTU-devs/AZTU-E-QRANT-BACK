-- =====================================================================
-- An activity may run over several months.
--
-- `project_activities.month` held exactly one month per activity, so a task
-- spanning e.g. March–May had to be entered three times. The new `months`
-- column carries the full comma-separated list ("3,4,5"); `month` stays as
-- the FIRST of them so the existing NOT NULL constraint and any reader that
-- still expects a single value keep working.
--
-- NOTE: the app also applies this on startup via ensure_schema() in app.py.
-- Running this SQL manually is safe (idempotent).
-- =====================================================================

ALTER TABLE project_activities ADD COLUMN IF NOT EXISTS months VARCHAR;

-- Existing rows each hold one month; seed the list from it.
UPDATE project_activities
   SET months = month::text
 WHERE months IS NULL OR months = '';

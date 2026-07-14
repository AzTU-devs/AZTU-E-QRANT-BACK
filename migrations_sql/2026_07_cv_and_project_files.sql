-- =====================================================================
-- CV upload (personal data) + unlimited project file uploads
-- Apply on the production (Neon) Postgres database.
--
-- NOTE: The app also does this automatically on startup:
--   * db.create_all()   -> creates the new `project_files` table
--   * ensure_schema()    -> adds the two cv_* columns to "User"
-- Running this SQL manually is safe (idempotent) and lets you apply the
-- change without a full app restart.
-- =====================================================================

-- 1) CV columns on the User table (name is quoted: uppercase "User").
ALTER TABLE "User" ADD COLUMN IF NOT EXISTS cv_original_filename VARCHAR;
ALTER TABLE "User" ADD COLUMN IF NOT EXISTS cv_stored_filename   VARCHAR;

-- 2) Project files table (arbitrary count of documents/images per project).
CREATE TABLE IF NOT EXISTS project_files (
    id                SERIAL PRIMARY KEY,
    project_code      INTEGER NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename   VARCHAR(255) NOT NULL UNIQUE,
    content_type      VARCHAR(120),
    file_size         BIGINT,
    uploaded_by       VARCHAR(100),
    uploaded_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_project_files_project_code
    ON project_files (project_code);

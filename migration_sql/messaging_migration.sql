-- ===========================================================================
-- AzTU e-grant — Messaging (user <-> admin chat) tables
-- New tables; also auto-created by the app on restart via create_all().
-- Safe/idempotent. Run on the production (Neon) Postgres database.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS message_threads (
    id              SERIAL PRIMARY KEY,
    user_fin_kod    VARCHAR(100) NOT NULL UNIQUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id             SERIAL PRIMARY KEY,
    thread_id      INTEGER NOT NULL REFERENCES message_threads(id) ON DELETE CASCADE,
    sender_type    VARCHAR(10) NOT NULL,          -- 'user' or 'admin'
    sender_fin_kod VARCHAR(100),
    body           TEXT,
    is_read        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_messages_thread ON messages (thread_id);

CREATE TABLE IF NOT EXISTS message_attachments (
    id                SERIAL PRIMARY KEY,
    message_id        INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    original_filename VARCHAR(255) NOT NULL,
    stored_filename   VARCHAR(255) NOT NULL UNIQUE,
    content_type      VARCHAR(120),
    file_size         BIGINT,
    uploaded_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_message_attachments_message ON message_attachments (message_id);

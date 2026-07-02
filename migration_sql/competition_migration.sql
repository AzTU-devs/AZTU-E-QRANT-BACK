CREATE TABLE IF NOT EXISTS competitions (
    id                   SERIAL PRIMARY KEY,
    code                 VARCHAR(100) NOT NULL UNIQUE,
    year                 INTEGER NOT NULL,
    title                TEXT,
    is_active            BOOLEAN NOT NULL DEFAULT FALSE,
    application_deadline TIMESTAMP,
    report_deadline      TIMESTAMP,
    contract_date        TIMESTAMP,
    max_smeta_amount     INTEGER NOT NULL DEFAULT 30000,
    collaborator_limit   INTEGER NOT NULL DEFAULT 7,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by           VARCHAR(100)
);
ALTER TABLE project       ADD COLUMN IF NOT EXISTS competition_id INTEGER;
ALTER TABLE collaborators ADD COLUMN IF NOT EXISTS competition_id INTEGER;
INSERT INTO competitions (code, year, title, is_active, created_at)
SELECT 'AzTU-DQL-2025', 2025, 'AzTU Daxili Qrant Müsabiqəsi 2025', TRUE, NOW()
WHERE NOT EXISTS (SELECT 1 FROM competitions);
UPDATE project
   SET competition_id = (SELECT id FROM competitions ORDER BY year ASC, id ASC LIMIT 1)
 WHERE competition_id IS NULL;

UPDATE collaborators
   SET competition_id = (SELECT id FROM competitions ORDER BY year ASC, id ASC LIMIT 1)
 WHERE competition_id IS NULL;
DO $$
DECLARE con record;
BEGIN
  FOR con IN
    SELECT c.conname, t.relname
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname IN ('project', 'collaborators')
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname)
        FROM unnest(c.conkey) AS k
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k
      ) = ARRAY['fin_kod']
  LOOP
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', con.relname, con.conname);
  END LOOP;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_project_fin_competition') THEN
    ALTER TABLE project ADD CONSTRAINT uq_project_fin_competition UNIQUE (fin_kod, competition_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_collaborator_fin_competition') THEN
    ALTER TABLE collaborators ADD CONSTRAINT uq_collaborator_fin_competition UNIQUE (fin_kod, competition_id);
  END IF;
END $$;

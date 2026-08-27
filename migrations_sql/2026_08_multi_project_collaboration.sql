-- =====================================================================
-- Multiple collaborations per competition.
--
-- Until now `collaborators` carried UNIQUE (fin_kod, competition_id), which
-- allowed a person exactly ONE project per competition. A person may now take
-- part in several:
--
--   * an executor (icraçı, project_role = 1) in up to TWO projects;
--   * a lead (layihə rəhbəri, project_role = 0) in ONE project on top of the
--     project they own.
--
-- The per-competition count depends on the person's role, so it is enforced in
-- the application (models/collaboratorModel.py). All the database still
-- guarantees is that nobody joins the SAME project twice.
--
-- NOTE: the app also applies this on startup via ensure_schema() in app.py.
-- Running this SQL manually is safe (idempotent) and lets you apply the change
-- without a full app restart.
-- =====================================================================

-- Drop the old one-project-per-competition rule, whatever it ended up named.
DO $$
DECLARE con record;
BEGIN
  FOR con IN
    SELECT c.conname
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'collaborators'
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname ORDER BY a.attname)
        FROM unnest(c.conkey) AS k
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k
      ) = ARRAY['competition_id', 'fin_kod']
  LOOP
    EXECUTE format('ALTER TABLE collaborators DROP CONSTRAINT %I', con.conname);
  END LOOP;
END $$;

-- Legacy databases may still carry the even older global UNIQUE (fin_kod).
DO $$
DECLARE con record;
BEGIN
  FOR con IN
    SELECT c.conname
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'collaborators'
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname)
        FROM unnest(c.conkey) AS k
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k
      ) = ARRAY['fin_kod']
  LOOP
    EXECUTE format('ALTER TABLE collaborators DROP CONSTRAINT %I', con.conname);
  END LOOP;
END $$;

-- Nobody joins the same project twice.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_collaborator_fin_project') THEN
    ALTER TABLE collaborators
      ADD CONSTRAINT uq_collaborator_fin_project UNIQUE (fin_kod, project_code);
  END IF;
END $$;

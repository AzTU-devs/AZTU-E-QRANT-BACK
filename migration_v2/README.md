# migration_v2 — old DB → new schema migration

Moves all data from the legacy E-Grant database into the new schema described in
[`docs/DB_ARCHITECTURE.md`](../docs/DB_ARCHITECTURE.md). It is a **two-database,
one-way ETL**: the old DB is read-only; everything is written into a fresh,
**empty** target DB. Re-runnable (truncates the target before each load).

## Files
- `new_models.py` — the new schema as standalone SQLAlchemy 2.0 models (creates
  the target DB; can later be promoted into the Flask app via
  `SQLAlchemy(model_class=Base)`).
- `etl.py` — extract (psycopg2, read-only) → transform → load (ORM).

## Steps

1. **Provision an empty Postgres DB** for the new schema — a new Neon project/branch
   or a local Postgres. Do **not** point it at the old DB.

2. **Set connection strings** (`OLD_*` defaults to the app's `DATABASE_URL`):
   ```bash
   export OLD_DATABASE_URL="postgresql://...neon.../neondb?sslmode=require"
   export NEW_DATABASE_URL="postgresql://...the-new-empty-db..."
   ```

3. **Dry run** (reads OLD only, prints the transform plan, writes nothing):
   ```bash
   ./venv/bin/python -m migration_v2.etl --dry-run
   ```

4. **Migrate** (creates schema, truncates target, loads, builds `v_budget_totals`,
   prints an old→new count reconciliation):
   ```bash
   ./venv/bin/python -m migration_v2.etl --reset
   ```
   - `--reset` drops + recreates the target schema first (clean slate).
   - omit `--reset` to keep the schema and just truncate+reload.

The script refuses to run if `NEW_DATABASE_URL == OLD_DATABASE_URL`.

## What it handles (verified end-to-end against the live data)
- Splits legacy `auth`/`User` into `users` + `credentials`; **synthesizes a `users`
  row for any `auth` with no profile** (`credentials.user_id` is NOT NULL).
- `auth.user_type` → `users.academic_type`; `auth.project_role==2` →
  `users.global_role=SUPER_ADMIN`; `auth.approved`+`blocked` → `credentials.status`.
- `project.fin_kod` → `projects.owner_id`; `project.priotet` (code string) →
  `priority_id`; `project.expert` (email) → `expert_assignments`;
  `approved`/`submitted` → `projects.status`.
- `collaborators` + each owner → `project_members` (`UNIQUE(project_id, user_id)`).
- 4 legacy line-item tables → unified `budget_line_items` (category enum);
  `salary_smeta` → `budget_salaries` linked to the member; line totals are
  **DB-computed** (`GENERATED STORED`); cached budget totals are recomputed and
  match the `v_budget_totals` view.
- `quarterly_reports.point_1..17` → `quarterly_report_items` rows.
- `User.image` (BLOB) → files under `avatars/` + `users.avatar_url` reference.
- Unknown `institution_code` → `NULL` (logged); absent legacy `assessment` table →
  skipped (logged).

## Notes
- `avatars/` is git-ignored — it holds extracted profile images (PII). On a real
  migration, move it to your object storage and update `users.avatar_url`.
- After cutover, point the Flask app at `NEW_DATABASE_URL` and migrate the
  controllers to the new models (separate task — not done by this script).

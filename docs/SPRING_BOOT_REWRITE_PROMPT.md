# Prompt — Rebuild AZTU E-Grant backend as a Spring Boot modular monolith

> Copy everything below the line into a fresh Claude Code session opened **in the
> root of the existing Flask repo** (`AZTU-E-QRANT-BACK`). It references this repo
> as the behavioural source of truth and `docs/DB_ARCHITECTURE.md` as the schema
> source of truth.

---

## Role & mission

You are a senior Java/Spring backend engineer. Rebuild the **AZTU E-Grant** backend
**from zero** as a **Spring Boot modular monolith**. E-Grant is a university grant
competition platform: researchers submit grant **projects**, build a **team**,
attach a budget estimate (**smeta**), plan monthly **activities**, file **quarterly
reports**; **experts** review and **assess**; admins approve users/projects and open
or lock the submission window.

There is an existing **Python/Flask + SQLAlchemy** implementation in this repository.
**It is the behavioural source of truth** — when a requirement is ambiguous, read the
corresponding Flask `controllers/*.py`, `models/*.py`, and `utils/*.py` and replicate
the observable behaviour. The new database schema is already designed in
**`docs/DB_ARCHITECTURE.md`** (read it fully first) and a working data-migration that
loads the legacy data into that schema lives in **`migration_v2/`** — your Flyway
schema **must** match `migration_v2/new_models.py` so that migration keeps working.

Build the new project in a **new top-level directory `egrant-springboot/`**. Do not
modify the Flask code.

## Hard constraints

1. **Design a clean, modern REST API on the new domain model — this is a from-zero
   rebuild, not a port.** Do **not** copy the legacy endpoint paths or payload shapes.
   The Flask app is a **feature & business-rule checklist** (every capability must be
   reachable in the new API), not a contract to preserve. Expose resource-oriented
   endpoints under `/api/v1`, named after the new entities (see "REST API design (target)").
   Use plural nouns, proper HTTP verbs, paginated list endpoints, and DTOs shaped by
   the new schema (not the legacy `*_details()` serializers). Frontends will be updated
   to this API; record the legacy→new mapping in `egrant-springboot/API_MAP.md`.
2. **Schema = `docs/DB_ARCHITECTURE.md` / `migration_v2/new_models.py`.** Surrogate
   `BIGINT` PKs, real FKs, enum statuses, unified `budget_line_items`, DB-computed
   line totals, the `v_budget_totals` view. Author it as Flyway migrations.
3. **Fix the known legacy defects** (don't reproduce them) — see "Defects to fix".
4. **Modular monolith with enforced boundaries** (Spring Modulith) — see "Architecture".
5. The build must be green: `./mvnw verify` compiles, passes unit + integration tests
   (Testcontainers Postgres), and the Spring Modulith boundary test passes.

## Tech stack (pin to current stable as of build time)

- **Java 21 LTS**, **Maven** (wrapper committed), **Spring Boot 3.5.x** (latest 3.x).
- **Spring Modulith** (version aligned to the Boot release) for module boundaries,
  `@ApplicationModule` metadata, and inter-module application events.
- **Spring Web** (REST), **Spring Data JPA** / Hibernate, **PostgreSQL** driver.
- **Flyway** for schema migrations (the app owns the schema).
- **Spring Security** + **JWT** (`io.jsonwebtoken:jjwt` or Spring resource-server),
  stateless, BCrypt password hashing.
- **Jakarta Bean Validation** for request DTOs.
- **MapStruct** for entity↔DTO mapping (records for DTOs).
- **springdoc-openapi** (Swagger UI at `/swagger-ui.html`, replacing flasgger).
- **Spring Mail** (`JavaMailSender`) + Thymeleaf templates for transactional email
  (port `templates/email/` and the `noto_sans` font asset).
- **PDF**: `openhtmltopdf` (or OpenPDF) for `/api/project-pdf/...`; **Excel**: Apache
  POI for `/api/project-excel/...` (replacing reportlab/pandas).
- **Bucket4j** (or Resilience4j) for rate limiting (legacy default: 200/day, 50/hour
  per client IP).
- **Testing**: JUnit 5, AssertJ, Spring Boot Test, **Testcontainers** (Postgres),
  Spring Modulith test support.
- **Lombok** optional for entities; prefer Java records for DTOs/events.
- **Docker**: `Dockerfile` (multi-stage) + `docker-compose.yml` (app + Postgres) to
  match the current Nixpacks/Procfile deployment.

## Architecture — modular monolith

One deployable Spring Boot app, internally split into **modules = bounded contexts**.
Base package `az.aztu.egrant`. Each module is a top-level package; cross-module calls
go only through a module's **published API package** (`...<module>.api`) or via
**Spring Modulith application events** — never by reaching into another module's
`internal` package. Add a `ModularityTests` that calls
`ApplicationModules.of(EGrantApplication.class).verify()`.

Modules:

| Module | Owns | Notes |
|--------|------|-------|
| `shared` | base entity, `ProblemDetail` error handling, JWT/security config, CORS, OpenAPI config, file-storage abstraction, mail abstraction, common value types | shared kernel; no business logic |
| `iam` | `users`, `credentials`, `otp_codes`, auth (signup/signin/OTP/reset), user approval/blocking, roles | issues JWTs; publishes `UserRegistered`, `UserApproved` events |
| `institution` | `institutions` lookup | |
| `priority` | `priorities` lookup | |
| `project` | `projects`, `project_members`, `project_activities`, submit/approve, lock-gated submission | publishes `ProjectSubmitted` |
| `expert` | `experts`, `expert_assignments`, `assessments` | consumes `ProjectSubmitted` |
| `budget` | `budgets`, `budget_salaries`, `budget_line_items`, totals, `v_budget_totals` | enforces `max_budget_amount` |
| `report` | `quarterly_reports`, `quarterly_report_items` | |
| `publicapi` | unauthenticated public views (`/api/public/...`) | read-only projections |
| `admin` (or fold into `shared`) | global system lock (`system_lock`), lock/unlock/status | gates project submission |
| `notification` | email sending, templates | listens to events from `iam`/`project`/`expert` |
| `document` | PDF + Excel generation for projects/smeta | reads via other modules' APIs |

Within each module use layered packages: `api` (DTOs, exposed services/interfaces),
`web` (controllers), `domain` (entities, enums), `internal` (repositories, service
impls, mappers), `events`.

## Domain model & migrations

- Read `docs/DB_ARCHITECTURE.md` and mirror `migration_v2/new_models.py` exactly:
  tables, columns, enums (`academic_type, account_status, global_role, project_status,
  member_role, member_status, assignment_status, budget_category`), unique
  constraints, indexes, `ON DELETE` rules, the two `GENERATED ... STORED` total
  columns, and the `v_budget_totals` view.
- Author **Flyway** `V1__init_schema.sql` (DDL incl. enum types, generated columns,
  view). Map JPA entities onto it; mark generated `total_amount` columns
  `insertable=false, updatable=false` and read them back after insert.
- Provide a `docker-compose` Postgres and a `local`/`prod` profile. Do **not** use
  `ddl-auto=update`; Flyway is authoritative.

## REST API design (target)

Design the new surface under `/api/v1`, resource-oriented and consistent. This is the
**target you build**; the legacy list further below is only a capability checklist to
make sure nothing is missed. Use JWT bearer auth, `@PreAuthorize`, paginated lists
(`page`/`size`/`sort`), and `ProblemDetail` errors.

```
# Auth (public)
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/otp                         # request OTP
POST   /api/v1/auth/otp/verify
POST   /api/v1/auth/password/reset

# Users & self
GET    /api/v1/users                            # admin; filter ?status=
GET    /api/v1/users/pending                    # admin approval queue
GET    /api/v1/users/{id}
GET    /api/v1/me                               # current user's profile
PUT    /api/v1/me                               # edit own profile
GET    /api/v1/users/{id}/avatar                # streams image
POST   /api/v1/users/{id}/approval              # admin approve
POST   /api/v1/users/{id}/block                 # admin block / DELETE to unblock
PUT    /api/v1/users/{id}/role                  # admin set global_role

# Lookups (public read, admin write)
GET    /api/v1/institutions      POST /api/v1/institutions
GET    /api/v1/institutions/{id} DELETE /api/v1/institutions/{id}
GET    /api/v1/priorities        POST /api/v1/priorities
PUT    /api/v1/priorities/{id}   DELETE /api/v1/priorities/{id}

# Projects
GET    /api/v1/projects                         # filter ?status= &mine=true
POST   /api/v1/projects
GET    /api/v1/projects/{id}
PATCH  /api/v1/projects/{id}
DELETE /api/v1/projects/{id}
POST   /api/v1/projects/{id}/submit             # lock-gated + budget-cap check
POST   /api/v1/projects/{id}/approve            # admin (also /reject)
GET    /api/v1/projects/{id}/pdf
GET    /api/v1/projects/{id}/excel

# Team (sub-resource of project)
GET    /api/v1/projects/{id}/members
POST   /api/v1/projects/{id}/members            # request to join (collaborator)
POST   /api/v1/projects/{id}/members/{userId}/approve   # owner/admin (also /reject)
DELETE /api/v1/projects/{id}/members/{userId}

# Activities (sub-resource)
GET    /api/v1/projects/{id}/activities         POST /api/v1/projects/{id}/activities
PATCH  /api/v1/projects/{id}/activities/{activityId}
DELETE /api/v1/projects/{id}/activities/{activityId}

# Budget (1:1 with project; totals come from v_budget_totals — never client-supplied)
GET    /api/v1/projects/{id}/budget             # header + computed totals
PUT    /api/v1/projects/{id}/budget             # total_fee, defense_fund
GET    /api/v1/projects/{id}/budget/salaries    POST .../salaries
PATCH  /api/v1/projects/{id}/budget/salaries/{salaryId}
DELETE /api/v1/projects/{id}/budget/salaries/{salaryId}
GET    /api/v1/projects/{id}/budget/line-items?category=EQUIPMENT   # one resource,
POST   /api/v1/projects/{id}/budget/line-items                      # category in body
PATCH  /api/v1/projects/{id}/budget/line-items/{itemId}            # (EQUIPMENT|
DELETE /api/v1/projects/{id}/budget/line-items/{itemId}           #  SERVICES|RENT|OTHER)

# Experts & review
GET    /api/v1/experts                          POST /api/v1/experts
POST   /api/v1/projects/{id}/expert-assignments # admin; only after submit
GET    /api/v1/projects/{id}/assessments        POST /api/v1/projects/{id}/assessments

# Reports
GET    /api/v1/projects/{id}/reports?year=&quarter=
POST   /api/v1/projects/{id}/reports            # body carries the 17 points as a list

# System lock (admin)
GET    /api/v1/system/lock
PUT    /api/v1/system/lock                      # { "locked": true|false }

# Public (unauthenticated)
GET    /api/v1/public/projects
GET    /api/v1/public/projects/{projectCode}
GET    /api/v1/public/priorities-tree           # the legacy "leads-tree"
```

Adjust as needed for correctness, but stay resource-oriented and consistent.

## Legacy capability checklist (build clean equivalents, do not copy paths)

Every capability below must be reachable in the new `/api/v1` API. Use the Flask
handlers only to learn the **behaviour, guards, and business rules** — then map each to
the clean design above and note the mapping in `API_MAP.md`. Grouped by module:

**iam / auth** — `POST /auth/signup`, `POST /auth/signin`,
`POST /auth/send-otp/{fin_kod}`, `POST /auth/validate-otp/{fin_kod}/{otp}`,
`POST /auth/reset-password`, `POST /auth/app-user/{fin_kod}` (approve),
`DELETE /auth/reject-user/{fin_kod}`, `GET /auth/app-wait-users`,
`POST /auth/{fin_kod}/update/role/{role}`.

**iam / user** — `GET /api/users/all`, `GET /api/profile/{fin_kod}`,
`PUT /api/profile/{fin_kod}/edit`, `GET /api/profile/image/{fin_kod}`,
`POST /api/approve/profile`.

**institution** — `GET /api/institutions`, `GET /api/institution/{code}`,
`POST /api/create-institution/{name}`.

**priority** — `GET /api/priotets`, `GET /api/priotet/{code}`,
`POST /api/create-priotet`, `POST /api/upd-prioritet`, `DELETE /api/del-prioritet/{code}`.

**project** — `GET /api/projects`, `GET /api/projects/submitted`,
`GET /api/project/{project_code}`, `GET /api/project/{fin_kod}`,
`GET /api/project-details/{project_code}`, `GET /api/project-owner/{project_code}`,
`GET /api/col-project/{fin_kod}`, `POST /api/save/project`, `PATCH /api/upd/project`,
`DELETE /api/delete/project`, `POST /api/submit-project`, `POST /api/approve_project`,
`GET /api/project-pdf/{project_code}`, `GET /api/project-excel/{project_code}`.

**project / collaborators (members)** — `GET /api/collaborators`,
`GET /api/collaborators/{project_code}`,
`GET /api/app-wait-collaborators/{project_code}`,
`GET /api/project/owner/{project_code}`, `POST /api/be-collaborator`,
`POST /api/app-collaborator/{fin_kod}`, `DELETE /api/reject-collaborator/{fin_kod}`.

**project / activities** — `GET /api/project-activity/{project_code}`,
`POST /api/project-activity/create`, `PATCH /api/project-activity/update/{id}`,
`DELETE /api/project-activity/delete/{id}`,
`DELETE /api/project-activity/{project_code}/{month}`.

**expert** — `GET /api/experts`, `POST /api/create-expert`, `POST /api/set-expert`.

**budget / smeta header** — `GET /api/main-smeta/{project_code}`,
`POST /api/create-smeta`, `PATCH /api/edit-smeta/{project_code}`,
`PATCH /api/update-smeta-field/{project_code}`, `DELETE /api/delete-smeta/{project_code}`.

**budget / salary** — `GET /api/salary/smeta/{project_code}`,
`GET /api/all-salaries-table`, `POST /api/create-salary-table`,
`PATCH /api/edit-salary-table/{project_code}`, `DELETE /api/delete-salary/{project_code}`.

**budget / equipment (subject)** — `GET /api/subject/smeta/{project_code}`,
`POST /api/add-subject`, `PATCH /api/update-subject/{project_code}`,
`DELETE /api/delete/smeta/subject/{project_code}/{id}`.

**budget / services** — `GET /api/get-services/{project_code}`, `POST /api/add-services`,
`PATCH /api/update-services/{project_code}`,
`DELETE /api/delete-services/{project_code}/{id}`.

**budget / rent** — `GET /api/get-rent-all-tables/{project_code}`, `POST /api/rent`,
`PATCH /api/edit-rent-table/{project_code}`,
`DELETE /api/delete-rent-table/{project_code}/{id}`.

**budget / other expenses** — `GET /api/get-other_exp-all-tables/{project_code}`,
`POST /api/other_exp`, `PATCH /api/edit-other_exp-table/{id}`,
`DELETE /api/delete-other_exp-table/{project_code}/{id}`.

> Note: the legacy equipment/services/rent/other groups collapse into the **single
> `/api/v1/projects/{id}/budget/line-items`** resource backed by the unified
> `budget_line_items` table, discriminated by `category`. Do not recreate four
> separate endpoint groups.

**report** — `GET /api/reports/{project_code}/{quarter_number}/{year}`,
`POST /api/reports/save` (map `point_1..17` ⇄ `quarterly_report_items`).

**admin / lock** — `GET /api/lock-status`, `POST /api/lock`, `POST /api/unlock`.

**publicapi** — `GET /api/public/projects`, `GET /api/public/project/{project_code}`,
`GET /api/public/leads-tree`.

## Cross-cutting concerns

- **Security / JWT**: stateless Spring Security. Reproduce the login flow and a
  JWT with claims `sub` (user id), `fin_kod`, `profile_completed`, and role. Map the
  legacy numeric roles to the new model: `global_role` (`APPLICANT/ADMIN/SUPER_ADMIN`)
  + project-scoped `member_role`. Enforce with `@PreAuthorize`. Public endpoints and
  auth endpoints are unauthenticated. **Fix the legacy bug** where the JWT is signed
  with claim `role` but the guard reads `role_code` — use one consistent claim.
- **OTP**: numeric OTP with issued/expires timestamps in `otp_codes`, emailed via the
  notification module; verify + mark consumed; mirror `send-otp` / `validate-otp`.
- **Password reset**: mirror `/auth/reset-password` (OTP-token based).
- **Email**: `JavaMailSender` + Thymeleaf; SMTP from env (`SMTP_*`). Send on signup,
  user approval, collaborator approval/rejection, expert assignment. Make it async
  (`@Async`) and event-driven so the request path doesn't block on SMTP.
- **File storage**: avatars are stored as a file reference (`users.avatar_url`), not a
  DB blob. Provide a `FileStorage` abstraction (local dir for dev; pluggable for
  object storage). `GET /api/profile/image/{fin_kod}` streams the avatar.
- **PDF/Excel**: project + smeta export endpoints.
- **Validation**: Jakarta validation on all request DTOs; reject early.
- **Error handling**: `@ControllerAdvice` returning RFC 7807 `ProblemDetail`; map
  domain exceptions to 400/403/404/409 consistent with the Flask responses
  (e.g., 409 on collaborator-limit and budget-cap violations).
- **Rate limiting**: Bucket4j filter, 200/day + 50/hour per IP (configurable).
- **CORS**: permissive like today (`origins="*"`, methods GET/POST/PUT/PATCH/DELETE/
  OPTIONS, headers incl. Authorization), but make origins configurable per profile.
- **Config**: 12-factor; `DATABASE_URL`, `SECRET_KEY`/JWT secret, `SMTP_*` from env.
  Never commit secrets.

## Business rules to preserve (verify against Flask)

- A user must have `profile_completed = true` before joining as collaborator or
  before owner can approve/submit.
- Collaborator count per project cannot exceed `projects.collaborator_limit` (default
  7) → 409.
- Budget `grand_total` cannot exceed `projects.max_budget_amount` (default 30000) at
  submission → 409. Compute totals from line items (use `v_budget_totals`); never
  trust client totals.
- An expert can be assigned only after the project is **submitted**.
- **System lock**: when `system_lock.is_locked = true`, block project submission
  (and any other write the Flask app blocks while locked).
- Sign-in blocked when account is `BLOCKED` or not `APPROVED`.
- Project status lifecycle replaces the old `approved`(int)+`submitted`(bool):
  `DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED/REJECTED`.

## Defects to fix (do not reproduce)

- JWT claim/guard mismatch (`role` vs `role_code`).
- `collaborators.fin_kod UNIQUE` (a person could only ever join one project) →
  modelled as `project_members` with `UNIQUE(project_id, user_id)`.
- Double primary keys on salary/subject/services tables → single surrogate PK.
- Manually-summed smeta totals that drift → DB-computed line totals + `v_budget_totals`.
- Expert/assessment linked by raw email string → FK to `experts`.
- Inconsistent `fin_kod`/`project_code` types → consistent types per schema doc.

## Working method

1. Read `docs/DB_ARCHITECTURE.md`, `migration_v2/new_models.py`, then skim every
   `controllers/*.py`, `models/*.py`, `utils/*.py` to extract the **features, guards,
   and business rules**. Produce `egrant-springboot/REQUIREMENTS.md` (capabilities +
   rules) and `egrant-springboot/API_MAP.md` (legacy endpoint → new `/api/v1` resource).
   Design the clean API before coding controllers.
2. Scaffold the Maven project, `shared` module, security, error handling, OpenAPI,
   Flyway `V1`, Testcontainers harness, and the Modulith boundary test. Get a green
   build with a health check before adding features.
3. Implement module by module in this order: `shared → iam → institution/priority →
   project → budget → expert → report → admin(lock) → publicapi → notification →
   document`. After each module: DTOs, controller, service, repo, mapper, validation,
   tests, and a slice of OpenAPI. Keep the build green.
4. Write integration tests (Testcontainers) for the critical flows: signup→OTP→signin,
   profile complete, create project, build team (limit), build smeta (cap), submit
   (lock gate), assign expert, file report, public views, lock/unlock.
5. Provide `Dockerfile`, `docker-compose.yml`, `application.yml` profiles, and a
   `README.md` (run, test, env vars, module map). Keep `API_MAP.md` up to date.

Commit per module with clear messages. When a behaviour is genuinely ambiguous and not
resolvable from the Flask code, list the question in `OPEN_QUESTIONS.md` and proceed
with the most reasonable assumption rather than blocking.

## Definition of done

- `./mvnw verify` is green (unit + Testcontainers integration + Modulith verify).
- Every legacy capability is reachable via the new `/api/v1` API; the legacy→new
  mapping is recorded in `API_MAP.md`.
- Flyway schema matches `docs/DB_ARCHITECTURE.md`; `migration_v2/etl.py` can load into
  it unchanged.
- Swagger UI lists all endpoints; app boots via `docker-compose up` against Postgres.
- All "Business rules" enforced and "Defects to fix" addressed; no secrets committed.
```
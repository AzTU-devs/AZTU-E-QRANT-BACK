"""
AZTU E-Grant — one-way data migration (old DB  ->  new v2 DB).

Reads the legacy schema (read-only, psycopg2) and loads it into the new schema
(SQLAlchemy 2.0 ORM, migration_v2/new_models.py). Safe to re-run: it truncates
the target tables before each load. The OLD database is never written to.

Usage
-----
  # 1. provision an EMPTY new Postgres DB (new Neon project/branch or local)
  # 2. set connection strings (OLD defaults to the app's DATABASE_URL):
  export OLD_DATABASE_URL="postgresql://...neon.../neondb?sslmode=require"
  export NEW_DATABASE_URL="postgresql://...the-new-empty-db..."

  ./venv/bin/python -m migration_v2.etl --dry-run     # report transform plan, no writes
  ./venv/bin/python -m migration_v2.etl --reset       # drop+recreate schema, then load
  ./venv/bin/python -m migration_v2.etl               # create-if-missing, truncate, load

Flags
-----
  --dry-run   read OLD only, print planned row counts + data issues, exit.
  --reset     DROP ALL new tables and recreate before loading (clean slate).
  --avatars-dir DIR   where to write extracted profile images (default beside this file).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from migration_v2.new_models import (
    Base, V_BUDGET_TOTALS_SQL,
    Institution, Priority, User, Credential, OtpCode, Expert,
    Project, ProjectMember, ProjectActivity, ExpertAssignment, Assessment,
    QuarterlyReport, QuarterlyReportItem, Budget, BudgetSalary, BudgetLineItem,
    AcademicType, AccountStatus, GlobalRole, ProjectStatus, MemberRole,
    MemberStatus, AssignmentStatus, BudgetCategory,
)

LOG = []


def log(msg):
    LOG.append(msg)
    print(msg)


# --------------------------------------------------------------------------- #
# OLD DB helpers (read-only)
# --------------------------------------------------------------------------- #
def fetch(cur, sql, params=None):
    cur.execute(sql, params or ())
    return [dict(r) for r in cur.fetchall()]


def table_exists(cur, name):
    cur.execute("SELECT to_regclass(%s) AS reg", (f"public.{name}",))
    return cur.fetchone()["reg"] is not None


# --------------------------------------------------------------------------- #
# value mappers
# --------------------------------------------------------------------------- #
ACADEMIC = {0: AcademicType.TEACHER, 1: AcademicType.PHD, 2: AcademicType.MASTER}


def academic_type(user_type):
    return ACADEMIC.get(user_type, AcademicType.TEACHER)


def global_role(project_role):
    # legacy project_role: 0=owner, 1=collaborator, 2=super admin
    return GlobalRole.SUPER_ADMIN if project_role == 2 else GlobalRole.APPLICANT


def account_status(approved, blocked):
    if blocked and int(blocked) == 1:
        return AccountStatus.BLOCKED
    return AccountStatus.APPROVED if approved else AccountStatus.PENDING


def project_status(submitted, has_expert):
    if submitted and has_expert:
        return ProjectStatus.UNDER_REVIEW
    if submitted:
        return ProjectStatus.SUBMITTED
    return ProjectStatus.DRAFT


def member_status(approved):
    return MemberStatus.APPROVED if approved else MemberStatus.PENDING


def now():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# avatar extraction (blob -> file reference)
# --------------------------------------------------------------------------- #
def save_avatar(image_bytes, fin_kod, outdir):
    if not image_bytes:
        return None
    os.makedirs(outdir, exist_ok=True)
    ext = "img"
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(bytes(image_bytes)))
        ext = (im.format or "png").lower()
    except Exception:
        ext = "bin"
    fname = f"{fin_kod}.{ext}"
    with open(os.path.join(outdir, fname), "wb") as f:
        f.write(bytes(image_bytes))
    return f"avatars/{fname}"


# --------------------------------------------------------------------------- #
# extraction
# --------------------------------------------------------------------------- #
def extract(cur):
    data = {
        "institution": fetch(cur, 'SELECT * FROM institution'),
        "prioritets": fetch(cur, 'SELECT * FROM prioritets'),
        "auth": fetch(cur, 'SELECT * FROM auth'),
        "user": fetch(cur, 'SELECT * FROM "User"'),
        "otp": fetch(cur, 'SELECT * FROM otp'),
        "experts": fetch(cur, 'SELECT * FROM experts'),
        "project": fetch(cur, 'SELECT * FROM project'),
        "collaborators": fetch(cur, 'SELECT * FROM collaborators'),
        "project_activities": fetch(cur, 'SELECT * FROM project_activities'),
        "quarterly_reports": fetch(cur, 'SELECT * FROM quarterly_reports'),
        "smeta": fetch(cur, 'SELECT * FROM smeta'),
        "salary_smeta": fetch(cur, 'SELECT * FROM salary_smeta'),
        "subject_of_purchase": fetch(cur, 'SELECT * FROM subject_of_purchase'),
        "services": fetch(cur, 'SELECT * FROM services'),
        "rent_table": fetch(cur, 'SELECT * FROM rent_table'),
        "other_expenses": fetch(cur, 'SELECT * FROM other_expenses'),
    }
    # assessment table may not exist (model was never created in the live DB)
    data["assessment"] = fetch(cur, 'SELECT * FROM assessment') if table_exists(cur, "assessment") else None
    return data


# --------------------------------------------------------------------------- #
# load
# --------------------------------------------------------------------------- #
def truncate_all(s):
    names = [t.name for t in Base.metadata.sorted_tables]
    s.execute(text("TRUNCATE TABLE " + ", ".join(f'"{n}"' for n in names) + " RESTART IDENTITY CASCADE"))


def load(data, s, avatars_dir):
    # 1) institutions ------------------------------------------------------- #
    inst_by_code = {}
    for r in data["institution"]:
        o = Institution(code=r["institution_code"], name=r["institution_name"],
                        created_at=r.get("created_at") or now())
        s.add(o)
        inst_by_code[r["institution_code"]] = o
    s.flush()
    log(f"institutions: {len(inst_by_code)}")

    # 2) priorities --------------------------------------------------------- #
    prio_by_code = {}
    for r in data["prioritets"]:
        o = Priority(code=r["prioritet_code"], name=r["prioritet_name"],
                     created_at=r.get("created_at") or now())
        s.add(o)
        prio_by_code[r["prioritet_code"]] = o
    s.flush()
    log(f"priorities: {len(prio_by_code)}")

    # 3) users (+ credentials, otp) ---------------------------------------- #
    users_by_fin = {row["fin_kod"]: row for row in data["user"]}
    auth_by_fin = {row["fin_kod"]: row for row in data["auth"]}
    all_fins = list(dict.fromkeys(list(users_by_fin) + list(auth_by_fin)))

    user_obj = {}      # fin_kod -> User
    avatars_saved = 0
    for fin in all_fins:
        u = users_by_fin.get(fin)
        a = auth_by_fin.get(fin)
        inst = None
        if u and u.get("institution_code"):
            inst = inst_by_code.get(u["institution_code"])
            if inst is None:
                log(f"  ! user {fin}: institution_code {u['institution_code']!r} not found -> NULL")
        avatar_url = None
        if u and u.get("image"):
            avatar_url = save_avatar(u["image"], fin, avatars_dir)
            if avatar_url:
                avatars_saved += 1

        obj = User(
            fin_kod=fin,
            global_role=global_role(a["project_role"]) if a else GlobalRole.APPLICANT,
            academic_type=academic_type(a["user_type"]) if a else None,
            name=(u or {}).get("name"),
            surname=(u or {}).get("surname"),
            father_name=(u or {}).get("father_name"),
            born_date=(u or {}).get("born_date"),
            born_place=(u or {}).get("born_place"),
            sex=(u or {}).get("sex"),
            citizenship=(u or {}).get("citizenship"),
            personal_id_number=(u or {}).get("personal_id_number"),
            living_location=(u or {}).get("living_location"),
            home_phone=(u or {}).get("home_phone"),
            personal_mobile_number=(u or {}).get("personal_mobile_number"),
            personal_email=(u or {}).get("personal_email"),
            work_place=(u or {}).get("work_place"),
            department=(u or {}).get("department"),
            duty=(u or {}).get("duty"),
            work_location=(u or {}).get("work_location"),
            work_phone=(u or {}).get("work_phone"),
            work_email=(u or {}).get("work_email"),
            main_education=(u or {}).get("main_education"),
            additional_education=(u or {}).get("additonal_education"),  # legacy typo
            scientific_degree=(u or {}).get("scientific_degree"),
            scientific_degree_date=(u or {}).get("scientific_date"),
            scientific_title=(u or {}).get("scientific_name"),
            scientific_title_date=(u or {}).get("scientific_name_date"),
            institution_id=inst.id if inst else None,
            avatar_url=avatar_url,
            profile_completed=bool((u or {}).get("profile_completed")),
            created_at=(u or {}).get("created_at") or (a or {}).get("created_at") or now(),
        )
        s.add(obj)
        user_obj[fin] = obj
        if u is None:
            log(f"  ! auth {fin} has no User profile -> synthesized minimal user")
    s.flush()
    log(f"users: {len(user_obj)} (avatars extracted: {avatars_saved})")

    # credentials
    n_cred = 0
    for fin, a in auth_by_fin.items():
        s.add(Credential(
            user_id=user_obj[fin].id,
            password_hash=a["password_hash"],
            status=account_status(a.get("approved"), a.get("blocked")),
            otp_verified=bool(a.get("otp_verificated")),
            approved_at=a.get("approved_at"),
            blocked_at=a.get("blocked_at"),
            unblocked_at=a.get("unblocked_at"),
            created_at=a.get("created_at") or now(),
        ))
        n_cred += 1
    s.flush()
    log(f"credentials: {n_cred}")

    # otp codes
    n_otp = 0
    for r in data["otp"]:
        u = user_obj.get(r["fin_kod"])
        if not u:
            log(f"  ! otp for unknown fin_kod {r['fin_kod']} -> skipped")
            continue
        s.add(OtpCode(user_id=u.id, code=str(r["otp"]),
                      issued_at=r["issued_at"], expires_at=r["expires_at"]))
        n_otp += 1
    s.flush()
    log(f"otp_codes: {n_otp}")

    # 4) experts ------------------------------------------------------------ #
    expert_by_email = {}
    for r in data["experts"]:
        o = Expert(
            email=r["email"], name=r["name"], surname=r["surname"],
            father_name=r["father_name"],
            personal_id_serial_number=r["personal_id_serial_number"],
            work_place=r.get("work_place"), duty=r.get("duty"),
            scientific_degree=r.get("scientific_degree"), phone_number=r.get("phone_number"),
        )
        s.add(o)
        expert_by_email[r["email"]] = o
    s.flush()
    log(f"experts: {len(expert_by_email)}")

    # 5) projects ----------------------------------------------------------- #
    proj_by_code = {}
    for r in data["project"]:
        owner = user_obj.get(r["fin_kod"])
        if owner is None:  # owner referenced but no auth/User -> synthesize
            owner = User(fin_kod=r["fin_kod"], global_role=GlobalRole.APPLICANT,
                         profile_completed=False, created_at=now())
            s.add(owner); s.flush()
            user_obj[r["fin_kod"]] = owner
            log(f"  ! project {r['project_code']} owner {r['fin_kod']} missing -> synthesized user")
        prio = None
        if r.get("priotet"):
            try:
                prio = prio_by_code.get(int(str(r["priotet"]).strip()))
            except (ValueError, TypeError):
                prio = None
            if prio is None:
                log(f"  ! project {r['project_code']}: priotet {r['priotet']!r} unresolved -> NULL")
        has_expert = bool(r.get("expert"))
        o = Project(
            project_code=r["project_code"],
            owner_id=owner.id,
            institution_id=None,
            priority_id=prio.id if prio else None,
            project_name=r.get("project_name"),
            project_purpose=r.get("project_purpose"),
            annotation=r.get("project_annotation"),
            key_words=r.get("project_key_words"),
            scientific_idea=r.get("project_scientific_idea"),
            structure=r.get("project_structure"),
            team_characterization=r.get("team_characterization"),
            monitoring_plan=r.get("project_monitoring"),
            assessment_plan=r.get("project_assessment"),
            requirements=r.get("project_requirements"),
            deadline=r.get("project_deadline"),
            status=project_status(r.get("submitted"), has_expert),
            submitted_at=r.get("submitted_at"),
            collaborator_limit=r.get("collaborator_limit") or 7,
            max_budget_amount=r.get("max_smeta_amount") or 30000,
        )
        s.add(o)
        proj_by_code[r["project_code"]] = o
    s.flush()
    log(f"projects: {len(proj_by_code)}")

    # 6) project_members (owner row + collaborators) ----------------------- #
    member_by_pc_fin = {}  # (project_code, fin_kod) -> ProjectMember
    for code, p in proj_by_code.items():
        proj_row = next(r for r in data["project"] if r["project_code"] == code)
        owner = ProjectMember(project_id=p.id, user_id=user_obj[proj_row["fin_kod"]].id,
                              role=MemberRole.OWNER, status=MemberStatus.APPROVED,
                              approved_at=proj_row.get("submitted_at"))
        s.add(owner)
        member_by_pc_fin[(code, proj_row["fin_kod"])] = owner
    for r in data["collaborators"]:
        p = proj_by_code.get(r["project_code"])
        u = user_obj.get(r["fin_kod"])
        if not p or not u:
            log(f"  ! collaborator {r['fin_kod']} / project {r['project_code']} unresolved -> skipped")
            continue
        if (r["project_code"], r["fin_kod"]) in member_by_pc_fin:
            continue  # already the owner
        m = ProjectMember(project_id=p.id, user_id=u.id, role=MemberRole.COLLABORATOR,
                          status=member_status(r.get("approved")))
        s.add(m)
        member_by_pc_fin[(r["project_code"], r["fin_kod"])] = m
    s.flush()
    log(f"project_members: {len(member_by_pc_fin)}")

    # 7) project_activities ------------------------------------------------- #
    n_act = 0
    for r in data["project_activities"]:
        p = proj_by_code.get(r["project_code"])
        if not p:
            log(f"  ! activity for unknown project {r['project_code']} -> skipped"); continue
        s.add(ProjectActivity(project_id=p.id, month=r["month"], activity_name=r["activity_name"],
                              created_at=r.get("created_at") or now()))
        n_act += 1
    s.flush()
    log(f"project_activities: {n_act}")

    # 8) expert_assignments (from project.expert email) -------------------- #
    n_assign = 0
    for r in data["project"]:
        email = (r.get("expert") or "").strip()
        if not email:
            continue
        e = expert_by_email.get(email)
        p = proj_by_code.get(r["project_code"])
        if not e or not p:
            log(f"  ! expert {email!r} for project {r['project_code']} unresolved -> skipped"); continue
        s.add(ExpertAssignment(project_id=p.id, expert_id=e.id,
                               status=AssignmentStatus.ASSIGNED,
                               assigned_at=r.get("submitted_at") or now()))
        n_assign += 1
    s.flush()
    log(f"expert_assignments: {n_assign}")

    # 9) assessments (table may be absent) --------------------------------- #
    n_assess = 0
    if data["assessment"] is None:
        log("assessments: legacy table absent -> skipped")
    else:
        for r in data["assessment"]:
            p = proj_by_code.get(r["project_code"])
            e = expert_by_email.get((r.get("expert") or "").strip())
            if not p or not e:
                log(f"  ! assessment project {r.get('project_code')} / expert {r.get('expert')} unresolved -> skipped"); continue
            s.add(Assessment(project_id=p.id, expert_id=e.id,
                             score=r.get("assessment"), note=r.get("note")))
            n_assess += 1
        s.flush()
        log(f"assessments: {n_assess}")

    # 10) quarterly_reports + items ---------------------------------------- #
    n_rep, n_item = 0, 0
    for r in data["quarterly_reports"]:
        p = proj_by_code.get(r["project_code"])
        if not p:
            log(f"  ! report for unknown project {r['project_code']} -> skipped"); continue
        rep = QuarterlyReport(project_id=p.id, quarter_number=r["quarter_number"],
                              year=r["year"], submission_date=r.get("submission_date"))
        s.add(rep); s.flush()
        n_rep += 1
        for i in range(1, 18):
            val = r.get(f"point_{i}")
            if val is not None and str(val).strip() != "":
                s.add(QuarterlyReportItem(report_id=rep.id, item_no=i, content=val))
                n_item += 1
    s.flush()
    log(f"quarterly_reports: {n_rep} (items: {n_item})")

    # 11) budgets (one per project) ---------------------------------------- #
    smeta_by_code = {r["project_code"]: r for r in data["smeta"]}
    budget_by_code = {}
    for code, p in proj_by_code.items():
        sm = smeta_by_code.get(code, {})
        b = Budget(project_id=p.id,
                   total_fee=sm.get("total_fee") or 0,
                   defense_fund=sm.get("defense_fund") or 0)
        s.add(b)
        budget_by_code[code] = b
    s.flush()
    log(f"budgets: {len(budget_by_code)}")

    # 12) budget_salaries --------------------------------------------------- #
    n_sal = 0
    for r in data["salary_smeta"]:
        b = budget_by_code.get(r["project_code"])
        m = member_by_pc_fin.get((r["project_code"], r["fin_kod"]))
        if not b or not m:
            log(f"  ! salary project {r['project_code']} / {r['fin_kod']} unresolved -> skipped"); continue
        s.add(BudgetSalary(budget_id=b.id, member_id=m.id,
                           salary_per_month=r["salary_per_month"], months=r["months"]))
        n_sal += 1
    s.flush()
    log(f"budget_salaries: {n_sal}")

    # 13) budget_line_items (unify 4 legacy tables) ------------------------ #
    def add_lines(rows, category, name_field, has_duration):
        added = 0
        for r in rows:
            b = budget_by_code.get(r["project_code"])
            if not b:
                log(f"  ! {category.value} line for unknown project {r['project_code']} -> skipped"); continue
            s.add(BudgetLineItem(
                budget_id=b.id, category=category,
                item_name=r[name_field],
                unit_of_measure=r.get("unit_of_measure"),
                unit_price=r.get("unit_price") if "unit_price" in r else r.get("price"),
                quantity=r["quantity"],
                duration=r.get("duration") if has_duration else 1,
            ))
            added += 1
        return added

    n_eq = add_lines(data["subject_of_purchase"], BudgetCategory.EQUIPMENT, "equipment_name", False)
    n_sv = add_lines(data["services"], BudgetCategory.SERVICES, "services_name", False)
    n_rt = add_lines(data["rent_table"], BudgetCategory.RENT, "rent_area", True)
    n_ot = add_lines(data["other_expenses"], BudgetCategory.OTHER, "expenses_name", True)
    s.flush()
    log(f"budget_line_items: {n_eq + n_sv + n_rt + n_ot} (eq={n_eq} sv={n_sv} rent={n_rt} other={n_ot})")

    # 14) refresh cached budget totals from the (DB-computed) children ------ #
    s.flush()
    for code, b in budget_by_code.items():
        sal = s.execute(text("SELECT COALESCE(SUM(total_amount),0) FROM budget_salaries WHERE budget_id=:b"),
                        {"b": b.id}).scalar()
        eq = s.execute(text("SELECT COALESCE(SUM(total_amount),0) FROM budget_line_items WHERE budget_id=:b AND category='EQUIPMENT'"), {"b": b.id}).scalar()
        sv = s.execute(text("SELECT COALESCE(SUM(total_amount),0) FROM budget_line_items WHERE budget_id=:b AND category='SERVICES'"), {"b": b.id}).scalar()
        rt = s.execute(text("SELECT COALESCE(SUM(total_amount),0) FROM budget_line_items WHERE budget_id=:b AND category='RENT'"), {"b": b.id}).scalar()
        ot = s.execute(text("SELECT COALESCE(SUM(total_amount),0) FROM budget_line_items WHERE budget_id=:b AND category='OTHER'"), {"b": b.id}).scalar()
        b.total_salary, b.total_equipment, b.total_services, b.total_rent, b.total_other = sal, eq, sv, rt, ot
        b.grand_total = sal + eq + sv + rt + ot + (b.total_fee or 0) + (b.defense_fund or 0)
    s.flush()
    log("budget totals: recomputed from line items")


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def validate(data, s):
    log("\n=== VALIDATION (old -> new) ===")
    checks = [
        ("institutions", len(data["institution"]), s.query(Institution).count()),
        ("priorities", len(data["prioritets"]), s.query(Priority).count()),
        ("users (auth ∪ User)", len(set([r["fin_kod"] for r in data["auth"]] + [r["fin_kod"] for r in data["user"]])), s.query(User).count()),
        ("credentials = auth", len(data["auth"]), s.query(Credential).count()),
        ("experts", len(data["experts"]), s.query(Expert).count()),
        ("projects", len(data["project"]), s.query(Project).count()),
        ("budgets = projects", len(data["project"]), s.query(Budget).count()),
        ("budget_salaries", len(data["salary_smeta"]), s.query(BudgetSalary).count()),
        ("line_items", len(data["subject_of_purchase"]) + len(data["services"]) + len(data["rent_table"]) + len(data["other_expenses"]), s.query(BudgetLineItem).count()),
    ]
    ok = True
    for label, old, new in checks:
        flag = "OK " if old == new else "!! "
        if old != new:
            ok = False
        log(f"  {flag}{label:28} old={old:<5} new={new}")
    log("=== " + ("ALL COUNTS MATCH" if ok else "MISMATCHES ABOVE — REVIEW") + " ===")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="E-Grant old->new data migration")
    ap.add_argument("--old-db-url", default=os.getenv("OLD_DATABASE_URL") or os.getenv("DATABASE_URL"))
    ap.add_argument("--new-db-url", default=os.getenv("NEW_DATABASE_URL"))
    ap.add_argument("--reset", action="store_true", help="DROP + recreate new schema first")
    ap.add_argument("--dry-run", action="store_true", help="read OLD only, print plan, no writes")
    ap.add_argument("--avatars-dir", default=os.path.join(os.path.dirname(__file__), "avatars"))
    args = ap.parse_args()

    if not args.old_db_url:
        sys.exit("ERROR: set OLD_DATABASE_URL (or DATABASE_URL).")

    # read OLD (read-only)
    oconn = psycopg2.connect(args.old_db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    oconn.set_session(readonly=True, autocommit=True)
    with oconn.cursor() as cur:
        data = extract(cur)
    oconn.close()
    log("extracted from OLD DB: " + ", ".join(f"{k}={len(v) if v is not None else 'absent'}" for k, v in data.items()))

    if args.dry_run:
        log("\n--dry-run: no target writes. Planned source rows above. "
            "Run without --dry-run (and NEW_DATABASE_URL set) to load.")
        return

    if not args.new_db_url:
        sys.exit("ERROR: set NEW_DATABASE_URL (an EMPTY Postgres DB).")
    if args.new_db_url == args.old_db_url:
        sys.exit("ERROR: NEW_DATABASE_URL must differ from OLD — refusing to write into the source.")

    engine = create_engine(args.new_db_url, future=True)
    if args.reset:
        log("reset: dropping + recreating schema")
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with Session(engine) as s:
        truncate_all(s)
        load(data, s, args.avatars_dir)
        s.execute(text(V_BUDGET_TOTALS_SQL))
        validate(data, s)
        s.commit()
    log("\nDONE — committed to NEW DB.")


if __name__ == "__main__":
    main()

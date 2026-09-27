"""End-to-end security checks against the real Flask app on a throwaway SQLite DB.

Run from the backend directory:
    <venv>/bin/python test_security.py
"""
import os, re, sys, tempfile, datetime

DB = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{DB}",
    "SECRET_KEY": "t" * 64,
    "PUBLIC_API_KEY": "public-test-key",
    "CORS_ORIGINS": "https://admin-e-grant.aztu.edu.az",
    "ENABLE_SWAGGER": "false",
    # Empty SMTP settings: nothing can leave this machine.
    "SMTP_SERVER": "", "SMTP_PORT": "", "SMTP_USER": "", "SMTP_PASSWORD": "",
    "UPLOAD_FOLDER": tempfile.mkdtemp(),
})
sys.path.insert(0, os.getcwd())

SENT = []
import utils.email_util as eu
def fake_send(subject, recipient, html, text=None):
    SENT.append((subject, recipient, html)); return True
eu.send_email = fake_send

# This machine's Python 3.9 has no hashlib.scrypt (Werkzeug's default). Force
# pbkdf2 for the test only — production Python 3.11/3.13 uses scrypt as shipped.
import werkzeug.security as _ws
_orig_hash = _ws.generate_password_hash
_ws.generate_password_hash = lambda pw, method="pbkdf2:sha256", salt_length=16: _orig_hash(pw, method="pbkdf2:sha256", salt_length=salt_length)

from app import main_app
from config.limiter import limiter
import controllers.AuthController as AC
AC.send_email = fake_send
import controllers.ProjectController as PC
class _NoNet:
    @staticmethod
    def get(*a, **k): raise RuntimeError("no network in tests")
PC.requests = _NoNet

# SQLite (test only) rejects autoincrement on a composite primary key, which a
# few smeta tables declare. Production runs Postgres, which accepts it; disable
# it just for this in-memory build.
import extentions.db as _ext
from sqlalchemy import PrimaryKeyConstraint as _PK
_orig_create_all = _ext.db.create_all
def _create_all(*a, **k):
    # A few smeta tables declare a composite PK (id, project_code); SQLite can't
    # autoincrement a column in a composite PK. For the test DB, reduce the PK to
    # just `id`. Production is Postgres and keeps the model as-is.
    for _t in list(_ext.db.metadata.tables.values()):
        _pkcols = [c for c in _t.primary_key.columns]
        if len(_pkcols) > 1 and 'id' in _t.columns:
            for _col in _pkcols:
                _col.primary_key = (_col.name == 'id')
            _t.constraints = {c for c in _t.constraints if not isinstance(c, _PK)}
            _t.append_constraint(_PK(_t.c.id))
    return _orig_create_all(*a, **k)
_ext.db.create_all = _create_all

app = main_app()
app.testing = True
limiter.enabled = False

from extentions.db import db
from models.authModel import Auth
from models.userModel import User
from models.projectModel import Project
from models.collaboratorModel import Collaborator
from models.competitionModel import Competition
from models.systemLockModel import SystemLock
from models.projectActivities import ProjectActivities
from utils.jwt_util import encode_auth_token, encode_expert_token, encode_otp_token

FAIL = []
PASS = 0
def check(cond, label):
    global PASS
    if cond: PASS += 1
    else: FAIL.append(label); print("FAIL:", label)

now = datetime.datetime.utcnow()
with app.app_context():
    comp = Competition(code="C-2026", year=2026, is_active=True)
    db.session.add(comp); db.session.flush()
    def person(fin, role, email, approved=True, blocked=0, must=False):
        a = Auth(fin_kod=fin, user_type=0, project_role=role, approved=approved,
                 created_at=now, blocked=blocked, must_change_password=must)
        a.set_password("Passw0rd!")
        db.session.add(a)
        if role != 3:
            db.session.add(User(fin_kod=fin, name=fin, surname="S", father_name="F",
                                profile_completed=1, personal_email=email, work_email=email,
                                personal_id_number="AA1234567", home_phone=f"h{fin}",
                                personal_mobile_number=f"m{fin}", created_at=now))
        return a
    person("ADMIN01", 2, "admin@aztu.edu.az")
    person("LEADA01", 0, "leada@aztu.edu.az")
    person("LEADB01", 0, "leadb@aztu.edu.az")
    person("COLLC01", 1, "collc@aztu.edu.az")
    person("expert@aztu.edu.az", 3, None)
    person("PEND001", 2, "pend@aztu.edu.az", approved=False)       # a prior self-registration as admin
    person("BLOCK01", 0, "block@aztu.edu.az", blocked=1)
    # 11111111 is a DRAFT owned by leadA (for owner-write tests); 22222222 is
    # leadB's SUBMITTED project; 33333333 is leadA's SUBMITTED project (submit
    # lock). PENDX01 is a PENDING applicant on 11111111 (B-H2).
    db.session.add(Project(project_code=11111111, fin_kod="LEADA01", competition_id=comp.id,
                           project_name="Alpha", approved=1, submitted=False, expert="expert@aztu.edu.az"))
    db.session.add(Project(project_code=22222222, fin_kod="LEADB01", competition_id=comp.id,
                           project_name="Beta", approved=1, submitted=True, winner=True))
    person("LEADD01", 0, "leadd@aztu.edu.az")
    db.session.add(Project(project_code=33333333, fin_kod="LEADD01", competition_id=comp.id,
                           project_name="Gamma", approved=1, submitted=True))
    person("PENDX01", 1, "pendx@aztu.edu.az")
    db.session.add(Collaborator(project_code=11111111, fin_kod="COLLC01", competition_id=comp.id, approved=True))
    db.session.add(Collaborator(project_code=11111111, fin_kod="PENDX01", competition_id=comp.id, approved=False))
    db.session.add(ProjectActivities(project_code=11111111, month=3, months="3", activity_name="x"))
    db.session.add(SystemLock(is_locked=False))
    db.session.commit()
    def _aid(fin):
        return Auth.query.filter_by(fin_kod=fin).first().id
    tok = {
        "admin": encode_auth_token(_aid("ADMIN01"), "ADMIN01", 1, 2),
        "leadA": encode_auth_token(_aid("LEADA01"), "LEADA01", 1, 0),
        "leadB": encode_auth_token(_aid("LEADB01"), "LEADB01", 1, 0),
        "collC": encode_auth_token(_aid("COLLC01"), "COLLC01", 1, 1),
        "expert": encode_expert_token(_aid("expert@aztu.edu.az"), "expert@aztu.edu.az"),
        "pendX": encode_auth_token(_aid("PENDX01"), "PENDX01", 1, 1),
        "leadD": encode_auth_token(_aid("LEADD01"), "LEADD01", 1, 0),
    }
    block_id = _aid("BLOCK01")
    leadd_id = _aid("LEADD01")
    lead_hash = Auth.query.filter_by(fin_kod="LEADA01").first().password_hash

c = app.test_client()
def H(who=None, **extra):
    h = dict(extra)
    if who: h["Authorization"] = f"Bearer {tok[who]}"
    return h

# ---- unauthenticated: everything that is not explicitly public must 401 ----
for m, path in [
    ("GET","/api/users/all"), ("GET","/api/profile/LEADA01"), ("GET","/auth/app-wait-users"),
    ("POST","/api/lock"), ("POST","/api/unlock"), ("GET","/api/lock-status"),
    ("DELETE","/api/del-prioritet/1"), ("POST","/api/upd-prioritet"),
    ("POST","/api/project-activity/create"), ("PATCH","/api/project-activity/update/1"),
    ("DELETE","/api/project-activity/delete/1"), ("POST","/api/reports/save"),
    ("POST","/auth/app-user/PEND001"), ("DELETE","/auth/reject-user/PEND001"),
    ("GET","/api/project-owner/11111111"), ("GET","/api/project-pdf/11111111"),
    ("GET","/api/project-excel/11111111"), ("GET","/api/reports-pdf/11111111"),
    ("GET","/api/projects/submitted"), ("GET","/api/priotet/1"),
    ("GET","/api/institution/1"), ("POST","/api/create-institution/x"),
    ("GET","/api/collaborators"), ("GET","/api/main-smeta/11111111"),
    ("GET","/api/public/projects"),  # public site key required
]:
    r = c.open(path, method=m)
    check(r.status_code in (401,403), f"unauth {m} {path} -> {r.status_code} (want 401/403)")

# public site key
check(c.get("/api/public/projects", headers={"X-Public-Api-Key":"public-test-key"}).status_code==200, "public key accepted")
check(c.get("/api/public/projects", headers={"X-Public-Api-Key":"wrong"}).status_code==401, "public wrong key rejected")

# ---- F1/F9: users/all admin-only, no id/PII ----
check(c.get("/api/users/all", headers=H("leadA")).status_code==403, "users/all non-admin 403")
r = c.get("/api/users/all", headers=H("admin"))
body = r.get_data(as_text=True)
check(r.status_code==200, "users/all admin 200")
check('"id"' not in body, "users/all has no numeric id")
check("personal_id_number" not in body, "users/all has no ID number")
check("home_phone" not in body, "users/all has no phone")

# ---- F2: profile PII only to owner/admin ----
r = c.get("/api/profile/LEADA01", headers=H("leadB"))
check("personal_id_number" not in r.get_data(as_text=True), "profile PII hidden from stranger")
check("personal_id_number" in c.get("/api/profile/LEADA01", headers=H("admin")).get_data(as_text=True), "admin sees PII")
check("personal_id_number" in c.get("/api/profile/LEADA01", headers=H("leadA")).get_data(as_text=True), "owner sees own PII")

# ---- BOLA writes ----
check(c.put("/api/profile/LEADB01/edit", json={"name":"x"}, headers=H("leadA")).status_code==403, "cannot edit another profile")
check(c.get("/api/profile/LEADB01/cv", headers=H("leadA")).status_code in (403,404) and
      c.get("/api/profile/LEADB01/cv", headers=H("leadA")).status_code==403, "cannot download another CV")

# ---- project ownership on writes ----
check(c.post("/api/save/project", json={"fin_kod":"LEADB01","project_name":"h"}, headers=H("leadA")).status_code==403, "cannot save under another fin")
check(c.delete("/api/delete/project", json={"fin_kod":"LEADB01","project_code":22222222}, headers=H("leadA")).status_code==403, "cannot delete another project")
check(c.patch("/api/project-activity/update/1", json={"activity_name":"z"}, headers=H("leadB")).status_code==403, "cannot edit another project's activity")
check(c.patch("/api/project-activity/update/1", json={"activity_name":"z"}, headers=H("leadA")).status_code==200, "owner edits own activity")

# ---- project read guard: expert only its own, member allowed, stranger blocked ----
check(c.get("/api/project-details/11111111", headers=H("expert")).status_code==200, "assigned expert reads project")
check(c.get("/api/project-details/22222222", headers=H("expert")).status_code==403, "expert blocked from other project")
check(c.get("/api/project-details/11111111", headers=H("collC")).status_code==200, "team member reads project")
check(c.get("/api/project-details/11111111", headers=H("leadB")).status_code==403, "stranger blocked from project")

# ---- admin lock is server-enforced on budget/activity writes ----
with app.app_context():
    SystemLock.query.first().is_locked = True; db.session.commit()
check(c.post("/api/project-activity/create", json={"activity_name":"n","project_code":11111111,"months":[4]}, headers=H("leadA")).status_code==423, "system lock blocks lead write")
check(c.post("/api/project-activity/create", json={"activity_name":"n","project_code":11111111,"months":[4]}, headers=H("admin")).status_code in (201,200), "admin bypasses system lock")
with app.app_context():
    SystemLock.query.first().is_locked = False; db.session.commit()

# ---- email sign-in ----
def signin(email, pw="Passw0rd!", ut=0):
    return c.post("/auth/signin", json={"email":email,"password":pw,"user_type":ut})
r = signin("leada@aztu.edu.az")
check(r.status_code==200, "sign in by email works")
check(r.get_json()["data"]["auth"]["fin_kod"]=="LEADA01", "email resolves to right account")
check(signin("expert@aztu.edu.az").status_code==200, "expert signs in by email")
check(signin("nope@aztu.edu.az").status_code==401, "unknown email 401")
check(signin("leada@aztu.edu.az","wrong").status_code==401, "wrong password 401")
check("yanlış" in signin("leada@aztu.edu.az","wrong").get_json().get("message","").lower(), "generic sign-in message")
check(signin("block@aztu.edu.az").status_code==401, "blocked account cannot sign in")

# ---- privilege escalation on pending self-registered admin ----
check(c.post("/auth/app-user/PEND001", headers=H("admin")).status_code==409, "cannot approve a self-assigned admin role")

# ---- role re-read: token role ignored, DB role wins (blocked user's token dead) ----
with app.app_context():
    dead = encode_auth_token(block_id, "BLOCK01", 1, 0)
check(c.get("/api/notifications", headers={"Authorization":f"Bearer {dead}"}).status_code==401, "blocked user's token rejected")

# ---- signup rejects self-assigned elevated role & duplicate email ----
check(c.post("/auth/signup", json={"fin_kod":"NEWU0001","password":"Passw0rd!","user_type":0,
      "project_role":2,"email":"new@aztu.edu.az","name":"n","surname":"s","father_name":"f",
      "institution_code":"1"}).status_code==400, "signup refuses project_role=2")
# B-L2: a duplicate e-mail gets the SAME generic response as a new signup
# (no 409), and no second account is created for it.
dup = c.post("/auth/signup", json={"fin_kod":"NEWU0002","password":"Passw0rd!","user_type":0,
      "project_role":0,"email":"leada@aztu.edu.az","name":"n","surname":"s","father_name":"f",
      "institution_code":"1"})
check(dup.status_code in (200,201), "duplicate-email signup returns generic success (no enumeration)")
with app.app_context():
    check(Auth.query.filter_by(fin_kod="NEWU0002").first() is None, "duplicate-email signup creates no account")

# ---- reset token is single-use / bound to password (uses a throwaway acct) ----
with app.app_context():
    reset_hash = Auth.query.filter_by(fin_kod="LEADD01").first().password_hash
    rt = encode_otp_token("LEADD01", reset_hash)
check(c.post("/auth/reset-password", json={"token":rt,"password":"NewPassw0rd!"}).status_code==200, "reset with valid token works")
check(c.post("/auth/reset-password", json={"token":rt,"password":"Another1!"}).status_code==401, "reset token dies after use")
# an access token must not work as a reset token
check(c.post("/auth/reset-password", json={"token":tok["leadA"],"password":"Zzzz1234!"}).status_code==401, "access token rejected as reset token")
# LEADD01's password/token_version just changed; re-mint its token for later tests.
with app.app_context():
    tok["leadD"] = encode_auth_token(leadd_id, "LEADD01", 1, 0)

# ---- security headers + no stack traces ----
r = c.get("/api/public/projects", headers={"X-Public-Api-Key":"public-test-key"})
for hdr in ("X-Content-Type-Options","X-Frame-Options","Content-Security-Policy","Referrer-Policy","Strict-Transport-Security"):
    check(hdr in r.headers, f"header {hdr} present")
check(r.headers.get("Server")=="AzTU", "server banner masked")
check("nginx" not in r.headers.get("Server",""), "no nginx version")
# force a handled error path: malformed project code write
r = c.post("/api/reports/save", json={}, headers=H("leadA"))
check("Traceback" not in r.get_data(as_text=True) and "File \"" not in r.get_data(as_text=True), "no stack trace in error body")

# ---- smeta (budget) object-level ownership ----
# leadB must not read or write leadA's project (11111111) budget tables.
check(c.get("/api/main-smeta/11111111", headers=H("leadB")).status_code==403, "stranger cannot read main smeta")
check(c.get("/api/get-rent-all-tables/11111111", headers=H("leadB")).status_code==403, "stranger cannot read rent table")
check(c.post("/api/rent", json={"project_code":11111111,"rent_area":"x","unit_of_measure":"u","unit_price":1,"quantity":1,"duration":1,"total_amount":1}, headers=H("leadB")).status_code==403, "stranger cannot add rent to another project")
check(c.post("/api/create-salary-table", json={"project_code":11111111,"fin_kod":"COLLC01","salary_per_month":1,"months":1}, headers=H("leadB")).status_code==403, "stranger cannot add salary to another project")
check(c.patch("/api/update-smeta-field/11111111", json={"column":"total_rent","value":5}, headers=H("leadB")).status_code==403, "stranger cannot edit another smeta field")
check(c.delete("/api/delete-smeta/11111111", headers=H("leadB")).status_code==403, "stranger cannot delete another smeta")
# the owner CAN
check(c.post("/api/rent", json={"project_code":11111111,"rent_area":"x","unit_of_measure":"u","unit_price":2,"quantity":3,"duration":4,"total_amount":24}, headers=H("leadA")).status_code in (200,201), "owner can add rent")
check(c.get("/api/main-smeta/11111111", headers=H("leadA")).status_code in (200,404), "owner can read own smeta")
# all-salaries is admin-only
check(c.get("/api/all-salaries-table", headers=H("leadA")).status_code==403, "all-salaries admin only")
check(c.get("/api/all-salaries-table", headers=H("admin")).status_code==200, "admin reads all salaries")

# ---- B-H1: lead cannot raise their own cap; submit recomputes total ----
c.post("/api/save/project", json={"fin_kod":"LEADA01","project_code":11111111,
       "project_name":"Alpha","max_smeta_amount":999999,"collaborator_limit":99}, headers=H("leadA"))
detail = c.get("/api/project/11111111", headers=H("leadA")).get_json()["data"]
check(detail["max_smeta_amount"] != 999999, "lead cannot raise max_smeta_amount")
check(detail["collaborator_limit"] != 99, "lead cannot raise collaborator_limit")
# add a line item over the 50000 cap, then submission must be refused
c.post("/api/add-subject", json={"project_code":11111111,"equipment_name":"e","unit_of_measure":"u","price":60000,"quantity":1}, headers=H("leadA"))
r = c.post("/api/submit-project", json={"project_code":11111111}, headers=H("leadA"))
check(r.status_code==409, f"over-cap submission refused (got {r.status_code})")
# client-sent total is ignored: send tiny total, server still computes 60000
check(c.get("/api/main-smeta/11111111", headers=H("leadA")).get_json()["data"]["total_tools_smeta"]==60000, "server computes equipment total from line items")

# ---- B-M2: update-smeta-field is allow-listed ----
check(c.patch("/api/update-smeta-field/11111111", json={"column":"project_code","value":42}, headers=H("leadA")).status_code==400, "update-smeta-field rejects project_code")
check(c.patch("/api/update-smeta-field/11111111", json={"column":"id","value":1}, headers=H("leadA")).status_code==400, "update-smeta-field rejects id")
check(c.patch("/api/update-smeta-field/11111111", json={"column":"total_fee","value":100}, headers=H("leadA")).status_code==200, "update-smeta-field allows total_fee")
check(c.patch("/api/update-smeta-field/11111111", json={"column":"total_fee","value":-5}, headers=H("leadA")).status_code==400, "update-smeta-field rejects negative")

# ---- B-H2: a pending applicant cannot read the project ----
check(c.get("/api/project-details/11111111", headers=H("pendX")).status_code==403, "pending applicant blocked from project detail")
check(c.get("/api/salary/smeta/11111111", headers=H("pendX")).status_code==403, "pending applicant blocked from salaries")

# ---- B-M3: /api/projects is minimal for non-admins, full for admins ----
rows_lead = c.get("/api/projects", headers=H("leadB")).get_json()["data"]
check(all("project_purpose" not in row for row in rows_lead), "non-admin project list is minimal (no proposal body)")
check(all(row.get("fin_kod") in (None, "LEADB01") for row in rows_lead), "non-admin project list hides other leads' FINs")
rows_admin = c.get("/api/projects", headers=H("admin")).get_json()["data"]
check(any("project_purpose" in row for row in rows_admin), "admin project list is full")

# ---- B-M4: public site publishes only submitted/winner ----
pub = {p["project_code"] for p in c.get("/api/public/projects", headers={"X-Public-Api-Key":"public-test-key"}).get_json()["data"]}
check(22222222 in pub and 33333333 in pub, "submitted/winner projects are public")
check(11111111 not in pub, "draft project is not public")

# ---- approve_project is admin-only (B-M4) ----
check(c.post("/api/approve_project", json={"fin_kod":"LEADA01","project_code":11111111}, headers=H("leadA")).status_code==403, "lead cannot self-approve project")

# ---- B-L7: a submitted project is frozen for its lead ----
check(c.post("/api/save/project", json={"fin_kod":"LEADD01","project_code":33333333,"project_name":"x"}, headers=H("leadD")).status_code==423, "submitted project frozen for lead")
check(c.post("/api/rent", json={"project_code":33333333,"rent_area":"x","unit_of_measure":"u","unit_price":1,"quantity":1,"duration":1}, headers=H("leadD")).status_code==423, "submitted project smeta frozen for lead")

# ---- B-L4: OTP moved to the body; old path form is gone ----
check(c.post("/auth/validate-otp/LEADA01/123456").status_code==404, "old validate-otp URL form removed")
check(c.post("/auth/validate-otp", json={"identifier":"leada@aztu.edu.az","otp":"000000"}).status_code==400, "validate-otp body form, wrong code -> 400")
check(c.post("/auth/send-otp", json={"identifier":"leada@aztu.edu.az"}).status_code==200, "send-otp body form returns generic 200")

# ---- B-L3: password change / logout invalidate old tokens ----
before = tok["collC"]
check(c.get("/api/notifications", headers={"Authorization":f"Bearer {before}"}).status_code==200, "token valid before logout")
newtok = c.post("/auth/change-password", json={"current_password":"Passw0rd!","new_password":"BrandNew1!"}, headers={"Authorization":f"Bearer {before}"}).get_json().get("token")
check(c.get("/api/notifications", headers={"Authorization":f"Bearer {before}"}).status_code==401, "old token dies after password change (B-L3)")
check(newtok and c.get("/api/notifications", headers={"Authorization":f"Bearer {newtok}"}).status_code==200, "fresh token from change-password works")

print(f"\n{PASS} checks passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)

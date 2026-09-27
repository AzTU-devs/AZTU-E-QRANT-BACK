import re
import secrets
import logging
import threading
from werkzeug.security import generate_password_hash, check_password_hash
from utils.email_validation import normalise_email, has_valid_syntax
from utils.identity import resolve_account_by_email, resolve_profile, email_taken
from models.otpModel import Otp
from models.authModel import Auth
from models.expertModel import EXPERT_ROLE
from config.limiter import limiter
from flask_limiter.util import get_remote_address
from flask_cors import cross_origin
from models.userModel import db, User
from utils.email_util import send_email
from models.projectModel import  Project
from models.competitionModel import Competition
from datetime import datetime, timedelta, timezone
from utils.jwt_required import token_required
from exceptions.exception import handle_creation
from exceptions.exception import handle_conflict
from exceptions.exception import handle_not_found
from models.collaboratorModel import  Collaborator
from exceptions.exception import handle_unauthorized
from flask import Blueprint, request, render_template, g, current_app
from exceptions.exception import handle_missing_field
from exceptions.exception import handle_signin_success, handle_success
from utils.jwt_util import encode_auth_token, encode_expert_token, encode_otp_token, decode_otp_token, password_fingerprint

auth_bp = Blueprint('auth', __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Roles a person may register themselves with: 0 = project lead, 1 = executor.
# Admin (2) and expert (3) accounts are only ever created by an admin — signup
# used to accept whatever `project_role` the client sent, including 2.
SELF_REGISTERABLE_ROLES = {0, 1}
# 0 = teacher, 1 = PhD, 2 = master
USER_TYPES = {0, 1, 2}
# Roles an admin may assign from the role-management screen.
ASSIGNABLE_ROLES = {0, 1, 2}
MIN_PASSWORD_LENGTH = 8
FIN_PATTERN = re.compile(r'^[A-Za-z0-9]{5,20}$')

# One neutral signup response, whether or not the FIN/e-mail already exists, so
# signup cannot be used to enumerate accounts (finding B-L2).
GENERIC_SIGNUP_MESSAGE = "Qeydiyyat sorğunuz qəbul edildi."

# One message for every sign-in failure, so the response never tells an
# attacker whether an account exists, is pending, is blocked, or which of the
# fields was wrong.
SIGNIN_FAILED = "FIN kod / e-poçt və ya şifrə yanlışdır."

# check_password against this when no account exists keeps the response time
# the same either way (no user-enumeration by timing).
_DUMMY_HASH = generate_password_hash('dummy-password-for-timing')


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _signin_identifier(data):
    """The address typed on the sign-in form. `email` is the field; `fin_kod`
    is still read for clients built before the switch, but only an ADDRESS is
    accepted from either — sign-in by FIN code is no longer possible."""
    return str(data.get('email') or data.get('fin_kod') or '').strip()


def _json_account_key():
    """Loose per-account key (all IPs): a high ceiling that stops sustained
    guessing of one account without letting an attacker lock it out cheaply."""
    data = request.get_json(silent=True) or {}
    return 'acct:' + normalise_email(_signin_identifier(data))


def _json_account_ip_key():
    """Strict key scoped to account + client IP: many rapid failures from one
    source are throttled, but an attacker cannot lock a victim out globally by
    burning the per-account budget from elsewhere (finding B-L5)."""
    data = request.get_json(silent=True) or {}
    return 'acct:' + normalise_email(_signin_identifier(data)) + '|' + get_remote_address()


def _otp_identifier():
    """The account an OTP request targets, from the URL (legacy) or the JSON
    body. Both spellings of one account collapse to one key."""
    identifier = str((request.view_args or {}).get('fin_kod') or '')
    if not identifier:
        data = request.get_json(silent=True) or {}
        identifier = str(data.get('identifier') or data.get('email') or data.get('fin_kod') or '')
    return identifier


def _route_account_key():
    identifier = _otp_identifier()
    user, _ = resolve_profile(identifier)
    return 'acct:' + (user.fin_kod.lower() if user else identifier.strip().lower())


# validate-otp reads the identifier from the body only.
_body_account_key = _route_account_key


@auth_bp.route('/auth/signup', methods=['POST'])
@limiter.limit("30 per hour")
def signup():
    try:
        # Never log the request body here: it contains the plaintext password.
        data = request.get_json(silent=True) or {}

        required_fields = [
            'fin_kod', 
            'password', 
            'user_type',
            'project_role',
            'email',
            'name',
            'surname',
            'father_name',
            'institution_code'
        ]

        for field in required_fields:
            if field not in data:
                logger.warning("Missing field in request data: %s", field)
                return handle_missing_field(400)

        fin_kod = data.get('fin_kod')
        password = data.get('password')
        user_type = data.get('user_type')
        project_role = data.get('project_role')
        email = data.get('email')
        name = data.get('name')
        surname = data.get('surname')
        father_name = data.get('father_name')
        institution_code = data.get('institution_code')

        if not all([fin_kod, password, user_type is not None, project_role is not None, email]):
            logger.warning("One or more required fields are empty")
            return handle_missing_field(400)

        # Validate every value that ends up deciding privileges or identity.
        project_role = _as_int(project_role)
        user_type = _as_int(user_type)
        if project_role not in SELF_REGISTERABLE_ROLES:
            return {"status": 400, "message": "Yalnız layihə rəhbəri və ya icraçı kimi qeydiyyat mümkündür."}, 400
        if user_type not in USER_TYPES:
            return {"status": 400, "message": "İstifadəçi növü düzgün deyil."}, 400
        if not isinstance(fin_kod, str) or not FIN_PATTERN.match(fin_kod):
            return {"status": 400, "message": "FIN kod düzgün formatda deyil."}, 400
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            return {"status": 400, "message": f"Şifrə ən azı {MIN_PASSWORD_LENGTH} simvol olmalıdır."}, 400
        email = normalise_email(email)
        if not has_valid_syntax(email):
            return {"status": 400, "message": "E-poçt ünvanı düzgün formatda deyil."}, 400

        # Account enumeration (finding B-L2): whether or not the FIN/e-mail is
        # already taken, the caller gets the SAME generic response. A duplicate
        # is logged and silently not created, so signup cannot be used to test
        # which FINs or addresses are registered.
        already_exists = (
            email_taken(email)
            or Auth.query.filter_by(fin_kod=fin_kod).first() is not None
            or User.query.filter_by(fin_kod=fin_kod).first() is not None
        )
        if already_exists:
            logger.info("Signup for an already-registered FIN/e-mail; returning generic response")
            return handle_creation(GENERIC_SIGNUP_MESSAGE)

        auth_record = Auth(
            fin_kod=fin_kod,
            user_type=user_type,
            project_role=project_role,
            approved=False,
            created_at=datetime.utcnow(),
            blocked=0
        )
        auth_record.set_password(password)

        user_record = User(
            name=name,
            surname=surname,
            father_name=father_name,
            fin_kod=fin_kod,
            profile_completed=0,
            personal_email=email,
            work_email=email,
            created_at=datetime.utcnow(),
            institution_code=institution_code
        )

        logger.info("Adding new user and auth records to database")
        db.session.add(auth_record)
        db.session.add(user_record)
        db.session.commit()

        subject = "Qeydiyyat"
        recipient = email

        if project_role == 1:
            html_content = render_template("email/coll_registration_template.html", project_role=project_role)
            send_email(subject, recipient, html_content)
        elif project_role == 0:
            html_content = render_template("email/owner_registration_template.html", project_role=project_role)
            send_email(subject, recipient, html_content)

        logger.info("User successfully registered")
        return handle_creation(GENERIC_SIGNUP_MESSAGE)

    except Exception as e:
        logger.exception("An unexpected error occurred during signup")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500

@auth_bp.route('/auth/signin', methods=['POST'])
@limiter.limit("20 per minute; 200 per hour")
@limiter.limit("10 per 10 minutes", key_func=_json_account_ip_key)
@limiter.limit("50 per hour", key_func=_json_account_key)
def signin():
    # Three limits: per client IP, strict per account+IP (throttles one
    # attacker), and a loose per-account ceiling (a victim can still sign in
    # even while someone hammers their account from elsewhere) — B-L5.
    # Two limits: per client address, and per targeted account — the second one
    # stops a password-guessing run against one person from many addresses.
    try:
        data = request.get_json(silent=True) or {}
        identifier = _signin_identifier(data)
        password = data.get('password')
        user_type = data.get('user_type')

        if not all([
            identifier,
            isinstance(password, str) and password,
            user_type is not None,
        ]):
            logger.warning("Missing required signin fields")
            return handle_missing_field(404)

        # Everybody signs in with their e-mail address: staff by the address on
        # their profile, experts by the address their account was created with.
        auth_data = resolve_account_by_email(identifier)
        if auth_data is not None:
            # From here on the FIN is the account's identity, as before.
            fin_kod = auth_data.fin_kod

        if auth_data is None:
            check_password_hash(_DUMMY_HASH, password)
            logger.info("Sign-in failed (unknown identifier)")
            return handle_unauthorized(401, SIGNIN_FAILED)

        if not auth_data.check_password(password) or not auth_data.approved or auth_data.blocked:
            logger.info("Sign-in failed for account id %s", auth_data.id)
            return handle_unauthorized(401, SIGNIN_FAILED)

        # Experts have no teacher/phd/master category, so the choice made on
        # the sign-in screen does not apply to them.
        is_expert = auth_data.project_role == EXPERT_ROLE
        if not is_expert and str(auth_data.user_type) != str(user_type):
            logger.info("Sign-in failed for account id %s (user type)", auth_data.id)
            return handle_unauthorized(401, SIGNIN_FAILED)

        # A profile row backs `encode_auth_token`; experts have none, so give
        # the token issuer what it needs without inventing a User record.
        if is_expert:
            token = encode_expert_token(auth_data.id, auth_data.fin_kod)
            return handle_signin_success({
                "auth": auth_data.auth_details(),
                "project_code": None,
                "collaborator_project_codes": [],
                "profile_completed": 1,
                "is_collaborator": False,
                "must_change_password": bool(auth_data.must_change_password),
            }, "Signed in successfully.", token)
        
        is_collaborator = False

        project_role = auth_data.project_role
        project_code = None

        # Resolve the project for the ACTIVE competition so the user loads this
        # season's project, not a previous year's.
        active_id = Competition.get_active_id()

        # Teams a person joined this season. A lead may take part in one project
        # besides the one they run, so this is read for BOTH roles — but for a
        # lead `project_code` stays the project they own.
        collaborations = Collaborator.query.filter_by(
            fin_kod=fin_kod, competition_id=active_id
        ).all()
        is_collaborator = bool(collaborations)
        collaborator_project_codes = [c.project_code for c in collaborations]

        if project_role == 0:
            project_owner = Project.query.filter_by(fin_kod=fin_kod, competition_id=active_id).first()
            project_code = project_owner.project_code if project_owner else None

        elif project_role == 1 and collaborations:
            project_code = collaborations[0].project_code

        user_data = User.query.filter_by(fin_kod=fin_kod).first()
        if user_data is None:
            logger.warning("Sign-in: account id %s has no profile row", auth_data.id)
            return handle_unauthorized(401, SIGNIN_FAILED)
        
        profile_completed = user_data.profile_completed

        signin_data = {
            "auth": auth_data.auth_details(),
            "project_code": project_code,
            "collaborator_project_codes": collaborator_project_codes,
            "profile_completed": profile_completed,
            "is_collaborator": is_collaborator
        }

        token = encode_auth_token(auth_data.id, fin_kod, profile_completed, role=project_role)
        logger.info("Signed in: account id %s", auth_data.id)
        return handle_signin_success(signin_data, "Signed in successfully.", token)

    except Exception as e:
        logger.exception("Unexpected error during signin")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500
    

def _current_account_key():
    """Rate-limit key for an authenticated action: the caller's own account."""
    return 'acct:' + str((getattr(g, 'user', None) or {}).get('fin_kod') or get_remote_address())


@auth_bp.route('/api/logout', methods=['POST'])
@limiter.limit("30 per minute")
@token_required([0, 1, 2, EXPERT_ROLE])
def logout():
    """Invalidate every token for the caller by bumping the token version
    (finding B-L3). The client also drops its copy; this makes a stolen or
    still-cached token useless server-side immediately."""
    try:
        account = Auth.query.filter_by(fin_kod=g.user.get('fin_kod')).first()
        if account:
            account.bump_token_version()
            db.session.commit()
        return handle_success(None, 'Çıxış edildi.')
    except Exception:
        db.session.rollback()
        logger.exception("logout failed")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500


@auth_bp.route('/auth/change-password', methods=['POST'])
@limiter.limit("5 per 15 minutes", key_func=_current_account_key)
@token_required([0, 1, 2, EXPERT_ROLE])
def change_password():
    """Replace your own password.

    This is what clears `must_change_password`, which is set when an expert is
    e-mailed a one-time password on appointment: the account works, but every
    screen keeps sending them back here until they choose their own.
    """
    try:
        data = request.get_json() or {}
        current_password = data.get('current_password')
        new_password = data.get('new_password')

        if not current_password or not new_password:
            return {'error': 'Cari və yeni şifrə tələb olunur.', 'status': 400}, 400

        if len(new_password) < 8:
            return {'error': 'Yeni şifrə ən azı 8 simvol olmalıdır.', 'status': 400}, 400

        account = Auth.query.filter_by(fin_kod=g.user.get('fin_kod')).first()
        if not account:
            return {'error': 'İstifadəçi tapılmadı.', 'status': 404}, 404

        if not account.check_password(current_password):
            return {'error': 'Cari şifrə yanlışdır.', 'status': 403}, 403

        if account.check_password(new_password):
            return {'error': 'Yeni şifrə köhnə şifrədən fərqli olmalıdır.', 'status': 400}, 400

        # set_password bumps token_version, so every OTHER session's token dies
        # (B-L3). We hand back a fresh token minted at the new version so the
        # CURRENT session keeps working.
        account.set_password(new_password)
        account.must_change_password = False
        db.session.commit()

        if account.project_role == EXPERT_ROLE:
            fresh = encode_expert_token(account.id, account.fin_kod)
            profile_completed = 1
        else:
            profile = User.query.filter_by(fin_kod=account.fin_kod).first()
            profile_completed = profile.profile_completed if profile else 0
            fresh = encode_auth_token(account.id, account.fin_kod, profile_completed, account.project_role)

        logger.info("Password changed for account id %s", account.id)
        return handle_signin_success(
            {'fin_kod': account.fin_kod, 'must_change_password': False,
             'profile_completed': profile_completed},
            'Şifrə uğurla dəyişdirildi.', fresh,
        )

    except Exception:
        db.session.rollback()
        logger.exception("change_password failed")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500


@auth_bp.route("/auth/app-wait-users", methods=['GET'])
@limiter.limit("300 per minute")
@token_required([2])
def get_app_wait_users():
    # Admin-only: this lists the FIN codes of everyone awaiting approval, which
    # was previously readable with no authentication at all (pentest F3).
    try:
        users = Auth.query.filter_by(approved=False).all()

        if not users:
            return handle_not_found(404)
        
        users_data = [
            {
                "fin_kod": user.fin_kod,
                "project_role": user.project_role
            } for user in users
        ]
        
        return handle_success(users_data, "Users fetched successfully.")
    
    except Exception as e:
        logger.exception("Unexpected error during signin")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500
    

@auth_bp.route("/auth/app-user/<string:fin_kod>", methods=['POST'])
@limiter.limit("300 per minute")
@token_required([2])
def app_user(fin_kod):
    # Admin-only: approves a pending registration. Without a token check anyone
    # could approve any account (pentest F4 — chained with the FIN codes leaked
    # by F3 and the numeric ids leaked by F9).
    try:
        user = Auth.query.filter_by(fin_kod=fin_kod).first()

        if not user:
            return handle_not_found(404)

        # A self-registration can only ever be a lead (0) or an executor (1).
        # Anything else in a pending row was requested by the client (signup
        # used to accept any role) and must not be approved into existence —
        # an admin grants elevated roles on the role-management screen instead.
        if not user.approved and user.project_role not in SELF_REGISTERABLE_ROLES:
            return {"status": 409, "message": "This registration requested a role that cannot be self-assigned."}, 409

        user.approved=True

        db.session.commit()

        profile = User.query.filter_by(fin_kod=fin_kod).first()
        user_email = profile.personal_email if profile else None

        subject = "Qeydiyyat təsdiqi"
        recipient = user_email

        if user.project_role == 1:
            html_content = render_template("email/coll_reg_approve_template.html", project_role=user.project_role)
            send_email(subject, recipient, html_content)
        elif user.project_role == 0:
            html_content = render_template("email/owner_reg_approve_template.html", project_role=user.project_role)
            send_email(subject, recipient, html_content)

        return {"statusCode": 200, "message": "User approved successfully."}, 200
    
    except Exception as e:
        logger.exception("Unexpected error during signin")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500
    
@auth_bp.route("/auth/reject-user/<string:fin_kod>", methods=['DELETE'])
@limiter.limit("30 per minute")
@token_required([2])
def reject_user(fin_kod):
    # Admin-only: rejects (deletes) a PENDING registration. Was reachable with
    # no authentication (pentest F4). It only ever acts on accounts still
    # awaiting approval — removing an approved person is `DELETE /api/user/<fin>`,
    # which also cleans up everything they own.
    try:
        auth_user = Auth.query.filter_by(fin_kod=fin_kod).first()
        if not auth_user:
            return handle_not_found(404)
        if auth_user.approved:
            return {"status": 409, "message": "Only pending registrations can be rejected."}, 409

        user = User.query.filter_by(fin_kod=fin_kod).first()
        user_email = user.personal_email if user else None
        project_role = auth_user.project_role

        db.session.delete(auth_user)
        if user:
            db.session.delete(user)
        db.session.commit()

        subject = "Uğursuz qeydiyyat"
        if user_email and project_role == 1:
            html_content = render_template("email/coll_reg_reject_template.html", project_role=project_role)
            send_email(subject, user_email, html_content)
        elif user_email and project_role == 0:
            html_content = render_template("email/owner_reg_reject_template.html", project_role=project_role)
            send_email(subject, user_email, html_content)

        return {"statusCode": 200, "message": "User rejected successfully."}, 200

    except Exception as e:
        db.session.rollback()
        logger.exception("Unexpected error while rejecting a registration")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500


OTP_LENGTH = 6
OTP_TTL_MINUTES = 5


def generateOtp(length: int = OTP_LENGTH) -> str:
    # `secrets`, not `random`: the code is a credential and must not be predictable.
    return ''.join(str(secrets.randbelow(10)) for _ in range(length))

import pytz

# Same answer whether or not the FIN exists, so this endpoint cannot be used to
# test which FIN codes are registered.
OTP_SENT_MESSAGE = "OTP sent successfully"


def _deliver_otp_async(app, subject, recipient, html):
    """Send the OTP e-mail on a background thread so the endpoint's response
    time does not depend on the SMTP round-trip — otherwise the delay itself
    would reveal whether the account exists (finding B-L4 / B-L2 timing)."""
    def _run():
        with app.app_context():
            try:
                send_email(subject, recipient, html)
            except Exception:
                logger.exception("Background OTP e-mail failed")
    threading.Thread(target=_run, daemon=True).start()


@auth_bp.route("/auth/send-otp", methods=['POST'])
@auth_bp.route("/auth/send-otp/<string:fin_kod>", methods=['POST'])
@limiter.limit("5 per minute; 20 per hour")
@limiter.limit("3 per 10 minutes", key_func=_route_account_key)
def send_otp(fin_kod=None):
    # The identifier (e-mail) is taken from the JSON body; the legacy path form
    # is still accepted. Rate-limited per address AND per account. Always the
    # same response, and the e-mail goes out on a background thread so timing
    # cannot reveal whether the account exists (B-L2 / B-L4).
    try:
        identifier = fin_kod or (request.get_json(silent=True) or {}).get('identifier') \
            or (request.get_json(silent=True) or {}).get('email')
        user, account = resolve_profile(identifier or '')

        email = (user.work_email or user.personal_email) if user else None
        if user and account and email:
            otp = generateOtp()
            issued_at = datetime.now(pytz.timezone("Asia/Baku"))
            # Only the newest code is ever valid; store its hash, never the code.
            Otp.query.filter_by(fin_kod=user.fin_kod).delete()
            new_otp = Otp(
                fin_kod=user.fin_kod,
                issued_at=issued_at,
                expires_at=issued_at + timedelta(minutes=OTP_TTL_MINUTES),
            )
            new_otp.set_code(otp)
            db.session.add(new_otp)
            db.session.commit()

            html_content = render_template("email/otp_verification.html", name=user.name, otp_code=otp)
            _deliver_otp_async(current_app._get_current_object(), "OTP", email, html_content)
        else:
            logger.info("OTP requested for an unknown or unreachable account")

        return handle_success(None, OTP_SENT_MESSAGE)

    except Exception:
        db.session.rollback()
        logger.exception("Unexpected error while sending an OTP")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500


@auth_bp.route("/auth/validate-otp", methods=['POST'])
@limiter.limit("10 per minute; 50 per hour")
@limiter.limit("5 per 15 minutes", key_func=_body_account_key)
def validate_otp():
    # The code is only 6 digits, so guesses are capped per address AND per
    # account. Both the identifier and the code come from the JSON body — the
    # code no longer travels in the URL, where nginx would log it (B-L4).
    invalid = ({"statusCode": 400, "message": "Invalid or expired OTP."}, 400)
    try:
        data = request.get_json(silent=True) or {}
        identifier = data.get('identifier') or data.get('email') or data.get('fin_kod')
        otp = data.get('otp')
        if identifier is None or otp is None:
            return invalid

        user, account = resolve_profile(str(identifier))
        if not user or not account:
            return invalid
        fin_kod = user.fin_kod

        sent_otp = (
            Otp.query.filter(Otp.fin_kod == fin_kod)
            .order_by(Otp.issued_at.desc())
            .first()
        )
        if not sent_otp:
            return invalid

        # `Otp.expires_at` is DateTime(timezone=True), so Postgres hands it back
        # tz-aware — comparing it with a naive utcnow() raises TypeError.
        now_utc = datetime.now(timezone.utc)
        otp_expiry = sent_otp.expires_at
        if otp_expiry.tzinfo is None:
            otp_expiry = otp_expiry.replace(tzinfo=timezone.utc)

        if now_utc > otp_expiry:
            Otp.query.filter_by(fin_kod=fin_kod).delete()
            db.session.commit()
            return invalid

        # Constant-time comparison against the stored SHA-256 (never plaintext).
        if not sent_otp.matches(str(otp).strip()):
            return invalid

        # Single use: the code dies the moment it is accepted.
        Otp.query.filter_by(fin_kod=fin_kod).delete()
        db.session.commit()

        token = encode_otp_token(user.fin_kod, account.password_hash)
        return handle_success(token, "OTP validated successfully.")

    except Exception:
        db.session.rollback()
        logger.exception("Unexpected error during OTP validation")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500


@auth_bp.route("/auth/reset-password", methods=['POST'])
@limiter.limit("10 per minute; 30 per hour")
def reset_password():
    # Gated by the signed reset token issued after a valid OTP. That token is
    # short-lived and bound to the CURRENT password hash, so it works once: the
    # moment the password changes, the token no longer matches.
    try:
        data = request.get_json(silent=True) or {}
        password = data.get('password')
        token = data.get('token')
        if not password or not token:
            return handle_missing_field(400)

        decoded_data = decode_otp_token(token)
        if not decoded_data:
            return handle_unauthorized(401, "Invalid or expired token.")

        user_auth = Auth.query.filter_by(fin_kod=decoded_data['fin_kod']).first()
        if not user_auth or not secrets.compare_digest(
            decoded_data['pwh'], password_fingerprint(user_auth.password_hash)
        ):
            return handle_unauthorized(401, "Invalid or expired token.")

        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            return {"status": 400, "message": f"Şifrə ən azı {MIN_PASSWORD_LENGTH} simvol olmalıdır."}, 400

        user_auth.set_password(password)
        Otp.query.filter_by(fin_kod=user_auth.fin_kod).delete()
        db.session.commit()

        return handle_success(None, "Password reseted successfully.")

    except Exception as e:
        db.session.rollback()
        logger.exception("Unexpected error during password reset")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500

@auth_bp.route("/auth/<string:fin_kod>/update/role/<int:role>", methods=['POST'])
@limiter.limit("30 per minute")
@token_required([2])
def update_role(fin_kod, role):
    try:
        role = int(role)
        if role not in ASSIGNABLE_ROLES:
            return {"status": 400, "message": "Role must be 0 (lead), 1 (executor) or 2 (admin)."}, 400

        user = Auth.query.filter_by(fin_kod=fin_kod).first()
        if not user:
            return handle_not_found("User not found.")

        # Expert accounts are managed on the experts screen, not here.
        if user.project_role == EXPERT_ROLE:
            return {"status": 400, "message": "Expert accounts cannot be re-roled here."}, 400

        # An admin cannot demote themselves, and the last admin cannot be
        # demoted by anyone — either would lock everybody out of administration.
        if user.project_role == 2 and role != 2:
            if fin_kod == g.user.get('fin_kod'):
                return {"status": 403, "message": "You cannot change your own admin role."}, 403
            if Auth.query.filter(Auth.project_role == 2, Auth.fin_kod != fin_kod).count() == 0:
                return {"status": 403, "message": "The last administrator cannot be demoted."}, 403

        user.project_role = role
        db.session.commit()
        db.session.refresh(user)

        logger.info("Admin %s set role %s on account id %s", g.user.get('fin_kod'), role, user.id)
        return handle_success(user.auth_details(), "User role updated successfully")

    except Exception as e:
        db.session.rollback()
        logger.exception("Unexpected error during role update")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500

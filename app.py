import os
from flask import Flask
from flask_cors import CORS
from flasgger import Swagger
from sqlalchemy import inspect, text
from dotenv import load_dotenv
from config.config import Config
from config.limiter import limiter
from extentions.db import migrate, db
from controllers.AuthController import auth_bp
from controllers.AnnouncementController import announcement_bp
from controllers.RoleChangeController import role_change_bp
from controllers.NotificationController import notification_bp
from controllers.CompetitionController import competition_bp
from controllers.MessageController import message_bp
from controllers.ProjectFileController import project_file_bp
from controllers.UserController import user_bp
from controllers.lockController import lock_bp
from controllers.ExpertController import expert_bp
from controllers.PriotetController import priotet_bp
from controllers.ProjectController import project_offer
from controllers.PublicController import public_bp
from controllers.InstitutionController import institution_bp
from controllers.CollaboratorController import collaborator_bp
from controllers.smetaControllers.rentController import rent_bp
from controllers.smetaControllers.smetaCotroller import smeta_bp
from controllers.smetaControllers.salaryController import salary_bp
from controllers.ProjectActivitiesController import project_activity
from controllers.ReportController import report_bp
from controllers.smetaControllers.subjectController import subject_bp
from controllers.smetaControllers.other_expensesController import other_exp
from controllers.smetaControllers.servicesTableController import services_bp

def collaborator_unique_statements(existing_uniques):
    """DDL that swaps the collaborator uniqueness rule, given what is there now.

    A person may now join SEVERAL projects per competition, so the old
    one-slot-per-person rules — UNIQUE (fin_kod) and its successor
    UNIQUE (fin_kod, competition_id) — give way to "never the same project
    twice". Returns an empty list once the swap has happened, which is what
    makes calling this on every boot harmless.
    """
    superseded = ({'fin_kod'}, {'fin_kod', 'competition_id'})
    statements = [
        f'ALTER TABLE collaborators DROP CONSTRAINT "{c["name"]}"'
        for c in existing_uniques
        if set(c['column_names']) in superseded
    ]

    if not any(set(c['column_names']) == {'fin_kod', 'project_code'} for c in existing_uniques):
        statements.append(
            "ALTER TABLE collaborators ADD CONSTRAINT uq_collaborator_fin_project "
            "UNIQUE (fin_kod, project_code)"
        )
    return statements


def ensure_schema():
    """Idempotently add columns that `db.create_all()` cannot add to existing
    tables. `create_all` only creates missing tables; it never ALTERs an
    existing one, so new columns on the `project` table are added here."""
    inspector = inspect(db.engine)
    if 'project' not in inspector.get_table_names():
        return

    existing_columns = {col['name'] for col in inspector.get_columns('project')}
    statements = []
    if 'winner' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN winner BOOLEAN DEFAULT FALSE")
    if 'winner_at' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN winner_at TIMESTAMP")
    if 'competition_id' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN competition_id INTEGER")
    # Per-project editing unlock for archived (previous competition) projects.
    if 'edit_unlocked' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN edit_unlocked BOOLEAN DEFAULT FALSE")
    if 'edit_unlocked_at' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN edit_unlocked_at TIMESTAMP")
    if 'edit_unlocked_by' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN edit_unlocked_by VARCHAR(100)")

    # Returning a submitted proposal to its lead for corrections.
    if 'revision_note' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN revision_note TEXT")
    if 'returned_at' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN returned_at TIMESTAMP")
    if 'returned_by' not in existing_columns:
        statements.append("ALTER TABLE project ADD COLUMN returned_by VARCHAR(100)")

    # collaborators.competition_id (additive, safe).
    if 'collaborators' in inspector.get_table_names():
        collab_columns = {col['name'] for col in inspector.get_columns('collaborators')}
        if 'competition_id' not in collab_columns:
            statements.append("ALTER TABLE collaborators ADD COLUMN competition_id INTEGER")

        # Let a person join SEVERAL projects per competition. This one IS done
        # here (unlike the earlier competition swap, which shipped as SQL only)
        # because the feature is simply broken until it runs — the database
        # would refuse the second application.
        # migrations_sql/2026_08_multi_project_collaboration.sql does the same
        # for anyone applying it by hand.
        #
        # ALTER TABLE ... DROP/ADD CONSTRAINT is Postgres syntax that SQLite
        # cannot parse, so a dev running on SQLite is left alone — `create_all`
        # builds the current constraint there anyway.
        if db.engine.dialect.name == 'postgresql':
            statements.extend(collaborator_unique_statements(
                inspector.get_unique_constraints('collaborators')
            ))

    # project_activities.months — an activity may span several months, kept as
    # a comma-separated list beside the original single `month`.
    if 'project_activities' in inspector.get_table_names():
        activity_columns = {col['name'] for col in inspector.get_columns('project_activities')}
        if 'months' not in activity_columns:
            statements.append("ALTER TABLE project_activities ADD COLUMN months VARCHAR")

    # Expert e-mail verification, and the forced password change that follows
    # the one-time password an expert is e-mailed on assignment.
    if 'experts' in inspector.get_table_names():
        expert_columns = {col['name'] for col in inspector.get_columns('experts')}
        for column, ddl in (
            ('email_verified', "ALTER TABLE experts ADD COLUMN email_verified BOOLEAN DEFAULT FALSE"),
            ('verification_token', "ALTER TABLE experts ADD COLUMN verification_token VARCHAR(64)"),
            ('verification_sent_at', "ALTER TABLE experts ADD COLUMN verification_sent_at TIMESTAMP"),
            ('email_verified_at', "ALTER TABLE experts ADD COLUMN email_verified_at TIMESTAMP"),
            ('created_at', "ALTER TABLE experts ADD COLUMN created_at TIMESTAMP"),
        ):
            if column not in expert_columns:
                statements.append(ddl)

    if 'auth' in inspector.get_table_names():
        auth_columns = {col['name'] for col in inspector.get_columns('auth')}
        if 'must_change_password' not in auth_columns:
            statements.append(
                "ALTER TABLE auth ADD COLUMN must_change_password BOOLEAN DEFAULT FALSE"
            )
        # Token invalidation on password change / logout (finding B-L3).
        if 'token_version' not in auth_columns:
            statements.append(
                "ALTER TABLE auth ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
            )

    # OTPs are now stored as a SHA-256 hash, and the plaintext column is no
    # longer written (finding B-L4).
    if 'otp' in inspector.get_table_names():
        otp_columns = {col['name']: col for col in inspector.get_columns('otp')}
        if 'otp_hash' not in otp_columns:
            statements.append("ALTER TABLE otp ADD COLUMN otp_hash VARCHAR(64)")
        # Stop requiring the plaintext column so new rows can omit it.
        if 'otp' in otp_columns and not otp_columns['otp'].get('nullable', True):
            if db.engine.dialect.name == 'postgresql':
                statements.append("ALTER TABLE otp ALTER COLUMN otp DROP NOT NULL")

    if 'assessment' in inspector.get_table_names():
        assessment_columns = {col['name'] for col in inspector.get_columns('assessment')}
        for column, ddl in (
            ('created_at', "ALTER TABLE assessment ADD COLUMN created_at TIMESTAMP"),
            ('updated_at', "ALTER TABLE assessment ADD COLUMN updated_at TIMESTAMP"),
            # The per-criterion breakdown behind the total score.
            ('criteria', "ALTER TABLE assessment ADD COLUMN criteria JSONB"),
        ):
            if column not in assessment_columns:
                statements.append(ddl)

    # CV columns on the User table (name is quoted because of the uppercase U).
    if 'User' in inspector.get_table_names():
        user_columns = {col['name'] for col in inspector.get_columns('User')}
        if 'cv_original_filename' not in user_columns:
            statements.append('ALTER TABLE "User" ADD COLUMN cv_original_filename VARCHAR')
        if 'cv_stored_filename' not in user_columns:
            statements.append('ALTER TABLE "User" ADD COLUMN cv_stored_filename VARCHAR')

    if statements:
        with db.engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))


# Endpoints that are reachable WITHOUT a bearer token. Each one is either the
# way a user obtains a token in the first place, or is gated by a different
# secret (an e-mailed OTP, a signed reset token, an e-mailed verification
# token). Everything else in the API must carry a valid token — see
# `default_deny` below, which enforces that centrally.
PUBLIC_ENDPOINTS = frozenset({
    'auth.signin',                   # obtains the token
    'auth.signup',                   # registration (account still needs admin approval)
    'auth.send_otp',                 # forgotten password: e-mails a one-time code
    'auth.validate_otp',             # gated by the e-mailed one-time code
    'auth.reset_password',           # gated by the signed, single-use reset token
    'expert.verify_expert_email',    # gated by the e-mailed verification token
    'institution.get_institutions',  # names only; the sign-up form needs it before login
})

# The public website (Next.js) reads these on ITS server, never in a visitor's
# browser, so it authenticates with a server-to-server key instead of a user
# token. The key is never shipped to browsers.
PUBLIC_SITE_BLUEPRINT = 'public_bp'
PUBLIC_SITE_KEY_HEADER = 'X-Public-Api-Key'


def _requires_auth(view):
    """True when `token_required` wraps this view (through any other
    decorators, e.g. the rate limiter)."""
    seen = 0
    while view is not None and seen < 10:
        if getattr(view, '_requires_auth', False):
            return True
        view = getattr(view, '__wrapped__', None)
        seen += 1
    return False


def _register_security(app, swagger_enabled=False):
    """Default-deny authentication (pentest F4 recommendation: centralised
    auth), response security headers (F7) and safe, generic error handlers
    (F6). Registered once per app in `main_app`."""
    import hmac
    from flask import jsonify, request

    swagger_prefixes = ('/apidocs', '/flasgger_static', '/apispec')

    @app.before_request
    def default_deny():
        # CORS preflight carries no credentials by design; Flask answers it
        # without running the view.
        if request.method == 'OPTIONS':
            return None
        endpoint = request.endpoint
        if endpoint is None:
            return None  # unknown URL: let Flask answer 404
        if endpoint in PUBLIC_ENDPOINTS:
            return None
        if swagger_enabled and endpoint.startswith('flasgger.'):
            return None
        if endpoint.startswith(PUBLIC_SITE_BLUEPRINT + '.'):
            expected = os.getenv('PUBLIC_API_KEY', '')
            supplied = request.headers.get(PUBLIC_SITE_KEY_HEADER, '')
            # Fail closed: with no key configured the public API answers nobody.
            if expected and hmac.compare_digest(supplied.encode(), expected.encode()):
                return None
            return jsonify({"error": "Unauthorized", "message": "API key is missing or invalid."}), 401
        if _requires_auth(app.view_functions.get(endpoint)):
            return None  # `token_required` authenticates and authorises it
        # A route nobody marked as public and nobody protected: refuse it, so a
        # forgotten decorator can never again expose data (the root cause of
        # pentest findings 1-4).
        app.logger.error("Refused unprotected endpoint %s (%s %s)", endpoint, request.method, request.path)
        return jsonify({"error": "Unauthorized", "message": "Authorization token is missing."}), 401

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        # HSTS is only honoured over HTTPS; harmless on plain HTTP. Keep the TLS
        # termination (nginx) in front for it to take effect.
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Do not advertise the exact server/framework build (pentest F8). nginx
        # in front should also set `server_tokens off;`.
        response.headers['Server'] = 'AzTU'
        # Authenticated data must not linger in shared/browser caches.
        if 'Authorization' in request.headers:
            response.headers['Cache-Control'] = 'no-store'
        # JSON gets a policy that forbids everything. Every other response is a
        # file (PDF/DOCX/XLSX exports, CVs, uploads, chat attachments): those are
        # additionally SANDBOXED, so an uploaded SVG/HTML-ish file opened
        # straight from the API origin can never run script there. The UI
        # fetches files as blobs, so this does not affect downloads/previews.
        if not (swagger_enabled and request.path.startswith(swagger_prefixes)):
            if (response.mimetype or '').startswith('application/json'):
                response.headers['Content-Security-Policy'] = (
                    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                )
            else:
                response.headers['Content-Security-Policy'] = (
                    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; sandbox"
                )
        return response

    # Uncaught exceptions and framework 4xx/5xx return clean JSON with NO Python
    # detail — the interactive debugger and stack traces never reach a client.
    @app.errorhandler(Exception)
    def _handle_uncaught(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return jsonify({"error": error.name, "message": error.description}), error.code
        app.logger.exception("Unhandled exception on %s %s", request.method, request.path)
        return jsonify({
            "error": "Internal Server Error",
            "message": "Daxili server xətası baş verdi."
        }), 500

    @app.errorhandler(404)
    def _handle_404(error):
        return jsonify({"error": "Not Found", "message": "Resource not found."}), 404

    @app.errorhandler(429)
    def _handle_429(error):
        return jsonify({
            "error": "Too Many Requests",
            "message": "Çox sayda sorğu göndərildi. Zəhmət olmasa bir azdan yenidən cəhd edin."
        }), 429


def main_app():
    load_dotenv()

    # Forbid ReportLab from resolving remote image hosts in PDF markup — a blind
    # SSRF vector if user text reaches a Paragraph (finding B-M1).
    from utils.pdf_safety import harden_reportlab
    harden_reportlab()

    app = Flask(__name__)

    # Behind nginx every request arrives from 127.0.0.1, so the rate limiter
    # would see ONE client and throttle all users together (and an attacker
    # could exhaust e.g. the password-reset bucket for everyone). ProxyFix
    # restores the real client address from the X-Forwarded-For header that
    # nginx appends. Trust exactly as many proxy hops as sit in front of the
    # app (1 = nginx). The app must NOT be reachable directly, or that header
    # could be forged — bind it to 127.0.0.1.
    from werkzeug.middleware.proxy_fix import ProxyFix
    proxy_hops = int(os.getenv('TRUSTED_PROXY_COUNT', '1'))
    if proxy_hops > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops, x_host=0)

    # The interactive API docs (Flasgger/Swagger UI at /apidocs) confirm the
    # backend's whole technology stack and, as the spec grows, would map every
    # route for an attacker. They are OFF unless ENABLE_SWAGGER is explicitly
    # truthy — so production ships without them (pentest F11).
    swagger_enabled = os.getenv('ENABLE_SWAGGER', 'false').lower() == 'true'
    if swagger_enabled:
        template = {
            "swagger": "2.0",
            "info": {
                "title": "E-Grant API",
                "description": "API documentation for E-Grant project",
                "version": "1.0"
            },
            "schemes": ["http", "https"]
        }
        Swagger(app, template=template)

    app.config.from_object(Config)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = os.getenv('SQLALCHEMY_TRACK_MODIFICATIONS', 'False').lower() == 'true'
    # Never let an unhandled exception render Werkzeug's interactive debugger or
    # a stack trace to a client; our own error handlers answer instead.
    app.config['PROPAGATE_EXCEPTIONS'] = False
    # Hard cap on a request body so oversized uploads are refused (413) before
    # they are read into memory. Per-file limits are still checked per route.
    app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '100')) * 1024 * 1024
    # Rate-limit counters. memory:// is per process; with several gunicorn
    # workers set RATELIMIT_STORAGE_URI=redis://127.0.0.1:6379 so limits are shared.
    app.config['RATELIMIT_STORAGE_URI'] = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')

    # Tokens are signed with SECRET_KEY: without it nobody can sign in, and a
    # short one can be brute-forced offline from any captured token.
    secret = app.config['SECRET_KEY'] or ''
    if not secret:
        raise RuntimeError("SECRET_KEY is not set — refusing to start.")
    if len(secret) < 32:
        app.logger.warning("SECRET_KEY is shorter than 32 characters; rotate it to a long random value.")

    limiter.init_app(app)

    # ---------------------------------------------------------------- CORS ----
    # Reflecting any Origin while also allowing credentials defeats the point of
    # CORS (pentest F5). Restrict to an explicit allow-list. The production
    # values come from CORS_ORIGINS in the environment; the fallback is
    # https-only (finding B-cleanup) — local dev sets CORS_ORIGINS itself.
    default_origins = (
        "https://e-grant.aztu.edu.az,https://admin-e-grant.aztu.edu.az"
    )
    allowed_origins = [
        o.strip() for o in os.getenv('CORS_ORIGINS', default_origins).split(',') if o.strip()
    ]
    CORS(
    	app,
    	origins=allowed_origins,
    	supports_credentials=True,
    	allow_headers=["Content-Type", "Authorization", "Content-Disposition"],
    	methods=["GET", "POST", "PUT", "PATCH", "OPTIONS", "DELETE"]
	)

    _register_security(app, swagger_enabled=swagger_enabled)

    db.init_app(app)
    migrate.init_app(app, db)
    
    with app.app_context():
        db.create_all()
        ensure_schema()

    app.register_blueprint(auth_bp)
    app.register_blueprint(announcement_bp)
    app.register_blueprint(role_change_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(competition_bp)
    app.register_blueprint(message_bp)
    app.register_blueprint(project_file_bp)
    app.register_blueprint(lock_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(rent_bp)
    app.register_blueprint(smeta_bp)
    app.register_blueprint(salary_bp)
    app.register_blueprint(other_exp)
    app.register_blueprint(expert_bp)
    app.register_blueprint(subject_bp)
    app.register_blueprint(priotet_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(project_offer)
    app.register_blueprint(public_bp)
    app.register_blueprint(institution_bp)
    app.register_blueprint(collaborator_bp)
    app.register_blueprint(project_activity)
    app.register_blueprint(report_bp)

    return app

if __name__ == '__main__':
    app = main_app()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
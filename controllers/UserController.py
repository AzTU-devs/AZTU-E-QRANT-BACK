import os
import uuid
import logging
from extentions.db import db
from datetime import datetime
from models.userModel import User
from models.authModel import Auth
from config.limiter import limiter
from werkzeug.utils import secure_filename
from flask import Blueprint, request, current_app, send_file, g
from utils.jwt_required import token_required
from utils.cascade_delete import delete_user_cascade
from exceptions.exception import handle_success
from exceptions.exception import handle_not_found
from exceptions.exception import handle_missing_field
from exceptions.exception import handle_global_exception
from utils.identity import email_taken
from utils.email_validation import normalise_email, has_valid_syntax

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_bp = Blueprint('user', __name__)


def _is_real_image(data):
    """True when the bytes decode as an image. The extension alone is chosen by
    the uploader, so a renamed file of any other type would otherwise be
    stored and later served as a profile photo."""
    try:
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(data)) as img:
            img.verify()
        return True
    except Exception:
        return False


def _email_error(value, fin_kod):
    """None when `value` may be stored as this person's address, else why not.
    Addresses are sign-in identifiers, so they must be well-formed and unique
    across all accounts (case-insensitively)."""
    email = normalise_email(value)
    if not has_valid_syntax(email):
        return 'E-poçt ünvanı düzgün formatda deyil.'
    if email_taken(email, exclude_fin=fin_kod):
        return 'Bu e-poçt ünvanı artıq başqa hesabda istifadə olunur.'
    return None

@user_bp.route('/api/profile/<string:fin_kod>', methods=['GET'])
@limiter.limit("60 per minute")
@token_required([0, 1, 2, 3])
def get_profile(fin_kod):
   """A single profile.

   Requires a valid token — the full database used to be reachable here with no
   authentication at all, and because the identifier IS the FIN code the whole
   user base could be enumerated (pentest F2, IDOR). Full personal data is now
   returned ONLY to the profile's own owner or to an admin; everyone else (a
   lead viewing a teammate, a teammate viewing the lead) receives a PII-free
   professional card via `user_public_details`.
   """
   try:
       user = User.query.filter_by(fin_kod=fin_kod).first()
       if not user:
           return handle_not_found(404)

       caller = g.user.get('fin_kod')
       is_admin = g.user.get('role') == 2
       if is_admin or caller == fin_kod:
           return handle_success(user.user_details(), "User found successfully.")
       return handle_success(user.user_public_details(), "User found successfully.")
   except Exception as e:
       return handle_global_exception(str(e))

@user_bp.route('/api/profile/<string:fin_kod>/edit', methods=['PUT'])
@limiter.limit("60 per minute")
@token_required([0, 1, 2])
def edit_user_details(fin_kod):
    try:
        # You may only edit your OWN profile; admins may edit anyone. Without
        # this any authenticated user could overwrite another person's profile
        # simply by naming their FIN in the URL (pentest — Broken Object Level
        # Authorization).
        if g.user.get('role') != 2 and g.user.get('fin_kod') != fin_kod:
            return {'error': 'You can only edit your own profile.', 'status': 403}, 403

        data = request.get_json(silent=True) or {}
        user = User.query.filter_by(fin_kod=fin_kod).first()
        if not user:
            return handle_not_found(404)

        # Fields editable (same as complete_profile, minus personal_email, personal_mobile_number, institution_code, fin_kod)
        editable_fields = [
            "name", "surname", "father_name", "born_place", "living_location",
            "home_phone", "citizenship", "personal_id_number", "sex",
            "work_place", "department", "duty", "main_education",
            "additonal_education", "scientific_degree", "scientific_date",
            "scientific_name", "scientific_name_date", "work_location",
            "work_phone", "work_email", "born_date"
        ]

        if data.get('work_email'):
            problem = _email_error(data['work_email'], fin_kod)
            if problem:
                return {'error': problem, 'status': 400}, 400
            data['work_email'] = normalise_email(data['work_email'])

        for field in editable_fields:
            if field in data:
                if field in ["scientific_date", "scientific_name_date", "born_date"] and data[field]:
                    try:
                        setattr(user, field, datetime.strptime(data[field], "%Y-%m-%d"))
                    except ValueError:
                        continue
                else:
                    setattr(user, field, data[field])

        db.session.commit()
        return handle_success(user.user_details(), "User details updated successfully.")
    except Exception as e:
        return handle_global_exception(str(e))
   
@user_bp.route('/api/profile/<string:fin_kod>/image', methods=['POST'])
@limiter.limit("60 per minute")
@token_required([0, 1, 2])
def update_profile_image(fin_kod):
    """Replace a profile photo.

    The photo used to be settable only once, while completing the profile.
    People may now change it afterwards — their own, or anybody's if an admin.
    """
    try:
        caller = g.user.get('fin_kod')
        is_admin = g.user.get('role') == 2
        if fin_kod != caller and not is_admin:
            return {'error': 'You can only change your own photo.', 'status': 403}, 403

        user = User.query.filter_by(fin_kod=fin_kod).first()
        if not user:
            return {'error': 'User not found.', 'status': 404}, 404

        image_file = request.files.get('image')
        if not image_file or not image_file.filename:
            return {'error': 'image file is required.', 'status': 400}, 400

        extension = image_file.filename.rsplit('.', 1)[-1].lower() if '.' in image_file.filename else ''
        allowed = current_app.config['ALLOWED_PROFILE_IMAGE_EXTENSIONS']
        if extension not in allowed:
            return {
                'error': f"Only these image types are allowed: {', '.join(sorted(allowed))}.",
                'status': 400
            }, 400

        image_bytes = image_file.read()
        max_size = current_app.config['MAX_PROFILE_IMAGE_SIZE']
        if len(image_bytes) > max_size:
            return {
                'error': f'The image must be smaller than {max_size // (1024 * 1024)} MB.',
                'status': 400
            }, 400
        if not image_bytes:
            return {'error': 'The uploaded image is empty.', 'status': 400}, 400
        if not _is_real_image(image_bytes):
            return {'error': 'The uploaded file is not a valid image.', 'status': 400}, 400

        user.image = image_bytes
        user.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info("Profile image updated for %s by %s", fin_kod, caller)
        return handle_success(user.get_user_image(), 'Profile image updated successfully.')

    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to update the profile image for %s", fin_kod)
        return handle_global_exception(str(e))


@user_bp.route('/api/approve/profile', methods=['POST'])
@limiter.limit("300 per minute")
@token_required([0, 1, 2])
def complete_profile():
    try:
        data = request.form

        # The profile being completed is named by `fin_kod` in the body. Only
        # its owner or an admin may write it, otherwise an authenticated user
        # could overwrite anyone's profile and photo (BOLA).
        target_fin = data.get('fin_kod')
        if g.user.get('role') != 2 and g.user.get('fin_kod') != target_fin:
            return {'error': 'You can only complete your own profile.', 'status': 403}, 403

        required_fields = [
            'born_place',
            'living_location', 'home_phone', 'personal_mobile_number', 'personal_email',
            'citizenship', 'personal_id_number', 'sex', 'work_place', 'department',
            'duty', 'main_education', 'additonal_education', 'scientific_degree',
            'scientific_date', 'scientific_name', 'scientific_name_date',
            'work_location', 'work_phone', 'work_email', 'born_date'
        ]

        for field in required_fields:
            if not data.get(field):
                logger.warning(f"Missing required field: {field}")
                return handle_missing_field(404)

        image_file = request.files.get('image')

        if image_file:
            image_bytes = image_file.read()
        else:
            logger.warning("Missing image file in request")
            return handle_missing_field(404)

        extension = image_file.filename.rsplit('.', 1)[-1].lower() if '.' in (image_file.filename or '') else ''
        if extension not in current_app.config['ALLOWED_PROFILE_IMAGE_EXTENSIONS']:
            return {'error': 'Only jpg, jpeg, png and webp images are allowed.', 'status': 400}, 400
        if len(image_bytes) > current_app.config['MAX_PROFILE_IMAGE_SIZE'] or not _is_real_image(image_bytes):
            return {'error': 'The uploaded file is not a valid image (max 5 MB).', 'status': 400}, 400

        for email_field in ('personal_email', 'work_email'):
            problem = _email_error(data.get(email_field), target_fin)
            if problem:
                return {'error': problem, 'status': 400}, 400

        fin_kod = target_fin
        user = User.query.filter_by(fin_kod=fin_kod).first()

        if not user:
            return handle_not_found(404)
        
        user.image = image_bytes
        user.born_place = data.get('born_place')
        user.living_location = data.get('living_location')
        user.home_phone = data.get('home_phone')
        user.personal_mobile_number = data.get('personal_mobile_number')
        user.personal_email = normalise_email(data.get('personal_email'))
        user.citizenship = data.get('citizenship')
        user.personal_id_number = data.get('personal_id_number')
        user.sex = data.get('sex')
        user.work_place = data.get('work_place')
        user.department = data.get('department')
        user.duty = data.get('duty')
        user.main_education = data.get('main_education')
        user.additonal_education = data.get('additonal_education')
        user.scientific_degree = data.get('scientific_degree')
        user.scientific_date = datetime.strptime(data.get('scientific_date'), '%Y-%m-%d') if data.get('scientific_date') else None
        user.scientific_name = data.get('scientific_name')
        user.scientific_name_date = datetime.strptime(data.get('scientific_name_date'), '%Y-%m-%d') if data.get('scientific_name_date') else None
        user.work_location = data.get('work_location')
        user.work_phone = data.get('work_phone')
        user.work_email = normalise_email(data.get('work_email'))
        user.profile_completed = 1
        user.born_date = data.get('born_date')

        db.session.commit()

        return {"message": "Profile completed successfully."}, 200
    except Exception as e:
        logger.exception("An unexpected error occurred while completing the profile")
        return {"error": "Internal server error", "message": "Daxili server xetasi bas verdi."}, 500

@user_bp.route("/api/users/all", methods=['GET'])
@limiter.limit("60 per minute")
@token_required([2])
def get_all_approved_user():
    """Admin-only user directory, for role management and the chat search.

    This endpoint used to be reachable with NO authentication and returned the
    FULL profile of every user — FIN code, ID-card number, phones, personal
    e-mail, date/place of birth, the Base64 photo and the internal numeric id —
    i.e. the whole personal-data set of every account, in one ~22MB response
    (pentest F1 + F9, CRITICAL). It now requires an admin token and returns only
    the lean, id-free directory fields the admin screens actually use.
    """
    try:
        name = request.args.get("name")
        surname = request.args.get("surname")
        fin_kod = request.args.get("finKod")

        query = Auth.query.filter(Auth.approved == True)
        if fin_kod:
            query = query.filter(Auth.fin_kod.ilike(f"%{fin_kod}%"))

        auth_users = query.all()

        if not auth_users:
            return handle_not_found("User not found.")

        users = []
        for auth_user in auth_users:
            user_query = User.query.filter_by(fin_kod=auth_user.fin_kod)
            if name:
                user_query = user_query.filter(User.name.ilike(f"%{name}%"))
            if surname:
                user_query = user_query.filter(User.surname.ilike(f"%{surname}%"))
            user = user_query.first()
            if user:
                users.append(user.user_list_summary(project_role=auth_user.project_role))

        return handle_success(users, "Users fetched successfully")
    except Exception as e:
        return handle_global_exception(str(e))


@user_bp.route('/api/user/<string:fin_kod>', methods=['DELETE'])
@limiter.limit("60 per minute")
@token_required([2])
def delete_user(fin_kod):
    """Admin-only: erase a person and everything of theirs.

    That means the login, the profile, every project they lead (with its team,
    plan, budget, files and reports) and their seat on anybody else's team.
    None of it is recoverable, which is why it is behind an admin token and an
    explicit confirmation in the UI.
    """
    try:
        account = Auth.query.filter_by(fin_kod=fin_kod).first()
        profile = User.query.filter_by(fin_kod=fin_kod).first()

        if not account and not profile:
            return {'error': 'User not found.', 'status': 404}, 404

        # An admin removing the last admin would lock everyone out of the
        # administration screens, so refuse rather than let it happen.
        if account and account.project_role == 2:
            if fin_kod == g.user.get('fin_kod'):
                return {'error': 'You cannot delete your own account.', 'status': 403}, 403
            remaining_admins = Auth.query.filter(
                Auth.project_role == 2, Auth.fin_kod != fin_kod
            ).count()
            if remaining_admins == 0:
                return {'error': 'The last administrator cannot be deleted.', 'status': 403}, 403

        removed = delete_user_cascade(fin_kod)
        db.session.commit()

        logger.info("Admin %s deleted user %s: %s", g.user.get('fin_kod'), fin_kod, removed)
        return handle_success(
            {'fin_kod': fin_kod, 'removed': removed},
            'User and all related records deleted successfully.'
        )

    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to delete user %s", fin_kod)
        return handle_global_exception(str(e))


# --------------------------------------------------------------- CV upload ----

def _cv_folder():
    folder = current_app.config['CV_FILES_FOLDER']
    os.makedirs(folder, exist_ok=True)
    return folder


def _cv_allowed(filename):
    if '.' not in filename:
        return False
    return filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_CV_EXTENSIONS']


@user_bp.route('/api/profile/<string:fin_kod>/cv', methods=['POST'])
@limiter.limit("120 per minute")
@token_required([0, 1, 2])
def upload_cv(fin_kod):
    """Upload/replace the user's CV (part of the personal data)."""
    try:
        # Users may only upload their own CV; admins may upload for anyone.
        if g.user.get('role') != 2 and g.user.get('fin_kod') != fin_kod:
            return {"status": 403, "message": "Bu əməliyyata icazəniz yoxdur."}, 403

        user = User.query.filter_by(fin_kod=fin_kod).first()
        if not user:
            return handle_not_found(404)

        file = request.files.get('cv') or (request.files.getlist('files') or [None])[0]
        if not file or not file.filename:
            return {"status": 400, "message": "Fayl seçilməyib."}, 400
        if not _cv_allowed(file.filename):
            allowed = ', '.join(sorted(current_app.config['ALLOWED_CV_EXTENSIONS']))
            return {"status": 400, "message": f"Yalnız {allowed} formatları qəbul edilir."}, 400

        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > current_app.config['MAX_CV_FILE_SIZE']:
            mb = current_app.config['MAX_CV_FILE_SIZE'] // (1024 * 1024)
            return {"status": 400, "message": f"Fayl çox böyükdür (maks. {mb} MB)."}, 400

        folder = _cv_folder()
        original_name = secure_filename(file.filename) or 'cv'
        ext = original_name.rsplit('.', 1)[1].lower()
        stored_name = f"{uuid.uuid4().hex}.{ext}"

        # Remove the previous CV file if present.
        if user.cv_stored_filename:
            old_path = os.path.join(folder, user.cv_stored_filename)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    pass

        file.save(os.path.join(folder, stored_name))
        user.cv_original_filename = original_name
        user.cv_stored_filename = stored_name
        db.session.commit()

        return handle_success({"cv_original_filename": original_name, "has_cv": True}, "CV yükləndi.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@user_bp.route('/api/profile/<string:fin_kod>/cv', methods=['GET'])
@limiter.limit("300 per minute")
@token_required([0, 1, 2])
def download_cv(fin_kod):
    try:
        # A CV is personal data: only its owner or an admin may download it,
        # mirroring the upload check above (BOLA hardening).
        if g.user.get('role') != 2 and g.user.get('fin_kod') != fin_kod:
            return {"status": 403, "message": "Bu əməliyyata icazəniz yoxdur."}, 403

        user = User.query.filter_by(fin_kod=fin_kod).first()
        if not user or not user.cv_stored_filename:
            return handle_not_found(404)
        path = os.path.join(current_app.config['CV_FILES_FOLDER'], user.cv_stored_filename)
        if not os.path.exists(path):
            return handle_not_found(404)
        return send_file(path, as_attachment=True, download_name=user.cv_original_filename or 'cv')
    except Exception as e:
        return handle_global_exception(str(e))
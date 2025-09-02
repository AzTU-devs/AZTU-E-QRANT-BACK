import random
import logging   
from models.otpModel import Otp
from models.authModel import Auth
from config.limiter import limiter
from flask_cors import cross_origin
from models.userModel import db, User
from utils.email_util import send_email
from models.projectModel import  Project
from datetime import datetime, timedelta
from exceptions.exception import handle_creation
from exceptions.exception import handle_conflict
from exceptions.exception import handle_not_found
from models.collaboratorModel import  Collaborator
from exceptions.exception import handle_unauthorized
from flask import Blueprint, request, render_template
from exceptions.exception import handle_missing_field
from exceptions.exception import handle_signin_success, handle_success
from utils.jwt_util import encode_auth_token, encode_otp_token, decode_otp_token

auth_bp = Blueprint('auth', __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@auth_bp.route('/auth/signup', methods=['POST'])
@limiter.limit("50 per second")
def signup():
    try:
        data = request.get_json()
        logger.info("Signup request data: %s", data)

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

        logger.info("Checking if user already exists: fin_kod=%s", fin_kod)
        if Auth.query.filter_by(fin_kod=fin_kod).first() or User.query.filter_by(fin_kod=fin_kod).first():
            logger.warning("User already exists with fin_kod: %s", fin_kod)
            return handle_conflict(409)
        
        
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
        return handle_creation("User registered successfully.")

    except Exception as e:
        logger.exception("An unexpected error occurred during signup")
        return {"error": "Internal server error", "message": str(e)}, 500

@auth_bp.route('/auth/signin', methods=['POST'])
@limiter.limit("50 per second")
def signin():
    try:
        data = request.get_json()
        fin_kod = data.get('fin_kod')
        password = data.get('password')
        user_type = data.get('user_type')

        if not all([
            fin_kod,
            password,
            user_type is not None,
        ]):
            logger.warning("Missing required signin fields")
            return handle_missing_field(404)

        logger.info("Attempting signin for FIN: %s", fin_kod)

        auth_data = Auth.query.filter_by(fin_kod=fin_kod).first()

        if auth_data is None:
            logger.warning("No auth record found for FIN: %s", fin_kod)
            return handle_unauthorized(401, "Invalid FIN code or user not found.")

        if not auth_data.check_password(password) or not auth_data.approved or auth_data.blocked:
            logger.warning("Incorrect password for FIN: %s", fin_kod)
            return handle_unauthorized(401, "Incorrect password.")

        if str(auth_data.user_type) != str(user_type):
            logger.warning("User type mismatch for FIN: %s. Expected %s, got %s", fin_kod, auth_data.user_type, user_type)
            return handle_unauthorized(401, "User type does not match.")
        
        is_collaborator = False

        project_role = auth_data.project_role
        project_code = None

        if project_role == 0:
            project_owner = Project.query.filter_by(fin_kod=fin_kod).first()
            project_code = project_owner.project_code if project_owner else None

        elif project_role == 1:
            collaborator = Collaborator.query.filter_by(fin_kod=fin_kod).first()
            if collaborator:
                project_code = collaborator.project_code
                is_collaborator = True

        user_data = User.query.filter_by(fin_kod=fin_kod).first()
        if user_data is None:
            logger.warning("No user data found for FIN: %s", fin_kod)
            return handle_unauthorized(401, "User data not found.")
        
        profile_completed = user_data.profile_completed

        signin_data = {
            "auth": auth_data.auth_details(),
            "project_code": project_code,
            "profile_completed": profile_completed,
            "is_collaborator": is_collaborator
        }

        token = encode_auth_token(auth_data.id, fin_kod, profile_completed, role=project_role)
        logger.info("User signed in successfully: %s", fin_kod)
        return handle_signin_success(signin_data, "Signed in successfully.", token)

    except Exception as e:
        logger.exception("Unexpected error during signin")
        return {"error": "Internal server error", "message": str(e)}, 500
    

@auth_bp.route("/auth/app-wait-users", methods=['GET'])
@limiter.limit("50 per second")
def get_app_wait_users():
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
        return {"error": "Internal server error", "message": str(e)}, 500
    

@auth_bp.route("/auth/app-user/<string:fin_kod>", methods=['POST'])
@limiter.limit("50 per second")
def app_user(fin_kod):
    try:
        user = Auth.query.filter_by(fin_kod=fin_kod).first()

        if not user:
            return handle_not_found(404)
        
        user.approved=True

        db.session.commit()

        user_email = User.query.filter_by(fin_kod=fin_kod).first().personal_email

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
        return {"error": "Internal server error", "message": str(e)}, 500
    
@auth_bp.route("/auth/reject-user/<string:fin_kod>", methods=['DELETE'])
@limiter.limit("50 per second")
def reject_user(fin_kod):
    try:
        auth_user = Auth.query.filter_by(fin_kod=fin_kod).first()

        user = User.query.filter_by(fin_kod=fin_kod).first()

        user_email = user.personal_email
        project_role=auth_user.project_role

        if not auth_user:
            return handle_not_found(404)
        
        db.session.delete(auth_user)
        db.session.delete(user)
        db.session.commit()

        subject = "Uğursuz qeydiyyat"
        recipient = user_email

        if project_role == 1:
            html_content = render_template("email/coll_reg_reject_template.html", project_role=project_role)
            send_email(subject, recipient, html_content)
        elif project_role == 0:
            html_content = render_template("email/owner_reg_reject_template.html", project_role=project_role)
            send_email(subject, recipient, html_content)

        return {"statusCode": 200, "message": "User rejected successfully."}, 200
    
    except Exception as e:
        logger.exception("Unexpected error during signin")
        return {"error": "Internal server error", "message": str(e)}, 500


def generateOtp(length: int = 6) -> str:
    otp = ''.join(str(random.randint(0, 9)) for _ in range(length))
    return otp

import pytz

@auth_bp.route("/auth/send-otp/<string:fin_kod>", methods=['POST'])
@limiter.limit("50 per second")
def send_otp(
    fin_kod: str
):
    try:
        user = User.query.filter(
            User.fin_kod == fin_kod
        ).first()

        if not user:
            return handle_not_found("User not found.")

        email = user.work_email

        subject = "OTP"
        recipient = email

        otp = generateOtp()

        baku_tz = pytz.timezone("Asia/Baku")
        issued_at = datetime.now(baku_tz)

        new_otp = Otp(
            fin_kod = user.fin_kod,
            issued_at=issued_at,
            otp=otp,
            expires_at=issued_at + timedelta(minutes=5)
        )

        db.session.add(new_otp)
        db.session.commit()
        db.session.refresh(new_otp)

        html_content = render_template("email/otp_verification.html", name=user.name, otp_code=otp)
        send_email(subject, recipient, html_content)

        return handle_success(fin_kod, "OTP sent successfully")
    
    except Exception as e:
        logger.exception("Unexpected error during signin")
        return {"error": "Internal server error", "message": str(e)}, 500
    
import pytz
from datetime import datetime

@auth_bp.route("/auth/validate-otp/<string:fin_kod>/<int:otp>", methods=['POST'])
def validate_otp(fin_kod: str, otp: int):
    try:
        user = User.query.filter_by(fin_kod=fin_kod).first()
        if not user:
            return handle_not_found("User not found.")

        sent_otp = (
            Otp.query.filter(Otp.fin_kod == fin_kod)
            .order_by(Otp.issued_at.desc())
            .first()
        )

        if not sent_otp:
            return handle_not_found("OTP not found.")

        now_utc = datetime.utcnow()
        otp_expiry = sent_otp.expires_at

        if now_utc > otp_expiry:
            return {"statusCode": 400, "message": "OTP has expired."}, 400

        if otp != int(sent_otp.otp):
            return {"statusCode": 400, "message": "Invalid OTP."}, 400

        token = encode_otp_token(user.fin_kod)
        
        Otp.query.filter_by(fin_kod=fin_kod).delete()
        db.session.commit()
        
        return handle_success(token, "OTP validated successfully.")

    except Exception as e:
        logger.exception("Unexpected error during OTP validation")
        return {"error": "Internal server error", "message": str(e)}, 500

@auth_bp.route("/auth/reset-password", methods=['POST'])
def reset_password():
    try:
        data = request.get_json()
        if not data or 'password' not in data or 'token' not in data:
            return handle_missing_field(400)

        password = data['password']
        token = data['token']

        decoded_data = decode_otp_token(token)
        if not decoded_data or 'fin_kod' not in decoded_data:
            return handle_unauthorized(401, "Invalid or expired token.")
        
        if not token:
            return {"status": 403, "message": "token is missing"}

        fin_kod = decoded_data['fin_kod']

        user_auth = Auth.query.filter_by(fin_kod=fin_kod).first()
        if not user_auth:
            return {"statusCode": 404, "message": "User not found."}, 404

        user_auth.set_password(password)
        db.session.commit()

        return handle_success(None, "Password reseted successfully.")

    except Exception as e:
        logger.exception("Unexpected error during password reset")
        return {"error": "Internal server error", "message": str(e)}, 500
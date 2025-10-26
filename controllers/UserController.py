import logging
from extentions.db import db
from datetime import datetime
from models.userModel import User
from models.authModel import Auth
from config.limiter import limiter
from flask import Blueprint, request
from utils.jwt_required import token_required
from exceptions.exception import handle_success
from exceptions.exception import handle_not_found
from exceptions.exception import handle_missing_field
from exceptions.exception import handle_global_exception

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_bp = Blueprint('user', __name__)

@user_bp.route('/api/profile/<string:fin_kod>', methods=['GET'])
@limiter.limit("10 per second")
# @token_required([0, 1, 2])
def get_profile(fin_kod):
   try:
       user = User.query.filter_by(fin_kod=fin_kod).first()
       if not user:
           return handle_not_found(404)
       return handle_success(user.user_details(), "User found successfully.")  
   except Exception as e:
       return handle_global_exception(str(e))

@user_bp.route('/api/profile/<string:fin_kod>/edit', methods=['PUT'])
@limiter.limit("10 per second")
@token_required([0, 1, 2])
def edit_user_details(fin_kod):
    try:
        data = request.get_json()
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
   
@user_bp.route('/api/profile/image/<string:fin_kod>', methods=['GET'])
@limiter.limit("10 per second")
@token_required([0, 1, 2])
def get_profile_image(fin_kod):
    try:
        user = User.query.filter_by(fin_kod=fin_kod).first()
        if not user:
            return handle_not_found(404)
        return handle_success(user.get_profile_image(), "User image found successfully.")
    except Exception as e:
        return handle_global_exception(str(e))
    
@user_bp.route('/api/approve/profile', methods=['POST'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def complete_profile():
    try:
        data = request.form
        print("Received form data:", data)
        print("Received files:", request.files)
        
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

        print("Checking for image_file...")
        image_file = request.files.get('image')

        if image_file:
            image_bytes = image_file.read()
        else:
            logger.warning("Missing image file in request")
            print("missing_field")
            return handle_missing_field(404)

        fin_kod = data['fin_kod']
        logger.info(f"Looking up user by FIN: {fin_kod}")
        user = User.query.filter_by(fin_kod=fin_kod).first()

        if not user:
            logger.warning(f"No user found with FIN: {fin_kod}")
            print("No user found with FIN:", fin_kod)
            return handle_not_found(404)
        
        user.image = image_bytes
        user.born_place = data.get('born_place')
        user.living_location = data.get('living_location')
        user.home_phone = data.get('home_phone')
        user.personal_mobile_number = data.get('personal_mobile_number')
        user.personal_email = data.get('personal_email')
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
        user.work_email = data.get('work_email')
        user.profile_completed = 1
        user.born_date = data.get('born_date')

        db.session.commit()

        return {"message": "Profile completed successfully."}, 200
    except Exception as e:
        logger.exception("An unexpected error occurred while completing the profile")
        return {"error": "Internal server error", "message": str(e)}, 500

@user_bp.route("/api/users/all", methods=['GET'])
@limiter.limit("100 per second")
def get_all_approved_user():
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
                user_details = user.user_details()
                user_details["project_role"] = auth_user.project_role
                users.append(user_details)

        return handle_success(users, "Users fetched successfully")
    except Exception as e:
        return handle_global_exception(str(e))
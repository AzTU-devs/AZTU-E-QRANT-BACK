from extentions.db import db
from config.limiter import limiter
from utils.email_util import send_email
from models.expertModel import Expert
from models.projectModel import Project
from utils.jwt_required import token_required
from flask import Blueprint, request, render_template
from exceptions.exception import handle_missing_field, handle_specific_not_found, handle_success, handle_global_exception, handle_creation

expert_bp = Blueprint('expert', __name__)


@expert_bp.route("/api/create-expert", methods=['POST'])
@limiter.limit("10 per second")
@token_required([2])
def create_expert():
    try:
        data = request.get_json()

        required_fields = [
            'email', 'name', 'surname',
            'father_name', 'personal_id_serial_number'
        ]

        for field in required_fields:
            if field not in data:
                return handle_missing_field(field)

        new_expert = Expert(
            email=data['email'],
            name=data['name'],
            surname=data['surname'],
            father_name=data['father_name'],
            personal_id_serial_number=data['personal_id_serial_number'],
            work_place=data.get('work_place'),
            duty=data.get('duty'),
            scientific_degree=data.get('scientific_degree'),
            phone_number=data.get('phone_number')
        )

        db.session.add(new_expert)
        db.session.commit()

        return handle_creation("Expert")

    except Exception as e:
        return handle_global_exception(e)
    
@expert_bp.route("/api/set-expert", methods=['POST'])
@limiter.limit("10 per second")
@token_required([2])
def set_expert():
    try:
        print("[DEBUG] Received request to set expert.")
        data = request.get_json()
        print(f"[DEBUG] Request data: {data}")

        required_fields = [
            'email', 'project_code'
        ]

        for field in required_fields:
            if field not in data:
                return handle_missing_field(field)
            
        project = Project.query.filter_by(project_code=str(data['project_code'])).first()
        print(f"[DEBUG] Project found: {project}")

        if project.submitted == False:
            return {
                "status": 409,
                "message": "Project not submitted."
            }, 409

        project.expert = data['email']

        db.session.commit()

        subject = "Ekspert Təyinatı"
        recipient = data['email']
        html_content = render_template("/email/set_expert_template.html")
        send_email(subject, recipient, html_content)

        print("[DEBUG] Expert set successfully.")
        return handle_success(project, "Expert setted successfully.")
    
    except Exception as e:
        print(f"[ERROR] set_expert failed: {e}")
        return handle_global_exception(e)
    
@expert_bp.route("/api/experts", methods=['GET'])
@limiter.limit("10 per second")
@token_required([2])
def get_experts():
    try:
        print("[DEBUG] Fetching all experts from database...")
        experts = Expert.query.all()

        if not experts:
            return handle_specific_not_found("Expert not found.")

        experts_data = []
        for expert in experts:
            experts_data.append({
                "id": expert.id,
                "email": expert.email,
                "name": expert.name,
                "surname": expert.surname,
                "father_name": expert.father_name,
                "personal_id_serial_number": expert.personal_id_serial_number,
                "work_place": expert.work_place,
                "duty": expert.duty,
                "scientific_degree": expert.scientific_degree,
                "phone_number": expert.phone_number
            })

        return handle_success(experts_data, "Experts fetched successfully.")
    
    except Exception as e:
        print(f"[ERROR] get_experts failed: {e}")
        return handle_global_exception(e)
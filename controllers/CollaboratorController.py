import logging
from extentions.db import db
from models.userModel import User
from models.authModel import Auth
from config.limiter import limiter
from flask_cors import cross_origin
from utils.email_util import send_email
from models.projectModel import Project
from utils.decarator import role_required
from utils.jwt_required import token_required
from models.collaboratorModel import Collaborator
from exceptions.exception import handle_not_found
from flask import Blueprint, request, render_template
from exceptions.exception import handle_global_exception
from exceptions.exception import handle_specific_not_found
from exceptions.exception import handle_missing_field, handle_creation, handle_success, handle_conflict


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

collaborator_bp = Blueprint('collaborator_bp', __name__)

@collaborator_bp.route("/api/collaborators", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 2])
def get_collaborators():
    try:
        logger.debug("Fetching all collaborators")
        collaborator_list = []
        collaborators = Collaborator.query.filter(approved=True).all()
        if not collaborators:
            return handle_not_found(404)
        for collaborator in collaborators:
            collaborator_list.append(collaborator)
        logger.debug(f"Collaborator list: {collaborator_list}")
    except Exception as e:
        return handle_global_exception(str(e))

@collaborator_bp.route("/api/collaborators/<int:project_code>")
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def get_collaborators_by_fin_kod(project_code):
    try:
        logger.debug(f"Fetching collaborators for project code: {project_code}")
        collaborator_list = []
        collaborators = Collaborator.query.filter_by(project_code=project_code, approved=True).all()
        logger.debug(f"Number of collaborators fetched: {len(collaborators)}")

        if not collaborators:
            logger.debug("No collaborators found for the given project code.")
            return handle_specific_not_found('No collaborator found.')

        for collaborator in collaborators:
            logger.debug(f"Processing collaborator with fin_kod: {collaborator.fin_kod}")
            user = User.query.filter_by(fin_kod=collaborator.fin_kod).first()
            if not user:
                logger.warning(f"No user found with fin_kod: {collaborator.fin_kod}")
                continue

            auth_record = Auth.query.filter_by(fin_kod=collaborator.fin_kod).first()
            if not auth_record:
                logger.warning(f"No auth record found for fin_kod: {collaborator.fin_kod}")
                continue

            user_role = auth_record.project_role
            logger.debug(f"Adding collaborator: fin_kod={collaborator.fin_kod}, name={user.name}, surname={user.surname}, role={user_role}")

            collaborator_list.append({
                'fin_kod': collaborator.fin_kod,
                'project_code': collaborator.project_code,
                'name': user.name,
                'surname': user.surname,
                'father_name': user.father_name,
                'image': user.get_user_image(),
                'project_role': user_role
            })

        logger.debug(f"Returning {len(collaborator_list)} collaborators in response")
        return {'data': collaborator_list, 'status': 200}, 200
    
    except Exception as e:
        logger.error(f"Exception occurred in get_collaborators_by_fin_kod: {str(e)}", exc_info=True)
        return handle_global_exception(str(e))
   
@collaborator_bp.route("/api/app-wait-collaborators/<int:project_code>", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 2])
def get_app_wait_collaborators_by_fin_kod(project_code):
    try:
        logger.debug(f"Fetching collaborators for project code: {project_code}")
        collaborator_list = []

        collaborators = Collaborator.query.filter_by(project_code=project_code, approved=False).all()
        logger.debug(f"Number of collaborators fetched: {len(collaborators)}")

        if not collaborators:
            logger.debug("No collaborators found for the given project code.")
            return handle_specific_not_found('No collaborator found.')

        for collaborator in collaborators:
            logger.debug(f"Processing collaborator with fin_kod: {collaborator.fin_kod}")
            user = User.query.filter_by(fin_kod=collaborator.fin_kod).first()
            if not user:
                logger.warning(f"No user found with fin_kod: {collaborator.fin_kod}")
                continue

            auth_record = Auth.query.filter_by(fin_kod=collaborator.fin_kod).first()
            if not auth_record:
                logger.warning(f"No auth record found for fin_kod: {collaborator.fin_kod}")
                continue

            user_role = auth_record.project_role
            logger.debug(f"Adding collaborator: fin_kod={collaborator.fin_kod}, name={user.name}, surname={user.surname}, role={user_role}")

            collaborator_list.append({
                'fin_kod': collaborator.fin_kod,
                'project_code': collaborator.project_code,
                'name': user.name,
                'surname': user.surname,
                'father_name': user.father_name,
                'image': user.get_user_image(),
                'project_role': user_role
            })

        logger.debug(f"Returning {len(collaborator_list)} collaborators in response")
        return {'data': collaborator_list, 'status': 200}, 200

    except Exception as e:
        logger.error(f"Exception occurred: {str(e)}", exc_info=True)
        return handle_global_exception(str(e))

@collaborator_bp.route("/api/project/owner/<int:project_code>", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def get_project_owner(project_code):
    try:
        logger.debug(f"Fetching project owner for project code: {project_code}")

        owner_fin_kod = Project.query.filter_by(project_code=project_code).first().fin_kod
        logger.debug(f"Project owner fin_kod: {owner_fin_kod}")

        user = User.query.filter_by(fin_kod=owner_fin_kod).first()
        logger.debug(f"Owner found: name={user.name}, surname={user.surname}")

        if not user:
            return handle_specific_not_found("Owner not found.")
        
        owner_details = {
            'name': user.name,
            'surname': user.surname,
            'father_name': user.father_name,
        }

        return handle_success(owner_details, 'Owner fetched successfully.')

    except Exception as e:
        return handle_global_exception(str(e))

@collaborator_bp.route('/api/be-collaborator', methods=['POST'])
@limiter.limit("100 per second")
@token_required([1, 2])
def be_collaborator():
    try:
        logger.debug("Received request to become collaborator")
        collaborator_details = request.get_json()
        required_fields = ['fin_kod', 'project_code']

        for field in required_fields:
            if field not in collaborator_details:
                return handle_missing_field(404)
            
        fin_kod = collaborator_details.get('fin_kod')
        project_code = collaborator_details.get('project_code')
        
        logger.debug(f"fin_kod: {fin_kod}, project_code: {project_code}")

        user = Auth.query.filter_by(fin_kod=fin_kod).first()
        project = Project.query.filter_by(project_code=project_code).first()

        collaborator_count = Collaborator.query.filter_by(project_code=project_code).count()

        max_collaborator_count = Project.query.filter_by(project_code=project_code).first().collaborator_limit

        if collaborator_count >= max_collaborator_count:
            return handle_conflict("There is no available place in project.")

        if not user:
            logger.debug("User not found.")
            return handle_specific_not_found("User not found.")
        if not project:
            logger.debug("Project not found.")
            return handle_specific_not_found("Project not found.")

        profile_approved = User.query.filter_by(fin_kod=fin_kod).first().profile_completed

        if not profile_approved:
            logger.debug("User profile not completed.")
            return {'error': 'User profile is not completed.', 'status': 403}, 403

        # A person may join only one project PER competition. The global UNIQUE on
        # fin_kod was relaxed to (fin_kod, competition_id), so check explicitly.
        existing = Collaborator.query.filter_by(
            fin_kod=fin_kod, competition_id=project.competition_id
        ).first()
        if existing:
            return handle_conflict("Already a collaborator in this competition.")

        new_collaborator_record = Collaborator(
            project_code=project_code,
            fin_kod=fin_kod,
            competition_id=project.competition_id
        )

        logger.debug("Adding new collaborator to the database")
        db.session.add(new_collaborator_record) 
        db.session.commit()

        return handle_creation("Collaborator added successfully.")

    except Exception as e:
        logger.exception("An error occurred while processing be-collaborator request")
        return handle_global_exception(str(e))

    
@collaborator_bp.route('/api/app-collaborator/<string:fin_kod>', methods=['POST'])
@limiter.limit("100 per second")
@token_required([0, 2])
def approve_collaborator(fin_kod):
    try:
        collaborator = Collaborator.query.filter_by(fin_kod=fin_kod).first()

        if not collaborator:
            return handle_specific_not_found("Collaborator not found.")
        project_code = collaborator.project_code
        email = User.query.filter_by(fin_kod=fin_kod).first().work_email

        project = Project.query.filter_by(project_code=project_code).first()

        collaborator.approved = True
        db.session.commit()

        subject = "İcraçı Təyinatı"
        recipient = email
        html_content = render_template("email/collaborator_success_template.html", project=project)
        send_email(subject, recipient, html_content)

        collaborator_data = {
            "fin_kod": collaborator.fin_kod,
            "project_code": collaborator.project_code,
            "approved": collaborator.approved
        }

        return handle_success(collaborator_data, "Collaborator approved successfully.")
            
    except Exception as e:
        logger.exception("An error occurred while processing approve-collaborator request")
        return handle_global_exception(str(e))
    
@collaborator_bp.route('/api/reject-collaborator/<string:fin_kod>', methods=['DELETE'])
@limiter.limit("100 per second")
@token_required([0, 2])
def reject_collaborator(fin_kod):
    try:
        collaborator = Collaborator.query.filter_by(fin_kod=fin_kod).first()

        if not collaborator:
            return handle_specific_not_found("Collaborator not found.")
        
        project_code = collaborator.project_code
        email = User.query.filter_by(fin_kod=fin_kod).first().work_email

        project = Project.query.filter_by(project_code=project_code).first()

        subject = "İcraçı Təyinatı"
        recipient = email
        html_content = render_template("email/collaborator_reject_template.html", project=project)
        send_email(subject, recipient, html_content)
        
        db.session.delete(collaborator)
        db.session.commit()
        return handle_success({"fin_kod": fin_kod}, "Collaborator rejected and removed successfully.")
    
    except Exception as e:
        logger.exception("An error occurred while processing approve-collaborator request")
        return handle_global_exception(str(e))
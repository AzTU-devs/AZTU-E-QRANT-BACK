import logging
from models.userModel import User
from config.limiter import limiter
from models.projectModel import Project
from utils.jwt_required import token_required
from flask import Blueprint, request, jsonify
from models.smetaModels.smetaModel import Smeta
from models.collaboratorModel import Collaborator
from models.smetaModels.salaryModel import db, Salary
from exceptions.exception import handle_specific_not_found, handle_global_exception

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

salary_bp = Blueprint('salary_bp', __name__)


@salary_bp.route('/api/create-salary-table', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def add_salary():
    data = request.get_json()
    logger.debug("Received request data: %s", data)

    try:
        salary_per_month = data.get('salary_per_month')
        months = data.get('months')

        if salary_per_month is None or months is None:
            logger.error("Missing salary_per_month or months. Data: %s", data)
            return jsonify({'error': 'Missing salary_per_month or months'}), 400

        try:
            salary_per_month = int(salary_per_month)
            months = int(months)
        except ValueError:
            logger.error("Invalid input types: salary_per_month=%s (type=%s), months=%s (type=%s)",
                         salary_per_month, type(salary_per_month), months, type(months))
            return jsonify({'error': 'Invalid input types'}), 400

        logger.debug("Parsed salary_per_month: %s, months: %s", salary_per_month, months)

        total_salary = salary_per_month * months
        logger.debug("Calculated total_salary: %s", total_salary)

        logger.debug("Creating Salary with project_code=%s, fin_kod=%s", data['project_code'], data['fin_kod'])
        new_salary = Salary(
            project_code=data['project_code'],
            fin_kod=data['fin_kod'],
            salary_per_month=salary_per_month,
            months=months,
            total_salary=total_salary
        )

        project_code = str(data['project_code'])

        main_smeta = Smeta.query.filter_by(project_code=project_code).first()

        if not main_smeta:
            main_smeta = Smeta(project_code=project_code)
            db.session.add(main_smeta)

        main_smeta.total_salary = (main_smeta.total_salary or 0) + total_salary

        logger.debug("New Salary object: %s", new_salary.salary_details())
        db.session.add(new_salary)
        db.session.commit()

        return jsonify({"status": 201, 'message': 'Salary record created', 'data': new_salary.salary_details()}), 201
    
    except Exception as e:
        logger.exception("Error occurred while creating salary record")
        return jsonify({'error': str(e)}), 400


@salary_bp.route("/api/salary/smeta/<int:project_code>", methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2])
def get_salary_smeta_by_project_code(project_code):
    logger.debug("Fetching salary smeta for project_code: %s", project_code)
    try:
        # Get the project
        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return handle_specific_not_found('Project not found')

        # Get project owner info
        project_owner_user = User.query.filter_by(fin_kod=project.fin_kod).first()
        project_owner_salary = Salary.query.filter_by(project_code=project_code, fin_kod=project.fin_kod).first()

        project_owner_data = {
            "fin_kod": project.fin_kod,
            "name": project_owner_user.name if project_owner_user else None,
            "surname": project_owner_user.surname if project_owner_user else None,
            "father_name": project_owner_user.father_name if project_owner_user else None,
            "salary": project_owner_salary.salary_details() if project_owner_salary else None,
        }

        # Get collaborators
        collaborators = Collaborator.query.filter_by(project_code=project_code).all()
        collaborator_list = []

        for collaborator in collaborators:
            user = User.query.filter_by(fin_kod=collaborator.fin_kod).first()
            salary = Salary.query.filter_by(project_code=project_code, fin_kod=collaborator.fin_kod).first()

            collaborator_list.append({
                "fin_kod": collaborator.fin_kod,
                "name": user.name if user else None,
                "surname": user.surname if user else None,
                "father_name": user.father_name if user else None,
                "salary": salary.salary_details() if salary else None
            })

        return jsonify({
            "project_owner": project_owner_data,
            "collaborators": collaborator_list
        })

    except Exception as e:
        logger.exception("Error occurred while fetching salary smeta")
        return handle_global_exception(str(e))

@salary_bp.route('/api/all-salaries-table', methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2])
def get_all_salaries():
    salaries = Salary.query.all()
    return jsonify([s.salarytable() for s in salaries]), 200



@salary_bp.route('/api/edit-salary-table/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_salary(project_code):
    data = request.get_json()
    fin_kod = data.get('fin_kod')
    salary_per_month = data.get('salary_per_month')
    months = data.get('months')

    if not fin_kod:
        logger.error("Missing required field: fin_kod")
        return jsonify({'error': 'fin_kod is required'}), 400

    salary = Salary.query.filter_by(project_code=project_code, fin_kod=fin_kod).first()
    if not salary:
        return jsonify({'message': 'Salary record not found'}), 404

    try:
        # Store old total before change
        old_total_salary = salary.total_salary or 0

        # Update fields if provided
        if salary_per_month is not None:
            salary.salary_per_month = int(salary_per_month)
        if months is not None:
            salary.months = int(months)

        # Recalculate total
        salary.total_salary = salary.salary_per_month * salary.months

        # Compute difference for main Smeta adjustment
        new_total_salary = salary.total_salary or 0
        difference = new_total_salary - old_total_salary

        # Update main smeta total
        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if not main_smeta:
            logger.info(f"No main smeta found for project_code={project_code}, creating new one")
            main_smeta = Smeta(project_code=str(project_code))
            db.session.add(main_smeta)

        if main_smeta.total_salary is None:
            main_smeta.total_salary = 0

        main_smeta.total_salary += difference

        db.session.commit()
        logger.debug(f"Updated Salary for fin_kod={fin_kod}, difference={difference}, "
                     f"new total_smeta_salary={main_smeta.total_salary}")

        return jsonify({'message': 'Salary record updated', 'data': salary.salary_details()}), 200

    except Exception as e:
        logger.exception("Exception during salary update")
        return jsonify({'error': str(e)}), 500

@salary_bp.route('/api/delete-salary/<int:project_code>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_salary(project_code):
    fin_kod = request.args.get('fin_kod') or (request.get_json(silent=True) or {}).get('fin_kod')

    query = Salary.query.filter_by(project_code=project_code)
    if fin_kod:
        query = query.filter_by(fin_kod=fin_kod)
    salary = query.first()

    if not salary:
        return jsonify({'message': 'Salary record not found'}), 404

    try:
        # Keep the aggregate Smeta.total_salary in sync (guard against None).
        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if main_smeta and main_smeta.total_salary is not None:
            main_smeta.total_salary -= (salary.total_salary or 0)

        db.session.delete(salary)
        db.session.commit()
        return jsonify({'message': 'Salary record deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

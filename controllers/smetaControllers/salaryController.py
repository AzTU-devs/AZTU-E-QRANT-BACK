import logging
from models.userModel import User
from config.limiter import limiter
from models.projectModel import Project
from utils.jwt_required import token_required
from utils.access import project_read_guard, project_write_guard
from utils.validation import non_negative_number, invalid_amount
from utils.smeta import line_total, recompute_project_smeta
from flask import Blueprint, request, jsonify
from models.collaboratorModel import Collaborator
from models.smetaModels.salaryModel import db, Salary
from exceptions.exception import handle_specific_not_found, handle_global_exception

logger = logging.getLogger(__name__)

salary_bp = Blueprint('salary_bp', __name__)


def _eligible_salary_fins(project):
    """FINs that may carry a salary line on a project: the lead plus everyone
    APPROVED on its team (B-L7). A salary for anyone else is refused."""
    fins = {project.fin_kod}
    fins.update(
        c.fin_kod for c in Collaborator.query.filter_by(
            project_code=project.project_code, approved=True
        ).all()
    )
    return fins


@salary_bp.route('/api/create-salary-table', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def add_salary():
    data = request.get_json(silent=True) or {}
    try:
        project, werror = project_write_guard(data.get('project_code'), respect_system_lock=True)
        if werror:
            return werror

        fin_kod = data.get('fin_kod')
        if not fin_kod:
            return jsonify({'error': 'fin_kod is required'}), 400
        if fin_kod not in _eligible_salary_fins(project):
            return jsonify({'error': 'Salary can only be set for the lead or an approved team member.'}), 403

        spm = non_negative_number(data.get('salary_per_month'))
        months = non_negative_number(data.get('months'))
        for name, val in (('salary_per_month', spm), ('months', months)):
            if val is None:
                return invalid_amount(name)

        # One salary line per person per project.
        if Salary.query.filter_by(project_code=project.project_code, fin_kod=fin_kod).first():
            return jsonify({'error': 'A salary line for this person already exists.'}), 409

        new_salary = Salary(
            project_code=project.project_code,
            fin_kod=fin_kod,
            salary_per_month=spm,
            months=months,
            total_salary=line_total(spm, months),
        )
        db.session.add(new_salary)
        recompute_project_smeta(project.project_code)
        db.session.commit()
        return jsonify({"status": 201, 'message': 'Salary record created', 'data': new_salary.salary_details()}), 201

    except Exception:
        db.session.rollback()
        logger.exception("Error occurred while creating salary record")
        return jsonify({'error': 'Internal server error'}), 500


@salary_bp.route("/api/salary/smeta/<int:project_code>", methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2, 3])
def get_salary_smeta_by_project_code(project_code):
    try:
        _rp, _re = project_read_guard(project_code)
        if _re:
            return _re

        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return handle_specific_not_found('Project not found')

        project_owner_user = User.query.filter_by(fin_kod=project.fin_kod).first()
        project_owner_salary = Salary.query.filter_by(project_code=project_code, fin_kod=project.fin_kod).first()

        project_owner_data = {
            "fin_kod": project.fin_kod,
            "name": project_owner_user.name if project_owner_user else None,
            "surname": project_owner_user.surname if project_owner_user else None,
            "father_name": project_owner_user.father_name if project_owner_user else None,
            "salary": project_owner_salary.salary_details() if project_owner_salary else None,
        }

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
@token_required([2])
def get_all_salaries():
    salaries = Salary.query.all()
    return jsonify([s.salary_details() for s in salaries]), 200


@salary_bp.route('/api/edit-salary-table/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_salary(project_code):
    try:
        data = request.get_json(silent=True) or {}
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror

        fin_kod = data.get('fin_kod')
        if not fin_kod:
            return jsonify({'error': 'fin_kod is required'}), 400

        salary = Salary.query.filter_by(project_code=project_code, fin_kod=fin_kod).first()
        if not salary:
            return jsonify({'message': 'Salary record not found'}), 404

        for field in ('salary_per_month', 'months'):
            if field in data:
                val = non_negative_number(data[field])
                if val is None:
                    return invalid_amount(field)
                setattr(salary, field, val)

        salary.total_salary = line_total(salary.salary_per_month, salary.months)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'Salary record updated', 'data': salary.salary_details()}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Exception during salary update")
        return jsonify({'error': 'Internal server error'}), 500


@salary_bp.route('/api/delete-salary/<int:project_code>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_salary(project_code):
    try:
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror
        fin_kod = request.args.get('fin_kod') or (request.get_json(silent=True) or {}).get('fin_kod')

        query = Salary.query.filter_by(project_code=project_code)
        if fin_kod:
            query = query.filter_by(fin_kod=fin_kod)
        salary = query.first()
        if not salary:
            return jsonify({'message': 'Salary record not found'}), 404

        db.session.delete(salary)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'Salary record deleted'}), 200
    except Exception:
        db.session.rollback()
        logger.exception("Exception in delete_salary")
        return jsonify({'error': 'Internal server error'}), 500

import logging
from config.limiter import limiter
from models.projectModel import Project
from utils.jwt_required import token_required
from utils.access import project_read_guard, project_write_guard
from utils.validation import non_negative_number, invalid_amount
from utils.smeta import (
    DIRECT_SMETA_FIELDS, recompute_project_smeta, get_or_create_smeta,
)
from flask import Blueprint, request, jsonify
from models.smetaModels.smetaModel import db, Smeta
from exceptions.exception import handle_specific_not_found, handle_global_exception, handle_success

logger = logging.getLogger(__name__)

smeta_bp = Blueprint('smeta_bp', __name__)

# The five category totals are always DERIVED from line items (see utils/smeta.py).
# Only the tax total and the social-fund contribution — which the UI computes and
# have no line-item table — may be written directly, and only through the
# allow-list below with validated values (findings B-H1 / B-M2).


def _apply_direct_fields(smeta, data):
    """Set only the allow-listed aggregate fields from `data`, validated.
    Returns an error response tuple, or None on success."""
    for field in DIRECT_SMETA_FIELDS:
        if field in data:
            val = non_negative_number(data[field])
            if val is None:
                return invalid_amount(field)
            setattr(smeta, field, val)
    return None


@smeta_bp.route('/api/create-smeta', methods=['POST'])
@limiter.limit("50 per second")
@token_required([2])
def create_smeta():
    """Admin-only: ensure the aggregate row exists and is consistent with the
    line items. Category totals are recomputed, not taken from the request."""
    data = request.get_json(silent=True) or {}
    try:
        project, werror = project_write_guard(data.get('project_code'), respect_system_lock=True)
        if werror:
            return werror
        smeta = recompute_project_smeta(project.project_code)
        err = _apply_direct_fields(smeta, data)
        if err:
            return err
        db.session.commit()
        return jsonify({'message': 'Smeta created', 'data': smeta.serialize()}), 201
    except Exception:
        db.session.rollback()
        logger.exception("create_smeta failed")
        return jsonify({'error': 'Internal server error'}), 500


@smeta_bp.route('/api/update-smeta-field/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_smeta_field(project_code):
    """Set ONE aggregate field. Restricted to the allow-listed direct fields —
    it previously did setattr for any attribute name, including project_code and
    id (finding B-M2)."""
    try:
        data = request.get_json(silent=True) or {}
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror

        column = data.get('column')
        if column not in DIRECT_SMETA_FIELDS:
            return jsonify({'error': "Only 'total_fee' and 'defense_fund' can be set here."}), 400
        value = non_negative_number(data.get('value'))
        if value is None:
            return invalid_amount(column)

        smeta = get_or_create_smeta(project_code)
        setattr(smeta, column, value)
        db.session.commit()
        return jsonify({'message': f"'{column}' updated successfully", 'data': smeta.serialize()}), 200
    except Exception:
        db.session.rollback()
        logger.exception("update_smeta_field failed")
        return jsonify({'error': 'Internal server error'}), 500


@smeta_bp.route("/api/main-smeta/<int:project_code>", methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2, 3])
def get_main_smeta_by_project_code(project_code):
    try:
        _rp, _re = project_read_guard(project_code)
        if _re:
            return _re
        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return handle_specific_not_found("Project or Smeta not found")

        # Recompute so the totals shown are always the authoritative ones.
        main_smeta = recompute_project_smeta(project_code)
        db.session.commit()

        total_main_amount = sum([
            main_smeta.total_salary or 0,
            main_smeta.total_equipment or 0,
            main_smeta.total_fee or 0,
            main_smeta.defense_fund or 0,
            main_smeta.total_services or 0,
            main_smeta.total_rent or 0,
            main_smeta.other_expenses or 0,
        ])
        max_amount_error = total_main_amount > (project.max_smeta_amount or 0)

        main_smeta_data = {
            "total_salary_smeta": main_smeta.total_salary,
            "total_tools_smeta": main_smeta.total_equipment,
            "total_services_smeta": main_smeta.total_services,
            "total_rent_smeta": main_smeta.total_rent,
            "total_other_smeta": main_smeta.other_expenses,
            "total_tax": main_smeta.total_fee,
            "total_defense_fund": main_smeta.defense_fund,
            "total_main_amount": total_main_amount,
            "max_amount_error": max_amount_error,
        }
        return handle_success(main_smeta_data, "Smeta fetched successfully.")
    except Exception as e:
        db.session.rollback()
        logger.exception("get_main_smeta failed")
        return handle_global_exception(str(e))


@smeta_bp.route('/api/edit-smeta/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_smeta(project_code):
    """Recompute the category totals from line items and, optionally, set the
    two direct fields. Client-supplied category totals are ignored (B-H1)."""
    try:
        data = request.get_json(silent=True) or {}
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror
        smeta = recompute_project_smeta(project_code)
        err = _apply_direct_fields(smeta, data)
        if err:
            return err
        db.session.commit()
        return jsonify({'message': 'Smeta updated', 'data': smeta.serialize()}), 200
    except Exception:
        db.session.rollback()
        logger.exception("update_smeta failed")
        return jsonify({'error': 'Internal server error'}), 500


@smeta_bp.route('/api/delete-smeta/<int:project_code>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_smeta(project_code):
    try:
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror
        smeta = Smeta.query.filter(Smeta.project_code.in_([int(project_code), str(project_code)])).first()
        if not smeta:
            return jsonify({'message': 'Smeta not found'}), 404
        db.session.delete(smeta)
        db.session.commit()
        return jsonify({'message': 'Smeta deleted'}), 200
    except Exception:
        db.session.rollback()
        logger.exception("delete_smeta failed")
        return jsonify({'error': 'Internal server error'}), 500

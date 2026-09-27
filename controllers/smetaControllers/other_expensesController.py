import logging
from config.limiter import limiter
from flask import Blueprint, request, jsonify
from utils.jwt_required import token_required
from utils.access import project_read_guard, project_write_guard
from utils.validation import non_negative_number, invalid_amount
from utils.smeta import line_total, recompute_project_smeta
from models.smetaModels.other_expensesModel import db, other_exp_model

logger = logging.getLogger(__name__)

other_exp = Blueprint('other_exp', __name__)

# Totals are computed server-side from validated inputs; client totals ignored (B-H1).


@other_exp.route('/api/other_exp', methods=['POST'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def create_other_exp():
    data = request.get_json(silent=True) or {}
    try:
        project, werror = project_write_guard(data.get('project_code'), respect_system_lock=True)
        if werror:
            return werror

        up = non_negative_number(data.get('unit_price'))
        qty = non_negative_number(data.get('quantity'))
        dur = non_negative_number(data.get('duration'))
        for name, val in (('unit_price', up), ('quantity', qty), ('duration', dur)):
            if val is None:
                return invalid_amount(name)

        new_other_exp = other_exp_model(
            project_code=project.project_code,
            expenses_name=data.get('expenses_name'),
            unit_of_measure=data.get('unit_of_measure'),
            unit_price=up,
            quantity=qty,
            duration=dur,
            total_amount=line_total(up, qty, dur),
        )
        db.session.add(new_other_exp)
        recompute_project_smeta(project.project_code)
        db.session.commit()
        return jsonify({'message': 'other_exp record created', 'data': new_other_exp.others()}), 201

    except Exception:
        db.session.rollback()
        logger.exception("Failed to create other_exp record")
        return jsonify({'error': 'Internal server error'}), 500


@other_exp.route('/api/get-other_exp-all-tables/<int:project_code>', methods=['GET'])
@limiter.limit("300 per minute")
@token_required([0, 1, 2, 3])
def get_all_other_exps(project_code):
    _rp, _re = project_read_guard(project_code)
    if _re:
        return _re
    other_exps = other_exp_model.query.filter_by(project_code=project_code).all()
    return jsonify([r.others() for r in other_exps]), 200


@other_exp.route('/api/edit-other_exp-table/<int:id>', methods=['PATCH'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def update_other_exp(id):
    try:
        data = request.get_json(silent=True) or {}
        record = other_exp_model.query.get(id)
        if not record:
            return jsonify({'message': 'other_exp record not found'}), 404

        project, werror = project_write_guard(record.project_code, respect_system_lock=True)
        if werror:
            return werror

        if 'expenses_name' in data:
            record.expenses_name = data['expenses_name']
        if 'unit_of_measure' in data:
            record.unit_of_measure = data['unit_of_measure']
        for field in ('unit_price', 'quantity', 'duration'):
            if field in data:
                val = non_negative_number(data[field])
                if val is None:
                    return invalid_amount(field)
                setattr(record, field, val)

        record.total_amount = line_total(record.unit_price, record.quantity, record.duration)
        recompute_project_smeta(record.project_code)
        db.session.commit()
        return jsonify({'message': 'other_exp record updated', 'data': record.others()}), 200
    except Exception:
        db.session.rollback()
        logger.exception("Failed to update other_exp record")
        return jsonify({'error': 'Internal server error'}), 500


@other_exp.route('/api/delete-other_exp-table/<int:project_code>/<int:id>', methods=['DELETE'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def delete_other_exp(project_code, id):
    try:
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror
        record = other_exp_model.query.filter_by(project_code=project_code, id=id).first()
        if not record:
            return jsonify({'message': 'other_exp record not found'}), 404

        db.session.delete(record)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'other_exp record deleted'}), 200
    except Exception:
        db.session.rollback()
        logger.exception("Error occurred in delete_other_exp")
        return jsonify({'error': 'Internal server error'}), 500

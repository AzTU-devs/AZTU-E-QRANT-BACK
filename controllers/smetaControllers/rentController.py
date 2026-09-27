import logging
from config.limiter import limiter
from flask import Blueprint, request, jsonify
from utils.jwt_required import token_required
from utils.access import project_read_guard, project_write_guard
from utils.validation import non_negative_number, invalid_amount
from utils.smeta import line_total, recompute_project_smeta
from models.smetaModels.rentModel import db, Rent

logger = logging.getLogger(__name__)

rent_bp = Blueprint('rent_bp', __name__)

# Money/quantity fields are validated and the total is computed on the server;
# the client's `total_amount` is ignored (finding B-H1).


def _validated_amounts(data):
    """(unit_price, quantity, duration, error). Any negative/NaN/Infinity -> 400."""
    up = non_negative_number(data.get('unit_price'))
    qty = non_negative_number(data.get('quantity'))
    dur = non_negative_number(data.get('duration'))
    for name, val in (('unit_price', up), ('quantity', qty), ('duration', dur)):
        if val is None:
            return None, None, None, invalid_amount(name)
    return up, qty, dur, None


@rent_bp.route('/api/rent', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def create_rent():
    data = request.get_json(silent=True) or {}
    try:
        project, werror = project_write_guard(data.get('project_code'), respect_system_lock=True)
        if werror:
            return werror

        up, qty, dur, err = _validated_amounts(data)
        if err:
            return err

        new_rent = Rent(
            project_code=project.project_code,
            rent_area=data.get('rent_area'),
            unit_of_measure=data.get('unit_of_measure'),
            unit_price=up,
            quantity=qty,
            duration=dur,
            total_amount=line_total(up, qty, dur),
        )
        db.session.add(new_rent)
        recompute_project_smeta(project.project_code)
        db.session.commit()
        return jsonify({'message': 'Rent record created', 'data': new_rent.rent()}), 201

    except Exception:
        db.session.rollback()
        logger.exception("Error occurred in create_rent")
        return jsonify({'error': 'Internal server error'}), 500


@rent_bp.route('/api/get-rent-all-tables/<int:project_code>', methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2, 3])
def get_all_rents(project_code):
    _rp, _re = project_read_guard(project_code)
    if _re:
        return _re
    rents = Rent.query.filter_by(project_code=project_code).all()
    return jsonify([r.rent() for r in rents]), 200


@rent_bp.route('/api/edit-rent-table/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_rent(project_code):
    try:
        data = request.get_json(silent=True) or {}
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror

        rent_id = data.get('id')
        if not rent_id:
            return jsonify({'error': 'Rent ID is required'}), 400

        rent = Rent.query.filter_by(project_code=project_code, id=rent_id).first()
        if not rent:
            return jsonify({'message': 'Rent record not found'}), 404

        if 'rent_area' in data:
            rent.rent_area = data['rent_area']
        if 'unit_of_measure' in data:
            rent.unit_of_measure = data['unit_of_measure']
        for field in ('unit_price', 'quantity', 'duration'):
            if field in data:
                val = non_negative_number(data[field])
                if val is None:
                    return invalid_amount(field)
                setattr(rent, field, val)

        rent.total_amount = line_total(rent.unit_price, rent.quantity, rent.duration)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'Rent record updated', 'data': rent.rent()}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Exception in update_rent")
        return jsonify({'error': 'Internal server error'}), 500


@rent_bp.route('/api/delete-rent-table/<int:project_code>/<int:id>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_rent(project_code, id):
    try:
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror
        rent = Rent.query.filter_by(project_code=project_code, id=id).first()
        if not rent:
            return jsonify({'message': 'Rent record not found'}), 404

        db.session.delete(rent)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'Rent record deleted'}), 200
    except Exception:
        db.session.rollback()
        logger.exception("Exception in delete_rent")
        return jsonify({'error': 'Internal server error'}), 500

import logging
from config.limiter import limiter
from models.projectModel import Project
from utils.jwt_required import token_required
from utils.access import project_read_guard, project_write_guard
from utils.validation import non_negative_number, invalid_amount
from utils.smeta import line_total, recompute_project_smeta
from flask import Blueprint, request, jsonify
from models.smetaModels.servicesTableModel import db, ServicesOfPurchase

logger = logging.getLogger(__name__)

services_bp = Blueprint('services_bp', __name__)

# Totals are computed server-side from validated inputs; client totals ignored (B-H1).


@services_bp.route('/api/add-services', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def add_subject():
    data = request.get_json(silent=True) or {}
    try:
        project, werror = project_write_guard(data.get('project_code'), respect_system_lock=True)
        if werror:
            return werror

        price = non_negative_number(data.get('price'))
        qty = non_negative_number(data.get('quantity'))
        for name, val in (('price', price), ('quantity', qty)):
            if val is None:
                return invalid_amount(name)

        new_subject = ServicesOfPurchase(
            project_code=project.project_code,
            services_name=data.get('services_name'),
            unit_of_measure=data.get('unit_of_measure'),
            price=price,
            quantity=qty,
            total_amount=line_total(price, qty),
        )
        db.session.add(new_subject)
        recompute_project_smeta(project.project_code)
        db.session.commit()
        return jsonify({'message': 'Subject added successfully'}), 201

    except Exception:
        db.session.rollback()
        logger.exception("Exception occurred while adding service")
        return jsonify({'error': 'Internal server error'}), 500


@services_bp.route('/api/get-services/<int:project_code>', methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2, 3])
def get_subjects(project_code):
    try:
        _rp, _re = project_read_guard(project_code)
        if _re:
            return _re
        results = ServicesOfPurchase.query.filter_by(project_code=project_code).all()
        return jsonify([s.subject() for s in results]), 200
    except Exception:
        logger.exception("Exception in get_subjects")
        return jsonify({'error': 'Internal server error'}), 500


@services_bp.route('/api/update-services/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_service(project_code):
    try:
        data = request.get_json(silent=True) or {}
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror

        service_id = data.get('id')
        if not service_id:
            return jsonify({'error': 'Service ID is required'}), 400

        service = ServicesOfPurchase.query.filter_by(project_code=project_code, id=service_id).first()
        if not service:
            return jsonify({'error': 'Service not found with the provided ID'}), 404

        if 'services_name' in data:
            service.services_name = data['services_name']
        if 'unit_of_measure' in data:
            service.unit_of_measure = data['unit_of_measure']
        for field in ('price', 'quantity'):
            if field in data:
                val = non_negative_number(data[field])
                if val is None:
                    return invalid_amount(field)
                setattr(service, field, val)

        service.total_amount = line_total(service.price, service.quantity)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'Service updated successfully'}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Exception during update_service")
        return jsonify({'error': 'Internal server error'}), 500


@services_bp.route('/api/delete-services/<int:project_code>/<int:id>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_subject(project_code, id):
    try:
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror
        service = ServicesOfPurchase.query.filter_by(project_code=project_code, id=id).first()
        if not service:
            return jsonify({'message': 'service not found'}), 404

        db.session.delete(service)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'service deleted successfully'}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Exception in delete_subject (services)")
        return jsonify({'error': 'Internal server error'}), 500

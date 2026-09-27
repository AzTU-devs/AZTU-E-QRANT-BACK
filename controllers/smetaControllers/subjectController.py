import logging
from config.limiter import limiter
from models.projectModel import Project
from utils.jwt_required import token_required
from utils.access import project_read_guard, project_write_guard
from utils.validation import non_negative_number, invalid_amount
from utils.smeta import line_total, recompute_project_smeta
from flask import Blueprint, request, jsonify
from models.smetaModels.subjectModel import db, SubjectOfPurchase
from exceptions.exception import handle_success, handle_global_exception

logger = logging.getLogger(__name__)

subject_bp = Blueprint('subject_bp', __name__)

# Totals are computed server-side from validated inputs; client totals ignored (B-H1).


@subject_bp.route('/api/add-subject', methods=['POST'])
@limiter.limit("300 per minute")
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

        new_subject = SubjectOfPurchase(
            project_code=project.project_code,
            equipment_name=data.get('equipment_name'),
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
        logger.exception("Error while adding subject")
        return jsonify({'error': 'Internal server error'}), 500


@subject_bp.route("/api/subject/smeta/<int:project_code>", methods=['GET'])
@limiter.limit("300 per minute")
@token_required([0, 1, 2, 3])
def get_subject_smeta_by_project_code(project_code):
    try:
        _rp, _re = project_read_guard(project_code)
        if _re:
            return _re
        subject_smeta = SubjectOfPurchase.query.filter_by(project_code=project_code).all()
        return handle_success([subject.subject_details() for subject in subject_smeta], "Smeta fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


@subject_bp.route('/api/update-subject/<int:project_code>', methods=['PATCH'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def update_subject(project_code):
    try:
        data = request.get_json(silent=True) or {}
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror

        # Target one row by id; the historical "first row" behaviour silently
        # edited the wrong line when a project had several.
        subject_id = data.get('id')
        query = SubjectOfPurchase.query.filter_by(project_code=project_code)
        subject = query.filter_by(id=subject_id).first() if subject_id else query.first()
        if not subject:
            return jsonify({'message': 'Subject not found'}), 404

        if 'equipment_name' in data:
            subject.equipment_name = data['equipment_name']
        if 'unit_of_measure' in data:
            subject.unit_of_measure = data['unit_of_measure']
        for field in ('price', 'quantity'):
            if field in data:
                val = non_negative_number(data[field])
                if val is None:
                    return invalid_amount(field)
                setattr(subject, field, val)

        subject.total_amount = line_total(subject.price, subject.quantity)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'Subject updated successfully', 'data': subject.subject_details()}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Exception during subject update for project_code=%s", project_code)
        return jsonify({'error': 'Internal server error'}), 500


@subject_bp.route('/api/delete/smeta/subject/<int:project_code>/<int:id>', methods=['DELETE'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def delete_subject(project_code, id):
    try:
        project, werror = project_write_guard(project_code, respect_system_lock=True)
        if werror:
            return werror
        subject = SubjectOfPurchase.query.filter_by(id=id, project_code=project_code).first()
        if not subject:
            return jsonify({'error': 'Subject not found with the provided project_code'}), 404

        db.session.delete(subject)
        recompute_project_smeta(project_code)
        db.session.commit()
        return jsonify({'message': 'Subject deleted successfully'}), 200

    except Exception:
        db.session.rollback()
        logger.exception("Exception in delete_subject")
        return jsonify({'error': 'Internal server error'}), 500

import logging
from decimal import Decimal
from config.limiter import limiter
from models.projectModel import Project
from utils.jwt_required import token_required
from flask import Blueprint, request, jsonify
from models.smetaModels.smetaModel import Smeta
from models.smetaModels.subjectModel import db, SubjectOfPurchase
from exceptions.exception import handle_success, handle_global_exception

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

subject_bp = Blueprint('subject_bp', __name__)

@subject_bp.route('/api/add-subject', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def add_subject():
    data = request.get_json()
    logger.debug(f"Received data for add_subject: {data}")
    try:
        matching_project = Project.query.filter_by(
            project_code=data['project_code'],
            fin_kod=data['fin_code']
        ).first()

        if not matching_project:
            logger.warning("No matching project found with given project_code and fin_code")
            return jsonify({'error': 'No matching project found with given project_code and fin_code'}), 404

        new_subject = SubjectOfPurchase(
            project_code=data['project_code'],
            equipment_name=data['equipment_name'],
            unit_of_measure=data['unit_of_measure'],
            price=data['price'],
            quantity=data['quantity'],
            total_amount=data['price'] * data['quantity']
        )

        project_code = str(data['project_code'])

        main_smeta = Smeta.query.filter_by(project_code=project_code).first()

        if not main_smeta:
            main_smeta = Smeta(project_code=project_code)
            db.session.add(main_smeta)

        if main_smeta.total_equipment is None:
            main_smeta.total_equipment = 0

        main_smeta.total_equipment += Decimal(data['price'] * data['quantity'])

        db.session.add(new_subject)
        db.session.commit()
        return jsonify({'message': 'Subject added successfully'}), 201

    except Exception as e:
        logger.error(f"Error while adding subject: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

@subject_bp.route("/api/subject/smeta/<int:project_code>", methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2])
def get_subject_smeta_by_project_code(project_code):
    try:
        subject_smeta = SubjectOfPurchase.query.filter_by(project_code=project_code).all()

        return handle_success([subject.subject_details() for subject in subject_smeta], "Smeta fetched successfully.")
    
    except Exception as e:
        return handle_global_exception(str(e))
    
@subject_bp.route('/api/update-subject/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_subject(project_code):
    data = request.get_json()
    logger.debug(f"Received update request for subject, project_code={project_code}, data={data}")

    try:
        subject = SubjectOfPurchase.query.filter_by(project_code=project_code).first()

        if not subject:
            logger.error(f"Subject not found for project_code={project_code}")
            return jsonify({'message': 'Subject not found'}), 404

        # Save old total_amount before changes
        old_total_amount = subject.total_amount or 0

        # Update fields if present
        if 'equipment_name' in data:
            subject.equipment_name = data['equipment_name']
        if 'unit_of_measure' in data:
            subject.unit_of_measure = data['unit_of_measure']
        if 'price' in data:
            subject.price = data['price']
        if 'quantity' in data:
            subject.quantity = data['quantity']

        # Recalculate total_amount if price or quantity changed
        if 'price' in data or 'quantity' in data:
            subject.total_amount = subject.price * subject.quantity

        new_total_amount = subject.total_amount or 0

        # Adjust main Smeta total_tools by difference between new and old total_amount
        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if not main_smeta:
            # If not exists, create one
            main_smeta = Smeta(project_code=str(project_code))
            db.session.add(main_smeta)

        if main_smeta.total_equipment is None:
            main_smeta.total_equipment = 0

        difference = new_total_amount - old_total_amount
        main_smeta.total_equipment += difference

        db.session.commit()
        logger.info(f"Subject updated successfully for project_code={project_code}")
        return jsonify({'message': 'Subject updated successfully', 'data': subject.subject_details()}), 200

    except Exception as e:
        logger.exception(f"Exception during subject update for project_code={project_code}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@subject_bp.route('/api/delete/smeta/subject/<int:project_code>/<int:id>', methods=['DELETE'])
@token_required([0, 2])
def delete_subject(project_code, id):
    try:
        subject = SubjectOfPurchase.query.filter_by(id=id, project_code=project_code).first()

        if not subject:
            return jsonify({'error': 'Subject not found with the provided project_code'}), 404

        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if main_smeta and main_smeta.total_equipment is not None:
            main_smeta.total_equipment -= subject.total_amount

        db.session.delete(subject)
        db.session.commit()
        return jsonify({'message': 'Subject deleted successfully'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
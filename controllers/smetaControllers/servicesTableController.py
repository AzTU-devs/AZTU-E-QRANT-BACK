import logging
from decimal import Decimal
from config.limiter import limiter
from models.projectModel import Project  
from utils.jwt_required import token_required
from flask import Blueprint, request, jsonify
from models.smetaModels.smetaModel import Smeta
from models.smetaModels.servicesTableModel import db, ServicesOfPurchase

logging.basicConfig(level=logging.DEBUG)

services_bp = Blueprint('services_bp', __name__)

@services_bp.route('/api/add-services', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def add_subject():
    data = request.get_json()
    logging.debug(f"Received data: {data}")
    try:
        matching_project = Project.query.filter_by(
            project_code=data['project_code']
        ).first()

        if not matching_project:
            logging.debug("No matching project found.")
            return jsonify({'error': 'No matching project found with given project_code and fin_code'}), 400

        new_subject = ServicesOfPurchase(
            project_code=data['project_code'],
            services_name=data['services_name'],
            unit_of_measure=data['unit_of_measure'],
            price=data['price'],
            quantity=data['quantity'],
            total_amount=Decimal(data['price'] * data['quantity'])
        )

        project_code = str(data['project_code'])

        main_smeta = Smeta.query.filter_by(project_code=project_code).first()

        if not main_smeta:
            main_smeta = Smeta(project_code=project_code)
            db.session.add(main_smeta)

        if main_smeta.total_services is None:
            main_smeta.total_services = 0

        main_smeta.total_services += Decimal(data['price'] * data['quantity'])

        db.session.add(new_subject)
        db.session.commit()
        logging.debug("New subject added successfully.")
        return jsonify({'message': 'Subject added successfully'}), 201

    except Exception as e:
        db.session.rollback()
        logging.exception("Exception occurred while adding subject:")
        return jsonify({'error': str(e)}), 400


@services_bp.route('/api/get-services/<int:project_code>', methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2])
def get_subjects(project_code):
    try:
        results = ServicesOfPurchase.query.filter_by(project_code=project_code).all()

        response = [{
        	'id': s.id,
            'project_code': s.project_code,
            'services_name': s.services_name,
            'unit_of_measure': s.unit_of_measure,
            'price': s.price,
            'quantity': s.quantity,
            'total_amount': s.total_amount
        } for s in results]

        return jsonify(response), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 400


import logging

@services_bp.route('/api/update-services/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_service(project_code):
    try:
        data = request.get_json()
        logging.debug(f"Received PATCH data for update_service: {data}")
        if not data:
            logging.error("No JSON data provided in request")
            return jsonify({'error': 'Invalid or missing JSON data'}), 400

        service_id = data.get('id')
        if not service_id:
            logging.error("Missing service ID in request data")
            return jsonify({'error': 'Service ID is required'}), 400

        service = ServicesOfPurchase.query.filter_by(project_code=project_code, id=service_id).first()
        if not service:
            logging.error(f"Service not found for project_code={project_code} and id={service_id}")
            return jsonify({'error': 'Service not found with the provided ID'}), 404

        old_total_amount = service.total_amount or 0
        logging.debug(f"Old total_amount: {old_total_amount}")

        # Update fields only if present
        if 'services_name' in data:
            logging.debug(f"Updating services_name to {data['services_name']}")
            service.services_name = data['services_name']
        if 'unit_of_measure' in data:
            logging.debug(f"Updating unit_of_measure to {data['unit_of_measure']}")
            service.unit_of_measure = data['unit_of_measure']
        if 'price' in data:
            logging.debug(f"Updating price to {data['price']}")
            service.price = data['price']
        if 'quantity' in data:
            logging.debug(f"Updating quantity to {data['quantity']}")
            service.quantity = data['quantity']

        if service.price is not None and service.quantity is not None:
            try:
                service.total_amount = float(service.price) * float(service.quantity)
                logging.debug(f"New total_amount calculated: {service.total_amount}")
            except Exception as e:
                logging.error(f"Error calculating total_amount: {e}")
                return jsonify({'error': f"Calculation error: {str(e)}"}), 400

        new_total_amount = service.total_amount or 0

        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if not main_smeta:
            logging.info(f"No main smeta found for project_code={project_code}, creating new one")
            main_smeta = Smeta(project_code=str(project_code))
            db.session.add(main_smeta)

        if main_smeta.total_services is None:
            main_smeta.total_services = 0

        difference = Decimal(str(new_total_amount)) - Decimal(str(old_total_amount))
        main_smeta.total_services += difference

        db.session.commit()
        logging.info(f"Service updated successfully for id={service_id} in project_code={project_code}")
        return jsonify({'message': 'Service updated successfully'}), 200

    except Exception as e:
        logging.exception("Exception during update_service:")
        db.session.rollback()
        return jsonify({'error': f"Server error: {str(e)}"}), 500


    
@services_bp.route('/api/delete-services/<int:project_code>/<int:id>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_subject(project_code, id):

    try:
        service = ServicesOfPurchase.query.filter_by(project_code=project_code, id=id).first()

        if not service:
            return jsonify({'message': 'service not found'}), 404

        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if main_smeta and main_smeta.total_services is not None:
            main_smeta.total_services -= service.total_amount

        db.session.delete(service)
        db.session.commit()
        return jsonify({'message': 'service deleted successfully'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
from decimal import Decimal
from config.limiter import limiter
from flask import Blueprint, request, jsonify
from utils.jwt_required import token_required
from models.smetaModels.smetaModel import Smeta
from models.smetaModels.rentModel import db, Rent

rent_bp = Blueprint('rent_bp', __name__)


@rent_bp.route('/api/rent', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def create_rent():
    data = request.get_json()
    try:
        new_rent = Rent(
            project_code=data['project_code'],
            rent_area=data['rent_area'],
            unit_of_measure=data['unit_of_measure'],
            unit_price=data['unit_price'],
            quantity=data['quantity'],
            duration=data['duration'],
            total_amount=data['total_amount']
        )

        project_code = str(data['project_code'])

        main_smeta = Smeta.query.filter_by(project_code=project_code).first()

        if not main_smeta:
            main_smeta = Smeta(project_code=project_code)
            db.session.add(main_smeta)
        
        if main_smeta.total_rent is None:
            main_smeta.total_rent = 0

        main_smeta.total_rent += data['total_amount']

        db.session.add(new_rent)
        db.session.commit()
        return jsonify({'message': 'Rent record created', 'data': new_rent.rent()}), 201
    
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Error occurred in create_rent: %s", traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@rent_bp.route('/api/get-rent-all-tables/<int:project_code>', methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2])
def get_all_rents(project_code):
    rents = Rent.query.filter_by(project_code=project_code).all()
    return jsonify([r.rent() for r in rents]), 200

@rent_bp.route('/api/edit-rent-table/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_rent(project_code):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid or missing JSON data'}), 400

        rent_id = data.get('id')
        if not rent_id:
            return jsonify({'error': 'Rent ID is required'}), 400

        rent = Rent.query.filter_by(project_code=project_code, id=rent_id).first()
        if not rent:
            return jsonify({'message': 'Rent record not found'}), 404

        old_total = rent.total_amount or 0

        if 'rent_area' in data:
            rent.rent_area = data['rent_area']
        if 'unit_of_measure' in data:
            rent.unit_of_measure = data['unit_of_measure']
        if 'unit_price' in data:
            rent.unit_price = data['unit_price']
        if 'quantity' in data:
            rent.quantity = data['quantity']
        if 'duration' in data:
            rent.duration = data['duration']

        if rent.unit_price is not None and rent.quantity is not None and rent.duration is not None:
            rent.total_amount = float(rent.unit_price) * float(rent.quantity) * float(rent.duration)

        new_total = rent.total_amount or 0

        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if not main_smeta:
            main_smeta = Smeta(project_code=str(project_code))
            db.session.add(main_smeta)

        if main_smeta.total_rent is None:
            main_smeta.total_rent = 0

        main_smeta.total_rent += Decimal(new_total - old_total)

        db.session.commit()
        return jsonify({'message': 'Rent record updated', 'data': rent.rent()}), 200

    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error("Exception in update_rent: %s", traceback.format_exc())
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@rent_bp.route('/api/delete-rent-table/<int:project_code>/<int:id>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_rent(project_code, id):

    try:
        rent = Rent.query.filter_by(project_code=project_code, id=id).first()

        if not rent:
            return jsonify({'message': 'Rent record not found'}), 404
        
        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if main_smeta and main_smeta.total_rent is not None:
            main_smeta.total_rent -= rent.total_amount

        db.session.delete(rent)
        db.session.commit()
        return jsonify({'message': 'Rent record deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
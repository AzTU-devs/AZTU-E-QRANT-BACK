import logging
from decimal import Decimal
from config.limiter import limiter
from flask import Blueprint, request, jsonify
from utils.jwt_required import token_required
from models.smetaModels.smetaModel import Smeta
from models.smetaModels.other_expensesModel import db, other_exp_model

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

other_exp = Blueprint('other_exp', __name__)


@other_exp.route('/api/other_exp', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def create_other_exp():
    data = request.get_json()
    try:
        new_other_exp = other_exp_model(
            project_code=data['project_code'],
            expenses_name=data['expenses_name'],
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

        if main_smeta.other_expenses is None:
            main_smeta.other_expenses = 0
            
        main_smeta.other_expenses += data['total_amount']

        db.session.add(new_other_exp)
        db.session.commit()
        return jsonify({'message': 'other_exp record created', 'data': new_other_exp.others()}), 201
    
    except Exception as e:
        logger.exception("Failed to create other_exp record")
        return jsonify({'error': str(e)}), 500


@other_exp.route('/api/get-other_exp-all-tables/<int:project_code>', methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2])
def get_all_other_exps(project_code):
    other_exps = other_exp_model.query.filter_by(project_code=project_code).all()
    return jsonify([r.others() for r in other_exps]), 200

@other_exp.route('/api/edit-other_exp-table/<int:id>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_other_exp(id):
    try:
        data = request.get_json()
        other_exp = other_exp_model.query.get(id)

        if not other_exp:
            return jsonify({'message': 'other_exp record not found'}), 404

        old_total_amount = other_exp.total_amount if other_exp.total_amount else 0

        if 'project_code' in data:
            other_exp.project_code = data['project_code']
        if 'expenses_name' in data:
            other_exp.expenses_name = data['expenses_name']
        if 'unit_of_measure' in data:
            other_exp.unit_of_measure = data['unit_of_measure']
        if 'unit_price' in data:
            other_exp.unit_price = data['unit_price']
        if 'quantity' in data:
            other_exp.quantity = data['quantity']
        if 'duration' in data:
            other_exp.duration = data['duration']
        if 'total_amount' in data:
            other_exp.total_amount = data['total_amount']

        # Update main_smeta.other_expenses if total_amount changed
        if 'total_amount' in data:
            main_smeta = Smeta.query.filter_by(project_code=str(other_exp.project_code)).first()
            if not main_smeta:
                main_smeta = Smeta(project_code=other_exp.project_code)
                db.session.add(main_smeta)
            if main_smeta.other_expenses is None:
                main_smeta.other_expenses = 0
            main_smeta.other_expenses = Decimal(main_smeta.other_expenses - old_total_amount + other_exp.total_amount)

        db.session.commit()
        return jsonify({'message': 'other_exp record updated', 'data': other_exp.others()}), 200
    except Exception as e:
        logger.exception("Failed to update other_exp record")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@other_exp.route('/api/delete-other_exp-table/<int:project_code>/<int:id>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_other_exp(project_code, id):
    try:
        record = other_exp_model.query.filter_by(project_code=project_code, id=id).first()
        if not record:
            return jsonify({'message': 'other_exp record not found'}), 404
        
        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
        if main_smeta and main_smeta.other_expenses is not None:
            main_smeta.other_expenses -= record.total_amount

        db.session.delete(record)
        db.session.commit()
        return jsonify({'message': 'other_exp record deleted'}), 200
    except Exception as e:
        db.session.rollback()
        import traceback
        logger.error("Error occurred in delete_other_exp: %s", traceback.format_exc())
        return jsonify({'error': str(e)}), 500

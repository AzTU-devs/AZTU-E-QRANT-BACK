import traceback
from config.limiter import limiter
from models.projectModel import Project
from models.projectModel import Project
from utils.jwt_required import token_required
from flask import Blueprint, request, jsonify
from models.smetaModels.rentModel import Rent
from models.smetaModels.salaryModel import Salary
from models.smetaModels.smetaModel import db, Smeta
from models.smetaModels.subjectModel import SubjectOfPurchase
from models.smetaModels.other_expensesModel import other_exp_model
from models.smetaModels.servicesTableModel import ServicesOfPurchase
from exceptions.exception import handle_specific_not_found, handle_global_exception, handle_success, handle_conflict

smeta_bp = Blueprint('smeta_bp', __name__)

# ➕ POST - Create new smeta record
@smeta_bp.route('/api/create-smeta', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 2])
def create_smeta():
    data = request.get_json()
    try:
        new_smeta = Smeta(
            project_code=data['project_code'],
            total_salary=data['total_salary'],
            total_fee=data['total_fee'],
            defense_fund=data['defense_fund'],
            total_equipment=data['total_equipment'],
            total_services=data['total_services'],
            total_rent=data['total_rent'],
            other_expenses=data.get('other_expenses')
        )
        db.session.add(new_smeta)
        db.session.commit()
        return jsonify({'message': 'Smeta created', 'data': new_smeta.serialize()}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@smeta_bp.route('/api/update-smeta-field/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_smeta_field(project_code):
    data = request.get_json()
    column = data.get('column')
    value = data.get('value')

    if not column or value is None:
        return jsonify({'error': 'Missing column or value'}), 400

    smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
    if not smeta:
        return jsonify({'error': 'Smeta not found'}), 404

    if not hasattr(smeta, column):
        return jsonify({'error': f"Column '{column}' does not exist in Smeta model"}), 400

    try:
        setattr(smeta, column, value)
        db.session.commit()
        return jsonify({'message': f"'{column}' updated successfully", 'data': smeta.serialize()}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@smeta_bp.route("/api/main-smeta/<int:project_code>", methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1, 2])
def get_main_smeta_by_project_code(project_code):
    try:
        project = Project.query.filter_by(project_code=str(project_code)).first()
        main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()

        if not main_smeta or not project:
            return handle_specific_not_found("Project or Smeta not found")

        total_main_amount = sum([
            main_smeta.total_salary or 0,
            main_smeta.total_equipment or 0,
            main_smeta.total_fee or 0,
            main_smeta.defense_fund or 0,
            main_smeta.total_services or 0,
            main_smeta.total_rent or 0,
            main_smeta.other_expenses or 0
        ])

        max_amount_error = True if total_main_amount > project.max_smeta_amount else False

        main_smeta_data = {
            "total_salary_smeta": main_smeta.total_salary,
            "total_tools_smeta": main_smeta.total_equipment,
            "total_services_smeta": main_smeta.total_services,
            "total_rent_smeta": main_smeta.total_rent,
            "total_other_smeta": main_smeta.other_expenses,
            "total_tax": main_smeta.total_fee,
            "total_defense_fund": main_smeta.defense_fund,
            "total_main_amount": total_main_amount,
            "max_amount_error": max_amount_error
        }

        return handle_success(main_smeta_data, "Smeta fetched successfully.")
    
    except Exception as e:
        import traceback
        print("❌ Exception occurred in get_main_smeta_by_project_code:")
        print(traceback.format_exc())
        return handle_global_exception(str(e))
    

@smeta_bp.route('/api/edit-smeta/<int:project_code>', methods=['PATCH'])
@limiter.limit("50 per second")
@token_required([0, 2])
def update_smeta(project_code):
    data = request.get_json()
    # `.get()` looks up by primary key (id), not project_code — must filter.
    smeta = Smeta.query.filter_by(project_code=str(project_code)).first()

    if not smeta:
        return jsonify({'message': 'Smeta not found'}), 404

    try:
        for field in ['total_salary', 'total_fee', 'defense_fund', 'total_equipment', 'total_services', 'total_rent', 'other_expenses']:
            if field in data:
                setattr(smeta, field, data[field])

        db.session.commit()
        return jsonify({'message': 'Smeta updated', 'data': smeta.serialize()}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@smeta_bp.route('/api/delete-smeta/<int:project_code>', methods=['DELETE'])
@limiter.limit("50 per second")
@token_required([0, 2])
def delete_smeta(project_code):
    smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
    if not smeta:
        return jsonify({'message': 'Smeta not found'}), 404

    try:
        db.session.delete(smeta)
        db.session.commit()
        return jsonify({'message': 'Smeta deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400

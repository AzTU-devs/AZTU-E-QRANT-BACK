from sqlalchemy import func
from flask import Blueprint
from extentions.db import db
from datetime import datetime
from config.limiter import limiter
from models.institutionModel import Institution
from utils.jwt_required import token_required
from exceptions.exception import handle_success, handle_global_exception, handle_not_found, handle_conflict, handle_creation
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

institution_bp = Blueprint('institution', __name__)

@institution_bp.route('/api/institutions', methods=['GET'])
@limiter.limit("100 per second")
# @token_required([0, 1, 2])
def get_institutions():
    """
    Get all institutions
    ---
    tags:
      - Institutions
    responses:
      200:
        description: List of all institutions
    """
    try:
        institutions = Institution.query.all()

        data = [
            {
                "id": i.id,
                "institution_code": i.institution_code,
                "institution_name": i.institution_name,
                "created_at": i.created_at.isoformat() if i.created_at else None
            }
            for i in institutions
        ]

        if not data:
            return handle_not_found("No data found")

        return handle_success(data, "Institutions fetched successfully")
    except Exception as e:
        return handle_global_exception(e)

import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

@institution_bp.route('/api/create-institution/<institution_name>', methods=['POST'])
@limiter.limit("10 per minute")
def create_institution(institution_name: str):
    try:
        logger.debug(f"Received institution_name: {institution_name} (type: {type(institution_name)})")

        exist_institution = Institution.query.filter(Institution.institution_name == institution_name).first()
        if exist_institution:
            logger.debug("Institution already exists.")
            return handle_conflict("Institution already exists")

        last_institution = Institution.query.order_by(Institution.institution_code.desc()).first()
        last_code = last_institution.institution_code if last_institution else 0
        logger.debug(f"Last institution code: {last_code} (type: {type(last_code)})")

        new_code = f"{last_code + 1}"
        logger.debug(f"New institution code: {new_code} (type: {type(new_code)})")

        new_institution = Institution(
            institution_name=institution_name,
            institution_code=new_code,
            created_at=datetime.utcnow()
        )
        db.session.add(new_institution)
        db.session.commit()

        logger.debug("Institution created successfully.")
        return handle_creation("Institution created successfully")
    except Exception as e:
        logger.error(f"Error occurred: {e}")
        db.session.rollback()
        return handle_global_exception(e)


@institution_bp.route('/api/institution/<institution_code>', methods=['GET'])
@limiter.limit("10 per minute")
def get_institution_by_code(
    institution_code: str
):
    try:
        institution = Institution.query.filter(Institution.institution_code == institution_code).first()
        institution_name = institution.institution_name

        if not institution_code:
            return handle_not_found("Institution not found.")
        
        return handle_success(institution_name, "Institute fetchd successfully.")
    
    except Exception as e:
        logger.error(f"Error occurred: {e}")
        db.session.rollback()
        return handle_global_exception(e)
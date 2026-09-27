from config.limiter import limiter
from extentions.db import db
from datetime import datetime
from flask import Blueprint, request
from models.prioritetModel import Priotet
from utils.jwt_required import token_required
from exceptions.exception import handle_missing_field, handle_specific_not_found, handle_success, handle_global_exception, handle_creation, handle_not_found
import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

priotet_bp = Blueprint('priotet', __name__)

@priotet_bp.route('/api/create-priotet', methods=['POST'])
@limiter.limit("10 per second")
@token_required([2])
def create_priotet():
    # Admin-only: priorities are a controlled reference list (finding B-M5).
    try:
        data = request.get_json()
        prioritet_name = data.get("prioritet_name")
        prioritet_code = data.get("prioritet_code")

        if not prioritet_name or not prioritet_code:
            return handle_missing_field()

        new_prioritet = Priotet(
            prioritet_name=prioritet_name,
            prioritet_code=prioritet_code,
            created_at=datetime.utcnow()
        )
        db.session.add(new_prioritet)
        db.session.commit()

        return handle_creation("Prioritet successfully created")

    except Exception as e:
        return handle_global_exception(e)

@priotet_bp.route('/api/priotets', methods=['GET'])
@limiter.limit("10 per second")
@token_required([0, 1, 2])
def get_priotets():
    try:
        prioritets = Priotet.query.all()

        data = [
            {
                "id": p.id,
                "prioritet_name": p.prioritet_name,
                "prioritet_code": p.prioritet_code,
                "created_at": p.created_at.isoformat() if p.created_at else None
            }
            for p in prioritets
        ]
        return handle_success(data, "Priotets fetched successfully")
    except Exception as e:
        return handle_global_exception(e)

@priotet_bp.route('/api/priotet/<int:prioritet_code>')
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def get_priotet_by_code(prioritet_code):
    try:
        priotet = Priotet.query.filter_by(prioritet_code=prioritet_code).first().prioritet_name

        return {"priotet_name": priotet}
    
    except Exception as e:
        return handle_global_exception(e)

@priotet_bp.route("/api/del-prioritet/<int:code>", methods=['DELETE'])
@limiter.limit("10 per second")
@token_required([2])
def delete_prioritet(code):
    # Admin-only: deleting a priority was possible with no token (pentest F4).
    try:
        prioritet = Priotet.query.filter_by(prioritet_code=code).first()

        if not prioritet:
            return handle_not_found(404)

        db.session.delete(prioritet)
        db.session.commit()

        return {"statusCode": 200, "message": "Prioritet deleted successfully."}, 200
    
    except Exception as e:
        return handle_global_exception(e)
    
@priotet_bp.route("/api/upd-prioritet", methods=['POST'])
@limiter.limit("10 per second")
@token_required([2])
def upd_prioritet():
    # Admin-only: updating a priority was possible with no token (pentest F4).
    try:
        data = request.get_json()

        prioritet_code = data.get('prioritet_code')
        new_prioritet_name = data.get('prioritet_name')

        prioritet = Priotet.query.filter_by(prioritet_code=prioritet_code).first()

        if not prioritet:
            return handle_not_found(404)

        prioritet.prioritet_name = new_prioritet_name

        db.session.commit()

        return {"statusCode": 200, "message": "Prioritet deleted successfully."}, 200
   
    except Exception as e:
        logger.exception("Error occurred while updating prioritet")
        return handle_global_exception(e)
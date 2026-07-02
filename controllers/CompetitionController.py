from datetime import datetime
from config.limiter import limiter
from extentions.db import db
from flask import Blueprint, request, g
from models.competitionModel import Competition
from utils.jwt_required import token_required
from exceptions.exception import (
    handle_missing_field,
    handle_specific_not_found,
    handle_success,
    handle_global_exception,
)
import logging

logger = logging.getLogger(__name__)

competition_bp = Blueprint('competition_bp', __name__)


def _parse_date(value):
    if not value:
        return None
    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


@competition_bp.route('/api/competitions', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def list_competitions():
    try:
        competitions = Competition.query.order_by(Competition.year.desc(), Competition.id.desc()).all()
        return handle_success([c.serialize() for c in competitions], "Competitions fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


@competition_bp.route('/api/competition/active', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def active_competition():
    try:
        active = Competition.get_active()
        return handle_success(active.serialize() if active else None, "Active competition fetched.")
    except Exception as e:
        return handle_global_exception(str(e))


@competition_bp.route('/api/competition', methods=['POST'])
@limiter.limit("20 per second")
@token_required([2])
def create_competition():
    """Admin creates a new competition (season). If `activate` is true (default),
    it becomes the single active competition."""
    try:
        data = request.get_json() or {}

        year = data.get('year')
        if year is None:
            return handle_missing_field('year')
        try:
            year = int(year)
        except (TypeError, ValueError):
            return handle_missing_field('year')

        code = (data.get('code') or f"AzTU-DQL-{year}").strip()

        if Competition.query.filter_by(code=code).first():
            return {"status": 409, "message": "Bu kodla müsabiqə artıq mövcuddur."}, 409

        activate = data.get('activate', True)

        competition = Competition(
            code=code,
            year=year,
            title=(data.get('title') or '').strip() or None,
            application_deadline=_parse_date(data.get('application_deadline')),
            report_deadline=_parse_date(data.get('report_deadline')),
            contract_date=_parse_date(data.get('contract_date')),
            max_smeta_amount=int(data.get('max_smeta_amount') or 30000),
            collaborator_limit=int(data.get('collaborator_limit') or 7),
            is_active=False,
            created_at=datetime.utcnow(),
            created_by=g.user.get('fin_kod') if getattr(g, 'user', None) else None,
        )
        db.session.add(competition)
        db.session.flush()  # get id before activating

        if activate:
            Competition.query.filter(Competition.id != competition.id).update({'is_active': False})
            competition.is_active = True

        db.session.commit()
        return handle_success(competition.serialize(), "Müsabiqə yaradıldı.")
    except Exception as e:
        db.session.rollback()
        logger.exception("create_competition failed")
        return handle_global_exception(str(e))


@competition_bp.route('/api/competition/<int:competition_id>/activate', methods=['POST'])
@limiter.limit("20 per second")
@token_required([2])
def activate_competition(competition_id):
    """Make the given competition the single active one."""
    try:
        competition = Competition.query.get(competition_id)
        if not competition:
            return handle_specific_not_found('Competition not found.')

        Competition.query.update({'is_active': False})
        competition.is_active = True
        db.session.commit()
        return handle_success(competition.serialize(), "Müsabiqə aktivləşdirildi.")
    except Exception as e:
        db.session.rollback()
        logger.exception("activate_competition failed")
        return handle_global_exception(str(e))

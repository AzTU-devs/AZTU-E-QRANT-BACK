"""
Public (no-auth) endpoints used by the public-facing grant website.

These endpoints expose ONLY safe, non-sensitive fields of *approved* projects
(approved == 1): project name, description (annotation), the project lead and
the approved collaborators. No smeta / budget / contact / personal data is
returned here.
"""

from config.limiter import limiter
from models.userModel import User
from models.projectModel import Project
from models.prioritetModel import Priotet
from models.collaboratorModel import Collaborator
from models.announcementModel import Announcement
from flask import Blueprint, current_app
from exceptions.exception import handle_success, handle_global_exception

public_bp = Blueprint('public_bp', __name__)


def _project_year(project):
    """Resolve the grouping year for a project: submitted_at, else deadline."""
    date_value = project.submitted_at or project.project_deadline
    if date_value:
        return date_value.year
    return None


def _lead_public(user):
    """Minimal, public-safe representation of a person."""
    if not user:
        return None
    return {
        'fin_kod': user.fin_kod,
        'name': user.name,
        'surname': user.surname,
        'father_name': user.father_name,
        'work_place': user.work_place,
        'department': user.department,
        'duty': user.duty,
        'scientific_degree': user.scientific_degree,
        'scientific_name': user.scientific_name,
    }


def _approved_collaborators(project_code):
    """Return public data for the approved collaborators of a project."""
    collaborators = Collaborator.query.filter_by(
        project_code=project_code, approved=True
    ).all()

    result = []
    for collaborator in collaborators:
        user = User.query.filter_by(fin_kod=collaborator.fin_kod).first()
        if not user:
            continue
        result.append(_lead_public(user))
    return result


@public_bp.route('/api/public/projects', methods=['GET'])
@limiter.limit("100 per second")
def public_projects():
    """List of approved projects with only name + description, grouped data."""
    current_app.logger.info("GET /api/public/projects called")
    try:
        projects = Project.query.filter_by(approved=1).all()

        # project.priotet is stored as Text while prioritet_code is Integer,
        # so key the lookup map by the string form to match reliably.
        priotet_map = {str(p.prioritet_code): p.prioritet_name for p in Priotet.query.all()}

        project_list = []
        for project in projects:
            lead = User.query.filter_by(fin_kod=project.fin_kod).first()
            description = project.project_annotation or project.project_purpose

            project_list.append({
                'project_code': project.project_code,
                'project_name': project.project_name,
                'description': description,
                'year': _project_year(project),
                'priotet_name': priotet_map.get(str(project.priotet)) if project.priotet else None,
                'winner': bool(project.winner),
                'lead': {
                    'name': lead.name if lead else None,
                    'surname': lead.surname if lead else None,
                } if lead else None,
            })

        return handle_success(project_list, 'Projects fetched successfully.')
    except Exception as e:
        current_app.logger.error(f"Exception in /api/public/projects: {e}", exc_info=True)
        return handle_global_exception(str(e))


@public_bp.route('/api/public/project/<int:project_code>', methods=['GET'])
@limiter.limit("100 per second")
def public_project_detail(project_code):
    """Single approved project with its lead and approved collaborators."""
    current_app.logger.info(f"GET /api/public/project/{project_code} called")
    try:
        project = Project.query.filter_by(project_code=project_code, approved=1).first()
        if not project:
            return handle_success(None, 'Project not found.')

        lead = User.query.filter_by(fin_kod=project.fin_kod).first()
        description = project.project_annotation or project.project_purpose

        priotet_obj = Priotet.query.filter_by(prioritet_code=project.priotet).first()

        data = {
            'project_code': project.project_code,
            'project_name': project.project_name,
            'description': description,
            'year': _project_year(project),
            'priotet_name': priotet_obj.prioritet_name if priotet_obj else None,
            'winner': bool(project.winner),
            'lead': _lead_public(lead),
            'collaborators': _approved_collaborators(project.project_code),
        }

        return handle_success(data, 'Project fetched successfully.')
    except Exception as e:
        current_app.logger.error(f"Exception in /api/public/project: {e}", exc_info=True)
        return handle_global_exception(str(e))


@public_bp.route('/api/public/leads-tree', methods=['GET'])
@limiter.limit("100 per second")
def public_leads_tree():
    """Tree of project leads with their projects and approved collaborators."""
    current_app.logger.info("GET /api/public/leads-tree called")
    try:
        projects = Project.query.filter_by(approved=1).all()

        tree = []
        for project in projects:
            lead = User.query.filter_by(fin_kod=project.fin_kod).first()
            tree.append({
                'project_code': project.project_code,
                'project_name': project.project_name,
                'year': _project_year(project),
                'lead': _lead_public(lead),
                'collaborators': _approved_collaborators(project.project_code),
            })

        return handle_success(tree, 'Leads tree fetched successfully.')
    except Exception as e:
        current_app.logger.error(f"Exception in /api/public/leads-tree: {e}", exc_info=True)
        return handle_global_exception(str(e))


@public_bp.route('/api/public/winners', methods=['GET'])
@limiter.limit("100 per second")
def public_winners():
    """Winner projects selected by the admin, with lead + approved collaborators."""
    current_app.logger.info("GET /api/public/winners called")
    try:
        projects = Project.query.filter_by(winner=True).all()

        priotet_map = {str(p.prioritet_code): p.prioritet_name for p in Priotet.query.all()}

        winners = []
        for project in projects:
            lead = User.query.filter_by(fin_kod=project.fin_kod).first()
            description = project.project_annotation or project.project_purpose

            winners.append({
                'project_code': project.project_code,
                'project_name': project.project_name,
                'description': description,
                'year': _project_year(project),
                'priotet_name': priotet_map.get(str(project.priotet)) if project.priotet else None,
                'lead': _lead_public(lead),
                'collaborators': _approved_collaborators(project.project_code),
            })

        return handle_success(winners, 'Winners fetched successfully.')
    except Exception as e:
        current_app.logger.error(f"Exception in /api/public/winners: {e}", exc_info=True)
        return handle_global_exception(str(e))


@public_bp.route('/api/public/announcements', methods=['GET'])
@limiter.limit("100 per second")
def public_announcements():
    """Published announcements for the public website."""
    current_app.logger.info("GET /api/public/announcements called")
    try:
        announcements = (
            Announcement.query
            .filter_by(published=True)
            .order_by(Announcement.created_at.desc())
            .all()
        )
        data = [a.serialize() for a in announcements]
        return handle_success(data, 'Announcements fetched successfully.')
    except Exception as e:
        current_app.logger.error(f"Exception in /api/public/announcements: {e}", exc_info=True)
        return handle_global_exception(str(e))

import os
import random
import requests
from extentions.db import db
from datetime import datetime
from models.authModel import Auth
from models.userModel import User
from config.limiter import limiter
from models.projectModel import Project
from models.prioritetModel import Priotet
from models.competitionModel import Competition
from models.smetaModels.rentModel import Rent
from utils.jwt_required import token_required
from utils.archive_lock import project_is_archived, ARCHIVE_LOCKED_MESSAGE
from utils.cascade_delete import delete_project_cascade
from utils.notify import create_notification, notify_admins
from utils.access import (
    project_read_guard, is_admin, submitted_lock_error, deadline_error,
)
from utils.smeta import project_grand_total
from utils.pdf_safety import rl_text
from xml.sax.saxutils import escape as _xml_escape
from utils.email_util import send_email
from models.smetaModels.smetaModel import Smeta
from models.collaboratorModel import Collaborator
from flask import Blueprint, request, current_app, g, render_template
from models.collaboratorModel import Collaborator
from models.smetaModels.salaryModel import Salary
from models.projectActivities import ProjectActivities
from models.smetaModels.subjectModel import SubjectOfPurchase
from models.smetaModels.other_expensesModel import other_exp_model
from models.smetaModels.servicesTableModel import ServicesOfPurchase
from exceptions.exception import handle_missing_field, handle_specific_not_found, handle_success, handle_global_exception

project_offer = Blueprint('project_offer', __name__)

# The fields a proposal carries when it is fully filled in. This drives
# `Project.approved` and the "these went in blank" note returned on submission.
# It is deliberately NOT a submission gate: a lead may submit an incomplete
# proposal, and the only thing that can refuse a submission is the smeta cap.
REQUIRED_PROJECT_FIELDS = [
    'project_name', 'project_purpose', 'project_annotation',
    'project_key_words', 'project_scientific_idea', 'project_structure',
    'team_characterization', 'project_monitoring', 'project_requirements',
    'project_deadline', 'collaborator_limit', 'max_smeta_amount', 'priotet'
]

# Azerbaijani labels, so a rejection names the fields the way the form does.
PROJECT_FIELD_LABELS = {
    'project_name': 'Layihənin adı',
    'project_purpose': 'Layihənin məqsədi',
    'project_annotation': 'Layihənin annotasiyası',
    'project_key_words': 'Açar sözlər',
    'project_scientific_idea': 'Elmi ideya',
    'project_structure': 'Layihənin strukturu',
    'team_characterization': 'Komandanın xarakteristikası',
    'project_monitoring': 'Monitorinq',
    'project_requirements': 'Layihənin tələbləri',
    'project_assessment': 'Qiymətləndirmə',
    'project_deadline': 'Layihənin müddəti',
    'collaborator_limit': 'İcraçı sayı',
    'max_smeta_amount': 'Maksimum smeta məbləği',
    'priotet': 'Layihə prioriteti',
}


def missing_project_fields(project):
    """Required fields that are still empty, in form order.

    Whitespace-only text counts as empty: a space typed into a textarea is not
    a filled-in proposal.
    """
    missing = []
    for field in REQUIRED_PROJECT_FIELDS:
        value = getattr(project, field, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def generate_unique_project_code():
    while True:
        code = random.randint(10000000, 99999999)
        if not Project.query.filter_by(project_code=code).first():
            return code


def resolve_writable_project(fin_kod, project_code=None):
    """Find the project the caller is allowed to write to.

    Without `project_code` this is the caller's project in the ACTIVE
    competition — the historical behaviour, unchanged. With a `project_code`
    an ARCHIVED project may also be targeted, but only when an admin has
    unlocked it for editing (`edit_unlocked`).

    Returns `(project, error)`; `error` is a ready-to-return Flask response
    tuple when the request must be refused, otherwise None. A None project
    with a None error means "nothing found for this fin_kod" and is left to
    the caller to phrase.
    """
    if project_code is None:
        active_id = Competition.get_active_id()
        return Project.query.filter_by(fin_kod=fin_kod, competition_id=active_id).first(), None

    # The clients hold the code as a string in places; the column is an INTEGER.
    try:
        project_code = int(project_code)
    except (TypeError, ValueError):
        return None, ({'error': 'project_code must be a number.'}, 400)

    project = Project.query.filter_by(project_code=project_code).first()
    if not project:
        return None, ({'error': 'Project not found for the provided project_code.'}, 404)

    # A lead only ever touches their own row; admins act on any project.
    # The identity comes from the TOKEN — a body-supplied fin_kod would let a
    # lead address someone else's project by naming its owner.
    if g.user.get('role') != 2 and project.fin_kod != g.user.get('fin_kod'):
        return None, ({'error': 'This project belongs to another user.'}, 403)

    if project_is_archived(project) and not project.edit_unlocked:
        return None, ({'error': ARCHIVE_LOCKED_MESSAGE, 'status': 403}, 403)

    return project, None

def body_fin_error(fin_kod):
    """Refuse a request whose body names someone else.

    Several project writes take the lead's `fin_kod` from the JSON body. A lead
    may only ever act as themselves — otherwise any lead could update or DELETE
    another lead's project just by naming them. Admins may act for anyone.
    """
    if g.user.get('role') != 2 and fin_kod != g.user.get('fin_kod'):
        return {'error': 'You can only act on your own project.', 'status': 403}, 403
    return None


def minimal_project_card(project, lead=None):
    """The public-to-participants view of a project (finding B-M3): just enough
    for the browse-and-apply list, with none of the proposal body, budget,
    internal flags or other people's identifiers. Full detail is reserved for
    admins, the lead, approved members and the assigned expert.
    """
    lead = lead if lead is not None else User.query.filter_by(fin_kod=project.fin_kod).first()
    team_size = Collaborator.query.filter_by(project_code=project.project_code).count()
    limit = project.collaborator_limit or 0
    priotet = Priotet.query.filter_by(prioritet_code=project.priotet).first() if project.priotet else None
    return {
        'project_code': project.project_code,
        'project_name': project.project_name,
        'description': project.project_annotation or project.project_purpose,
        'priotet_name': priotet.prioritet_name if priotet else None,
        'winner': bool(project.winner),
        'user': {'name': lead.name, 'surname': lead.surname} if lead else None,
        'collaborator_limit': limit,
        'current_collaborators': team_size,
        'free_slots': max(0, limit - team_size),
        # So the caller's own project is still recognisable in the list.
        'is_mine': project.fin_kod == g.user.get('fin_kod'),
    }


def full_project_row(project):
    """The full detail row (admins only), with the lead's display name attached."""
    data = project.project_detail()
    lead = User.query.filter_by(fin_kod=project.fin_kod).first()
    data['user'] = {'name': lead.name, 'surname': lead.surname} if lead else None
    return data


@project_offer.route('/api/save/project', methods=['POST'])
@limiter.limit("100 per second")
@token_required([0, 2])
def save_project():
    current_app.logger.info("POST /api/save/project called")
    data = request.get_json(silent=True) or {}
    fin_kod = data.get('fin_kod')

    if not fin_kod:
        current_app.logger.warning("Missing fin_kod in request")
        return handle_missing_field(404)

    error = body_fin_error(fin_kod)
    if error:
        return error

    # An explicit project_code targets one specific project — that is how an
    # unlocked ARCHIVED project is edited. Never auto-create in that mode.
    project_code = data.get('project_code')
    if project_code is not None:
        project, error = resolve_writable_project(fin_kod, project_code)
        if error:
            return error
        # A submitted proposal is frozen until an admin returns it (B-L7).
        locked = submitted_lock_error(project)
        if locked:
            return locked
        current_app.logger.info(f"Updating project_code={project_code} (explicit target)")
    else:
        # Scope to the ACTIVE competition so a returning user creates a NEW project
        # each season instead of overwriting last year's row.
        active = Competition.get_active()
        active_id = active.id if active else None

        # The application window must be open to create or edit this season's
        # proposal (B-L7). Admins are exempt.
        dl_error = deadline_error(competition_id=active_id)
        if dl_error:
            return dl_error

        project = Project.query.filter_by(fin_kod=fin_kod, competition_id=active_id).first()
        if not project:
            current_app.logger.info(f"No project for fin_kod={fin_kod} in active competition, creating new one.")
            project = Project(
                fin_kod=fin_kod,
                project_code=generate_unique_project_code(),
                competition_id=active_id
            )
            # Snapshot the competition's limits onto the project.
            if active:
                project.collaborator_limit = active.collaborator_limit
                project.max_smeta_amount = active.max_smeta_amount
            db.session.add(project)
        else:
            locked = submitted_lock_error(project)
            if locked:
                return locked
            current_app.logger.info(f"Updating existing project with fin_kod={fin_kod} in active competition")

    for field in [
        'project_name', 'project_purpose', 'project_annotation',
        'project_key_words', 'project_scientific_idea', 'project_structure',
        'team_characterization', 'project_monitoring', 'project_requirements',
        # `collaborator_limit` and `max_smeta_amount` are deliberately NOT here:
        # they come only from the active competition and only an admin may change
        # them (finding B-H1). A lead writing them could raise their own cap.
        'project_assessment', 'priotet'
    ]:
        if field in data:
            setattr(project, field, data[field])

    if 'project_deadline' in data:
        try:
            project.project_deadline = datetime.strptime(data['project_deadline'], '%Y-%m-%d')
        except ValueError:
            return {'error': 'Invalid date format. Use YYYY-MM-DD.'}, 400

    project.approved = 0 if missing_project_fields(project) else 1
    current_app.logger.info(f"Project approved={project.approved}")

    db.session.commit()

    # The code is returned so a form that started without one (a brand-new
    # project is created by this very call) can address the row from now on.
    if project.approved == 1:
        current_app.logger.info("Project fully submitted and approved=1.")
        return {
            'message': 'Project fully submitted and approved=1.',
            'project_code': project.project_code,
            'approved': project.approved,
        }, 200
    else:
        current_app.logger.info("Project draft saved with approved=0.")
        return {
            'message': 'Project draft saved with approved=0.',
            'project_code': project.project_code,
            'approved': project.approved,
        }, 200
    
def serialize_project(project):
    return {
        'project_code': project.project_code,
        'fin_kod': project.fin_kod,
        'project_name': project.project_name,
        'project_purpose': project.project_purpose,
        'project_annotation': project.project_annotation,
        'project_key_words': project.project_key_words,
        'project_scientific_idea': project.project_scientific_idea,
        'project_structure': project.project_structure,
        'team_characterization': project.team_characterization,
        'project_monitoring': project.project_monitoring,
        'project_requirements': project.project_requirements,
        'project_assessment': project.project_assessment,
        'project_deadline': project.project_deadline.strftime('%Y-%m-%d') if project.project_deadline else None,
        'approved': project.approved
    }

@project_offer.route("/api/approve_project", methods=['POST'])
@limiter.limit("100 per second")
@token_required([2])
def approve_project():
    # Admin-only (finding B-M4). `approved` is otherwise an automatic
    # "form complete" flag maintained by save_project; a lead must not be able
    # to set it by hand and thereby mark their own proposal approved.
    try:
        project_details = request.get_json(silent=True) or {}

        fin_kod = project_details.get('fin_kod')
        # The form starts with an empty project_code and only learns the real
        # one after the first save; treat "" as "not supplied" so the lookup
        # falls back to this user's project in the active competition instead
        # of asking Postgres to compare an INTEGER against ''.
        project_code = project_details.get('project_code') or None

        error = body_fin_error(fin_kod)
        if error:
            return error

        user = Auth.query.filter_by(fin_kod=fin_kod).first()

        if not user:
            return {'error': 'User not found.', 'status': 404}, 404

        project, error = resolve_writable_project(fin_kod, project_code)
        if error:
            return error

        if not project:
            return {'error': 'Project not found for the provided fin_kod.', 'status': 404}, 404

        user_profile = User.query.filter_by(fin_kod=fin_kod).first()
        if not user_profile:
            return {'error': 'User profile not found.', 'status': 404}, 404

        profile_approved = user_profile.profile_completed

        if not profile_approved:
            return {'error': 'User profile is not completed.', 'status': 403}, 403

        project.approved = 1
        db.session.commit()

        return {'message': 'Project approved successfully.'}, 200

    except Exception as e:
        return handle_global_exception(str(e))


@project_offer.route("/api/project/return-for-revision", methods=['POST'])
@limiter.limit("100 per second")
@token_required([2])
def return_project_for_revision():
    """Admin-only: send a submitted proposal back to its lead for corrections.

    The note is mandatory — the whole point is telling the lead what to fix —
    and it reaches them three ways: on the project page, as a dashboard
    notification, and by e-mail.
    """
    try:
        data = request.get_json() or {}

        try:
            project_code = int(data.get('project_code'))
        except (TypeError, ValueError):
            return {'error': 'project_code must be a number.', 'status': 400}, 400

        note = (data.get('note') or '').strip()
        if not note:
            return {
                'error': 'Qeyd yazılmalıdır — layihə rəhbəri nəyi düzəltməli olduğunu bilməlidir.',
                'status': 400
            }, 400

        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return {'error': 'Layihə tapılmadı.', 'status': 404}, 404

        if not project.submitted:
            return {
                'error': 'Bu layihə təqdim edilməyib, geri qaytarmaq mümkün deyil.',
                'status': 409
            }, 409

        project.submitted = False
        project.revision_note = note
        project.returned_at = datetime.utcnow()
        project.returned_by = g.user.get('fin_kod')
        db.session.commit()

        lead = User.query.filter_by(fin_kod=project.fin_kod).first()
        project_name = project.project_name or 'Adsız layihə'

        # In-platform notification. Best-effort: the project is already back in
        # the lead's hands and must not be un-returned by a messaging failure.
        try:
            create_notification(
                recipient_fin_kod=project.fin_kod,
                title='Layihəniz düzəliş üçün geri qaytarıldı',
                body=f"'{project_name}' layihəsi düzəliş üçün geri qaytarıldı. Qeyd: {note}",
                type='general',
                link='/project-offer',
            )
        except Exception:
            current_app.logger.exception('Could not notify %s about the return', project.fin_kod)

        email_sent = False
        try:
            recipient = (lead.work_email or lead.personal_email) if lead else None
            if recipient:
                html = render_template(
                    'email/project_returned_template.html',
                    project=project,
                    lead_name=f"{lead.name or ''} {lead.surname or ''}".strip(),
                    note=note,
                    login_url=f"{current_app.config.get('FRONTEND_URL', 'http://e-grant.aztu.edu.az').rstrip('/')}/project-offer",
                )
                email_sent = send_email('Layihə düzəliş üçün geri qaytarıldı', recipient, html)
        except Exception:
            current_app.logger.exception('Could not e-mail %s about the return', project.fin_kod)

        return handle_success({
            'project_code': project.project_code,
            'submitted': False,
            'revision_note': note,
            'returned_at': project.returned_at.isoformat(),
            'returned_by': project.returned_by,
            'email_sent': bool(email_sent),
        }, 'Layihə düzəliş üçün geri qaytarıldı.')

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('return_project_for_revision failed')
        return handle_global_exception(str(e))


@project_offer.route("/api/project/winner", methods=['POST'])
@limiter.limit("100 per second")
@token_required([2])
def set_project_winner():
    """Admin-only: mark / unmark a project as a competition winner."""
    try:
        data = request.get_json() or {}

        project_code = data.get('project_code')
        if project_code is None:
            return handle_missing_field('project_code')

        # `winner` is optional; when omitted the flag is toggled.
        winner_value = data.get('winner')

        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return handle_specific_not_found('Project not found.')

        if winner_value is None:
            new_state = not bool(project.winner)
        else:
            new_state = bool(winner_value)

        project.winner = new_state
        project.winner_at = datetime.utcnow() if new_state else None
        db.session.commit()

        return handle_success(project.project_detail(), 'Project winner status updated.')
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@project_offer.route("/api/project/archive/edit-access", methods=['POST'])
@limiter.limit("100 per second")
@token_required([2])
def set_archive_edit_access():
    """Admin-only: open / close an ARCHIVED project so its owner can edit it.

    `unlocked` is optional; when omitted the flag is toggled."""
    try:
        data = request.get_json() or {}

        project_code = data.get('project_code')
        if project_code is None:
            return handle_missing_field('project_code')

        try:
            project_code = int(project_code)
        except (TypeError, ValueError):
            return {'error': 'project_code must be a number.'}, 400

        project = Project.query.filter_by(project_code=project_code).first()
        if not project:
            return {'error': 'Project not found for the provided project_code.', 'status': 404}, 404

        # The active competition is editable by its own rules — there is
        # nothing to unlock there, and unlocking it would be misleading.
        if not project_is_archived(project):
            return {
                'error': 'This project belongs to the active competition, not the archive.',
                'status': 409
            }, 409

        unlocked_value = data.get('unlocked')
        new_state = (not bool(project.edit_unlocked)) if unlocked_value is None else bool(unlocked_value)

        project.edit_unlocked = new_state
        project.edit_unlocked_at = datetime.utcnow() if new_state else None
        project.edit_unlocked_by = g.user.get('fin_kod') if new_state else None
        db.session.commit()

        message = 'Archived project unlocked for editing.' if new_state else 'Archived project locked again.'
        return handle_success(project.project_detail(), message)
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@project_offer.route("/api/archive/project/<int:project_code>", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 2])
def get_archived_project_for_edit(project_code):
    """The owner's (or an admin's) view of an archived project that has been
    unlocked — the payload backing the archive edit form."""
    try:
        fin_kod = g.user.get('fin_kod')
        project, error = resolve_writable_project(fin_kod, project_code)
        if error:
            return error

        priotet_obj = Priotet.query.filter_by(prioritet_code=project.priotet).first()
        competition = Competition.query.filter_by(id=project.competition_id).first()

        data = project.project_detail()
        data['priotet_name'] = priotet_obj.prioritet_name if priotet_obj else None
        data['competition_year'] = competition.year if competition else None
        data['competition_code'] = competition.code if competition else None
        data['archived'] = project_is_archived(project)

        return handle_success(data, 'Archived project fetched successfully.')
    except Exception as e:
        return handle_global_exception(str(e))


@project_offer.route('/api/my-project-history', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def my_project_history():
    """Every project the signed-in user has been part of across ALL competitions
    — as lead (owner) and as member (collaborator). Read-only, so a lead who
    later becomes a member still sees their past projects in the profile."""
    try:
        fin_kod = g.user.get('fin_kod')
        competitions = {c.id: c for c in Competition.query.all()}
        active_id = Competition.get_active_id()

        def comp_info(cid):
            c = competitions.get(cid)
            return {
                'competition_year': c.year if c else None,
                'competition_code': c.code if c else None,
                'archived': active_id is not None and cid != active_id,
            }

        history = []

        for p in Project.query.filter_by(fin_kod=fin_kod).all():
            info = comp_info(p.competition_id)
            history.append({
                'project_code': p.project_code,
                'project_name': p.project_name,
                'role': 'lead',
                'approved': p.approved,
                'submitted': bool(p.submitted),
                'winner': bool(p.winner),
                # Only a lead edits, and only once an admin unlocked the archived row.
                'editable': info['archived'] and bool(p.edit_unlocked),
                **info,
            })

        for col in Collaborator.query.filter_by(fin_kod=fin_kod).all():
            proj = Project.query.filter_by(project_code=col.project_code).first()
            history.append({
                'project_code': col.project_code,
                'project_name': proj.project_name if proj else None,
                'role': 'member',
                'approved': proj.approved if proj else None,
                'submitted': bool(proj.submitted) if proj else None,
                'winner': bool(proj.winner) if proj else None,
                'editable': False,
                **comp_info(col.competition_id or (proj.competition_id if proj else None)),
            })

        history.sort(key=lambda x: (x.get('competition_year') or 0), reverse=True)
        return handle_success(history, 'Project history fetched successfully.')
    except Exception as e:
        return handle_global_exception(str(e))


@project_offer.route('/api/projects', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def get_projects():
    current_app.logger.info("GET /api/projects called")
    try:
        project_list = []
        # Only the ACTIVE competition's projects appear in the main list.
        # Previous competitions live in the admin-only archive.
        active_id = Competition.get_active_id()
        if active_id is not None:
            projects = Project.query.filter_by(competition_id=active_id).all()
        else:
            projects = Project.query.all()

        if not projects:
            current_app.logger.warning("No projects found in database")
            return handle_specific_not_found('No project found.')

        # Admins get the full rows; everyone else gets the minimal browse card
        # only (finding B-M3) — the full proposal, budget and internal flags of
        # another lead's project are not theirs to read from the list.
        admin = is_admin()
        for project in projects:
            project_list.append(full_project_row(project) if admin else minimal_project_card(project))

        current_app.logger.info(f"Returning {len(project_list)} projects")
        return handle_success(project_list, 'Projects fetched successfully.')
    except Exception as e:
        current_app.logger.error(f"Exception in /api/projects: {e}", exc_info=True)
        return handle_global_exception(str(e))

# new submitted users api

@project_offer.route('/api/projects/submitted', methods=['GET'])
@limiter.limit("100 per second")
@token_required([2])
def get_projects_submitted():
    current_app.logger.info("GET /api/projects called")
    try:
        project_list = []
        # Only the ACTIVE competition's submitted projects.
        active_id = Competition.get_active_id()
        query = Project.query.filter_by(submitted=True)
        if active_id is not None:
            query = query.filter_by(competition_id=active_id)
        projects = query.all()

        if not projects:
            current_app.logger.warning("No projects found in database")
            return handle_specific_not_found('No project found.')

        for project in projects:
            project_data = project.project_detail()
            fin_kod = project_data.get('fin_kod')
            user = User.query.filter_by(fin_kod=fin_kod).first()

            if user:
                project_data['user'] = {
                    'name': user.name,
                    'surname': user.surname
                }
            else:
                project_data['user'] = None

            project_list.append(project_data)

        current_app.logger.info(f"Returning {len(project_list)} projects")
        return handle_success(project_list, 'Projects fetched successfully.')
    except Exception as e:
        current_app.logger.error(f"Exception in /api/projects: {e}", exc_info=True)
        return handle_global_exception(str(e))


@project_offer.route('/api/projects/archive', methods=['GET'])
@limiter.limit("100 per second")
@token_required([2])
def get_projects_archive():
    """Admin-only: all projects from PREVIOUS (non-active) competitions."""
    current_app.logger.info("GET /api/projects/archive called")
    try:
        active_id = Competition.get_active_id()
        competitions = {c.id: c for c in Competition.query.all()}

        query = Project.query
        if active_id is not None:
            query = query.filter(Project.competition_id != active_id)
        projects = query.all()

        project_list = []
        for project in projects:
            data = project.project_detail()
            user = User.query.filter_by(fin_kod=data.get('fin_kod')).first()
            data['user'] = {'name': user.name, 'surname': user.surname} if user else None
            comp = competitions.get(project.competition_id)
            data['competition_year'] = comp.year if comp else None
            data['competition_code'] = comp.code if comp else None
            project_list.append(data)

        project_list.sort(key=lambda x: (x.get('competition_year') or 0), reverse=True)
        return handle_success(project_list, 'Archived projects fetched successfully.')
    except Exception as e:
        current_app.logger.error(f"Exception in /api/projects/archive: {e}", exc_info=True)
        return handle_global_exception(str(e))


@project_offer.route("/api/project/<string:fin_kod>")
@limiter.limit("100 per second")
@token_required([0 ,1, 2])
def get_project_by_fin_kod(fin_kod):
    try:
        # Your own proposal only (admins may look up anyone's).
        if g.user.get('role') != 2 and fin_kod != g.user.get('fin_kod'):
            return {'error': 'You can only read your own project.', 'status': 403}, 403

        user = Auth.query.filter_by(fin_kod=fin_kod).first()

        if not user:
            return handle_specific_not_found('User not found.')
        
        active_id = Competition.get_active_id()
        project = Project.query.filter_by(fin_kod=fin_kod, competition_id=active_id).first()

        # A user who has not started a proposal this season has no row yet —
        # that is an empty form, not a server error.
        if not project:
            return {'error': 'No project for this user in the active competition.', 'status': 404}, 404

        return handle_success(project.project_detail(), 'Project fetched successfully')
    except Exception as e:
        return handle_global_exception(str(e))
    
@project_offer.route("/api/project/<int:project_code>", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2, 3])
def project_by_project_code(project_code):
    try:
        project, error = project_read_guard(project_code)
        if error:
            return error
        
        priotet_obj = Priotet.query.filter_by(prioritet_code=project.priotet).first()
        priotet_name = priotet_obj.prioritet_name if priotet_obj else None

        project_data = project.project_detail()
        project_data["priotet_name"] = priotet_name

        return handle_success(project_data, "Project data fetched successfully.")
    
    except Exception as e:
        return handle_global_exception(str(e))

@project_offer.route('/api/upd/project', methods=['PATCH'])
@limiter.limit("100 per second")
@token_required([0, 2])
def update_project_offer():
    data = request.get_json(silent=True) or {}

    fin_kod = data.get('fin_kod')
    if not fin_kod:
        return {'error': 'fin_kod field is required to update a project.'}, 400

    error = body_fin_error(fin_kod)
    if error:
        return error

    # With a project_code an unlocked ARCHIVED project may be targeted too.
    project, error = resolve_writable_project(fin_kod, data.get('project_code'))
    if error:
        return error
    if not project:
        return {'error': 'Project not found for the provided fin_kod.'}, 404

    # Frozen once submitted, until an admin returns it (B-L7).
    locked = submitted_lock_error(project)
    if locked:
        return locked

    updatable_fields = [
        'project_name', 'project_purpose', 'project_annotation',
        'project_key_words', 'project_scientific_idea', 'project_structure',
        'team_characterization', 'project_monitoring', 'project_requirements',
        # `collaborator_limit` / `max_smeta_amount` intentionally excluded (B-H1).
        'project_assessment', 'project_deadline'
    ]

    for field in updatable_fields:
        if field in data:
            if field == 'project_deadline':
                try:
                    setattr(project, field, datetime.strptime(data[field], '%Y-%m-%d'))
                except ValueError:
                    return {'error': 'Invalid date format for project_deadline. Use YYYY-MM-DD.'}, 400
            else:
                setattr(project, field, data[field])

    db.session.commit()

    return {'message': 'Project successfully updated.'}, 200



@project_offer.route('/api/delete/project', methods=['DELETE'])
@limiter.limit("100 per second")
@token_required([0, 2])
def delete_project_offer():
    data = request.get_json(silent=True) or {}
    fin_kod = data.get('fin_kod')

    if not fin_kod:
        return {'error': 'fin_kod parameter is required.'}, 400

    error = body_fin_error(fin_kod)
    if error:
        return error

    # With a project_code an unlocked ARCHIVED project may be deleted too.
    project, error = resolve_writable_project(fin_kod, data.get('project_code'))
    if error:
        return error

    if not project:
        return {'error': 'Project not found for the provided fin_kod.'}, 404

    # A lead cannot delete a submitted proposal; an admin must return it first
    # (or delete it themselves) (B-L7).
    locked = submitted_lock_error(project)
    if locked:
        return locked

    # Approved olanların silinmemesi ucun, isteye gore bunu acariq
    # if project.approved == 1:
    #     return {'error': 'Approved projects cannot be deleted.'}, 403

    # Everything hanging off the project goes with it — team, activities,
    # smeta, files, reports. Nothing here is tied by a database foreign key,
    # so without this the children simply outlive their parent; an orphaned
    # collaborator row would even keep occupying its owner's competition slot.
    try:
        removed = delete_project_cascade(project.project_code)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete project %s", project.project_code)
        return {'error': 'Project could not be deleted.'}, 500

    return {
        'message': 'Project successfully deleted.',
        'removed': removed,
        'removed_collaborators': removed.get('collaborators', 0)
    }, 200

@project_offer.route("/api/project-details/<int:project_code>", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2, 3])
def get_project_details_by_project_code(project_code):

    try:
        
        # Admins, the lead, the team and the assigned expert only.
        project, error = project_read_guard(project_code)
        if error:
            return error

        project_owner_fin_kod = project.fin_kod

        project_owner = User.query.filter_by(fin_kod=project_owner_fin_kod).first()

        collaborator_list = []

        collaborators = Collaborator.query.filter_by(project_code=project_code).all()

        for collaborator in collaborators:

            collaborator_details = User.query.filter_by(fin_kod=collaborator.fin_kod).first()

            collaborator_data = {
                "name": collaborator_details.name,
                "surname": collaborator_details.surname,
                "father_name": collaborator_details.father_name,
                "fin_kod": collaborator_details.fin_kod,
                "image": collaborator_details.get_user_image()
            }

            collaborator_list.append(collaborator_data)

        project_smeta_salary_list = []

        preoject_smeta_salaries = Salary.query.filter_by(project_code=project_code).all()

        for salary_smeta in preoject_smeta_salaries:

            project_smeta_salary_list.append(salary_smeta.salary_details())
        
        project_data = {
            "project_owner": {
                "name": project_owner.name,
                "surname": project_owner.surname,
                "father_name": project_owner.father_name,
                "fin_kod": project_owner_fin_kod
            },
            "collaborators": collaborator_list,
            "project_details": project.project_detail(),
            "project_saalry_smeta": project_smeta_salary_list
        }
        
        return handle_success(project_data, "Project data fetched successfully")
    
    except Exception as e:
        return handle_global_exception(str(e))


@project_offer.route("/api/submit-project", methods=['POST'])
@limiter.limit("100 per second")
@token_required([0, 2])
def submit_project():
    data = request.get_json()
    project_code = data.get('project_code')

    if not project_code:
        return {'error': 'project_code field is required.'}, 400

    # Submitting is a write on somebody's proposal, so it goes through the same
    # ownership and archive-lock check as every other write. Without this any
    # lead could submit another lead's project just by quoting its code.
    project, error = resolve_writable_project(g.user.get('fin_kod'), project_code)
    if error:
        return error

    if not project:
        return {'error': 'Project not found for the provided project_code.'}, 404

    # Enforce the application deadline on the server (B-L7): once the
    # competition's window has closed, a lead can no longer submit.
    dl_error = deadline_error(project)
    if dl_error:
        return dl_error

    # Submission is deliberately permissive about EMPTY categories, but the
    # total is checked against the cap. The grand total is RECOMPUTED here from
    # the line-item tables (utils/smeta), never read from the stored aggregate —
    # a lead could otherwise have written a small aggregate and slipped an
    # over-budget proposal through (finding B-H1).
    total_amount = project_grand_total(project.project_code)
    db.session.commit()

    # The cap comes only from the competition (snapshotted on the project).
    max_amount = project.max_smeta_amount or 50000
    if total_amount > max_amount:
        return {
            "status": 409,
            "error": f"Smeta məbləği {max_amount} AZN limitini aşır.",
            "message": f"Total amount is over {max_amount}",
            "total_amount": total_amount,
            "max_amount": max_amount,
        }, 409

    project.submitted = True
    project.submitted_at = datetime.utcnow()

    was_returned = bool(project.returned_at)
    if was_returned:
        # Handing it in again answers the return. `revision_note` is kept as a
        # record of what was asked for; `returned_at` is what marks it open.
        project.returned_at = None

        try:
            notify_admins(
                title='Düzəldilmiş layihə yenidən təqdim edildi',
                body=f"'{project.project_name or 'Adsız layihə'}' layihəsi düzəlişdən sonra yenidən təqdim edildi.",
                type='general',
                link='/projects/submitted',
            )
        except Exception:
            current_app.logger.exception('Could not notify admins about the resubmission')

    db.session.commit()

    # Empty fields do not block the submission, but the lead is told which ones
    # went in blank so it is a choice rather than an accident.
    incomplete = missing_project_fields(project)

    return {
        'message': 'Project successfully submitted.',
        'total_amount': total_amount,
        'max_amount': max_amount,
        'incomplete_fields': incomplete,
        'incomplete_labels': [PROJECT_FIELD_LABELS.get(f, f) for f in incomplete],
        'was_resubmission': was_returned,
    }, 200

@project_offer.route("/api/col-project/<string:fin_kod>")
@limiter.limit("100 per second")
@token_required([0, 1])
def collaborator_projet(fin_kod):
    # Read your OWN memberships only, and only for the ACTIVE competition — the
    # same resolution sign-in uses, so a past season's row cannot resurface as
    # "the project I work on". A lead may be an executor somewhere too, hence
    # role 0 is allowed in.
    if fin_kod != g.user.get('fin_kod'):
        return {'error': 'You can only read your own project.'}, 403

    active_id = Competition.get_active_id()
    collaborations = Collaborator.query.filter_by(
        fin_kod=fin_kod, competition_id=active_id, approved=True
    ).all()

    if not collaborations:
        return {'error': 'Collaborator not found'}, 404

    return {
        'status': 200,
        'message': "Project codes fetched successfully.",
        # `project_code` is the first one, kept for clients written when a
        # person could only ever be on a single team.
        'project_code': collaborations[0].project_code,
        'project_codes': [c.project_code for c in collaborations],
    }, 200

@project_offer.route("/api/project-owner/<int:project_code>")
@limiter.limit("100 per second")
@token_required([0, 1, 2, 3])
def get_project_owner(project_code):
    project, error = project_read_guard(project_code)
    if error:
        return error

    owner_fin_kod = project.fin_kod
    owner = User.query.filter_by(fin_kod=owner_fin_kod).first()

    if not owner:
        return {
            "status": 404,
            "message": "No user found."
        }, 404
    
    return {
        "status": 200,
        "message": "Owner fetched successfully.",
        "owner_data": {
            "name": owner.name,
            "surname": owner.surname,
            "father_name": owner.father_name,
            "fin_kod": owner.fin_kod,
            "project_role": owner.work_location,
            "image": owner.get_user_image()
        }
    }, 200


# pdf export new

from io import BytesIO
from flask import make_response
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import A4
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

@project_offer.route("/api/project-pdf/<int:project_code>", methods=["GET"])
@limiter.limit("100 per second")
@token_required([0, 1, 2, 3])
def download_pdf(project_code):
    # Register the local Noto Sans font (supports Azerbaijani letters)
    font_name = "NotoSans"
    try:
        # Use local path for NotoSans-Regular.ttf
        font_path = "./utils/noto_sans/static/NotoSans-Regular.ttf"
        pdfmetrics.registerFont(TTFont(font_name, font_path))
    except Exception as e:
        return {
            "status": 500,
            "message": "Report could not be generated."
        }, 500

    # The dossier contains the whole proposal, budget and the team's FIN codes:
    # admins, the lead, the team and the assigned expert only.
    project, error = project_read_guard(project_code)
    if error:
        return error

    # smeta logic to get total and each smeta values
    main_smeta = Smeta.query.filter_by(project_code=str(project_code)).first()
    if not main_smeta:
        main_smeta = type("EmptySmeta", (), {
            "total_salary": 0,
            "total_equipment": 0,
            "total_fee": 0,
            "defense_fund": 0,
            "total_services": 0,
            "total_rent": 0,
            "other_expenses": 0
        })()

    total_main_amount = sum([
        main_smeta.total_salary or 0,
        main_smeta.total_equipment or 0,
        main_smeta.total_fee or 0,
        main_smeta.defense_fund or 0,
        main_smeta.total_services or 0,
        main_smeta.total_rent or 0,
        main_smeta.other_expenses or 0
    ])

    # equipment smeta
    subject_smeta = SubjectOfPurchase.query.filter_by(project_code=project_code).all()

    # service smeta
    service_smeta = ServicesOfPurchase.query.filter_by(project_code=project_code).all()

    # rent smeta
    rent_smeta = Rent.query.filter_by(project_code=project_code).all()

    # other expenses smeta
    other_exps = other_exp_model.query.filter_by(project_code=project_code).all()

    # "max_amount_error": max_amount_error

    # project activity query
    activities = ProjectActivities.query.filter_by(project_code=project_code).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    # All styles use NotoSans font for Unicode Azerbaijani support
    heading1 = ParagraphStyle(
        "Heading1Custom",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=18,
        alignment=1,  # center
        spaceAfter=12,
    )
    heading2 = ParagraphStyle(
        "Heading2Custom",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=14,
        alignment=1,  # center
        spaceAfter=12,
    )
    title_style = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=12,
        alignment=1,  # center
        spaceAfter=12,
    )
    table_heading_style = ParagraphStyle(
        "TableHeadingCustom",
        fontName=font_name,
        fontSize=11,
        alignment=1,  # center
        leading=14,
    )
    table_content_style = ParagraphStyle(
        "TableContentCustom",
        fontName=font_name,
        fontSize=11,
        alignment=0,  # left
        leading=14,
        wordWrap='CJK',
    )

    elements = []

    # The emblem is read from a local copy when one is installed
    # (utils/assets/emblem.png); otherwise it is fetched with a short timeout,
    # and the PDF is still produced without it if that fails — an external
    # host must never be able to hang or break contract generation.
    emblem = None
    local_emblem = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'utils', 'assets', 'emblem.png')
    try:
        if os.path.isfile(local_emblem):
            with open(local_emblem, 'rb') as fh:
                emblem = BytesIO(fh.read())
        else:
            response = requests.get("https://imgs.search.brave.com/vbEBGTiOqsEBji5vMQfxvvJJtCHIrwqwPFMgdQ6D22M/rs:fit:860:0:0:0/g:ce/aHR0cHM6Ly9pbWFn/ZXMuc2Vla2xvZ28u/Y29tL2xvZ28tcG5n/LzMxLzEvYXplcmJh/aWphbi1nZXJiLWxv/Z28tcG5nX3NlZWts/b2dvLTMxODE0MC5w/bmc", timeout=5)
            if response.ok and response.headers.get('Content-Type', '').startswith('image/'):
                emblem = BytesIO(response.content)
    except Exception:
        current_app.logger.warning("PDF emblem unavailable; generating the PDF without it")
    if emblem is not None:
        elements.append(RLImage(emblem, width=2*inch, height=2*inch))
        elements.append(Spacer(1, 12))

    text_under_image = "AZƏRBAYCAN TEXNİKİ UNİVERSİTETİ (AzTU) daxili qrant müsabiqəsi"
    elements.append(Paragraph(text_under_image, heading1))
    elements.append(Spacer(1, 12))

    heading_2 = "Azərbaycan Texniki Universiteti (AzTU) elmi-tədqiqat işlərinin və innovasiyaların dəstəklənməsi və inkşafı məqsədilə daxili qrant müsabiqəsi"
    elements.append(Paragraph(heading_2, heading2))
    elements.append(Spacer(1, 12))

    # Source the competition identity from the project's competition instead of
    # hardcoded 2025 values, so each season's PDFs/contracts are correct.
    competition = Competition.query.get(project.competition_id) if project.competition_id else None
    comp_code = competition.code if competition else "AzTU-DQL-2025"
    comp_year = competition.year if competition else 2025
    comp_contract = (
        competition.contract_date.strftime('%d.%m.%Y')
        if (competition and competition.contract_date)
        else f"01 dekabr {comp_year}-ci il"
    )

    heading_56789 = f"({comp_code}) qalibi olmuş"
    elements.append(Paragraph(heading_56789, heading2))
    elements.append(Spacer(1, 12))

    heading_09876 = "Layihənin yerinə yetirilməsi haqqında" 
    elements.append(Paragraph( heading_09876, heading2))
    elements.append(Spacer(1, 12))
    
    heading_56745788 = "Azərbaycan Texniki Universiteti (AzTU) ilə Layihə rəhbəri arasında bağlanılmış" 
    elements.append(Paragraph(heading_56745788, heading2))
    elements.append(Spacer(1, 12))

    heading_90 = f"Müqavilə № {comp_code}-M01/{project_code}"
    elements.append(Paragraph(heading_90, heading2))
    elements.append(Spacer(1, 12))

    heading_915678 = "Əlavə-1"
    elements.append(Paragraph(heading_915678, heading2))
    elements.append(Spacer(1, 12))

    elements.append(HRFlowable(width="100%", thickness=1, lineCap='round', color=colors.black, spaceBefore=6, spaceAfter=6))
    elements.append(Spacer(1, 12))

    heading_912345 = "Bakı şəhəri"
    elements.append(Paragraph(heading_912345, heading2))
    elements.append(Spacer(1, 12))

    heading_23456 = comp_contract
    elements.append(Paragraph(heading_23456, heading2))
    elements.append(Spacer(1, 12))

    project_fields = [
        ("1. Layihə adı", project.project_name),
        ("2. Layihənin məqsədi, qarşıya qoyulan məsələlərin, aktuallığının əsaslandırılması (2-5 səhifə) Layihənin məqsədini ifadə edin. Layihədə həllinə çalışmaq istədiyiniz problemi (məsələni) təsvir edin. Problemin elmi-tədqiqatın inkişafı üçün aktual olduğunu əsaslandırın.", project.project_purpose),
        ("3. Layihənin annotasiyası (0,5-1 səhifə)", project.project_annotation),
        ("4. Layihənin məzmununu tam əks etdirən açar sözlər Layihədə əsas açar sözləri qeyd edin.", project.project_key_words),
        ("5. Layihənin elmi ideyası; (1-2 səhifə)", project.project_scientific_idea),
        ("6. Layihə üzrə tədqiqatın strukturu  (1-2 səhifə) (işin planı, mərhələləri və tədqiqat üsulları göstərilməlidir)", project.project_structure),
        ("7. Elmi kollektivin xarakterizə edilməsi (layihə rəhbəri və icraçılarının ixtisasları və onların layihə mövzusuna uyğunluq dərəcəsi; əvvəllər həmin sahədə tədqiqat aparmaq təcrübəsi ölkədaxili, regional və beynəlxalq qrant müsabiqələri çərçivəsində; layihə mövzusu üzrə iştirakçıların əsas elmi əsərləri, 8-dan artıq olmamaq şərtilə)", project.team_characterization),
        ("8. Layihənin monitorinqi və davamlılığı (1-2 səhifə) Layihənin icrası və nəticələri haqqında ictimaiyyətin məlumatlandırılması və informasiya əldə edilməsi yollarını göstərin. Layihənin icrası başa çatdıqdan sonra onun davamlılığının təmin olunması istiqamətində görəcəyiniz işləri qeyd edin.", project.project_monitoring),
        ("9. Layihənin qiymətləndirilməsi və hesabatlılığı (1-2 səhifə) Layihənin qiymətləndirilməsi meyarlarını və hesabatlılıq formalarını qeyd edin. Nail olunmuş dəyişikliyin hansı meyarlar əsasında müəyyənləşdiriləcəyini izah edin.", project.project_assessment),
        ("10. Layihə üzrə elmi-tədqiqat işinin yerinə yetirilməsi üçün lazım olan avadanlıq, cihaz və qurğulardan mövcud olanlar haqqında məlumat, əlavə lazım olanların əsaslandırılması", project.project_requirements),
    ]

    for field_name, value in project_fields:
        # Proposal text is user input and reportlab treats it as markup: escape
        # it, or a stray "<" breaks the PDF and tags could inject content.
        text_content = _xml_escape(value) if value else "—"
        # If the text is very long, handle it as paragraphs instead of a table
        if len(text_content) > 1000:
            current_app.logger.warning(f"Long content detected in '{field_name}', using paragraph layout.")
            elements.append(Paragraph(f"<b>{field_name}</b>", table_heading_style))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(text_content, table_content_style))
            elements.append(Spacer(1, 12))
            continue

        try:
            data = [
                [Paragraph(field_name, table_heading_style)],
                [Paragraph(text_content, table_content_style)]
            ]
            table = Table(data, colWidths=[6.5 * inch])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d3d3d3")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("FONTNAME", (0, 0), (-1, 0), font_name),
                ("FONTNAME", (0, 1), (-1, -1), font_name),
                ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                ("ALIGN", (0, 1), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]))
            table._argW[0] = 6.5 * inch
            table.splitByRow = True
            elements.append(table)
            elements.append(Spacer(1, 12))
        except Exception as e:
            current_app.logger.error(f"Error adding project field table for '{field_name}': {e}")
            elements.append(Paragraph(f"<b>{field_name}</b>", table_heading_style))
            elements.append(Spacer(1, 6))
            elements.append(Paragraph(text_content, table_content_style))
            elements.append(Spacer(1, 12))

    # Signature section will be added at the end, after all tables

    # activities table
    # Activities Table Section (refactored for UnboundLocalError and month highlight)
    elements.append(Spacer(1, 18))
    elements.append(Paragraph("Layihə Fəaliyyətləri və Aylar üzrə Plan", heading2))
    elements.append(Spacer(1, 6))

    activity_table_data = []
    # Header: №, Fəaliyyətlər, Aylar (spanning 12 columns)
    activity_table_data.append([
        Paragraph("№", table_heading_style),
        Paragraph("Fəaliyyətlər", table_heading_style),
        Paragraph("Aylar", table_heading_style), "", "", "", "", "", "", "", "", "", "", ""
    ])
    months_row = ["", ""] + [Paragraph(str(i), table_heading_style) for i in range(1, 13)]
    activity_table_data.append(months_row)

    activity_table_style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),  # № column
        ("ALIGN", (1, 0), (1, -1), "LEFT"),    # Fəaliyyətlər column
        ("ALIGN", (2, 0), (-1, 0), "CENTER"),  # Aylar header
        ("ALIGN", (2, 1), (-1, 1), "CENTER"),  # Months row
        ("ALIGN", (2, 2), (-1, -1), "CENTER"), # Activity month cells
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#e0e0e0")),
    ]
    # Span "Aylar" header cell over columns 2 to 13 (zero-based col 2 to 13)
    activity_table_style.append(("SPAN", (2, 0), (13, 0)))

    # Prepare list of highlight positions for valid months
    bg_highlight_positions = []
    if activities:
        for idx, activity in enumerate(activities, start=1):
            row = [
                Paragraph(str(idx), table_content_style),
                Paragraph(rl_text(activity.activity_name), table_content_style)
            ]

            # The model normalises "3", 3 and "3,4,5" alike, so every stored
            # shape ends up as the same list of months here.
            activity_months = activity.month_list()

            # Build month cells (index 2 to 13 for months 1 to 12)
            for m in range(1, 13):
                row.append(Paragraph("", table_content_style))
            activity_table_data.append(row)

            # For each valid month, add the highlight position for this row and month column
            for m in activity_months:
                # Row index in table: idx+1 (header is row 0, months row is 1, data starts at 2)
                # Column for month m: m+1 (since months start at col 2)
                activity_table_style.append((
                    "BACKGROUND", (m+1, idx+1), (m+1, idx+1), colors.HexColor("#d3d3d3")
                ))
    else:
        activity_table_data.append([
            Paragraph("Məlumat yoxdur", table_content_style),
            "", "", "", "", "", "", "", "", "", "", "", "", ""
        ])
        activity_table_style.append(("SPAN", (0, 2), (-1, 2)))

    col_widths = [doc.width * 0.07, doc.width * 0.38] + [doc.width * 0.55 / 12] * 12
    activity_table = Table(activity_table_data, colWidths=col_widths, repeatRows=2)
    activity_table.setStyle(TableStyle(activity_table_style))
    elements.append(activity_table)
    elements.append(Spacer(1, 18))

    # Removed the second occurrence of the image in the activities section as requested

    heading_1 = "LAYİHƏNİN ÜMUMİ SMETASI"
    elements.append(Paragraph(heading_1, heading1))
    elements.append(Spacer(1, 12))

    heading_4 = "Layihənin xərclər smetası (manatla)"
    elements.append(Paragraph(heading_4, heading2))
    elements.append(Spacer(1, 12))

    smeta_table_data = [
        [
            Paragraph("Xərc maddələrinin adları", table_heading_style),
            Paragraph("Layihə üzrə cəmi", table_heading_style)
        ],
        [
            Paragraph("1. Layihə rəhbərinin və icraçıların xidmət haqları", table_content_style),
            Paragraph(str(main_smeta.total_salary), table_content_style)
        ],
        [
            Paragraph("2. Layihə üzrə vergilər və digər məcburi  ödənişlər", table_content_style),
            Paragraph(str(main_smeta.total_fee), table_content_style)
        ],
        [
            Paragraph("3. Dövlət Sosial Müdafiə Fonduna ayırmalar ", table_content_style),
            Paragraph(str(main_smeta.defense_fund), table_content_style)
        ],
        [
            Paragraph("4. Avadanlıq, cihaz, qurğu və mal-materialların satınalınması* (vergilər və digər məcburi ödənişlər daxil olmaqla)**", table_content_style),
            Paragraph(str(main_smeta.total_equipment), table_content_style)
        ],
        [
            Paragraph("5. İşlərin və xidmətlərin satınalınması (çatdırılma, quraşdırılma, sazlanma, sınaqdan keçirilmə, treninqlər və s.)", table_content_style),
            Paragraph(str(main_smeta.total_services), table_content_style)
        ],
        [
            Paragraph("6. İcarə", table_content_style),
            Paragraph(str(main_smeta.total_rent), table_content_style)
        ],
        [
            Paragraph("7. Digər birbaşa xərclər", table_content_style),
            Paragraph(str(main_smeta.other_expenses), table_content_style)
        ],
        [
            Paragraph("Cəmi:", table_content_style),
            Paragraph(str(total_main_amount), table_content_style)
        ],
    ]

    # Set table width to 100% of page width by using doc.width, divide proportionally
    col1_width = doc.width * 0.65
    col2_width = doc.width * 0.35
    smeta_table = Table(smeta_table_data, colWidths=[col1_width, col2_width])
    smeta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d3d3d3")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(smeta_table)

    # --- Collaborators Salary Table (after main smeta, before signature) ---
    elements.append(Spacer(1, 18))
    elements.append(Paragraph("Layihə Rəhbəri və İcraçıların Siyahısı və Əmək Haqqı", heading2))
    elements.append(Spacer(1, 6))

    # Fetch collaborators for this project
    collaborators = Collaborator.query.filter_by(project_code=project_code).all()
    salary_smeta = Salary.query.filter_by(project_code=project_code).all()
    # Build a map: fin_kod -> total_salary
    salary_map = {}
    for s in salary_smeta:
        salary_map[s.fin_kod] = s.total_salary

    # Add project owner to the list as well
    project_owner_user = User.query.filter_by(fin_kod=project.fin_kod).first()

    project_owner_salary = salary_map.get(project.fin_kod, "—")

    owner_row = None
    if project_owner_user:
        owner_row = [
            Paragraph(rl_text(project_owner_user.name), table_content_style),
            Paragraph(rl_text(project_owner_user.surname), table_content_style),
            Paragraph(rl_text(f"{project_owner_user.father_name} ({project_owner_user.fin_kod})"), table_content_style),
            Paragraph(str(project_owner_salary), table_content_style)
        ]

    # Prepare table data
    collaborators_table_data = [
        [
            Paragraph("Ad", table_heading_style),
            Paragraph("Soyad", table_heading_style),
            Paragraph("Ata adı (FIN KOD)", table_heading_style),
            Paragraph("Ümumi əmək haqqı", table_heading_style)
        ]
    ]
    if owner_row:
        collaborators_table_data.append(owner_row)

    if collaborators:
        for collab in collaborators:
            user = User.query.filter_by(fin_kod=collab.fin_kod).first()
            name = user.name if user and hasattr(user, "name") else "—"
            surname = user.surname if user and hasattr(user, "surname") else "—"
            father_name = user.father_name if user and hasattr(user, "father_name") else "—"
            fin_kod = user.fin_kod if user and hasattr(user, "fin_kod") else "—"
            salary_total = salary_map.get(fin_kod, "—")
            collaborators_table_data.append([
                Paragraph(rl_text(name), table_content_style),
                Paragraph(rl_text(surname), table_content_style),
                Paragraph(rl_text(f"{father_name} ({fin_kod})"), table_content_style),
                Paragraph(str(salary_total), table_content_style)
            ])
    else:
        if not owner_row:
            collaborators_table_data.append([
                Paragraph("Məlumat yoxdur", table_content_style),
                "", "", ""
            ])

    collaborators_table = Table(collaborators_table_data, colWidths=[doc.width * 0.22, doc.width * 0.22, doc.width * 0.30, doc.width * 0.26])
    collaborators_table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e0e0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]
    if not collaborators:
        collaborators_table_style.append(("SPAN", (0, 1), (-1, 1)))
    collaborators_table.setStyle(TableStyle(collaborators_table_style))
    elements.append(collaborators_table)
    elements.append(Spacer(1, 12))

    heading_5 = "Əlavə 2. Avadanlıq, cihaz, qurğu və mal-materialların satınalınması"
    elements.append(Paragraph(heading_5, heading2))
    elements.append(Spacer(1, 12))

    table_data = [
        [Paragraph("Satınalınma predmeti ", table_heading_style)],
        [
            Paragraph("№", table_heading_style),
            Paragraph("Avadanlıq, cihaz, qurğu və mal-materialların adları*", table_heading_style),
            Paragraph("Ölçü vahidi", table_heading_style),
            Paragraph("Vahidin qiyməti (manat)", table_heading_style),
            Paragraph("Miqdarı", table_heading_style),
            Paragraph("Cəmi məbləğ (manat)", table_heading_style)
        ]
    ]

    total_subject_sum = 0

    if subject_smeta:
        for idx, subject in enumerate(subject_smeta, start=1):
            table_data.append([
                Paragraph(str(idx), table_content_style),
                Paragraph(rl_text(subject.equipment_name), table_content_style),
                Paragraph(rl_text(subject.unit_of_measure), table_content_style),
                Paragraph(str(subject.price), table_content_style),
                Paragraph(str(subject.quantity), table_content_style),
                Paragraph(str(subject.total_amount), table_content_style)
            ])
            total_subject_sum += subject.total_amount

        # Footer row for total
        table_data.append([
            Paragraph("<b>Cəmi:</b>", table_heading_style),
            "", "", "", "",
            Paragraph(f"<b>{total_subject_sum}</b>", table_heading_style)
        ])
    else:
        table_data.append([
            Paragraph("Məlumat yoxdur", table_content_style),
            "", "", "", "", ""
        ])

    two_header_table = Table(table_data, colWidths=[doc.width / 6] * 6)
    table_style_commands = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#e0e0e0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]
    if not subject_smeta:
        table_style_commands.append(("SPAN", (0, 2), (-1, 2)))
    two_header_table.setStyle(TableStyle(table_style_commands))
    elements.append(two_header_table)
    elements.append(Spacer(1, 12))

    heading_6 = "Əlavə 3. İşlərin və xidmətlərin satınalınması"
    elements.append(Paragraph(heading_6, heading2))
    elements.append(Spacer(1, 12))

    table_data = [
        [Paragraph("İşlərin və xidmətlərin (vergilər və sair  xərclər daxil olmaqla) satınalması xərclərinin hesablanması", table_heading_style)],
        [
            Paragraph("№", table_heading_style),
            Paragraph("İş və xidmətlərin adları*", table_heading_style),
            Paragraph("Ölçü vahidi", table_heading_style),
            Paragraph("Vahidin qiyməti (manat)", table_heading_style),
            Paragraph("Miqdarı", table_heading_style),
            Paragraph("Cəmi məbləğ (manat)", table_heading_style)
        ]
    ]

    total_services_sum = 0

    if service_smeta:
        for idx, service in enumerate(service_smeta, start=1):
            table_data.append([
                Paragraph(str(idx), table_content_style),
                Paragraph(rl_text(service.services_name), table_content_style),
                Paragraph(rl_text(service.unit_of_measure), table_content_style),
                Paragraph(str(service.price), table_content_style),
                Paragraph(str(service.quantity), table_content_style),
                Paragraph(str(service.total_amount), table_content_style)
            ])
            total_services_sum += service.total_amount

        # Footer row for total
        table_data.append([
            Paragraph("<b>Cəmi:</b>", table_heading_style),
            "", "", "", "",
            Paragraph(f"<b>{total_services_sum}</b>", table_heading_style)
        ])
    else:
        table_data.append([
            Paragraph("Məlumat yoxdur", table_content_style),
            "", "", "", "", ""
        ])

    services_table = Table(table_data, colWidths=[doc.width / 6] * 6)
    services_style = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#e0e0e0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]
    if not service_smeta:
        services_style.append(("SPAN", (0, 2), (-1, 2)))
    services_table.setStyle(TableStyle(services_style))
    elements.append(services_table)
    elements.append(Spacer(1, 12))

    # 4
    heading_7 = "Əlavə 4. Layihə üzrə icarə xərcləri"
    elements.append(Paragraph(heading_7, heading2))
    elements.append(Spacer(1, 12))

    table_data = [
        [
            Paragraph("№", table_heading_style),
            Paragraph("İcarəyə götürüləcək daşınar və daşınmaz əmlakın adı*", table_heading_style),
            Paragraph("Ölçü vahidi", table_heading_style),
            Paragraph("Vahidin qiyməti (manat)", table_heading_style),
            Paragraph("Miqdarı", table_heading_style),
            Paragraph("Müddət (ay)", table_heading_style),
            Paragraph("Cəmi məbləğ (manat)", table_heading_style)
        ]
    ]

    total_rent_sum = 0

    if rent_smeta:
        for idx, rent in enumerate(rent_smeta, start=1):
            table_data.append([
                Paragraph(str(idx), table_content_style),
                Paragraph(rl_text(rent.rent_area), table_content_style),
                Paragraph(rl_text(rent.unit_of_measure), table_content_style),
                Paragraph(str(rent.unit_price), table_content_style),
                Paragraph(str(rent.quantity), table_content_style),
                Paragraph(str(rent.duration), table_content_style),
                Paragraph(str(rent.total_amount), table_content_style)
            ])
            total_rent_sum += rent.total_amount

        # Footer for total
        table_data.append([
            Paragraph("<b>Cəmi:</b>", table_heading_style),
            "", "", "", "", "",
            Paragraph(f"<b>{total_rent_sum}</b>", table_heading_style)
        ])
    else:
        table_data.append([
            Paragraph("Məlumat yoxdur", table_content_style),
            "", "", "", "", "", ""
        ])

    rent_table = Table(table_data, colWidths=[doc.width / 7] * 7)
    rent_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e0e0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]
    if not rent_smeta:
        rent_style.append(("SPAN", (0, 1), (-1, 1)))
    rent_table.setStyle(TableStyle(rent_style))
    elements.append(rent_table)
    elements.append(Spacer(1, 12))

    # 5
    heading_8 = "Əlavə 5. Digər birbaşa xərclər"
    elements.append(Paragraph(heading_8, heading2))
    elements.append(Spacer(1, 12))

    table_data = [
        [
            Paragraph("№", table_heading_style),
            Paragraph("Xərc maddələrinin adı*", table_heading_style),
            Paragraph("Ölçü vahidi", table_heading_style),
            Paragraph("Vahidin qiyməti (manat)", table_heading_style),
            Paragraph("Miqdarı", table_heading_style),
            Paragraph("Müddət (ay)", table_heading_style),
            Paragraph("Cəmi məbləğ (manat)", table_heading_style)
        ]
    ]

    total_other_exp_sum = 0

    if other_exps:
        for idx, exp in enumerate(other_exps, start=1):
            table_data.append([
                Paragraph(str(idx), table_content_style),
                Paragraph(rl_text(exp.expenses_name), table_content_style),
                Paragraph(rl_text(exp.unit_of_measure), table_content_style),
                Paragraph(str(exp.unit_price), table_content_style),
                Paragraph(str(exp.quantity), table_content_style),
                Paragraph(str(exp.duration), table_content_style),
                Paragraph(str(exp.total_amount), table_content_style)
            ])
            total_other_exp_sum += exp.total_amount

        # Footer for total
        table_data.append([
            Paragraph("<b>Cəmi:</b>", table_heading_style),
            "", "", "", "", "",
            Paragraph(f"<b>{total_other_exp_sum}</b>", table_heading_style)
        ])
    else:
        table_data.append([
            Paragraph("Məlumat yoxdur", table_content_style),
            "", "", "", "", "", ""
        ])

    other_exp_table = Table(table_data, colWidths=[doc.width / 7] * 7)
    other_exp_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e0e0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]
    if not other_exps:
        other_exp_style.append(("SPAN", (0, 1), (-1, 1)))
    other_exp_table.setStyle(TableStyle(other_exp_style))
    elements.append(other_exp_table)
    elements.append(Spacer(1, 12))

    # SIGNATURE SECTION - at the end of the PDF
    elements.append(Spacer(1, 36))
    # Fetch project owner
    owner = None
    if hasattr(project, "fin_kod"):
        owner = User.query.filter_by(fin_kod=project.fin_kod).first()
    owner_full_name = ""
    if owner:
        owner_full_name = f"{owner.name or ''} {owner.surname or ''} {owner.father_name or ''}".strip()
    else:
        owner_full_name = "—"

    # Two-column signature table
    left_title = "Azərbaycan Texniki Universiteti adından rektor"
    left_name = "Professor Vəliyev Vilayət Məmməd oğlu"
    right_title = "Layihə rəhbəri"
    right_name = owner_full_name

    # First row: titles
    sig_titles = [
        Paragraph(f"{left_title}", table_content_style),
        Paragraph(f"{right_title}", table_content_style)
    ]
    # Second row: names
    sig_names = [
        Paragraph(rl_text(left_name), table_content_style),
        Paragraph(rl_text(right_name), table_content_style)
    ]
    # Third row: signature lines
    sig_lines = [
        Paragraph("_____________________", table_content_style),
        Paragraph("_____________________", table_content_style)
    ]
    # Fourth row: (imza)
    sig_imza = [
        Paragraph("(imza)", table_content_style),
        Paragraph("(imza)", table_content_style)
    ]
    signature_table_final = Table(
        [sig_titles, sig_names, sig_lines, sig_imza],
        colWidths=[3.25 * inch, 3.25 * inch]
    )
    signature_table_final.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # Optionally, vertical spacing
    ]))
    elements.append(signature_table_final)

    doc.build(elements)
    pdf_data = buffer.getvalue()
    buffer.close()

    response = make_response(pdf_data)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=project_{project_code}.pdf"
    return response

from io import BytesIO
from flask import send_file
import pandas as pd

@project_offer.route("/api/project-excel/<int:project_code>", methods=["GET"])
@limiter.limit("100 per second")
@token_required([0, 1, 2, 3])
def download_excel(project_code):
    # Budget lines and salaries by FIN: admins, the lead, the team and the
    # assigned expert only.
    project, error = project_read_guard(project_code)
    if error:
        return error

    subject_smeta = SubjectOfPurchase.query.filter_by(project_code=project_code).all()
    service_smeta = ServicesOfPurchase.query.filter_by(project_code=project_code).all()
    rent_smeta = Rent.query.filter_by(project_code=project_code).all()
    other_exps = other_exp_model.query.filter_by(project_code=project_code).all()

    output = BytesIO()

    # Use context manager to avoid writer.save()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Subject sheet
        if subject_smeta:
            df_subject = pd.DataFrame([{
                "№": idx + 1,
                "Equipment Name": s.equipment_name,
                "Unit": s.unit_of_measure,
                "Price": s.price,
                "Quantity": s.quantity,
                "Total": s.total_amount
            } for idx, s in enumerate(subject_smeta)])
        else:
            df_subject = pd.DataFrame([{"Message": "No data"}])
        df_subject.to_excel(writer, sheet_name="Subject of Purchase", index=False)

        # Services sheet
        if service_smeta:
            df_services = pd.DataFrame([{
                "№": idx + 1,
                "Service Name": s.services_name,
                "Unit": s.unit_of_measure,
                "Price": s.price,
                "Quantity": s.quantity,
                "Total": s.total_amount
            } for idx, s in enumerate(service_smeta)])
        else:
            df_services = pd.DataFrame([{"Message": "No data"}])
        df_services.to_excel(writer, sheet_name="Services of Purchase", index=False)

        # Rent sheet
        if rent_smeta:
            df_rent = pd.DataFrame([{
                "№": idx + 1,
                "Rent Area": r.rent_area,
                "Unit": r.unit_of_measure,
                "Unit Price": r.unit_price,
                "Quantity": r.quantity,
                "Duration": r.duration,
                "Total": r.total_amount
            } for idx, r in enumerate(rent_smeta)])
        else:
            df_rent = pd.DataFrame([{"Message": "No data"}])
        df_rent.to_excel(writer, sheet_name="Rent", index=False)

        # Other Expenses sheet
        if other_exps:
            df_other = pd.DataFrame([{
                "№": idx + 1,
                "Expense Name": e.expenses_name,
                "Unit": e.unit_of_measure,
                "Price": e.unit_price,
                "Quantity": e.quantity,
                "Duration": e.duration,
                "Total": e.total_amount
            } for idx, e in enumerate(other_exps)])
        else:
            df_other = pd.DataFrame([{"Message": "No data"}])
        df_other.to_excel(writer, sheet_name="Other Expenses", index=False)

        # Salary sheet
        salary_smeta = Salary.query.filter_by(project_code=project_code).all()
        if salary_smeta:
            df_salary = pd.DataFrame([{
                "№": idx + 1,
                "FIN KOD": s.fin_kod,
                "Salary per Month": s.salary_per_month,
                "Months": s.months,
                "Total Salary": s.total_salary
            } for idx, s in enumerate(salary_smeta)])
        else:
            df_salary = pd.DataFrame([{"Message": "No data"}])
        df_salary.to_excel(writer, sheet_name="Salary", index=False)

    # Prepare file for download
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=f"project_{project_code}_smeta.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
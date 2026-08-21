import logging
from extentions.db import db
from models.userModel import User
from models.authModel import Auth
from config.limiter import limiter
from flask_cors import cross_origin
from utils.notify import create_notification
from utils.email_util import send_email
from models.projectModel import Project
from models.competitionModel import Competition
from models.smetaModels.smetaModel import Smeta
from models.smetaModels.salaryModel import Salary
from utils.decarator import role_required
from utils.jwt_required import token_required
from utils.archive_lock import archive_write_blocked
from models.collaboratorModel import Collaborator
from exceptions.exception import handle_not_found
from flask import Blueprint, request, render_template, g
from exceptions.exception import handle_global_exception
from exceptions.exception import handle_specific_not_found
from exceptions.exception import handle_missing_field, handle_creation, handle_success, handle_conflict


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

collaborator_bp = Blueprint('collaborator_bp', __name__)


# --------------------------------------------------------------- helpers ----

def caller_is_admin():
    """Admins (project_role == 2) act on any project; everyone else on their own."""
    return g.user.get('role') == 2


def resolve_managed_project(project_code):
    """Find the project whose TEAM the caller is allowed to change.

    An admin manages every project; a lead manages only the project they own.
    Archived projects stay read-only unless an admin unlocked them, which is
    the same rule every other write on a `project_code` follows.

    Returns `(project, error)`; `error` is a ready-to-return Flask response
    tuple when the request must be refused, otherwise None.
    """
    try:
        project_code = int(project_code)
    except (TypeError, ValueError):
        return None, ({'error': 'project_code must be a number.', 'status': 400}, 400)

    project = Project.query.filter_by(project_code=project_code).first()
    if not project:
        return None, ({'error': 'Project not found.', 'status': 404}, 404)

    # The identity comes from the TOKEN: a body-supplied fin_kod would let a
    # lead manage someone else's team by naming its owner.
    if not caller_is_admin() and project.fin_kod != g.user.get('fin_kod'):
        return None, ({'error': 'This project belongs to another user.', 'status': 403}, 403)

    blocked = archive_write_blocked(project_code)
    if blocked:
        return None, blocked

    return project, None


def drop_collaborator(collaborator, project_code):
    """Detach a person from a project, removing what only existed because they
    were on the team. Deliberately does NOT commit — the caller decides when.

    Their salary line is part of that: leaving it behind would keep paying a
    person who is no longer an executor and would skew the project's smeta.
    """
    project_code = int(project_code)
    salaries = Salary.query.filter_by(
        project_code=project_code, fin_kod=collaborator.fin_kod
    ).all()

    if salaries:
        main_smeta = Smeta.query.filter_by(project_code=project_code).first()
        for salary in salaries:
            if main_smeta and main_smeta.total_salary is not None:
                main_smeta.total_salary -= (salary.total_salary or 0)
            db.session.delete(salary)

    db.session.delete(collaborator)


def collaborator_payload(collaborator):
    """Team-table row: the collaborator joined with their profile + auth role."""
    user = User.query.filter_by(fin_kod=collaborator.fin_kod).first()
    if not user:
        return None

    auth_record = Auth.query.filter_by(fin_kod=collaborator.fin_kod).first()
    if not auth_record:
        return None

    return {
        'fin_kod': collaborator.fin_kod,
        'project_code': collaborator.project_code,
        'name': user.name,
        'surname': user.surname,
        'father_name': user.father_name,
        'image': user.get_user_image(),
        'project_role': auth_record.project_role,
        'approved': bool(collaborator.approved)
    }


def notify_removed_collaborator(fin_kod, project, template):
    """Tell a removed/rejected person, by e-mail and in the dashboard.

    Best-effort: a mail server hiccup must not roll back a removal that has
    already been committed.
    """
    try:
        create_notification(
            recipient_fin_kod=fin_kod,
            title="Layihə komandasından çıxarıldınız",
            body=(
                f"'{project.project_name or 'Adsız layihə'}' layihəsinin icraçıları "
                "siyahısından çıxarıldınız. İndi başqa bir layihəyə müraciət edə bilərsiniz."
            ),
            type='general',
            link='/projects'
        )
    except Exception:
        logger.exception("Could not create the removal notification for %s", fin_kod)

    try:
        user = User.query.filter_by(fin_kod=fin_kod).first()
        if user and user.work_email:
            send_email(
                "İcraçı Təyinatı",
                user.work_email,
                render_template(template, project=project)
            )
    except Exception:
        logger.exception("Could not e-mail the removal notice to %s", fin_kod)


# ----------------------------------------------------------------- reads ----

@collaborator_bp.route("/api/collaborators", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 2])
def get_collaborators():
    try:
        logger.debug("Fetching all collaborators")
        collaborators = Collaborator.query.filter_by(approved=True).all()
        if not collaborators:
            return handle_specific_not_found('No collaborator found.')

        collaborator_list = [c.collaborator_details() for c in collaborators]
        logger.debug(f"Collaborator list: {collaborator_list}")
        return handle_success(collaborator_list, 'Collaborators fetched successfully.')
    except Exception as e:
        return handle_global_exception(str(e))

@collaborator_bp.route("/api/collaborators/<int:project_code>")
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def get_collaborators_by_fin_kod(project_code):
    try:
        logger.debug(f"Fetching collaborators for project code: {project_code}")
        collaborator_list = []
        collaborators = Collaborator.query.filter_by(project_code=project_code, approved=True).all()
        logger.debug(f"Number of collaborators fetched: {len(collaborators)}")

        if not collaborators:
            logger.debug("No collaborators found for the given project code.")
            return handle_specific_not_found('No collaborator found.')

        for collaborator in collaborators:
            logger.debug(f"Processing collaborator with fin_kod: {collaborator.fin_kod}")
            payload = collaborator_payload(collaborator)
            if not payload:
                logger.warning(f"No user/auth record for fin_kod: {collaborator.fin_kod}")
                continue
            collaborator_list.append(payload)

        logger.debug(f"Returning {len(collaborator_list)} collaborators in response")
        return {'data': collaborator_list, 'status': 200}, 200
    
    except Exception as e:
        logger.error(f"Exception occurred in get_collaborators_by_fin_kod: {str(e)}", exc_info=True)
        return handle_global_exception(str(e))
   
@collaborator_bp.route("/api/app-wait-collaborators/<int:project_code>", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 2])
def get_app_wait_collaborators_by_fin_kod(project_code):
    try:
        logger.debug(f"Fetching collaborators for project code: {project_code}")
        collaborator_list = []

        collaborators = Collaborator.query.filter_by(project_code=project_code, approved=False).all()
        logger.debug(f"Number of collaborators fetched: {len(collaborators)}")

        if not collaborators:
            logger.debug("No collaborators found for the given project code.")
            return handle_specific_not_found('No collaborator found.')

        for collaborator in collaborators:
            logger.debug(f"Processing collaborator with fin_kod: {collaborator.fin_kod}")
            payload = collaborator_payload(collaborator)
            if not payload:
                logger.warning(f"No user/auth record for fin_kod: {collaborator.fin_kod}")
                continue
            collaborator_list.append(payload)

        logger.debug(f"Returning {len(collaborator_list)} collaborators in response")
        return {'data': collaborator_list, 'status': 200}, 200

    except Exception as e:
        logger.error(f"Exception occurred: {str(e)}", exc_info=True)
        return handle_global_exception(str(e))

@collaborator_bp.route("/api/project/owner/<int:project_code>", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def get_project_owner(project_code):
    try:
        logger.debug(f"Fetching project owner for project code: {project_code}")

        owner_fin_kod = Project.query.filter_by(project_code=project_code).first().fin_kod
        logger.debug(f"Project owner fin_kod: {owner_fin_kod}")

        user = User.query.filter_by(fin_kod=owner_fin_kod).first()
        logger.debug(f"Owner found: name={user.name}, surname={user.surname}")

        if not user:
            return handle_specific_not_found("Owner not found.")
        
        owner_details = {
            'name': user.name,
            'surname': user.surname,
            'father_name': user.father_name,
        }

        return handle_success(owner_details, 'Owner fetched successfully.')

    except Exception as e:
        return handle_global_exception(str(e))


@collaborator_bp.route("/api/my-collaborator-status", methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def my_collaborator_status():
    """The caller's own membership in the ACTIVE competition.

    The clients cache `is_collaborator` from sign-in, so a person removed from
    a team mid-session would keep seeing "İştirakçı Ol" disabled until their
    next login. This lets the UI re-read the truth instead.
    """
    try:
        fin_kod = g.user.get('fin_kod')
        active_id = Competition.get_active_id()

        collaborator = Collaborator.query.filter_by(
            fin_kod=fin_kod, competition_id=active_id
        ).first()

        return handle_success({
            'is_collaborator': collaborator is not None,
            'approved': bool(collaborator.approved) if collaborator else False,
            'project_code': collaborator.project_code if collaborator else None
        }, 'Collaborator status fetched successfully.')

    except Exception as e:
        logger.exception("An error occurred while fetching the collaborator status")
        return handle_global_exception(str(e))


@collaborator_bp.route("/api/project/<int:project_code>/collaborator-candidates", methods=['GET'])
@limiter.limit("100 per second")
@token_required([2])
def collaborator_candidates(project_code):
    """People an admin may still add to this project.

    A candidate is an approved, unblocked account registered as an executor
    (project_role == 1) with a completed profile, who is not already on a team
    in this competition.
    """
    try:
        project, error = resolve_managed_project(project_code)
        if error:
            return error

        search = (request.args.get('search') or '').strip()

        taken = {
            c.fin_kod for c in Collaborator.query.filter_by(
                competition_id=project.competition_id
            ).all()
        }

        candidates = []
        accounts = Auth.query.filter_by(project_role=1, approved=True, blocked=0).all()
        for account in accounts:
            if account.fin_kod in taken:
                continue

            user = User.query.filter_by(fin_kod=account.fin_kod).first()
            if not user or not user.profile_completed:
                continue

            if search:
                haystack = ' '.join(filter(None, [
                    user.name, user.surname, user.father_name, user.fin_kod
                ])).lower()
                if search.lower() not in haystack:
                    continue

            candidates.append({
                'fin_kod': user.fin_kod,
                'name': user.name,
                'surname': user.surname,
                'father_name': user.father_name,
                'work_place': user.work_place,
                'duty': user.duty,
                'image': user.get_user_image()
            })

        candidates.sort(key=lambda c: ((c['surname'] or ''), (c['name'] or '')))
        return handle_success(candidates, 'Candidates fetched successfully.')

    except Exception as e:
        logger.exception("An error occurred while fetching collaborator candidates")
        return handle_global_exception(str(e))


# ---------------------------------------------------------------- writes ----

@collaborator_bp.route('/api/be-collaborator', methods=['POST'])
@limiter.limit("100 per second")
@token_required([1, 2])
def be_collaborator():
    try:
        logger.debug("Received request to become collaborator")
        collaborator_details = request.get_json()
        required_fields = ['fin_kod', 'project_code']

        for field in required_fields:
            if field not in collaborator_details:
                return handle_missing_field(404)
            
        fin_kod = collaborator_details.get('fin_kod')
        project_code = collaborator_details.get('project_code')
        
        logger.debug(f"fin_kod: {fin_kod}, project_code: {project_code}")

        # People apply for THEMSELVES. Without this an executor could sign
        # someone else up for a project by posting their FIN.
        if not caller_is_admin() and fin_kod != g.user.get('fin_kod'):
            return {'error': 'You can only apply on your own behalf.', 'status': 403}, 403

        user = Auth.query.filter_by(fin_kod=fin_kod).first()
        project = Project.query.filter_by(project_code=project_code).first()

        if not user:
            logger.debug("User not found.")
            return handle_specific_not_found("User not found.")
        if not project:
            logger.debug("Project not found.")
            return handle_specific_not_found("Project not found.")

        collaborator_count = Collaborator.query.filter_by(project_code=project_code).count()

        max_collaborator_count = project.collaborator_limit

        if collaborator_count >= max_collaborator_count:
            return handle_conflict("There is no available place in project.")

        blocked = archive_write_blocked(project_code)
        if blocked:
            return blocked

        profile_approved = User.query.filter_by(fin_kod=fin_kod).first().profile_completed

        if not profile_approved:
            logger.debug("User profile not completed.")
            return {'error': 'User profile is not completed.', 'status': 403}, 403

        # A person may join only one project PER competition. The global UNIQUE on
        # fin_kod was relaxed to (fin_kod, competition_id), so check explicitly.
        # Once a lead or an admin removes them, this frees up again and they may
        # apply somewhere else.
        existing = Collaborator.query.filter_by(
            fin_kod=fin_kod, competition_id=project.competition_id
        ).first()
        if existing:
            return handle_conflict("Already a collaborator in this competition.")

        new_collaborator_record = Collaborator(
            project_code=project_code,
            fin_kod=fin_kod,
            competition_id=project.competition_id
        )

        logger.debug("Adding new collaborator to the database")
        db.session.add(new_collaborator_record) 
        db.session.commit()

        return handle_creation("Collaborator added successfully.")

    except Exception as e:
        logger.exception("An error occurred while processing be-collaborator request")
        return handle_global_exception(str(e))


@collaborator_bp.route('/api/project/<int:project_code>/collaborator', methods=['POST'])
@limiter.limit("100 per second")
@token_required([2])
def add_collaborator(project_code):
    """Put a person on a project's team directly. Admin only.

    A lead still composes their team through apply-and-approve; this is the
    administrative override, so the member is approved straight away.
    """
    try:
        project, error = resolve_managed_project(project_code)
        if error:
            return error

        data = request.get_json(silent=True) or {}
        fin_kod = data.get('fin_kod')
        if not fin_kod:
            return {'error': 'fin_kod field is required.', 'status': 400}, 400

        account = Auth.query.filter_by(fin_kod=fin_kod).first()
        if not account:
            return {'error': 'User not found.', 'status': 404}, 404
        if not account.approved or account.blocked:
            return {'error': 'This account is not approved or is blocked.', 'status': 403}, 403
        if account.project_role != 1:
            return {'error': 'Only users registered as executors can join a team.', 'status': 400}, 400

        user = User.query.filter_by(fin_kod=fin_kod).first()
        if not user or not user.profile_completed:
            return {'error': 'This user has not completed their profile.', 'status': 403}, 403

        if project.fin_kod == fin_kod:
            return {'error': 'The project lead is already on the team.', 'status': 409}, 409

        existing = Collaborator.query.filter_by(
            fin_kod=fin_kod, competition_id=project.competition_id
        ).first()
        if existing:
            if existing.project_code == project.project_code:
                return {'error': 'This user is already on this team.', 'status': 409}, 409
            return {
                'error': 'This user already belongs to another project in this competition.',
                'status': 409
            }, 409

        team_size = Collaborator.query.filter_by(project_code=project.project_code).count()
        if team_size >= project.collaborator_limit:
            return {'error': 'There is no available place in project.', 'status': 409}, 409

        collaborator = Collaborator(
            project_code=project.project_code,
            fin_kod=fin_kod,
            competition_id=project.competition_id,
            approved=True
        )
        db.session.add(collaborator)
        db.session.commit()

        try:
            create_notification(
                recipient_fin_kod=fin_kod,
                title="Layihə komandasına əlavə olundunuz",
                body=f"'{project.project_name or 'Adsız layihə'}' layihəsinin icraçısı təyin edildiniz.",
                type='general',
                link='/collaborator-project'
            )
            if user.work_email:
                send_email(
                    "İcraçı Təyinatı",
                    user.work_email,
                    render_template("email/collaborator_success_template.html", project=project)
                )
        except Exception:
            logger.exception("Could not announce the new collaborator %s", fin_kod)

        return handle_success(collaborator.collaborator_details(), "Collaborator added successfully.")

    except Exception as e:
        db.session.rollback()
        logger.exception("An error occurred while adding a collaborator")
        return handle_global_exception(str(e))


@collaborator_bp.route('/api/project/<int:project_code>/collaborator/<string:fin_kod>', methods=['DELETE'])
@limiter.limit("100 per second")
@token_required([0, 2])
def remove_collaborator(project_code, fin_kod):
    """Take a person off a project's team.

    Open to the project's own lead and to any admin. Removing the row is what
    frees the (fin_kod, competition_id) slot, so the person can immediately
    apply to another project in the same competition.
    """
    try:
        project, error = resolve_managed_project(project_code)
        if error:
            return error

        collaborator = Collaborator.query.filter_by(
            project_code=project.project_code, fin_kod=fin_kod
        ).first()
        if not collaborator:
            return {'error': 'Collaborator not found on this project.', 'status': 404}, 404

        drop_collaborator(collaborator, project.project_code)
        db.session.commit()

        notify_removed_collaborator(
            fin_kod, project, "email/collaborator_removed_template.html"
        )

        return handle_success(
            {'fin_kod': fin_kod, 'project_code': project.project_code},
            "Collaborator removed successfully."
        )

    except Exception as e:
        db.session.rollback()
        logger.exception("An error occurred while removing a collaborator")
        return handle_global_exception(str(e))

    
@collaborator_bp.route('/api/app-collaborator/<string:fin_kod>', methods=['POST'])
@limiter.limit("100 per second")
@token_required([0, 2])
def approve_collaborator(fin_kod):
    try:
        # Scoped to the project the caller manages: a bare fin_kod lookup would
        # pick an arbitrary row when the person applied in several seasons.
        collaborator, error = resolve_team_member(fin_kod)
        if error:
            return error

        project_code = collaborator.project_code

        blocked = archive_write_blocked(project_code)
        if blocked:
            return blocked

        project = Project.query.filter_by(project_code=project_code).first()

        collaborator.approved = True
        db.session.commit()

        user = User.query.filter_by(fin_kod=fin_kod).first()
        if user and user.work_email:
            subject = "İcraçı Təyinatı"
            html_content = render_template("email/collaborator_success_template.html", project=project)
            send_email(subject, user.work_email, html_content)

        collaborator_data = {
            "fin_kod": collaborator.fin_kod,
            "project_code": collaborator.project_code,
            "approved": collaborator.approved
        }

        return handle_success(collaborator_data, "Collaborator approved successfully.")
            
    except Exception as e:
        logger.exception("An error occurred while processing approve-collaborator request")
        return handle_global_exception(str(e))
    
@collaborator_bp.route('/api/reject-collaborator/<string:fin_kod>', methods=['DELETE'])
@limiter.limit("100 per second")
@token_required([0, 2])
def reject_collaborator(fin_kod):
    try:
        collaborator, error = resolve_team_member(fin_kod)
        if error:
            return error

        project_code = collaborator.project_code

        blocked = archive_write_blocked(project_code)
        if blocked:
            return blocked

        project = Project.query.filter_by(project_code=project_code).first()

        drop_collaborator(collaborator, project_code)
        db.session.commit()

        notify_removed_collaborator(
            fin_kod, project, "email/collaborator_reject_template.html"
        )

        return handle_success({"fin_kod": fin_kod}, "Collaborator rejected and removed successfully.")
    
    except Exception as e:
        db.session.rollback()
        logger.exception("An error occurred while processing approve-collaborator request")
        return handle_global_exception(str(e))


def resolve_team_member(fin_kod):
    """Resolve the person an approve/reject call is about.

    The clients only send a FIN, so the project comes from the caller: a lead's
    own project, or — for an admin — an explicit `project_code`, falling back to
    the applicant's row in the active competition.

    Returns `(collaborator, error)`.
    """
    project_code = request.args.get('project_code') or (request.get_json(silent=True) or {}).get('project_code')

    if project_code:
        project, error = resolve_managed_project(project_code)
        if error:
            return None, error
        collaborator = Collaborator.query.filter_by(
            project_code=project.project_code, fin_kod=fin_kod
        ).first()
    elif caller_is_admin():
        active_id = Competition.get_active_id()
        query = Collaborator.query.filter_by(fin_kod=fin_kod)
        collaborator = query.filter_by(competition_id=active_id).first() or query.first()
    else:
        # A lead may only act on applicants to their OWN project.
        active_id = Competition.get_active_id()
        project = Project.query.filter_by(
            fin_kod=g.user.get('fin_kod'), competition_id=active_id
        ).first()
        if not project:
            return None, ({'error': 'You have no project in the active competition.', 'status': 404}, 404)
        collaborator = Collaborator.query.filter_by(
            project_code=project.project_code, fin_kod=fin_kod
        ).first()

    if not collaborator:
        return None, ({'error': 'Collaborator not found.', 'status': 404}, 404)

    return collaborator, None

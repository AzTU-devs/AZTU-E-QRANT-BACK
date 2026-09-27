"""Object-level authorization for everything addressed by a `project_code`.

`token_required` answers "is this a signed-in user with an allowed role?". It
does NOT answer "may THIS user touch THIS project?" — and for most project data
nobody asked, so any signed-in lead could read or rewrite another lead's budget,
activity plan, reports and files by quoting a different project code
(OWASP API1:2023, Broken Object Level Authorization).

These helpers are the single place that rule lives:

* read  — admins; the project's lead; anyone on its team (a `collaborators`
          row, approved or pending); the expert assigned to review it.
* write — admins and the project's lead only.

Each guard returns `(project, error)`; `error` is a ready-to-return Flask
response tuple when the request must be refused, otherwise None.
"""

from datetime import datetime

from flask import g

from models.projectModel import Project
from models.collaboratorModel import Collaborator
from models.competitionModel import Competition
from models.expertModel import EXPERT_ROLE
from models.systemLockModel import SystemLock
from utils.archive_lock import project_is_archived, ARCHIVE_LOCKED_MESSAGE

ADMIN_ROLE = 2

SYSTEM_LOCKED_MESSAGE = (
    'Sistem kilidlənib: smeta və fəaliyyət planı hazırda redaktə üçün bağlıdır.'
)
SUBMITTED_LOCKED_MESSAGE = (
    'Layihə təqdim edilib və redaktə üçün bağlıdır. Dəyişiklik üçün administratordan '
    'geri qaytarılmasını istəyin.'
)
DEADLINE_PASSED_MESSAGE = 'Müraciət müddəti bitib.'


def caller_fin():
    return (getattr(g, 'user', None) or {}).get('fin_kod')


def caller_role():
    return (getattr(g, 'user', None) or {}).get('role')


def is_admin():
    return caller_role() == ADMIN_ROLE


def _as_code(project_code):
    try:
        return int(project_code)
    except (TypeError, ValueError):
        return None


def load_project(project_code):
    """(project, error) for a code that arrives from a URL or a JSON body."""
    code = _as_code(project_code)
    if code is None:
        return None, ({'error': 'project_code must be a number.', 'status': 400}, 400)
    project = Project.query.filter_by(project_code=code).first()
    if not project:
        return None, ({'error': 'Project not found.', 'status': 404}, 404)
    return project, None


def is_project_member(project, fin_kod=None, approved_only=False):
    fin_kod = fin_kod or caller_fin()
    if not fin_kod:
        return False
    query = Collaborator.query.filter_by(
        project_code=project.project_code, fin_kod=fin_kod
    )
    if approved_only:
        query = query.filter_by(approved=True)
    return query.first() is not None


def can_read_project(project):
    if is_admin():
        return True
    fin = caller_fin()
    if not fin:
        return False
    if project.fin_kod == fin:
        return True
    if caller_role() == EXPERT_ROLE:
        return (project.expert or '').strip().lower() == fin.strip().lower()
    # Only an APPROVED member sees the project's data. A pending/rejected
    # applicant is not yet on the team and must not read salaries, budget,
    # files or the dossier (finding B-H2).
    return is_project_member(project, fin, approved_only=True)


def can_write_project(project):
    return is_admin() or (caller_fin() is not None and project.fin_kod == caller_fin())


def project_read_guard(project_code):
    """Anyone with a legitimate relation to the project may read it."""
    project, error = load_project(project_code)
    if error:
        return None, error
    if not can_read_project(project):
        return None, ({'error': 'You do not have access to this project.', 'status': 403}, 403)
    return project, None


def system_locked():
    lock = SystemLock.query.first()
    return bool(lock and lock.is_locked)


def submitted_lock_error(project):
    """A lead may not edit a project once it is submitted, until an admin
    returns it for corrections (finding B-L7). Admins are never held back.
    Returns a ready-to-return error tuple, or None."""
    if is_admin():
        return None
    if getattr(project, 'submitted', False):
        return {'error': SUBMITTED_LOCKED_MESSAGE, 'status': 423}, 423
    return None


def deadline_error(project=None, competition_id=None):
    """Refuse a lead's create/save/submit once the competition's application
    deadline has passed (finding B-L7). Admins are exempt. A competition with no
    deadline set is treated as open."""
    if is_admin():
        return None
    cid = competition_id if competition_id is not None else getattr(project, 'competition_id', None)
    if cid is None:
        return None
    competition = Competition.query.get(cid)
    if competition and competition.application_deadline and datetime.utcnow() > competition.application_deadline:
        return {'error': DEADLINE_PASSED_MESSAGE, 'status': 403}, 403
    return None


def project_write_guard(project_code, check_archive=True, respect_system_lock=False,
                        respect_submit_lock=True):
    """Only the project's lead (or an admin) may change it.

    `check_archive` keeps an archived project read-only for its lead until an
    admin unlocks it (admins are not held back by it here, so they can still
    correct an archived record). Quarterly reports pass False on purpose —
    winners keep reporting after their season is archived.

    `respect_system_lock` makes the admin's platform-wide lock (the switch on
    the Role Permissions screen) binding on the SERVER, not just in the UI, for
    the budget and activity-plan screens it was designed to close.

    `respect_submit_lock` freezes the project for its lead once it is submitted
    (finding B-L7); reports pass False so winners can keep reporting.
    """
    project, error = load_project(project_code)
    if error:
        return None, error
    if not can_write_project(project):
        return None, ({'error': 'This project belongs to another user.', 'status': 403}, 403)
    if not is_admin():
        if check_archive and project_is_archived(project) and not project.edit_unlocked:
            return None, ({'error': ARCHIVE_LOCKED_MESSAGE, 'status': 403}, 403)
        if respect_submit_lock:
            locked = submitted_lock_error(project)
            if locked:
                return None, locked
        if respect_system_lock and system_locked():
            return None, ({'error': SYSTEM_LOCKED_MESSAGE, 'status': 423}, 423)
    return project, None

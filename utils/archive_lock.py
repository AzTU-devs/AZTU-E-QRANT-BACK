"""Read-only protection for the project archive.

A project belongs to the archive once its competition is no longer the active
one. Archived projects are read-only by default; an admin can unlock a single
project (`Project.edit_unlocked`) to hand it back to its owner for editing.

The guards here are used by every write that hangs off a `project_code`
(activities, collaborators, files) so the unlock means the same thing
everywhere. Quarterly reports are deliberately NOT guarded: winners of past
competitions keep reporting after their season is archived.
"""

from models.projectModel import Project
from models.competitionModel import Competition

ARCHIVE_LOCKED_MESSAGE = (
    'Archived project is closed for editing. Ask an administrator to unlock it.'
)


def _as_code(project_code):
    """`project_code` arrives from JSON/route params in mixed shapes."""
    try:
        return int(project_code)
    except (TypeError, ValueError):
        return None


def project_is_archived(project):
    """True when the project belongs to a PREVIOUS (non-active) competition.

    With no active competition configured nothing counts as archived, so the
    guards stay inert rather than locking the whole system out.
    """
    active_id = Competition.get_active_id()
    return active_id is not None and project.competition_id != active_id


def archive_write_blocked(project_code):
    """Guard for writes addressed by `project_code`.

    Returns a ready-to-return Flask response tuple when the target project is
    archived and still locked, otherwise None. Unknown/unparsable codes return
    None so each caller keeps its own 404 wording.
    """
    code = _as_code(project_code)
    if code is None:
        return None

    project = Project.query.filter_by(project_code=code).first()
    if not project:
        return None

    if project_is_archived(project) and not project.edit_unlocked:
        return {'error': ARCHIVE_LOCKED_MESSAGE, 'status': 403}, 403

    return None

from extentions.db import db
from flask_sqlalchemy import SQLAlchemy

# How many projects one person may JOIN as an executor within a single
# competition, keyed by their registered project_role.
#   0 = lead (layihə rəhbəri) — already carries their OWN project, so they may
#       take part in one further project as an executor.
#   1 = executor (icraçı) — no project of their own, so they may serve on two.
# Anyone else (admins) is not a participant and gets no slots.
COLLABORATION_LIMIT_BY_ROLE = {0: 1, 1: 2}


def collaboration_limit(project_role):
    """Slots this role gets per competition. Unknown roles get none."""
    return COLLABORATION_LIMIT_BY_ROLE.get(project_role, 0)


class Collaborator(db.Model):
    __tablename__ = 'collaborators'
    # A person may join SEVERAL projects per competition (see the limits above),
    # but never the same project twice — that is all the database enforces; the
    # per-competition count is checked in the controller, where the person's
    # role is known.
    __table_args__ = (
        db.UniqueConstraint('fin_kod', 'project_code', name='uq_collaborator_fin_project'),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_code = db.Column(db.Integer, nullable=False)
    fin_kod = db.Column(db.String, nullable=False)
    approved = db.Column(db.Boolean, nullable=False, default=False)
    competition_id = db.Column(db.Integer)  # FK-by-convention -> competitions.id

    def collaborator_details(self):
        return {
            'id': self.id,
            'project_code': self.project_code,
            'fin_code': self.fin_kod,
            'approved': self.approved,
            'competition_id': self.competition_id
        }

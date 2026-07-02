from extentions.db import db
from flask_sqlalchemy import SQLAlchemy

class Collaborator(db.Model):
    __tablename__ = 'collaborators'
    # A person may join one project PER competition (not one globally).
    __table_args__ = (
        db.UniqueConstraint('fin_kod', 'competition_id', name='uq_collaborator_fin_competition'),
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
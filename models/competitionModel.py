from extentions.db import db
from datetime import datetime


class Competition(db.Model):
    """A yearly grant competition (season). Projects/collaborations attach to
    one competition so returning users create fresh projects each year while
    keeping their accounts, profiles and past projects intact."""
    __tablename__ = 'competitions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(100), unique=True, nullable=False)   # e.g. AzTU-DQL-2026
    year = db.Column(db.Integer, nullable=False)
    title = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    application_deadline = db.Column(db.DateTime)
    report_deadline = db.Column(db.DateTime)
    contract_date = db.Column(db.DateTime)
    max_smeta_amount = db.Column(db.Integer, nullable=False, default=50000)
    collaborator_limit = db.Column(db.Integer, nullable=False, default=7)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.String(100))

    @staticmethod
    def get_active():
        return Competition.query.filter_by(is_active=True).first()

    @staticmethod
    def get_active_id():
        active = Competition.get_active()
        return active.id if active else None

    def serialize(self):
        return {
            'id': self.id,
            'code': self.code,
            'year': self.year,
            'title': self.title,
            'is_active': bool(self.is_active),
            'application_deadline': self.application_deadline.isoformat() if self.application_deadline else None,
            'report_deadline': self.report_deadline.isoformat() if self.report_deadline else None,
            'contract_date': self.contract_date.isoformat() if self.contract_date else None,
            'max_smeta_amount': self.max_smeta_amount,
            'collaborator_limit': self.collaborator_limit,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by,
        }

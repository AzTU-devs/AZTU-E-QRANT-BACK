from extentions.db import db
from datetime import datetime

# An expert scores a project out of ten.
MIN_SCORE = 0
MAX_SCORE = 10


class Assessment(db.Model):
    __tablename__ = 'assessment'
    # One verdict per expert per project — scoring again edits the same row
    # rather than stacking up duplicates.
    __table_args__ = (
        db.UniqueConstraint('project_code', 'expert', name='uq_assessment_project_expert'),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_code = db.Column(db.Integer, nullable=False)
    expert = db.Column(db.String, nullable=False)   # the expert's e-mail
    assessment = db.Column(db.Integer)              # score out of 10
    note = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def serialize(self):
        return {
            'id': self.id,
            'project_code': self.project_code,
            'expert': self.expert,
            'assessment': self.assessment,
            'note': self.note,
            'max_score': MAX_SCORE,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

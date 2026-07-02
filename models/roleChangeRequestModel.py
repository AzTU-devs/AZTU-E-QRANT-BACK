from extentions.db import db
from datetime import datetime


class RoleChangeRequest(db.Model):
    __tablename__ = 'role_change_requests'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    fin_kod = db.Column(db.String(100), nullable=False)
    # project_role values: 0 = lead (owner), 1 = member (collaborator)
    current_role = db.Column(db.Integer, nullable=False)
    requested_role = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending / approved / rejected
    admin_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime)
    decided_by = db.Column(db.String(100))

    def serialize(self):
        return {
            'id': self.id,
            'fin_kod': self.fin_kod,
            'current_role': self.current_role,
            'requested_role': self.requested_role,
            'reason': self.reason,
            'status': self.status,
            'admin_note': self.admin_note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'decided_at': self.decided_at.isoformat() if self.decided_at else None,
            'decided_by': self.decided_by,
        }

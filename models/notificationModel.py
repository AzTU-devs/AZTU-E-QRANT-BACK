from extentions.db import db
from datetime import datetime


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    recipient_fin_kod = db.Column(db.String(100), nullable=False, index=True)
    # role_change / message / announcement / competition / general
    type = db.Column(db.String(40), nullable=False, default='general')
    title = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text)
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def serialize(self):
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'body': self.body,
            'link': self.link,
            'is_read': bool(self.is_read),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

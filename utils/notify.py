"""Small helpers to create in-dashboard notifications.

Kept separate from controllers so any feature (role changes, messaging,
announcements) can emit notifications without circular imports.
"""
from datetime import datetime
from extentions.db import db
from models.authModel import Auth
from models.notificationModel import Notification


def create_notification(recipient_fin_kod, title, body=None, type='general', link=None, commit=True):
    notification = Notification(
        recipient_fin_kod=recipient_fin_kod,
        title=title,
        body=body,
        type=type,
        link=link,
        created_at=datetime.utcnow(),
    )
    db.session.add(notification)
    if commit:
        db.session.commit()
    return notification


def notify_admins(title, body=None, type='general', link=None, commit=True):
    """Create a notification for every admin (project_role == 2)."""
    admins = Auth.query.filter_by(project_role=2).all()
    for admin in admins:
        db.session.add(Notification(
            recipient_fin_kod=admin.fin_kod,
            title=title,
            body=body,
            type=type,
            link=link,
            created_at=datetime.utcnow(),
        ))
    if commit:
        db.session.commit()

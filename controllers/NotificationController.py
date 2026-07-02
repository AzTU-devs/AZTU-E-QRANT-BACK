from config.limiter import limiter
from extentions.db import db
from flask import Blueprint, g
from models.notificationModel import Notification
from utils.jwt_required import token_required
from exceptions.exception import handle_specific_not_found, handle_success, handle_global_exception

notification_bp = Blueprint('notification_bp', __name__)


@notification_bp.route('/api/notifications', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def list_notifications():
    """Recent notifications for the signed-in user (newest first)."""
    try:
        fin_kod = g.user.get('fin_kod')
        notifications = (
            Notification.query
            .filter_by(recipient_fin_kod=fin_kod)
            .order_by(Notification.created_at.desc())
            .limit(50)
            .all()
        )
        return handle_success([n.serialize() for n in notifications], "Notifications fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


@notification_bp.route('/api/notifications/unread-count', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def unread_count():
    try:
        fin_kod = g.user.get('fin_kod')
        count = Notification.query.filter_by(recipient_fin_kod=fin_kod, is_read=False).count()
        return handle_success({'count': count}, "Unread count fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


@notification_bp.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def mark_read(notification_id):
    try:
        fin_kod = g.user.get('fin_kod')
        notification = Notification.query.filter_by(id=notification_id, recipient_fin_kod=fin_kod).first()
        if not notification:
            return handle_specific_not_found('Notification not found.')
        notification.is_read = True
        db.session.commit()
        return handle_success(notification.serialize(), "Notification marked as read.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@notification_bp.route('/api/notifications/read-all', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 1, 2])
def mark_all_read():
    try:
        fin_kod = g.user.get('fin_kod')
        Notification.query.filter_by(recipient_fin_kod=fin_kod, is_read=False).update({'is_read': True})
        db.session.commit()
        return handle_success({'ok': True}, "All notifications marked as read.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))

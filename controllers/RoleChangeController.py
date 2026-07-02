from datetime import datetime
from config.limiter import limiter
from extentions.db import db
from flask import Blueprint, request, g, render_template
from models.authModel import Auth
from models.userModel import User
from models.roleChangeRequestModel import RoleChangeRequest
from utils.jwt_required import token_required
from utils.email_util import send_email
from utils.notify import create_notification, notify_admins
from exceptions.exception import (
    handle_missing_field,
    handle_specific_not_found,
    handle_success,
    handle_global_exception,
)
import logging

logger = logging.getLogger(__name__)

role_change_bp = Blueprint('role_change_bp', __name__)

# 0 = lead (owner), 1 = member (collaborator)
VALID_ROLES = (0, 1)
ROLE_LABELS_AZ = {0: "Layihə rəhbəri", 1: "İcraçı"}


def _user_name(fin_kod):
    user = User.query.filter_by(fin_kod=fin_kod).first()
    if not user:
        return {"name": None, "surname": None, "email": None}
    return {
        "name": user.name,
        "surname": user.surname,
        "email": user.personal_email or user.work_email,
    }


@role_change_bp.route('/api/role-change', methods=['POST'])
@limiter.limit("20 per second")
@token_required([0, 1])
def create_role_change_request():
    """A user (lead or member) requests to switch to the other role."""
    try:
        data = request.get_json() or {}
        fin_kod = g.user.get('fin_kod')

        auth = Auth.query.filter_by(fin_kod=fin_kod).first()
        if not auth:
            return handle_specific_not_found('User not found.')

        current_role = auth.project_role
        requested_role = data.get('requested_role')

        if requested_role is None:
            return handle_missing_field('requested_role')
        try:
            requested_role = int(requested_role)
        except (TypeError, ValueError):
            return handle_missing_field('requested_role')

        if requested_role not in VALID_ROLES:
            return {"status": 400, "message": "Yalnız rəhbər və icraçı rolları arasında dəyişiklik mümkündür."}, 400
        if requested_role == current_role:
            return {"status": 400, "message": "Siz artıq bu roldasınız."}, 400

        # Block a second pending request.
        existing = RoleChangeRequest.query.filter_by(fin_kod=fin_kod, status='pending').first()
        if existing:
            return {"status": 409, "message": "Sizin artıq gözləyən rol dəyişiklik sorğunuz var."}, 409

        req = RoleChangeRequest(
            fin_kod=fin_kod,
            current_role=current_role,
            requested_role=requested_role,
            reason=(data.get('reason') or '').strip() or None,
            status='pending',
            created_at=datetime.utcnow(),
        )
        db.session.add(req)
        db.session.commit()

        # Notify admins in their dashboard that a request awaits review.
        info = _user_name(fin_kod)
        full_name = " ".join(filter(None, [info.get('name'), info.get('surname')])) or fin_kod
        try:
            notify_admins(
                title="Yeni rol dəyişiklik sorğusu",
                body=f"{full_name} — {ROLE_LABELS_AZ.get(current_role, '')} → {ROLE_LABELS_AZ.get(requested_role, '')}",
                type='role_change',
                link='/role-change-requests',
            )
        except Exception:
            logger.exception("Failed to notify admins of role-change request")

        return handle_success(req.serialize(), "Rol dəyişiklik sorğusu göndərildi.")
    except Exception as e:
        db.session.rollback()
        logger.exception("create_role_change_request failed")
        return handle_global_exception(str(e))


@role_change_bp.route('/api/role-change/mine', methods=['GET'])
@limiter.limit("50 per second")
@token_required([0, 1])
def my_role_change_requests():
    """The signed-in user's own requests (history)."""
    try:
        fin_kod = g.user.get('fin_kod')
        requests_ = (
            RoleChangeRequest.query
            .filter_by(fin_kod=fin_kod)
            .order_by(RoleChangeRequest.created_at.desc())
            .all()
        )
        return handle_success([r.serialize() for r in requests_], "Requests fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


@role_change_bp.route('/api/role-change/pending', methods=['GET'])
@limiter.limit("50 per second")
@token_required([2])
def pending_role_change_requests():
    """Admin: all pending requests, enriched with the requester's name."""
    try:
        requests_ = (
            RoleChangeRequest.query
            .filter_by(status='pending')
            .order_by(RoleChangeRequest.created_at.asc())
            .all()
        )
        data = []
        for r in requests_:
            item = r.serialize()
            item['user'] = _user_name(r.fin_kod)
            data.append(item)
        return handle_success(data, "Pending requests fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


def _decide(request_id, approve, admin_note=None):
    req = RoleChangeRequest.query.get(request_id)
    if not req:
        return None, handle_specific_not_found('Request not found.')
    if req.status != 'pending':
        return None, ({"status": 409, "message": "Bu sorğu artıq cavablandırılıb."}, 409)

    decided_by = g.user.get('fin_kod') if getattr(g, 'user', None) else None
    req.decided_at = datetime.utcnow()
    req.decided_by = decided_by
    req.admin_note = (admin_note or '').strip() or None

    if approve:
        auth = Auth.query.filter_by(fin_kod=req.fin_kod).first()
        if not auth:
            return None, handle_specific_not_found('User not found.')
        # Flip the role. Per product decision, existing projects/collaborations
        # are kept in history and are NOT deleted.
        auth.project_role = req.requested_role
        req.status = 'approved'
    else:
        req.status = 'rejected'

    db.session.commit()
    return req, None


def _notify(req):
    """Inform the requester of the decision via BOTH the dashboard notification
    tab and email."""
    approved = req.status == 'approved'
    title = "Rol dəyişikliyi " + ("təsdiqləndi" if approved else "rədd edildi")
    body = (
        f"Yeni rolunuz: {ROLE_LABELS_AZ.get(req.requested_role, '')}."
        if approved
        else (req.admin_note or "Sorğunuz rədd edildi.")
    )
    # In-dashboard notification (best-effort).
    try:
        create_notification(
            recipient_fin_kod=req.fin_kod,
            title=title,
            body=body,
            type='role_change',
            link='/role-change',
        )
    except Exception:
        logger.exception("Failed to create role-change notification")

    # Email (best-effort).
    info = _user_name(req.fin_kod)
    recipient = info.get('email')
    if not recipient:
        return
    subject = "Rol dəyişiklik sorğusu" + (" təsdiqləndi" if approved else " rədd edildi")
    try:
        html_content = render_template(
            "email/role_change_result.html",
            approved=approved,
            name=info.get('name'),
            surname=info.get('surname'),
            requested_role=ROLE_LABELS_AZ.get(req.requested_role, ""),
            admin_note=req.admin_note,
        )
        send_email(subject, recipient, html_content)
    except Exception:
        logger.exception("Failed to send role-change email")


@role_change_bp.route('/api/role-change/<int:request_id>/approve', methods=['POST'])
@limiter.limit("20 per second")
@token_required([2])
def approve_role_change(request_id):
    try:
        data = request.get_json(silent=True) or {}
        req, err = _decide(request_id, approve=True, admin_note=data.get('admin_note'))
        if err:
            return err
        _notify(req)
        return handle_success(req.serialize(), "Rol dəyişikliyi təsdiqləndi.")
    except Exception as e:
        db.session.rollback()
        logger.exception("approve_role_change failed")
        return handle_global_exception(str(e))


@role_change_bp.route('/api/role-change/<int:request_id>/reject', methods=['POST'])
@limiter.limit("20 per second")
@token_required([2])
def reject_role_change(request_id):
    try:
        data = request.get_json(silent=True) or {}
        req, err = _decide(request_id, approve=False, admin_note=data.get('admin_note'))
        if err:
            return err
        _notify(req)
        return handle_success(req.serialize(), "Rol dəyişikliyi rədd edildi.")
    except Exception as e:
        db.session.rollback()
        logger.exception("reject_role_change failed")
        return handle_global_exception(str(e))

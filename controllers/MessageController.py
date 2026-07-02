import os
import uuid
import logging
from datetime import datetime
from config.limiter import limiter
from extentions.db import db
from flask import Blueprint, request, g, current_app, send_file, render_template
from werkzeug.utils import secure_filename
from models.authModel import Auth
from models.userModel import User
from models.messageModel import MessageThread, Message, MessageAttachment
from utils.jwt_required import token_required
from utils.email_util import send_email
from utils.notify import create_notification, notify_admins
from exceptions.exception import (
    handle_specific_not_found,
    handle_success,
    handle_global_exception,
)

logger = logging.getLogger(__name__)

message_bp = Blueprint('message_bp', __name__)


# ---------------------------------------------------------------- helpers ----

def _files_folder():
    folder = current_app.config['MESSAGE_FILES_FOLDER']
    os.makedirs(folder, exist_ok=True)
    return folder


def _allowed(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config['ALLOWED_MESSAGE_EXTENSIONS']


def _get_or_create_thread(user_fin_kod):
    thread = MessageThread.query.filter_by(user_fin_kod=user_fin_kod).first()
    if not thread:
        thread = MessageThread(user_fin_kod=user_fin_kod, created_at=datetime.utcnow(),
                               last_message_at=datetime.utcnow())
        db.session.add(thread)
        db.session.flush()
    return thread


def _user_display(fin_kod):
    user = User.query.filter_by(fin_kod=fin_kod).first()
    if not user:
        return {"name": None, "surname": None, "email": None}
    return {
        "name": user.name,
        "surname": user.surname,
        "email": user.work_email or user.personal_email,
    }


def _save_attachments(message, files):
    """Validate + persist uploaded files as MessageAttachment rows. Returns
    (ok, error_response). Accepts all configured document and image types."""
    folder = _files_folder()
    max_size = current_app.config['MAX_MESSAGE_FILE_SIZE']
    for file in files:
        if not file or not file.filename:
            continue
        if not _allowed(file.filename):
            allowed = ', '.join(sorted(current_app.config['ALLOWED_MESSAGE_EXTENSIONS']))
            return False, ({"status": 400, "message": f"'{file.filename}' faylı qəbul edilmir. İcazə verilən növlər: {allowed}"}, 400)

        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > max_size:
            return False, ({"status": 400, "message": f"'{file.filename}' faylı çox böyükdür (maks. {max_size // (1024 * 1024)} MB)"}, 400)

        original_name = secure_filename(file.filename) or 'file'
        ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else 'bin'
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(folder, stored_name))

        db.session.add(MessageAttachment(
            message_id=message.id,
            original_filename=original_name,
            stored_filename=stored_name,
            content_type=file.mimetype,
            file_size=size,
        ))
    return True, None


def _preview(body, attachment_count):
    if body:
        return body[:80]
    if attachment_count:
        return f"📎 {attachment_count} fayl"
    return ""


def _admin_email():
    return os.getenv('ADMIN_EMAIL') or os.getenv('SMTP_USER')


def _send_message_email(recipient, sender_name, preview):
    if not recipient:
        return
    try:
        html = render_template("email/new_message.html", sender_name=sender_name, preview=preview)
        send_email("Yeni mesaj — AzTU E-Qrant", recipient, html)
    except Exception:
        logger.exception("Failed to send message email")


# ------------------------------------------------------------------ user ----

@message_bp.route('/api/messages/thread', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1])
def get_my_thread():
    """The user's single chat with admin. Marks admin messages as read."""
    try:
        fin_kod = g.user.get('fin_kod')
        thread = _get_or_create_thread(fin_kod)
        # mark admin -> user messages as read
        Message.query.filter_by(thread_id=thread.id, sender_type='admin', is_read=False).update({'is_read': True})
        db.session.commit()
        return handle_success(thread.serialize(with_messages=True), "Thread fetched successfully.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@message_bp.route('/api/messages/thread', methods=['POST'])
@limiter.limit("50 per second")
@token_required([0, 1])
def send_message_as_user():
    """Send a message (text and/or attachments) to admin."""
    try:
        fin_kod = g.user.get('fin_kod')
        body = (request.form.get('body') or '').strip()
        files = request.files.getlist('files')

        if not body and not any(f and f.filename for f in files):
            return {"status": 400, "message": "Mesaj boş ola bilməz."}, 400

        thread = _get_or_create_thread(fin_kod)
        message = Message(thread_id=thread.id, sender_type='user', sender_fin_kod=fin_kod,
                          body=body or None, is_read=False, created_at=datetime.utcnow())
        db.session.add(message)
        db.session.flush()

        ok, err = _save_attachments(message, files)
        if not ok:
            db.session.rollback()
            return err

        thread.last_message_at = datetime.utcnow()
        db.session.commit()

        # Notify admins (dashboard bell + email).
        info = _user_display(fin_kod)
        sender_name = " ".join(filter(None, [info.get('name'), info.get('surname')])) or fin_kod
        preview = _preview(body, len(message.attachments))
        try:
            notify_admins(title=f"Yeni mesaj: {sender_name}", body=preview, type='message', link='/messages-admin')
        except Exception:
            logger.exception("notify_admins failed")
        _send_message_email(_admin_email(), sender_name, preview)

        return handle_success(message.serialize(), "Mesaj göndərildi.")
    except Exception as e:
        db.session.rollback()
        logger.exception("send_message_as_user failed")
        return handle_global_exception(str(e))


@message_bp.route('/api/messages/unread-count', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1])
def my_unread_messages():
    try:
        fin_kod = g.user.get('fin_kod')
        thread = MessageThread.query.filter_by(user_fin_kod=fin_kod).first()
        if not thread:
            return handle_success({'count': 0}, "ok")
        count = Message.query.filter_by(thread_id=thread.id, sender_type='admin', is_read=False).count()
        return handle_success({'count': count}, "ok")
    except Exception as e:
        return handle_global_exception(str(e))


# ----------------------------------------------------------------- admin ----

@message_bp.route('/api/messages/threads', methods=['GET'])
@limiter.limit("100 per second")
@token_required([2])
def list_threads():
    """Admin inbox: every user's chat with last message + unread count."""
    try:
        threads = MessageThread.query.order_by(MessageThread.last_message_at.desc()).all()
        data = []
        for t in threads:
            last = Message.query.filter_by(thread_id=t.id).order_by(Message.created_at.desc()).first()
            unread = Message.query.filter_by(thread_id=t.id, sender_type='user', is_read=False).count()
            info = _user_display(t.user_fin_kod)
            data.append({
                'id': t.id,
                'user_fin_kod': t.user_fin_kod,
                'user': info,
                'last_message_at': t.last_message_at.isoformat() if t.last_message_at else None,
                'last_preview': _preview(last.body if last else None, len(last.attachments) if last else 0),
                'unread': unread,
            })
        return handle_success(data, "Threads fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


@message_bp.route('/api/messages/threads/<string:user_fin_kod>', methods=['GET'])
@limiter.limit("100 per second")
@token_required([2])
def get_thread_admin(user_fin_kod):
    try:
        thread = _get_or_create_thread(user_fin_kod)
        Message.query.filter_by(thread_id=thread.id, sender_type='user', is_read=False).update({'is_read': True})
        db.session.commit()
        data = thread.serialize(with_messages=True)
        data['user'] = _user_display(user_fin_kod)
        return handle_success(data, "Thread fetched successfully.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@message_bp.route('/api/messages/threads/<string:user_fin_kod>', methods=['POST'])
@limiter.limit("50 per second")
@token_required([2])
def send_message_as_admin(user_fin_kod):
    try:
        admin_fin = g.user.get('fin_kod')
        body = (request.form.get('body') or '').strip()
        files = request.files.getlist('files')

        if not body and not any(f and f.filename for f in files):
            return {"status": 400, "message": "Mesaj boş ola bilməz."}, 400

        thread = _get_or_create_thread(user_fin_kod)
        message = Message(thread_id=thread.id, sender_type='admin', sender_fin_kod=admin_fin,
                          body=body or None, is_read=False, created_at=datetime.utcnow())
        db.session.add(message)
        db.session.flush()

        ok, err = _save_attachments(message, files)
        if not ok:
            db.session.rollback()
            return err

        thread.last_message_at = datetime.utcnow()
        db.session.commit()

        # Notify the user (dashboard bell + email).
        preview = _preview(body, len(message.attachments))
        try:
            create_notification(recipient_fin_kod=user_fin_kod, title="Admindən yeni mesaj",
                                body=preview, type='message', link='/messages')
        except Exception:
            logger.exception("create_notification failed")
        info = _user_display(user_fin_kod)
        _send_message_email(info.get('email'), "Admin", preview)

        return handle_success(message.serialize(), "Mesaj göndərildi.")
    except Exception as e:
        db.session.rollback()
        logger.exception("send_message_as_admin failed")
        return handle_global_exception(str(e))


# --------------------------------------------------------------- download ----

@message_bp.route('/api/messages/attachment/<int:attachment_id>', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def download_attachment(attachment_id):
    try:
        attachment = MessageAttachment.query.get(attachment_id)
        if not attachment:
            return handle_specific_not_found('Attachment not found.')

        # Authorize: admins can access any; a user only their own thread.
        message = Message.query.get(attachment.message_id)
        thread = MessageThread.query.get(message.thread_id) if message else None
        is_admin = g.user.get('role') == 2
        if not is_admin and (not thread or thread.user_fin_kod != g.user.get('fin_kod')):
            return {"status": 403, "message": "Bu fayla girişiniz yoxdur."}, 403

        path = os.path.join(current_app.config['MESSAGE_FILES_FOLDER'], attachment.stored_filename)
        if not os.path.exists(path):
            return handle_specific_not_found('File not found on server.')

        return send_file(
            path,
            as_attachment=False,
            download_name=attachment.original_filename,
            mimetype=attachment.content_type or 'application/octet-stream',
        )
    except Exception as e:
        return handle_global_exception(str(e))

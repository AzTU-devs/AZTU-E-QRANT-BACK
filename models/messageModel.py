from extentions.db import db
from datetime import datetime


class MessageThread(db.Model):
    """One WhatsApp-style conversation per user, between that user and the
    admins (shared support side)."""
    __tablename__ = 'message_threads'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_fin_kod = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow)

    messages = db.relationship(
        'Message',
        backref='thread',
        cascade='all, delete-orphan',
        order_by='Message.created_at',
        lazy='select',
    )

    def serialize(self, with_messages=False):
        data = {
            'id': self.id,
            'user_fin_kod': self.user_fin_kod,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_message_at': self.last_message_at.isoformat() if self.last_message_at else None,
        }
        if with_messages:
            data['messages'] = [m.serialize() for m in self.messages]
        return data


class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    thread_id = db.Column(db.Integer, db.ForeignKey('message_threads.id', ondelete='CASCADE'), nullable=False)
    sender_type = db.Column(db.String(10), nullable=False)   # 'user' or 'admin'
    sender_fin_kod = db.Column(db.String(100))
    body = db.Column(db.Text)
    is_read = db.Column(db.Boolean, nullable=False, default=False)  # read by the recipient side
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    attachments = db.relationship(
        'MessageAttachment',
        backref='message',
        cascade='all, delete-orphan',
        lazy='select',
    )

    def serialize(self):
        return {
            'id': self.id,
            'thread_id': self.thread_id,
            'sender_type': self.sender_type,
            'sender_fin_kod': self.sender_fin_kod,
            'body': self.body,
            'is_read': bool(self.is_read),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'attachments': [a.serialize() for a in self.attachments],
        }


class MessageAttachment(db.Model):
    __tablename__ = 'message_attachments'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    content_type = db.Column(db.String(120))
    file_size = db.Column(db.BigInteger)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def serialize(self):
        content_type = self.content_type or ''
        is_image = content_type.startswith('image/')
        return {
            'id': self.id,
            'original_filename': self.original_filename,
            'content_type': self.content_type,
            'file_size': self.file_size,
            'is_image': is_image,
            'url': f"/api/messages/attachment/{self.id}",
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

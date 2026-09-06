from extentions.db import db
from datetime import datetime

# `Auth.project_role` value that marks an expert account. Kept here beside the
# model so every controller agrees on it: 0 = lead, 1 = executor, 2 = admin.
EXPERT_ROLE = 3


class Expert(db.Model):
    __tablename__ = 'experts'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.Text, nullable=False, unique=True)
    name = db.Column(db.Text, nullable=False)
    surname = db.Column(db.Text, nullable=False)
    father_name = db.Column(db.Text, nullable=False)
    personal_id_serial_number = db.Column(db.Text, nullable=False, unique=True)
    work_place = db.Column(db.Text)
    duty = db.Column(db.Text)
    scientific_degree = db.Column(db.Text)
    phone_number = db.Column(db.Text)

    # An expert may only be assigned once their address has proved it can
    # receive mail — they are told about the assignment, and given their
    # one-time password, entirely by e-mail.
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    verification_token = db.Column(db.String(64), index=True)
    verification_sent_at = db.Column(db.DateTime)
    email_verified_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def full_name(self):
        return ' '.join(filter(None, [self.name, self.surname, self.father_name]))

    def serialize(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'surname': self.surname,
            'father_name': self.father_name,
            'personal_id_serial_number': self.personal_id_serial_number,
            'work_place': self.work_place,
            'duty': self.duty,
            'scientific_degree': self.scientific_degree,
            'phone_number': self.phone_number,
            'email_verified': bool(self.email_verified),
            'verification_sent_at': self.verification_sent_at.isoformat() if self.verification_sent_at else None,
            'email_verified_at': self.email_verified_at.isoformat() if self.email_verified_at else None,
        }

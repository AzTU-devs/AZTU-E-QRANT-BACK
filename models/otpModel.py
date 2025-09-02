from extentions.db import db

class Otp(db.Model):
    __tablename__ = 'otp'

    id = db.Column(db.Integer, primary_key=True)
    otp = db.Column(db.Integer, nullable=False)
    fin_kod = db.Column(db.String, nullable=False)
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
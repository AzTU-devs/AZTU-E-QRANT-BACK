from extentions.db import db

class Institution(db.Model):
    __tablename__ = 'institution'

    id = db.Column(db.Integer, primary_key=True)
    institution_code = db.Column(db.String, unique=True, nullable=False)
    institution_name = db.Column(db.String, unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
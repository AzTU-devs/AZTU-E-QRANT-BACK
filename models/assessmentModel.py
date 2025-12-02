from extentions.db import db
from flask_sqlalchemy import SQLAlchemy

class Assessment(db.Model):
    __tablename__ = 'assessment'

    id = db.Column(db.Integer, primary_key=True)
    project_code = db.Column(db.Integer, nullable=False)
    expert = db.Column(db.String, nullable = False)
    assessment = db.Column(db.Integer)
    note = db.Column(db.String)
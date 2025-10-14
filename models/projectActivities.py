from extentions.db import db
from datetime import datetime

class ProjectActivities(db.Model):
    __tablename__ = 'project_activities'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_code = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    activity_name = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
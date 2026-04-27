from extentions.db import db
from datetime import datetime


class QuarterlyReport(db.Model):
    __tablename__ = 'quarterly_reports'

    id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_code   = db.Column(db.String(50), nullable=False)
    quarter_number = db.Column(db.Integer, nullable=False)
    year           = db.Column(db.Integer, nullable=False)

    point_1  = db.Column(db.Text)
    point_2  = db.Column(db.Text)
    point_3  = db.Column(db.Text)
    point_4  = db.Column(db.Text)
    point_5  = db.Column(db.Text)
    point_6  = db.Column(db.Text)
    point_7  = db.Column(db.Text)
    point_8  = db.Column(db.Text)
    point_9  = db.Column(db.Text)
    point_10 = db.Column(db.Text)
    point_11 = db.Column(db.Text)
    point_12 = db.Column(db.Text)
    point_13 = db.Column(db.Text)
    point_14 = db.Column(db.Text)
    point_15 = db.Column(db.Text)
    point_16 = db.Column(db.Text)
    point_17 = db.Column(db.Text)

    submission_date = db.Column(db.DateTime, default=datetime.utcnow)

    def serialize(self):
        return {
            "id": self.id,
            "project_code": self.project_code,
            "quarter_number": self.quarter_number,
            "year": self.year,
            **{f"point_{i}": getattr(self, f"point_{i}") for i in range(1, 18)},
            "submission_date": self.submission_date.isoformat() if self.submission_date else None,
        }

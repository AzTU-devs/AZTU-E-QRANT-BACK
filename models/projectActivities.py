from extentions.db import db
from datetime import datetime


def parse_months(value):
    """Normalise whatever the clients send into a sorted list of month numbers.

    Accepts a list, a single int, or a comma-separated string, because the
    activity table has been read and written in all three shapes over time.
    Anything outside 1-12 is dropped rather than stored.
    """
    if value is None:
        return []

    if isinstance(value, int):
        raw = [value]
    elif isinstance(value, str):
        raw = value.split(',')
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        return []

    months = set()
    for item in raw:
        try:
            month = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12:
            months.add(month)

    return sorted(months)


class ProjectActivities(db.Model):
    __tablename__ = 'project_activities'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_code = db.Column(db.Integer, nullable=False)
    # The FIRST month of the activity. Kept alongside `months` because it is
    # NOT NULL in the existing table and older rows carry nothing else.
    month = db.Column(db.Integer, nullable=False)
    # Every month the activity runs in, comma-separated ("3,4,5"). An activity
    # may span several months; `month` stays the earliest of them.
    months = db.Column(db.String)
    activity_name = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    def month_list(self):
        """The months this activity runs in, oldest rows included."""
        return parse_months(self.months) or parse_months(self.month)

    def set_months(self, value):
        """Write both columns from any accepted shape. Returns the parsed list."""
        months = parse_months(value)
        if not months:
            return []
        self.months = ','.join(str(m) for m in months)
        self.month = months[0]
        return months

    def serialize(self):
        months = self.month_list()
        return {
            'id': self.id,
            'activity_name': self.activity_name,
            # `month` is the first one, for clients written when an activity
            # could only ever occupy a single month.
            'month': months[0] if months else self.month,
            'months': months,
            'project_code': self.project_code,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

from extentions.db import db


class SystemLock(db.Model):
    """Single-row flag that closes budget (smeta) and activity-plan editing.

    Lives in its own module so the access guards in `utils/access.py` can read
    it without importing a controller.
    """
    __tablename__ = "system_lock"
    id = db.Column(db.Integer, primary_key=True)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)

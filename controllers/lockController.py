from flask import Blueprint, jsonify
from models.smetaModels.salaryModel import db
from sqlalchemy.exc import SQLAlchemyError

lock_bp = Blueprint("lock", __name__)

# Database model for lock state
class SystemLock(db.Model):
    __tablename__ = "system_lock"
    id = db.Column(db.Integer, primary_key=True)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)

def set_lock(value: bool):
    lock = SystemLock.query.first()
    if not lock:
        lock = SystemLock(is_locked=value)
        db.session.add(lock)
    else:
        lock.is_locked = value
    db.session.commit()

@lock_bp.route("/api/lock-status", methods=["GET"])
def lock_status():
    try:
        lock_status = SystemLock.query.first()

        # No lock row yet → system is unlocked by default
        return jsonify({"locked": lock_status.is_locked if lock_status else False})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Database error"}), 500

@lock_bp.route("/api/lock", methods=["POST"])
def lock():
    try:
        set_lock(True)
        return jsonify({"message": "Locked successfully", "locked": True})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Database error"}), 500

@lock_bp.route("/api/unlock", methods=["POST"])
def unlock():
    try:
        set_lock(False)
        return jsonify({"message": "Unlocked successfully", "locked": False})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Database error"}), 500
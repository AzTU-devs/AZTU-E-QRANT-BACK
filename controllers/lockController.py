from flask import Blueprint, jsonify
from extentions.db import db
from sqlalchemy.exc import SQLAlchemyError
from config.limiter import limiter
from models.systemLockModel import SystemLock
from utils.jwt_required import token_required

lock_bp = Blueprint("lock", __name__)

def set_lock(value: bool):
    lock = SystemLock.query.first()
    if not lock:
        lock = SystemLock(is_locked=value)
        db.session.add(lock)
    else:
        lock.is_locked = value
    db.session.commit()

@lock_bp.route("/api/lock-status", methods=["GET"])
@limiter.limit("300 per minute")
@token_required([0, 1, 2, 3])
def lock_status():
    # Requires a token: the system's lock state is internal operational
    # information and was previously readable anonymously (pentest F10).
    try:
        lock_status = SystemLock.query.first()

        # No lock row yet → system is unlocked by default
        return jsonify({"locked": lock_status.is_locked if lock_status else False})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Database error"}), 500

@lock_bp.route("/api/lock", methods=["POST"])
@limiter.limit("120 per minute")
@token_required([2])
def lock():
    # Admin-only. This flips the whole platform into a read-only "locked" state;
    # it previously had NO authentication, so any anonymous caller could lock or
    # unlock the entire system (a gap the report's probe of `/lock` missed
    # because the real route is `/api/lock`).
    try:
        set_lock(True)
        return jsonify({"message": "Locked successfully", "locked": True})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Database error"}), 500

@lock_bp.route("/api/unlock", methods=["POST"])
@limiter.limit("120 per minute")
@token_required([2])
def unlock():
    # Admin-only (see `lock` above).
    try:
        set_lock(False)
        return jsonify({"message": "Unlocked successfully", "locked": False})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Database error"}), 500
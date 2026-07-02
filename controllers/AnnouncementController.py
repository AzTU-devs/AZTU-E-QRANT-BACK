from datetime import datetime
from config.limiter import limiter
from extentions.db import db
from flask import Blueprint, request, g, current_app
from models.announcementModel import Announcement
from utils.jwt_required import token_required
from exceptions.exception import (
    handle_missing_field,
    handle_specific_not_found,
    handle_success,
    handle_global_exception,
)

announcement_bp = Blueprint('announcement_bp', __name__)


@announcement_bp.route('/api/announcements', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def get_announcements():
    """Published announcements for authenticated user dashboards (all roles)."""
    try:
        announcements = (
            Announcement.query
            .filter_by(published=True)
            .order_by(Announcement.created_at.desc())
            .all()
        )
        data = [a.serialize() for a in announcements]
        return handle_success(data, "Announcements fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


@announcement_bp.route('/api/admin/announcements', methods=['GET'])
@limiter.limit("100 per second")
@token_required([2])
def get_all_announcements():
    """All announcements (published + drafts) for admin management."""
    try:
        announcements = (
            Announcement.query
            .order_by(Announcement.created_at.desc())
            .all()
        )
        data = [a.serialize() for a in announcements]
        return handle_success(data, "Announcements fetched successfully.")
    except Exception as e:
        return handle_global_exception(str(e))


@announcement_bp.route('/api/announcements', methods=['POST'])
@limiter.limit("10 per second")
@token_required([2])
def create_announcement():
    try:
        data = request.get_json() or {}
        title = (data.get('title') or '').strip()
        content = (data.get('content') or '').strip()

        if not title or not content:
            return handle_missing_field('title/content')

        published = data.get('published')
        published = True if published is None else bool(published)

        created_by = g.user.get('fin_kod') if getattr(g, 'user', None) else None

        announcement = Announcement(
            title=title,
            content=content,
            published=published,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )
        db.session.add(announcement)
        db.session.commit()

        return handle_success(announcement.serialize(), "Announcement created successfully.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@announcement_bp.route('/api/announcements/<int:announcement_id>', methods=['PATCH'])
@limiter.limit("10 per second")
@token_required([2])
def update_announcement(announcement_id):
    try:
        announcement = Announcement.query.get(announcement_id)
        if not announcement:
            return handle_specific_not_found('Announcement not found.')

        data = request.get_json() or {}

        if 'title' in data:
            new_title = (data.get('title') or '').strip()
            if not new_title:
                return handle_missing_field('title')
            announcement.title = new_title

        if 'content' in data:
            new_content = (data.get('content') or '').strip()
            if not new_content:
                return handle_missing_field('content')
            announcement.content = new_content

        if 'published' in data:
            announcement.published = bool(data.get('published'))

        announcement.updated_at = datetime.utcnow()
        db.session.commit()

        return handle_success(announcement.serialize(), "Announcement updated successfully.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@announcement_bp.route('/api/announcements/<int:announcement_id>', methods=['DELETE'])
@limiter.limit("10 per second")
@token_required([2])
def delete_announcement(announcement_id):
    try:
        announcement = Announcement.query.get(announcement_id)
        if not announcement:
            return handle_specific_not_found('Announcement not found.')

        db.session.delete(announcement)
        db.session.commit()

        return handle_success({'id': announcement_id}, "Announcement deleted successfully.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))

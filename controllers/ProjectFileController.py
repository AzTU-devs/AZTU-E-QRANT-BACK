import os
import uuid
import logging
from extentions.db import db
from config.limiter import limiter
from flask import Blueprint, request, current_app, send_file, g
from werkzeug.utils import secure_filename
from models.projectFileModel import ProjectFile
from utils.jwt_required import token_required
from exceptions.exception import handle_specific_not_found, handle_success, handle_global_exception

logger = logging.getLogger(__name__)

project_file_bp = Blueprint('project_file_bp', __name__)


def _folder():
    folder = current_app.config['PROJECT_FILES_FOLDER']
    os.makedirs(folder, exist_ok=True)
    return folder


def _allowed(filename):
    if '.' not in filename:
        return False
    return filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_PROJECT_FILE_EXTENSIONS']


@project_file_bp.route('/api/project/<int:project_code>/files', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def list_project_files(project_code):
    try:
        files = (
            ProjectFile.query
            .filter_by(project_code=project_code)
            .order_by(ProjectFile.uploaded_at.desc())
            .all()
        )
        return handle_success([f.serialize() for f in files], "Project files fetched.")
    except Exception as e:
        return handle_global_exception(str(e))


@project_file_bp.route('/api/project/<int:project_code>/files', methods=['POST'])
@limiter.limit("30 per second")
@token_required([0, 2])
def upload_project_files(project_code):
    """Upload one or more files to a project — no limit on the number of files."""
    try:
        files = request.files.getlist('files')
        if not files or all(not f or not f.filename for f in files):
            return {"status": 400, "message": "Fayl seçilməyib."}, 400

        folder = _folder()
        max_size = current_app.config['MAX_PROJECT_FILE_SIZE']
        uploaded_by = g.user.get('fin_kod') if getattr(g, 'user', None) else None

        saved = []
        for file in files:
            if not file or not file.filename:
                continue
            if not _allowed(file.filename):
                db.session.rollback()
                allowed = ', '.join(sorted(current_app.config['ALLOWED_PROJECT_FILE_EXTENSIONS']))
                return {"status": 400, "message": f"'{file.filename}' qəbul edilmir. İcazə: {allowed}"}, 400

            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            if size > max_size:
                db.session.rollback()
                mb = max_size // (1024 * 1024)
                return {"status": 400, "message": f"'{file.filename}' çox böyükdür (maks. {mb} MB)."}, 400

            original_name = secure_filename(file.filename) or 'file'
            ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else 'bin'
            stored_name = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(folder, stored_name))

            record = ProjectFile(
                project_code=project_code,
                original_filename=original_name,
                stored_filename=stored_name,
                content_type=file.mimetype,
                file_size=size,
                uploaded_by=uploaded_by,
            )
            db.session.add(record)
            saved.append(record)

        db.session.commit()
        return handle_success([f.serialize() for f in saved], "Fayllar yükləndi.")
    except Exception as e:
        db.session.rollback()
        logger.exception("upload_project_files failed")
        return handle_global_exception(str(e))


@project_file_bp.route('/api/project/files/<int:file_id>', methods=['DELETE'])
@limiter.limit("30 per second")
@token_required([0, 2])
def delete_project_file(file_id):
    try:
        record = ProjectFile.query.get(file_id)
        if not record:
            return handle_specific_not_found('File not found.')

        path = os.path.join(current_app.config['PROJECT_FILES_FOLDER'], record.stored_filename)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

        db.session.delete(record)
        db.session.commit()
        return handle_success({'id': file_id}, "Fayl silindi.")
    except Exception as e:
        db.session.rollback()
        return handle_global_exception(str(e))


@project_file_bp.route('/api/project/files/<int:file_id>/download', methods=['GET'])
@limiter.limit("100 per second")
@token_required([0, 1, 2])
def download_project_file(file_id):
    try:
        record = ProjectFile.query.get(file_id)
        if not record:
            return handle_specific_not_found('File not found.')
        path = os.path.join(current_app.config['PROJECT_FILES_FOLDER'], record.stored_filename)
        if not os.path.exists(path):
            return handle_specific_not_found('File not found on server.')
        return send_file(
            path,
            as_attachment=False,
            download_name=record.original_filename,
            mimetype=record.content_type or 'application/octet-stream',
        )
    except Exception as e:
        return handle_global_exception(str(e))

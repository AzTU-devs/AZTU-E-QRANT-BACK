import os
import uuid
import logging
from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.utils import secure_filename
from extentions.db import db
from models.reportModel import QuarterlyReport, ReportFile
from datetime import datetime

logger = logging.getLogger(__name__)

report_bp = Blueprint('report_bp', __name__)

POINT_FIELDS = [f"point_{i}" for i in range(1, 18)]

# Fayl yükləmə yalnız 4-cü rüb üçün icazəlidir
FOURTH_QUARTER = 4


def _allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config['ALLOWED_REPORT_EXTENSIONS']


def _report_files_folder():
    folder = current_app.config['REPORT_FILES_FOLDER']
    os.makedirs(folder, exist_ok=True)
    return folder


def _get_or_create_report(project_code, quarter_number, year):
    report = QuarterlyReport.query.filter_by(
        project_code=project_code,
        quarter_number=quarter_number,
        year=year
    ).first()
    if not report:
        report = QuarterlyReport(
            project_code=project_code,
            quarter_number=quarter_number,
            year=year,
        )
        db.session.add(report)
        db.session.flush()
    return report


@report_bp.route('/api/reports/save', methods=['POST'])
def save_report():
    try:
        data = request.get_json()

        required = ['project_code', 'quarter_number', 'year']
        for field in required:
            if field not in data:
                return jsonify({"error": f"{field} is required"}), 400

        project_code   = int(data['project_code'])
        quarter_number = int(data['quarter_number'])
        year           = int(data['year'])

        report = QuarterlyReport.query.filter_by(
            project_code=project_code,
            quarter_number=quarter_number,
            year=year
        ).first()

        if report:
            for field in POINT_FIELDS:
                if field in data:
                    setattr(report, field, data[field])
            report.submission_date = datetime.utcnow()
            db.session.commit()
            return jsonify({
                "message": "Hesabat yeniləndi",
                "report": report.serialize(),
                "status_code": 200
            }), 200
        else:
            new_report = QuarterlyReport(
                project_code=project_code,
                quarter_number=quarter_number,
                year=year,
                **{field: data.get(field) for field in POINT_FIELDS}
            )
            db.session.add(new_report)
            db.session.commit()
            return jsonify({
                "message": "Hesabat yaradıldı",
                "report": new_report.serialize(),
                "status_code": 201
            }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving report: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@report_bp.route('/api/reports/<int:project_code>/<int:quarter_number>/<int:year>', methods=['GET'])
def get_report(project_code, quarter_number, year):
    try:
        report = QuarterlyReport.query.filter_by(
            project_code=project_code,
            quarter_number=quarter_number,
            year=year
        ).first()

        if not report:
            return jsonify({"message": "Hesabat tapılmadı"}), 404

        return jsonify({
            "message": "Hesabat tapıldı",
            "report": report.serialize(),
            "status_code": 200
        }), 200

    except Exception as e:
        logger.error(f"Error getting report: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@report_bp.route('/api/reports/files/upload', methods=['POST'])
def upload_report_files():
    """4-cü rüb hesabatına bir və ya bir neçə fayl (pdf, doc, docx) əlavə edir."""
    try:
        project_code   = request.form.get('project_code')
        quarter_number = request.form.get('quarter_number')
        year           = request.form.get('year')

        if not all([project_code, quarter_number, year]):
            return jsonify({"error": "project_code, quarter_number və year tələb olunur"}), 400

        project_code   = int(project_code)
        quarter_number = int(quarter_number)
        year           = int(year)

        if quarter_number != FOURTH_QUARTER:
            return jsonify({"error": "Fayl yükləmə yalnız 4-cü rüb üçün mümkündür"}), 400

        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            return jsonify({"error": "Heç bir fayl seçilməyib"}), 400

        max_size = current_app.config['MAX_REPORT_FILE_SIZE']
        folder = _report_files_folder()

        report = _get_or_create_report(project_code, quarter_number, year)

        saved = []
        for file in files:
            if not file or file.filename == '':
                continue

            if not _allowed_file(file.filename):
                db.session.rollback()
                return jsonify({
                    "error": f"'{file.filename}' faylının tipinə icazə verilmir. "
                             f"Yalnız: {', '.join(sorted(current_app.config['ALLOWED_REPORT_EXTENSIONS']))}"
                }), 400

            # Fayl ölçüsünü yoxla
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            if size > max_size:
                db.session.rollback()
                return jsonify({
                    "error": f"'{file.filename}' faylı çox böyükdür (maks. "
                             f"{max_size // (1024 * 1024)} MB)"
                }), 400

            original_name = secure_filename(file.filename) or 'file'
            ext = original_name.rsplit('.', 1)[1].lower()
            stored_name = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(folder, stored_name))

            report_file = ReportFile(
                report_id=report.id,
                original_filename=original_name,
                stored_filename=stored_name,
                content_type=file.mimetype,
                file_size=size,
            )
            db.session.add(report_file)
            saved.append(report_file)

        db.session.commit()

        return jsonify({
            "message": f"{len(saved)} fayl uğurla yükləndi",
            "files": [f.serialize() for f in saved],
            "status_code": 201
        }), 201

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error uploading report files: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@report_bp.route('/api/reports/files/<int:project_code>/<int:quarter_number>/<int:year>', methods=['GET'])
def list_report_files(project_code, quarter_number, year):
    """Verilmiş hesabata aid faylların siyahısını qaytarır."""
    try:
        report = QuarterlyReport.query.filter_by(
            project_code=project_code,
            quarter_number=quarter_number,
            year=year
        ).first()

        if not report:
            return jsonify({"files": [], "status_code": 200}), 200

        return jsonify({
            "files": [f.serialize() for f in report.files],
            "status_code": 200
        }), 200

    except Exception as e:
        logger.error(f"Error listing report files: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@report_bp.route('/api/reports/files/download/<int:file_id>', methods=['GET'])
def download_report_file(file_id):
    """Faylı yükləmək üçün qaytarır."""
    try:
        report_file = ReportFile.query.get(file_id)
        if not report_file:
            return jsonify({"error": "Fayl tapılmadı"}), 404

        path = os.path.join(current_app.config['REPORT_FILES_FOLDER'], report_file.stored_filename)
        if not os.path.exists(path):
            return jsonify({"error": "Fayl serverdə tapılmadı"}), 404

        return send_file(
            path,
            as_attachment=True,
            download_name=report_file.original_filename,
            mimetype=report_file.content_type or 'application/octet-stream',
        )

    except Exception as e:
        logger.error(f"Error downloading report file: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@report_bp.route('/api/reports/files/<int:file_id>', methods=['DELETE'])
def delete_report_file(file_id):
    """Yüklənmiş faylı silir."""
    try:
        report_file = ReportFile.query.get(file_id)
        if not report_file:
            return jsonify({"error": "Fayl tapılmadı"}), 404

        path = os.path.join(current_app.config['REPORT_FILES_FOLDER'], report_file.stored_filename)
        if os.path.exists(path):
            os.remove(path)

        db.session.delete(report_file)
        db.session.commit()

        return jsonify({"message": "Fayl silindi", "status_code": 200}), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting report file: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

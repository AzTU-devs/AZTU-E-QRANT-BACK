from flask import Blueprint, request, jsonify
from extentions.db import db
from models.reportModel import QuarterlyReport
from datetime import datetime

report_bp = Blueprint('report_bp', __name__)

POINT_FIELDS = [f"point_{i}" for i in range(1, 18)]


@report_bp.route('/api/reports/save', methods=['POST'])
def save_report():
    try:
        data = request.get_json()

        required = ['project_code', 'quarter_number', 'year']
        for field in required:
            if field not in data:
                return jsonify({"error": f"{field} is required"}), 400

        project_code   = data['project_code']
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
        return jsonify({"error": str(e)}), 500


@report_bp.route('/api/reports/<project_code>/<int:quarter_number>/<int:year>', methods=['GET'])
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
        return jsonify({"error": str(e)}), 500

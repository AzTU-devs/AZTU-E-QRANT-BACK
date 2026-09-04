from flask import Blueprint, request, jsonify
from extentions.db import db
from models.projectActivities import ProjectActivities, parse_months
from utils.archive_lock import archive_write_blocked

project_activity = Blueprint('project_activity', __name__)

@project_activity.route('/api/project-activity/create', methods=['POST'])
def create_activity():
    try:
        data = request.get_json()
        for field in ['activity_name', 'project_code']:
            if field not in data:
                return jsonify({"error": f"{field} is required"}), 400

        # An activity may span several months. `months` is the current field;
        # `month` is still accepted from clients that send a single value.
        months = parse_months(data.get('months', data.get('month')))
        if not months:
            return jsonify({"error": "months is required (1-12)"}), 400

        blocked = archive_write_blocked(data['project_code'])
        if blocked:
            return blocked

        new_activity = ProjectActivities(
            activity_name=data['activity_name'],
            project_code=data['project_code']
        )
        new_activity.set_months(months)

        db.session.add(new_activity)
        db.session.commit()

        return jsonify({
            "message": "Project activity created successfully",
            "activity": new_activity.serialize(),
            "status_code": 201
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@project_activity.route('/api/project-activity/<int:project_code>', methods=['GET'])
def get_activities_by_project_code(project_code):
    try:
        activities = ProjectActivities.query.filter_by(project_code=project_code).order_by(ProjectActivities.month.asc()).all()

        if not activities:
            return jsonify({"message": "No activities found for this project code"}), 404

        activities_list = [act.serialize() for act in activities]

        return jsonify({
            "message": "Project activities fetched successfully",
            "activities": activities_list,
            "status_code": 200
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@project_activity.route('/api/project-activity/<int:project_code>/<int:month>', methods=['DELETE'])
def delete_activity_by_month(project_code, month):
    try:
        blocked = archive_write_blocked(project_code)
        if blocked:
            return blocked

        # An activity may now cover several months, so match on the full list
        # rather than only on the stored first month.
        activity = next(
            (a for a in ProjectActivities.query.filter_by(project_code=project_code).all()
             if month in a.month_list()),
            None
        )

        if not activity:
            return jsonify({"message": "No activity found for this project code and month"}), 404

        db.session.delete(activity)
        db.session.commit()

        return jsonify({
            "message": f"Activity for project_code {project_code} and month {month} deleted successfully",
            "status_code": 200
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@project_activity.route('/api/project-activity/update/<int:id>', methods=['PATCH'])
def update_activity(id):
    try:
        data = request.get_json()
        activity = ProjectActivities.query.get(id)
        if not activity:
            return jsonify({"message": "Activity not found"}), 404

        blocked = archive_write_blocked(activity.project_code)
        if blocked:
            return blocked

        if 'activity_name' in data:
            activity.activity_name = data['activity_name']
        if 'project_code' in data:
            activity.project_code = data['project_code']

        if 'months' in data or 'month' in data:
            months = parse_months(data.get('months', data.get('month')))
            if not months:
                return jsonify({"error": "months is required (1-12)"}), 400
            activity.set_months(months)

        db.session.commit()

        return jsonify({
            "message": "Project activity updated successfully",
            "activity": activity.serialize(),
            "status_code": 200
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@project_activity.route('/api/project-activity/delete/<int:id>', methods=['DELETE'])
def delete_activity(id):
    try:
        activity = ProjectActivities.query.get(id)
        if not activity:
            return jsonify({"message": "Activity not found"}), 404

        blocked = archive_write_blocked(activity.project_code)
        if blocked:
            return blocked

        db.session.delete(activity)
        db.session.commit()

        return jsonify({
            "message": f"Project activity with ID {id} deleted successfully",
            "status_code": 200
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
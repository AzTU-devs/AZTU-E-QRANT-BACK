from flask import Blueprint, request, jsonify
from extentions.db import db
from config.limiter import limiter
from models.projectActivities import ProjectActivities, parse_months
from utils.jwt_required import token_required
from utils.access import project_read_guard, project_write_guard

project_activity = Blueprint('project_activity', __name__)

# Every write below goes through `project_write_guard`: only the project's lead
# (or an admin) may change its activity plan, archived projects stay read-only
# until an admin unlocks them, and the admin's platform lock is binding here.
# Before, any signed-in lead could rewrite any project's plan by its code.


@project_activity.route('/api/project-activity/create', methods=['POST'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def create_activity():
    try:
        data = request.get_json(silent=True) or {}
        for field in ['activity_name', 'project_code']:
            if field not in data:
                return jsonify({"error": f"{field} is required"}), 400

        # An activity may span several months. `months` is the current field;
        # `month` is still accepted from clients that send a single value.
        months = parse_months(data.get('months', data.get('month')))
        if not months:
            return jsonify({"error": "months is required (1-12)"}), 400

        project, error = project_write_guard(data['project_code'], respect_system_lock=True)
        if error:
            return error

        new_activity = ProjectActivities(
            activity_name=data['activity_name'],
            project_code=project.project_code
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
        db.session.rollback()
        return jsonify({"error": "Internal server error"}), 500

@project_activity.route('/api/project-activity/<int:project_code>', methods=['GET'])
@limiter.limit("300 per minute")
@token_required([0, 1, 2, 3])
def get_activities_by_project_code(project_code):
    try:
        _, error = project_read_guard(project_code)
        if error:
            return error

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
        return jsonify({"error": "Internal server error"}), 500

@project_activity.route('/api/project-activity/<int:project_code>/<int:month>', methods=['DELETE'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def delete_activity_by_month(project_code, month):
    try:
        _, error = project_write_guard(project_code, respect_system_lock=True)
        if error:
            return error

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
        db.session.rollback()
        return jsonify({"error": "Internal server error"}), 500

@project_activity.route('/api/project-activity/update/<int:id>', methods=['PATCH'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def update_activity(id):
    try:
        data = request.get_json(silent=True) or {}
        activity = ProjectActivities.query.get(id)
        if not activity:
            return jsonify({"message": "Activity not found"}), 404

        _, error = project_write_guard(activity.project_code, respect_system_lock=True)
        if error:
            return error

        if 'activity_name' in data:
            activity.activity_name = data['activity_name']
        # `project_code` is deliberately NOT writable: it would let an activity
        # be moved into a project the caller does not own.

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
        db.session.rollback()
        return jsonify({"error": "Internal server error"}), 500

@project_activity.route('/api/project-activity/delete/<int:id>', methods=['DELETE'])
@limiter.limit("300 per minute")
@token_required([0, 2])
def delete_activity(id):
    try:
        activity = ProjectActivities.query.get(id)
        if not activity:
            return jsonify({"message": "Activity not found"}), 404

        _, error = project_write_guard(activity.project_code, respect_system_lock=True)
        if error:
            return error

        db.session.delete(activity)
        db.session.commit()

        return jsonify({
            "message": f"Project activity with ID {id} deleted successfully",
            "status_code": 200
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Internal server error"}), 500

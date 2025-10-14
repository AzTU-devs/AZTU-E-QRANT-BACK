from flask import Blueprint, request, jsonify
from extentions.db import db
from models.projectActivities import ProjectActivities

project_activity = Blueprint('project_activity', __name__)

@project_activity.route('/api/project-activity/create', methods=['POST'])
def create_activity():
    try:
        data = request.get_json()
        required_fields = ['activity_name', 'month', 'project_code']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"{field} is required"}), 400

        new_activity = ProjectActivities(
            activity_name=data['activity_name'],
            month=data['month'],
            project_code=data['project_code']
        )
        
        db.session.add(new_activity)
        db.session.commit()
        
        return jsonify({
            "message": "Project activity created successfully",
            "status_code": 201
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@project_activity.route('/api/project-activity/<int:project_code>', methods=['GET'])
def get_activities_by_project_code(project_code):
    try:
        activities = ProjectActivities.query.filter_by(project_code=project_code).all()

        if not activities:
            return jsonify({"message": "No activities found for this project code"}), 404

        activities_list = []
        for act in activities:
            activities_list.append({
                "id": act.id,
                "activity_name": act.activity_name,
                "month": act.month,
                "project_code": act.project_code,
                "created_at": act.created_at,
                "updated_at": act.updated_at
            })

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
        activity = ProjectActivities.query.filter_by(project_code=project_code, month=month).first()

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

        if 'activity_name' in data:
            activity.activity_name = data['activity_name']
        if 'month' in data:
            activity.month = data['month']
        if 'project_code' in data:
            activity.project_code = data['project_code']

        db.session.commit()

        updated_activity = {
            "id": activity.id,
            "activity_name": activity.activity_name,
            "month": activity.month,
            "project_code": activity.project_code,
            "created_at": activity.created_at,
            "updated_at": activity.updated_at
        }

        return jsonify({
            "message": "Project activity updated successfully",
            "activity": updated_activity,
            "status_code": 200
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
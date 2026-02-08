"""
Admin API Routes
=================

Endpoints for user management (admin-only).
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import admin_required

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/users", methods=["GET"])
@admin_required
def list_users():
    """
    List all users with stats (admin only).

    Returns: [ { "id", "username", "email", "is_admin", "created_at", "last_login", "project_count", "file_count" } ]
    """
    users = dbm.get_all_user()

    result = []
    for user in users:
        user_id, username, email, is_admin, created_at, last_login, project_count, file_count = user
        result.append({
            "id": user_id,
            "username": username,
            "email": email or "",
            "is_admin": is_admin,
            "created_at": str(created_at) if created_at else None,
            "last_login": str(last_login) if last_login else None,
            "project_count": project_count,
            "file_count": file_count,
        })

    return jsonify(result), 200


@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    """
    Delete a user and all their projects (admin only).

    Returns: { "message": str }
    """
    success, message = dbm.delete_user_and_projects(user_id)

    if not success:
        return jsonify({"error": message}), 400

    return jsonify({"message": "User deleted successfully"}), 200


@admin_bp.route("/users/<int:user_id>/password", methods=["PUT"])
@admin_required
def reset_password(user_id):
    """
    Reset a user's password (admin only).

    Body: { "password": str }
    Returns: { "message": str }
    """
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")

    if not password:
        return jsonify({"error": "Password is required"}), 400

    success, error = dbm.admin_reset_user_password(user_id, password)

    if not success:
        return jsonify({"error": error}), 400

    return jsonify({"message": "Password reset successfully"}), 200


@admin_bp.route("/users/<int:user_id>/projects", methods=["GET"])
@admin_required
def user_projects(user_id):
    """
    View a user's projects (admin only).

    Returns: [ { "id", "name", "description", "created_at", "last_accessed", "file_count", "total_size" } ]
    """
    user = dbm.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    projects = dbm.get_user_projects_admin(user_id)

    result = []
    for p in projects:
        proj_id, name, description, created_at, last_accessed, file_count, total_size = p
        result.append({
            "id": proj_id,
            "name": name,
            "description": description or "",
            "created_at": str(created_at) if created_at else None,
            "last_accessed": str(last_accessed) if last_accessed else None,
            "file_count": file_count,
            "total_size_mb": round(total_size / (1024 * 1024), 2) if total_size else 0,
        })

    return jsonify({
        "username": user.username,
        "projects": result,
    }), 200

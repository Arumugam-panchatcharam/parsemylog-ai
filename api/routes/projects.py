"""
Projects API Routes
====================

CRUD endpoints for project management.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id

projects_bp = Blueprint("projects", __name__)


@projects_bp.route("/", methods=["GET"])
@jwt_required()
def list_projects():
    """
    List all projects for the authenticated user.

    Returns: [ { "id", "name", "description", "created_at", "last_accessed" } ]
    """
    user_id = get_user_id()
    projects = dbm.get_user_projects(user_id)

    result = []
    for p in projects:
        result.append({
            "id": p.id,
            "name": p.name,
            "description": p.description or "",
            "created_at": str(p.created_at) if p.created_at else None,
            "last_accessed": str(p.last_accessed) if p.last_accessed else None,
        })

    return jsonify(result), 200


@projects_bp.route("/", methods=["POST"])
@jwt_required()
def create_project():
    """
    Create a new project.

    Body: { "name": str, "description"?: str }
    Returns: { "id", "name", "message" }
    """
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()

    if not name:
        return jsonify({"error": "Project name is required"}), 400

    success, project_id, message = dbm.create_project(user_id, name, description)

    if not success:
        return jsonify({"error": message}), 400

    return jsonify({
        "id": project_id,
        "name": name,
        "message": "Project created successfully",
    }), 201


@projects_bp.route("/<project_id>", methods=["GET"])
@jwt_required()
def get_project(project_id):
    """
    Get a single project by ID.

    Returns: { "id", "name", "description", "created_at", "last_accessed" }
    """
    user_id = get_user_id()
    project = dbm.get_project_by_id(project_id)

    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Verify ownership
    if project.user_id != user_id:
        return jsonify({"error": "Access denied"}), 403

    return jsonify({
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "created_at": str(project.created_at) if project.created_at else None,
        "last_accessed": str(project.last_accessed) if project.last_accessed else None,
        "user_id": project.user_id,
    }), 200


@projects_bp.route("/<project_id>", methods=["DELETE"])
@jwt_required()
def delete_project(project_id):
    """
    Delete a project and all associated resources.

    Returns: { "message": str }
    """
    user_id = get_user_id()
    project = dbm.get_project_by_id(project_id)

    if not project:
        return jsonify({"error": "Project not found"}), 404

    if project.user_id != user_id:
        return jsonify({"error": "Access denied"}), 403

    success, message = dbm.delete_project(project_id, user_id)

    if not success:
        return jsonify({"error": message}), 400

    return jsonify({"message": "Project deleted successfully"}), 200


# ---------- CPE listing ----------

@projects_bp.route("/<project_id>/cpes", methods=["GET"])
@jwt_required()
def list_cpes(project_id):
    """
    List all CPE devices in a project.

    Returns: [ { "serial", "mac", "date_from", "date_to", "created_at" } ]
    """
    user_id = get_user_id()
    project = dbm.get_project_by_id(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    if project.user_id != user_id:
        return jsonify({"error": "Access denied"}), 403

    cpes = dbm.list_project_cpes(project_id)
    result = []
    for c in cpes:
        result.append({
            "serial": c.serial,
            "mac": c.mac,
            "date_from": c.date_from,
            "date_to": c.date_to,
            "created_at": str(c.created_at) if c.created_at else None,
        })

    return jsonify(result), 200

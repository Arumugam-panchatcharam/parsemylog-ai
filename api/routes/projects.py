"""
Projects API Routes
====================

CRUD endpoints for project management.
"""

from typing import Any, List, Optional, Tuple

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from api.user_db_mngr import project_tags_from_db, project_tags_to_db

projects_bp = Blueprint("projects", __name__)

_MAX_TAGS = 20
_MAX_TAG_LEN = 40


def _tags_for_project_row(project: Any) -> List[str]:
    return project_tags_from_db(getattr(project, "tags", None))


def normalize_project_tags(raw: Any) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Validate and normalize tags from JSON body.
    Returns (tags, None) on success, or (None, error_message).
    """
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "tags must be an array of strings"
    if len(raw) > _MAX_TAGS:
        return None, f"at most {_MAX_TAGS} tags allowed"
    seen_lower: set = set()
    out: List[str] = []
    for item in raw:
        s = str(item).strip()
        if not s:
            continue
        if len(s) > _MAX_TAG_LEN:
            return None, f"each tag must be at most {_MAX_TAG_LEN} characters"
        low = s.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        out.append(s)
    out.sort(key=lambda t: t.lower())
    return out, None


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
        natco_info = None
        if p.natco_id:
            natco = dbm.db.session.get(dbm.Natco, p.natco_id)
            if natco:
                natco_info = {"id": natco.id, "code": natco.code, "name": natco.name}
        result.append({
            "id": p.id,
            "name": p.name,
            "description": p.description or "",
            "project_type": p.project_type or "normal",
            "tags": _tags_for_project_row(p),
            "created_at": str(p.created_at) if p.created_at else None,
            "last_accessed": str(p.last_accessed) if p.last_accessed else None,
            "natco_id": p.natco_id,
            "natco": natco_info,
        })

    return jsonify(result), 200


@projects_bp.route("/", methods=["POST"])
@jwt_required()
def create_project():
    """
    Create a new project.

    Body: { "name": str, "description"?: str, "natco_id": int (required), "project_type"?: str }
    Returns: { "id", "name", "message" }
    """
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    natco_id = data.get("natco_id")
    project_type = data.get("project_type", "normal")  # "normal" or "batch"

    if not name:
        return jsonify({"error": "Project name is required"}), 400
    
    if project_type not in ["normal", "batch"]:
        return jsonify({"error": "Invalid project type. Must be 'normal' or 'batch'"}), 400

    # NATCO is now required
    if not natco_id:
        return jsonify({"error": "NATCO selection is required"}), 400
    
    natco_id = int(natco_id)
    natco = dbm.db.session.get(dbm.Natco, natco_id)
    if not natco:
        return jsonify({"error": "NATCO not found"}), 400

    tags_norm, tag_err = normalize_project_tags(data.get("tags"))
    if tag_err:
        return jsonify({"error": tag_err}), 400

    success, project_id, message = dbm.create_project(
        user_id, name, description, project_type, tags=tags_norm
    )

    if not success:
        return jsonify({"error": message}), 400

    # Assign NATCO to project
    project = dbm.get_project_by_id(project_id)
    if project:
        project.natco_id = natco_id
        dbm.db.session.commit()

    return jsonify({
        "id": project_id,
        "name": name,
        "project_type": project_type,
        "tags": tags_norm,
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

    natco_info = None
    if project.natco_id:
        natco = dbm.db.session.get(dbm.Natco, project.natco_id)
        if natco:
            natco_info = {"id": natco.id, "code": natco.code, "name": natco.name}

    return jsonify({
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "project_type": project.project_type or "normal",
        "tags": _tags_for_project_row(project),
        "created_at": str(project.created_at) if project.created_at else None,
        "last_accessed": str(project.last_accessed) if project.last_accessed else None,
        "user_id": project.user_id,
        "natco_id": project.natco_id,
        "natco": natco_info,
    }), 200


@projects_bp.route("/<project_id>", methods=["PUT"])
@jwt_required()
def update_project(project_id):
    """
    Update project metadata (name, description, natco_id).

    Body: { "name"?: str, "description"?: str, "natco_id"?: int | null }
    """
    user_id = get_user_id()
    project = dbm.get_project_by_id(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    if project.user_id != user_id:
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name_val = (data["name"] or "").strip()
        if not name_val:
            return jsonify({"error": "Project name cannot be empty"}), 400
        project.name = name_val
    if "description" in data:
        project.description = data["description"].strip()
    if "natco_id" in data:
        natco_id = data["natco_id"]
        if natco_id is not None:
            natco_id = int(natco_id)
            if not dbm.db.session.get(dbm.Natco, natco_id):
                return jsonify({"error": "NATCO not found"}), 400
        project.natco_id = natco_id
    if "project_type" in data:
        pt = data["project_type"]
        if pt not in ["normal", "batch"]:
            return jsonify({"error": "Invalid project type. Must be 'normal' or 'batch'"}), 400
        project.project_type = pt
    if "tags" in data:
        tags_norm, tag_err = normalize_project_tags(data.get("tags"))
        if tag_err:
            return jsonify({"error": tag_err}), 400
        project.tags = project_tags_to_db(tags_norm)

    try:
        dbm.db.session.commit()
        return jsonify({"message": "Project updated"}), 200
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500


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

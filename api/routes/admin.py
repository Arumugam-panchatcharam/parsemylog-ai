"""
Admin API Routes
=================

Endpoints for user management (admin-only) and system settings.
"""

import json
import re
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from api.app import dbm
from api.auth import admin_required
from api.routes.regex_analyzer import (
    _scan_progress_path,
    _scan_result_path,
    regex_scan_validate_and_start_async,
)
from logai.utils.constants import NON_TEXT_EXTENSIONS, UPLOAD_DIRECTORY

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


# =====================================================================
# LLM Settings
# =====================================================================

@admin_bp.route("/settings/llm", methods=["GET"])
@admin_required
def get_llm_settings():
    """
    Get LLM settings (admin only).

    Returns: { 
        enabled: bool, 
        providers: {
            openai: { available: bool, configured: bool, model: str },
            openrouter: { available: bool, configured: bool, model: str }
        },
        active_provider: "openai" | "openrouter" | null,
        model_info: {...} | null 
    }
    """
    import api.llm_service as llm
    import os
    
    enabled = llm.is_enabled(dbm)
    available = llm.is_available() if enabled else False
    model_info = llm.get_model_info() if available else None
    
    # Check individual providers
    openai_configured = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    openrouter_configured = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    
    openai_available = False
    openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    
    if openai_configured:
        try:
            from api.openai_service import is_available as openai_is_available
            openai_available = openai_is_available()
        except Exception:
            pass
    
    openrouter_available = openrouter_configured
    openrouter_model = "free-tier models"
    
    # Determine active provider
    active_provider = None
    if enabled and available:
        if openai_available:
            active_provider = "openai"
        elif openrouter_available:
            active_provider = "openrouter"
    
    return jsonify({
        "enabled": enabled,
        "available": available,
        "providers": {
            "openai": {
                "configured": openai_configured,
                "available": openai_available,
                "model": openai_model if openai_configured else None,
                "base_url": openai_base_url if openai_configured else None
            },
            "openrouter": {
                "configured": openrouter_configured,
                "available": openrouter_available,
                "model": openrouter_model if openrouter_configured else None
            }
        },
        "active_provider": active_provider,
        "model_info": model_info,
    }), 200


@admin_bp.route("/settings/llm", methods=["PUT"])
@admin_required
def update_llm_settings():
    """
    Toggle LLM on/off (admin only).

    Body: { "enabled": bool }
    Returns: { enabled: bool, message: str }
    """
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled")

    if enabled is None:
        return jsonify({"error": "'enabled' field is required"}), 400

    dbm.set_setting("llm_enabled", "true" if enabled else "false")

    return jsonify({
        "enabled": bool(enabled),
        "message": f"LLM {'enabled' if enabled else 'disabled'} successfully",
    }), 200


# =====================================================================
# Pattern Analyzer preview (admin — any project's uploads)
# =====================================================================


@admin_bp.route("/projects/<project_id>/cpes", methods=["GET"])
@admin_required
def admin_list_project_cpes(project_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

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


@admin_bp.route("/projects/<project_id>/files", methods=["GET"])
@admin_required
def admin_list_project_files(project_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    cpe_id = request.args.get("cpe_id")
    files = dbm.get_project_files(project_id, cpe_id=cpe_id)
    result = []
    for f in files:
        filename, file_path, original_name, file_size, uploaded_at = f
        if file_size == 0:
            continue
        is_viewable = not any(filename.lower().endswith(ext) for ext in NON_TEXT_EXTENSIONS)
        result.append({
            "filename": filename,
            "file_path": file_path,
            "original_name": original_name,
            "file_size": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size else 0,
            "uploaded_at": str(uploaded_at) if uploaded_at else None,
            "is_viewable": is_viewable,
        })
    return jsonify(result), 200


@admin_bp.route("/projects/<project_id>/regex-scan", methods=["POST"])
@admin_required
def admin_regex_scan(project_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json(silent=True) or {}
    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")
    resp, code = regex_scan_validate_and_start_async(project.user_id, project_id, cpe_id, data)
    return resp, code


@admin_bp.route("/projects/<project_id>/regex-scan/<scan_id>/progress", methods=["GET"])
@admin_required
def admin_regex_scan_progress(project_id, scan_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not re.fullmatch(r"[0-9a-f]{12}", scan_id):
        return jsonify({"error": "Invalid scan_id"}), 400

    cpe_id = request.args.get("cpe_id")
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{project.user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    prog_path = _scan_progress_path(project_dir, scan_id)

    if not prog_path.exists():
        return jsonify({"error": "Scan progress not found"}), 404

    try:
        payload = json.loads(prog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return jsonify({"error": "Could not read scan progress"}), 500

    return jsonify(payload), 200


@admin_bp.route("/projects/<project_id>/regex-scan/<scan_id>/results", methods=["GET"])
@admin_required
def admin_regex_scan_results(project_id, scan_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not re.fullmatch(r"[0-9a-f]{12}", scan_id):
        return jsonify({"error": "Invalid scan_id"}), 400

    cpe_id = request.args.get("cpe_id")
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{project.user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    cache_path = _scan_result_path(project_dir, scan_id)

    if not cache_path.exists():
        return jsonify({"error": "Scan results not found or expired"}), 404

    return send_file(cache_path, mimetype="application/json", as_attachment=False)

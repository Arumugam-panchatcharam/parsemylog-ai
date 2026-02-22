"""
Auth API Routes
================

Endpoints for user authentication, registration, and profile management.
Uses the existing DBManager for all database operations.
"""

import json
import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
)

from pathlib import Path

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY

auth_bp = Blueprint("auth", __name__)

LOG_VIEWER_QUICK_SEARCHES_FILENAME = "log_viewer_quick_searches.json"


def _quick_searches_path(user_id: int) -> Path:
    return Path(UPLOAD_DIRECTORY) / str(user_id) / LOG_VIEWER_QUICK_SEARCHES_FILENAME


@auth_bp.route("/health", methods=["GET"])
def health():
    """
    Simple health check endpoint (no auth required).
    Returns: { "status": "ok" }
    """
    return jsonify({"status": "ok"}), 200


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Authenticate user and return JWT tokens.

    Body: { "username": str, "password": str }
    Returns: { "access_token", "refresh_token", "user": {...} }
    """
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    success, user_id, is_admin = dbm.authenticate_user(username, password)

    if not success:
        return jsonify({"error": "Invalid username or password"}), 401

    access_token = create_access_token(identity=str(user_id))
    refresh_token = create_refresh_token(identity=str(user_id))

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": user_id,
            "username": username,
            "is_admin": is_admin,
        },
    }), 200


@auth_bp.route("/register", methods=["POST"])
def register():
    """
    Register a new user account.

    Body: { "username": str, "password": str, "email"?: str }
    Returns: { "message": str }
    """
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    email = data.get("email", "").strip() or None

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    success, error = dbm.create_user(username, password, email)

    if not success:
        return jsonify({"error": error}), 409

    return jsonify({"message": "Account created successfully"}), 201


@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """
    Refresh an access token using a valid refresh token.

    Returns: { "access_token": str }
    """
    identity = get_jwt_identity()
    access_token = create_access_token(identity=str(identity))
    return jsonify({"access_token": access_token}), 200


@auth_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    """
    Get the current user's profile.

    Returns: { "id", "username", "email", "is_admin", "created_at" }
    """
    user_id = get_user_id()
    user = dbm.get_user_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": user.id,
        "username": user.username,
        "email": user.email or "",
        "is_admin": user.is_admin,
        "created_at": str(user.created_at) if user.created_at else None,
    }), 200


@auth_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    """
    Update the current user's profile.

    Body: { "username"?: str, "email"?: str }
    Returns: { "message": str, "user": {...} }
    """
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}

    username = data.get("username")
    email = data.get("email")

    success, error = dbm.update_user(
        user_id,
        username=username.strip() if username else None,
        email=email.strip() if email is not None else None,
    )

    if not success:
        return jsonify({"error": error}), 400

    user = dbm.get_user_by_id(user_id)
    return jsonify({
        "message": "Profile updated successfully",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email or "",
            "is_admin": user.is_admin,
        },
    }), 200


@auth_bp.route("/change-password", methods=["POST"])
@jwt_required()
def change_password():
    """
    Change the current user's password.
    Requires the current password for verification.

    Body: { "current_password": str, "new_password": str }
    Returns: { "message": str }
    """
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}

    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not current_password or not new_password:
        return jsonify({"error": "Current password and new password are required"}), 400

    if len(new_password) < 4:
        return jsonify({"error": "New password must be at least 4 characters"}), 400

    user = dbm.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not user.check_password(current_password):
        return jsonify({"error": "Current password is incorrect"}), 403

    success, error = dbm.update_user(user_id, password=new_password)
    if not success:
        return jsonify({"error": error}), 400

    return jsonify({"message": "Password changed successfully"}), 200


@auth_bp.route("/log-viewer-quick-searches", methods=["GET"])
@jwt_required()
def get_log_viewer_quick_searches():
    """
    Get the current user's log viewer quick search buttons (name -> regex).
    Stored per user in UPLOAD_DIRECTORY/{user_id}/log_viewer_quick_searches.json.
    Returns: { "buttons": [ { "id", "name", "pattern" }, ... ] }
    """
    user_id = get_user_id()
    path = _quick_searches_path(user_id)
    if not path.exists():
        return jsonify({"buttons": []}), 200
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        buttons = data.get("buttons") if isinstance(data, dict) else data
        if not isinstance(buttons, list):
            return jsonify({"buttons": []}), 200
        out = []
        for b in buttons:
            if isinstance(b, dict) and "id" in b and "name" in b and "pattern" in b:
                out.append({"id": str(b["id"]), "name": str(b["name"]), "pattern": str(b["pattern"])})
        return jsonify({"buttons": out}), 200
    except (json.JSONDecodeError, OSError):
        return jsonify({"buttons": []}), 200


@auth_bp.route("/log-viewer-quick-searches", methods=["PUT"])
@jwt_required()
def save_log_viewer_quick_searches():
    """
    Save the current user's log viewer quick search buttons.
    Body: { "buttons": [ { "id", "name", "pattern" }, ... ] }
    """
    user_id = get_user_id()
    data = request.get_json(silent=True) or {}
    buttons = data.get("buttons")
    if not isinstance(buttons, list):
        return jsonify({"error": "buttons array required"}), 400
    out = []
    for b in buttons:
        if not isinstance(b, dict):
            continue
        bid, name, pattern = b.get("id"), b.get("name"), b.get("pattern")
        if bid is None or name is None or pattern is None:
            continue
        out.append({"id": str(bid), "name": str(name), "pattern": str(pattern)})
    path = _quick_searches_path(user_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"buttons": out}, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to save log-viewer quick searches for user %s: %s", user_id, e)
        return jsonify({"error": "Could not save settings. Check server write permissions."}), 500
    return jsonify({"buttons": out}), 200

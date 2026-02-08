"""
JWT Auth Utilities
===================

Provides decorators and helpers for JWT-based authentication.
"""

from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from api.app import dbm


def get_user_id() -> int:
    """
    Get the current user ID from JWT identity as an integer.

    flask-jwt-extended 4.x requires string subjects, so we store
    user_id as a string and convert back here.
    """
    return int(get_jwt_identity())


def admin_required(fn):
    """
    Decorator that requires a valid JWT AND admin privileges.

    Returns 403 if the user is not an admin.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        user = dbm.get_user_by_id(get_user_id())
        if not user or not user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def get_current_user():
    """
    Get the current authenticated user from JWT identity.

    Returns:
        User model instance or None.
    """
    user_id = get_jwt_identity()
    if user_id is None:
        return None
    return dbm.get_user_by_id(int(user_id))

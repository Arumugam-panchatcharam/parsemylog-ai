"""
NATCO User Routes
==================

Public (authenticated) endpoint for listing available NATCOs.
"""

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm

natco_bp = Blueprint("natco", __name__)


@natco_bp.route("/", methods=["GET"])
@jwt_required()
def list_natcos():
    """List all available NATCOs (for project assignment dropdown)."""
    natcos = dbm.db.session.query(dbm.Natco).order_by(dbm.Natco.code).all()
    return jsonify([
        {
            "id": n.id,
            "code": n.code,
            "name": n.name,
            "description": n.description or "",
            "remote_log_tenant_id": getattr(n, "remote_log_tenant_id", None) or "",
        }
        for n in natcos
    ]), 200

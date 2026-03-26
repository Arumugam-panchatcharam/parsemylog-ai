"""
NATCO Admin Routes
====================

Admin-only endpoints for managing NATCOs, global patterns,
and reviewing user pattern submissions.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml
from flask import Blueprint, jsonify, request

from api.app import dbm
from api.auth import admin_required, get_user_id

logger = logging.getLogger(__name__)

natco_admin_bp = Blueprint("natco_admin", __name__)

# Pattern config directory (domain presets from YAML files)
_RG_PATTERNS_DIR = Path(__file__).resolve().parent.parent.parent / "configs" / "rg_patterns"


# ---------------------------------------------------------------------------
# NATCO CRUD
# ---------------------------------------------------------------------------

@natco_admin_bp.route("/natcos", methods=["GET"])
@admin_required
def list_natcos():
    """List all NATCOs with pattern counts."""
    natcos = dbm.db.session.query(dbm.Natco).order_by(dbm.Natco.code).all()
    result = []
    for n in natcos:
        pattern_count = (
            dbm.db.session.query(dbm.GlobalPattern)
            .filter_by(natco_id=n.id)
            .count()
        )
        result.append({
            "id": n.id,
            "code": n.code,
            "name": n.name,
            "description": n.description or "",
            "pattern_count": pattern_count,
            "created_at": str(n.created_at) if n.created_at else None,
        })
    return jsonify(result), 200


@natco_admin_bp.route("/natcos", methods=["POST"])
@admin_required
def create_natco():
    """Create a new NATCO."""
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    name = (data.get("name") or "").strip()

    if not code or not name:
        return jsonify({"error": "Code and name are required"}), 400

    if dbm.db.session.query(dbm.Natco).filter_by(code=code).first():
        return jsonify({"error": f"NATCO with code '{code}' already exists"}), 409

    natco = dbm.Natco(code=code, name=name, description=(data.get("description") or "").strip())
    dbm.db.session.add(natco)
    try:
        dbm.db.session.commit()
        return jsonify({"id": natco.id, "code": natco.code, "name": natco.name}), 201
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500


@natco_admin_bp.route("/natcos/<int:natco_id>", methods=["PUT"])
@admin_required
def update_natco(natco_id):
    """Update a NATCO's name/description."""
    natco = dbm.db.session.get(dbm.Natco, natco_id)
    if not natco:
        return jsonify({"error": "NATCO not found"}), 404

    data = request.get_json(silent=True) or {}
    if "name" in data:
        natco.name = data["name"].strip()
    if "description" in data:
        natco.description = data["description"].strip()
    if "code" in data:
        new_code = data["code"].strip().upper()
        existing = dbm.db.session.query(dbm.Natco).filter(
            dbm.Natco.code == new_code, dbm.Natco.id != natco_id
        ).first()
        if existing:
            return jsonify({"error": f"Code '{new_code}' is already taken"}), 409
        natco.code = new_code

    try:
        dbm.db.session.commit()
        return jsonify({"id": natco.id, "code": natco.code, "name": natco.name}), 200
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500


@natco_admin_bp.route("/natcos/<int:natco_id>", methods=["DELETE"])
@admin_required
def delete_natco(natco_id):
    """Delete a NATCO and all its global patterns."""
    natco = dbm.db.session.get(dbm.Natco, natco_id)
    if not natco:
        return jsonify({"error": "NATCO not found"}), 404
    try:
        dbm.db.session.delete(natco)
        dbm.db.session.commit()
        return jsonify({"message": "NATCO deleted"}), 200
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Global Pattern Management
# ---------------------------------------------------------------------------

@natco_admin_bp.route("/natcos/<int:natco_id>/patterns", methods=["GET"])
@admin_required
def get_global_patterns(natco_id):
    """Get global patterns for a NATCO, grouped by domain."""
    natco = dbm.db.session.get(dbm.Natco, natco_id)
    if not natco:
        return jsonify({"error": "NATCO not found"}), 404

    patterns = (
        dbm.db.session.query(dbm.GlobalPattern)
        .filter_by(natco_id=natco_id)
        .order_by(dbm.GlobalPattern.domain, dbm.GlobalPattern.name)
        .all()
    )

    domains: Dict[str, List[Dict[str, Any]]] = {}
    for p in patterns:
        if p.domain not in domains:
            domains[p.domain] = []
        entry: Dict[str, Any] = {
            "id": p.id,
            "name": p.name,
            "regex": p.regex,
            "enabled": p.enabled,
        }
        if p.maintenance_window_json:
            try:
                entry["maintenance_window"] = json.loads(p.maintenance_window_json)
            except (json.JSONDecodeError, TypeError):
                pass
        if p.reboot_proximity_minutes is not None:
            entry["reboot_proximity_minutes"] = p.reboot_proximity_minutes
        domains[p.domain].append(entry)

    return jsonify({"domains": domains, "natco": {"id": natco.id, "code": natco.code, "name": natco.name}}), 200


@natco_admin_bp.route("/natcos/<int:natco_id>/patterns", methods=["PUT"])
@admin_required
def set_global_patterns(natco_id):
    """Replace all global patterns for a NATCO (full replace by domain)."""
    natco = dbm.db.session.get(dbm.Natco, natco_id)
    if not natco:
        return jsonify({"error": "NATCO not found"}), 404

    data = request.get_json(silent=True) or {}
    domains_raw = data.get("domains", {})

    if not isinstance(domains_raw, dict):
        return jsonify({"error": "domains must be an object"}), 400

    user_id = get_user_id()

    # Delete existing patterns for this NATCO
    dbm.db.session.query(dbm.GlobalPattern).filter_by(natco_id=natco_id).delete()

    total = 0
    for domain_name, patterns in domains_raw.items():
        domain_name = str(domain_name).strip()
        if not domain_name or not isinstance(patterns, list):
            continue
        for p in patterns:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "")).strip()
            regex_val = str(p.get("regex", "")).strip()
            enabled = bool(p.get("enabled", True))
            if not name or not regex_val:
                continue
            try:
                re.compile(regex_val)
            except re.error:
                continue

            mw = p.get("maintenance_window")
            mw_json = json.dumps(mw) if isinstance(mw, dict) and mw.get("start") and mw.get("end") else None
            rp = p.get("reboot_proximity_minutes")
            rp_val = int(rp) if rp is not None and str(rp).strip().lstrip("-").isdigit() and 1 <= int(rp) <= 60 else None

            gp = dbm.GlobalPattern(
                natco_id=natco_id,
                domain=domain_name,
                name=name,
                regex=regex_val,
                enabled=enabled,
                maintenance_window_json=mw_json,
                reboot_proximity_minutes=rp_val,
                created_by=user_id,
            )
            dbm.db.session.add(gp)
            total += 1

    try:
        dbm.db.session.commit()
        return jsonify({"saved": total}), 200
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500


@natco_admin_bp.route("/natcos/<int:natco_id>/patterns/import-presets", methods=["POST"])
@admin_required
def import_presets(natco_id):
    """Seed global patterns from configs/rg_patterns/*.yaml presets."""
    natco = dbm.db.session.get(dbm.Natco, natco_id)
    if not natco:
        return jsonify({"error": "NATCO not found"}), 404

    if not _RG_PATTERNS_DIR.exists():
        return jsonify({"error": "Preset directory not found"}), 404

    user_id = get_user_id()
    imported = 0

    # Collect existing patterns to avoid duplicates
    existing = set()
    for gp in dbm.db.session.query(dbm.GlobalPattern).filter_by(natco_id=natco_id).all():
        existing.add((gp.domain, gp.regex))

    for yaml_file in sorted(_RG_PATTERNS_DIR.glob("*.yaml")):
        try:
            with open(yaml_file, "r") as f:
                raw = yaml.safe_load(f)
            if not raw or "domain" not in raw:
                continue

            domain = raw["domain"]

            for rx in raw.get("regex", []):
                if (domain, rx) in existing:
                    continue
                name = rx[:50].replace("\\b", "").replace("\\s+", " ").strip("()?|")
                dbm.db.session.add(dbm.GlobalPattern(
                    natco_id=natco_id, domain=domain,
                    name=name, regex=rx, enabled=True, created_by=user_id,
                ))
                existing.add((domain, rx))
                imported += 1

        except Exception as e:
            logger.warning(f"[NATCOAdmin] Error loading preset {yaml_file}: {e}")

    try:
        dbm.db.session.commit()
        return jsonify({"imported": imported}), 200
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Submission Review
# ---------------------------------------------------------------------------

@natco_admin_bp.route("/submissions", methods=["GET"])
@admin_required
def list_submissions():
    """List all pattern submissions, filterable by status."""
    status_filter = request.args.get("status")  # pending / approved / rejected

    q = dbm.db.session.query(dbm.PatternSubmission).order_by(dbm.PatternSubmission.created_at.desc())
    if status_filter:
        q = q.filter_by(status=status_filter)

    submissions = q.all()
    result = []
    for s in submissions:
        user = dbm.get_user_by_id(s.user_id)
        natco = dbm.db.session.get(dbm.Natco, s.natco_id)
        result.append({
            "id": s.id,
            "user_id": s.user_id,
            "username": user.username if user else "unknown",
            "natco_id": s.natco_id,
            "natco_code": natco.code if natco else "?",
            "domain": s.domain,
            "patterns": json.loads(s.patterns_json) if s.patterns_json else [],
            "comment": s.comment or "",
            "status": s.status,
            "reviewed_by": s.reviewed_by,
            "admin_comment": s.admin_comment or "",
            "created_at": str(s.created_at) if s.created_at else None,
            "reviewed_at": str(s.reviewed_at) if s.reviewed_at else None,
        })

    return jsonify(result), 200


@natco_admin_bp.route("/submissions/<int:submission_id>", methods=["GET"])
@admin_required
def get_submission(submission_id):
    """Get a single submission with details and diff against current global patterns."""
    sub = dbm.db.session.get(dbm.PatternSubmission, submission_id)
    if not sub:
        return jsonify({"error": "Submission not found"}), 404

    user = dbm.get_user_by_id(sub.user_id)
    natco = dbm.db.session.get(dbm.Natco, sub.natco_id)

    # Current global patterns for this domain
    current_global = (
        dbm.db.session.query(dbm.GlobalPattern)
        .filter_by(natco_id=sub.natco_id, domain=sub.domain)
        .all()
    )
    current_dict: Dict[str, Dict[str, Any]] = {}
    for gp in current_global:
        entry: Dict[str, Any] = {"name": gp.name, "regex": gp.regex, "enabled": gp.enabled}
        if gp.maintenance_window_json:
            try:
                entry["maintenance_window"] = json.loads(gp.maintenance_window_json)
            except (json.JSONDecodeError, TypeError):
                pass
        if gp.reboot_proximity_minutes is not None:
            entry["reboot_proximity_minutes"] = gp.reboot_proximity_minutes
        current_dict[gp.regex] = entry

    submitted_patterns = json.loads(sub.patterns_json) if sub.patterns_json else []

    # Compute diff
    new_patterns = []
    modified_patterns = []
    for p in submitted_patterns:
        rx = p.get("regex", "")
        if rx in current_dict:
            cur = current_dict[rx]
            changed = (
                cur["name"] != p.get("name")
                or cur["enabled"] != p.get("enabled", True)
                or cur.get("maintenance_window") != p.get("maintenance_window")
                or cur.get("reboot_proximity_minutes") != p.get("reboot_proximity_minutes")
            )
            if changed:
                modified_patterns.append({"submitted": p, "current": cur})
        else:
            new_patterns.append(p)

    return jsonify({
        "id": sub.id,
        "user_id": sub.user_id,
        "username": user.username if user else "unknown",
        "natco_id": sub.natco_id,
        "natco_code": natco.code if natco else "?",
        "domain": sub.domain,
        "patterns": submitted_patterns,
        "comment": sub.comment or "",
        "status": sub.status,
        "admin_comment": sub.admin_comment or "",
        "created_at": str(sub.created_at) if sub.created_at else None,
        "reviewed_at": str(sub.reviewed_at) if sub.reviewed_at else None,
        "diff": {
            "new": new_patterns,
            "modified": modified_patterns,
            "total_current": len(current_global),
        },
    }), 200


@natco_admin_bp.route("/submissions/<int:submission_id>/approve", methods=["POST"])
@admin_required
def approve_submission(submission_id):
    """Approve a submission and merge patterns into the global config."""
    sub = dbm.db.session.get(dbm.PatternSubmission, submission_id)
    if not sub:
        return jsonify({"error": "Submission not found"}), 404
    if sub.status != "pending":
        return jsonify({"error": f"Submission is already {sub.status}"}), 400

    data = request.get_json(silent=True) or {}
    admin_comment = (data.get("comment") or "").strip()
    reviewer_id = get_user_id()

    submitted_patterns = json.loads(sub.patterns_json) if sub.patterns_json else []

    # Upsert into GlobalPattern
    merged = 0
    for p in submitted_patterns:
        name = str(p.get("name", "")).strip()
        regex_val = str(p.get("regex", "")).strip()
        enabled = bool(p.get("enabled", True))
        if not name or not regex_val:
            continue

        mw = p.get("maintenance_window")
        mw_json = json.dumps(mw) if isinstance(mw, dict) and mw.get("start") and mw.get("end") else None
        rp = p.get("reboot_proximity_minutes")
        rp_val = int(rp) if rp is not None and str(rp).strip().lstrip("-").isdigit() and 1 <= int(rp) <= 60 else None

        existing = (
            dbm.db.session.query(dbm.GlobalPattern)
            .filter_by(natco_id=sub.natco_id, domain=sub.domain, regex=regex_val)
            .first()
        )
        if existing:
            existing.name = name
            existing.enabled = enabled
            existing.maintenance_window_json = mw_json
            existing.reboot_proximity_minutes = rp_val
            existing.updated_at = datetime.utcnow()
        else:
            dbm.db.session.add(dbm.GlobalPattern(
                natco_id=sub.natco_id,
                domain=sub.domain,
                name=name,
                regex=regex_val,
                enabled=enabled,
                maintenance_window_json=mw_json,
                reboot_proximity_minutes=rp_val,
                created_by=sub.user_id,
            ))
        merged += 1

    sub.status = "approved"
    sub.reviewed_by = reviewer_id
    sub.reviewed_at = datetime.utcnow()
    sub.admin_comment = admin_comment

    try:
        dbm.db.session.commit()
        return jsonify({"message": f"Approved. {merged} patterns merged into global config."}), 200
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500


@natco_admin_bp.route("/submissions/<int:submission_id>/reject", methods=["POST"])
@admin_required
def reject_submission(submission_id):
    """Reject a submission with an optional admin comment."""
    sub = dbm.db.session.get(dbm.PatternSubmission, submission_id)
    if not sub:
        return jsonify({"error": "Submission not found"}), 404
    if sub.status != "pending":
        return jsonify({"error": f"Submission is already {sub.status}"}), 400

    data = request.get_json(silent=True) or {}
    admin_comment = (data.get("comment") or "").strip()
    reviewer_id = get_user_id()

    sub.status = "rejected"
    sub.reviewed_by = reviewer_id
    sub.reviewed_at = datetime.utcnow()
    sub.admin_comment = admin_comment

    try:
        dbm.db.session.commit()
        return jsonify({"message": "Submission rejected."}), 200
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500

"""
Analytics API Routes

REST API endpoints for CPE analytics powered by DuckDB read-only queries.
Provides fleet-level insights, WiFi STA issues, and SelfHeal signals.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from typing import Dict, Any, Optional, Tuple
import logging

from api.app import dbm
from api.auth import get_user_id
from api.pattern_lab_validation import validate_pattern_lab
from api.pattern_lab_storage import (
    delete_profile,
    doc_from_request_body,
    duplicate_from_request_body,
    duplicate_profile,
    get_pattern_lab_state,
    list_profiles,
    load_active_or_starter,
    load_profile,
    load_starter_example,
    save_profile,
    set_active_profile,
)
from logai.analytics.pattern_lab_paths import read_active_profile_id, sanitize_profile_id
from logai.analytics.duckdb_query import (
    get_fleet_summary,
    get_sta_issues_analysis,
    get_sta_issues_grouped_analysis,
    get_selfheal_insights_analysis,
    execute_custom_query,
    get_analytics_schema
)
from logai.analytics.pattern_lab_preview import preview_pattern_lab

logger = logging.getLogger(__name__)


def _verify_project_access(project_id: str, user_id: int) -> Tuple[Optional[Any], Optional[Any]]:
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"success": False, "error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"success": False, "error": "Access denied"}), 403)
    return project, None

# Create Blueprint
analytics_bp = Blueprint('analytics', __name__)


@analytics_bp.route('/projects/<project_id>/analytics/regenerate', methods=['POST'])
@jwt_required()
def regenerate_project_analytics(project_id: str):
    """
    Re-run Polars fleet aggregation from current per-CPE issue_analysis Parquet files.
    Use after new CPEs are processed or to refresh stale fleet_summary.json.

    Optional: force Polars ETL for every CPE that has ``*_rg.parquet`` (refreshes
    ``sta_issues`` and other consolidated Parquet), via JSON body
    ``{"force_polars_etl": true}`` or query ``?force_polars_etl=1``.
    """
    try:
        user_id = str(get_jwt_identity())
        from logai.analytics.backfill import backfill_missing_issue_analysis
        from logai.analytics.fleet_summary import generate_fleet_summary

        force_etl = False
        if request.args.get("force_polars_etl", "").lower() in ("1", "true", "yes"):
            force_etl = True
        body = request.get_json(silent=True)
        if isinstance(body, dict) and body.get("force_polars_etl") is True:
            force_etl = True

        backfill_report = backfill_missing_issue_analysis(
            user_id, project_id, force=force_etl
        )
        result = generate_fleet_summary(user_id, project_id)
        status = result.get("status")
        if status == "error":
            return jsonify({
                "success": False,
                "error": result.get("error", "Unknown error"),
                "backfill": backfill_report,
            }), 500
        if status == "no_data":
            return jsonify({
                "success": True,
                "data": None,
                "message": "No per-CPE analytics found under issue_analysis yet.",
                "backfill": backfill_report,
            }), 200
        return jsonify({
            "success": True,
            "data": result.get("summary"),
            "cpe_count": result.get("cpe_count"),
            "backfill": backfill_report,
        }), 200
    except Exception as e:
        logger.error(f"Regenerate analytics error for project {project_id}: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route('/projects/<project_id>/analytics/fleet-summary', methods=['GET'])
@jwt_required()
def get_project_fleet_summary(project_id: str):
    """
    Get fleet-level summary analytics for a project.

    Returns fleet statistics, reboot distribution, firmware analysis, and
    aggregated error / health fields from the fleet summary artifact.
    """
    try:
        user_id = str(get_jwt_identity())
        
        fleet_data = get_fleet_summary(user_id, project_id)
        
        return jsonify({
            "success": True,
            "data": fleet_data
        })
        
    except Exception as e:
        logger.error(f"Fleet summary error for project {project_id}: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/sta-issues', methods=['GET'])
@jwt_required()
def get_project_sta_issues(project_id: str):
    """
    WiFi per-STA protocol issues (auth/assoc/handshake patterns).

    Query parameters:
    - device_serial: optional filter
    - issue_key: optional filter (e.g. assoc_no_response)
    - limit: max rows (default 500, max 10000)
    """
    try:
        user_id = str(get_jwt_identity())
        device_serial = request.args.get('device_serial')
        issue_key = request.args.get('issue_key')
        limit = request.args.get('limit', 500, type=int)

        data = get_sta_issues_analysis(
            user_id, project_id, device_serial=device_serial, issue_key=issue_key, limit=limit
        )
        return jsonify({
            "success": True,
            "data": data,
            "count": len(data),
        })
    except Exception as e:
        logger.error("STA issues error for project %s: %s", project_id, e, exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/selfheal-insights', methods=['GET'])
@jwt_required()
def get_project_selfheal_insights(project_id: str):
    """
    SelfHeal-based signals per CPE (CPU, restarting processes, RSS leakage, slab/overcommit).

    Query parameters:
    - device_serial: optional filter
    - limit: max rows (default 500, max 2000)
    """
    try:
        user_id = str(get_jwt_identity())
        device_serial = request.args.get('device_serial')
        limit = request.args.get('limit', 500, type=int)

        data = get_selfheal_insights_analysis(
            user_id, project_id, device_serial=device_serial, limit=limit
        )
        return jsonify({
            "success": True,
            "data": data,
            "count": len(data),
        })
    except Exception as e:
        logger.error("SelfHeal insights error for project %s: %s", project_id, e, exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/sta-issues-grouped', methods=['GET'])
@jwt_required()
def get_project_sta_issues_grouped(project_id: str):
    """
    WiFi STA issues rolled up per device + issue type, with STA list and local OUI vendor.

    Query parameters:
    - device_serial: optional filter
    - issue_key: optional filter
    - limit: max grouped rows (default 500, max 2000)
    """
    try:
        user_id = str(get_jwt_identity())
        device_serial = request.args.get('device_serial')
        issue_key = request.args.get('issue_key')
        limit = request.args.get('limit', 500, type=int)

        data = get_sta_issues_grouped_analysis(
            user_id, project_id, device_serial=device_serial, issue_key=issue_key, limit=limit
        )
        return jsonify({
            "success": True,
            "data": data,
            "count": len(data),
        })
    except Exception as e:
        logger.error("STA issues grouped error for project %s: %s", project_id, e, exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/custom-query', methods=['POST'])
@jwt_required()
def execute_project_custom_query(project_id: str):
    """
    Execute a custom SQL query against the analytics data.
    
    Request body:
    {
        "sql": "SELECT * FROM device_health_view LIMIT 10"
    }
    
    Note: Only SELECT queries are allowed for security.
    """
    try:
        user_id = str(get_jwt_identity())
        
        data = request.get_json()
        if not data or 'sql' not in data:
            return jsonify({
                "success": False,
                "error": "SQL query is required in request body"
            }), 400
        
        sql_query = data['sql']
        
        result = execute_custom_query(user_id, project_id, sql_query)
        
        if "error" in result:
            return jsonify({
                "success": False,
                "error": result["error"]
            }), 400
        
        return jsonify({
            "success": True,
            "data": result["data"],
            "count": len(result["data"]) if isinstance(result["data"], list) else 1
        })
        
    except Exception as e:
        logger.error(f"Custom query error for project {project_id}: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/schema', methods=['GET'])
@jwt_required()
def get_project_analytics_schema(project_id: str):
    """
    Get schema information for all available analytics views.
    
    Returns the structure of all available views including column names and types.
    """
    try:
        user_id = str(get_jwt_identity())
        
        schema_info = get_analytics_schema(user_id, project_id)
        
        return jsonify({
            "success": True,
            "data": schema_info
        })
        
    except Exception as e:
        logger.error(f"Analytics schema error for project {project_id}: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/pattern-lab', methods=['GET'])
@jwt_required()
def get_pattern_lab(project_id: str):
    """Load active profile for project, or generic starter example if none selected."""
    try:
        user_id = get_user_id()
        _project, err = _verify_project_access(project_id, user_id)
        if err:
            return err
        profile_q = (request.args.get("profile") or "").strip()
        if profile_q:
            pid = sanitize_profile_id(profile_q)
            if not pid:
                return jsonify({"success": False, "error": "Invalid profile name"}), 400
            doc = load_profile(user_id, pid)
            if doc is None:
                return jsonify({"success": False, "error": "Profile not found"}), 404
            profiles = list_profiles(user_id)
            active = read_active_profile_id(user_id, project_id)
            return jsonify(
                {
                    "success": True,
                    "data": doc,
                    "source": "profile",
                    "active_profile": active,
                    "loaded_profile": pid,
                    "profiles": profiles,
                }
            )
        data, source, active, profiles = get_pattern_lab_state(user_id, project_id)
        return jsonify(
            {
                "success": True,
                "data": data,
                "source": source,
                "active_profile": active,
                "loaded_profile": active if source == "profile" else None,
                "profiles": profiles,
            }
        )
    except Exception as e:
        logger.error("pattern-lab GET error for %s: %s", project_id, e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route('/projects/<project_id>/analytics/pattern-lab/active', methods=['POST'])
@jwt_required()
def set_pattern_lab_active(project_id: str):
    """Set active profile for this project."""
    try:
        user_id = get_user_id()
        _project, err = _verify_project_access(project_id, user_id)
        if err:
            return err
        body = request.get_json(silent=True)
        profile_raw = body.get("profile") if isinstance(body, dict) else None
        if not isinstance(profile_raw, str):
            return jsonify({"success": False, "error": "profile is required"}), 400
        pid = sanitize_profile_id(profile_raw)
        if not pid:
            return jsonify({"success": False, "error": "Invalid profile name"}), 400
        try:
            active = set_active_profile(user_id, project_id, pid)
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400
        data, source, _active, profiles = get_pattern_lab_state(user_id, project_id)
        return jsonify(
            {
                "success": True,
                "active_profile": active,
                "data": data,
                "source": source,
                "profiles": profiles,
            }
        )
    except Exception as e:
        logger.error("pattern-lab active POST error for %s: %s", project_id, e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route('/projects/<project_id>/analytics/pattern-lab', methods=['PUT'])
@jwt_required()
def put_pattern_lab(project_id: str):
    """Save pattern lab to a named user profile and set it active for this project."""
    try:
        user_id = get_user_id()
        _project, err = _verify_project_access(project_id, user_id)
        if err:
            return err
        body = request.get_json(silent=True)
        doc, parse_err, profile_id = doc_from_request_body(body)
        if parse_err:
            return jsonify({"success": False, "error": parse_err}), 400
        if not profile_id:
            return jsonify(
                {
                    "success": False,
                    "error": "profile name is required (letters, numbers, underscore, hyphen)",
                }
            ), 400
        ok, msg = validate_pattern_lab(doc)
        if not ok:
            return jsonify({"success": False, "error": msg}), 400
        try:
            path = save_profile(user_id, profile_id, doc)
            set_active_profile(user_id, project_id, profile_id)
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400
        return jsonify({"success": True, "path": str(path), "profile": profile_id})
    except Exception as e:
        logger.error("pattern-lab PUT error for %s: %s", project_id, e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route('/projects/<project_id>/analytics/pattern-lab/profile', methods=['DELETE'])
@jwt_required()
def delete_pattern_lab_profile(project_id: str):
    """Delete one user profile and unset active profile if it points to it."""
    try:
        user_id = get_user_id()
        _project, err = _verify_project_access(project_id, user_id)
        if err:
            return err
        profile_q = (request.args.get("profile") or "").strip()
        pid = sanitize_profile_id(profile_q)
        if not pid:
            return jsonify({"success": False, "error": "profile query parameter is required"}), 400
        active = read_active_profile_id(user_id, project_id)
        deleted = delete_profile(user_id, pid)
        if not deleted:
            return jsonify({"success": False, "error": "Profile not found"}), 404
        if active == pid:
            from logai.analytics.pattern_lab_paths import project_active_profile_path
            ap = project_active_profile_path(user_id, project_id)
            if ap.is_file():
                ap.unlink()
        data, source, active_now, profiles = get_pattern_lab_state(user_id, project_id)
        return jsonify(
            {
                "success": True,
                "deleted_profile": pid,
                "active_profile": active_now,
                "data": data,
                "source": source,
                "profiles": profiles,
            }
        )
    except Exception as e:
        logger.error("pattern-lab profile DELETE error for %s: %s", project_id, e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route('/projects/<project_id>/analytics/pattern-lab/profile/duplicate', methods=['POST'])
@jwt_required()
def duplicate_pattern_lab_profile(project_id: str):
    """Clone a saved profile or the current editor document into a new profile name."""
    try:
        user_id = get_user_id()
        _project, err = _verify_project_access(project_id, user_id)
        if err:
            return err
        body = request.get_json(silent=True)
        target_id, source_id, doc, parse_err = duplicate_from_request_body(body)
        if parse_err:
            return jsonify({"success": False, "error": parse_err}), 400
        try:
            path = duplicate_profile(user_id, target_id, source_id=source_id, doc=doc)
        except ValueError as ve:
            return jsonify({"success": False, "error": str(ve)}), 400
        profiles = list_profiles(user_id)
        return jsonify(
            {
                "success": True,
                "profile": target_id,
                "path": str(path),
                "profiles": profiles,
            }
        )
    except Exception as e:
        logger.error("pattern-lab duplicate error for %s: %s", project_id, e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route('/projects/<project_id>/analytics/pattern-lab-preview', methods=['POST'])
@jwt_required()
def post_pattern_lab_preview(project_id: str):
    """
    Run issue detectors for one CPE using request body or saved lab file.

    Query: cpe_serial (required, CPE folder id). use_saved=1 uses active profile for this project.
    Body (when use_saved is not set): JSON { "events": {...}, "issues": {...} }.
    """
    try:
        user_id = get_user_id()
        _project, err = _verify_project_access(project_id, user_id)
        if err:
            return err

        cpe_serial = (request.args.get("cpe_serial") or "").strip()
        if not cpe_serial:
            return jsonify({"success": False, "error": "cpe_serial query parameter is required"}), 400

        use_saved = request.args.get("use_saved", "").lower() in ("1", "true", "yes")
        if use_saved:
            doc = load_active_or_starter(user_id, project_id)
        else:
            body = request.get_json(silent=True)
            doc, parse_err, _profile_id = doc_from_request_body(body)
            if parse_err:
                return jsonify({"success": False, "error": parse_err}), 400

        ok, msg = validate_pattern_lab(doc)
        if not ok:
            return jsonify({"success": False, "error": msg}), 400

        rows, stats = preview_pattern_lab(str(user_id), project_id, cpe_serial, doc)
        return jsonify({"success": True, "data": rows, "stats": stats, "count": len(rows)})
    except Exception as e:
        logger.error("pattern-lab-preview error for %s: %s", project_id, e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route('/projects/<project_id>/analytics/pattern-lab-defaults', methods=['GET'])
@jwt_required()
def get_pattern_lab_defaults(project_id: str):
    """Return generic starter example events/issues for quick onboarding."""
    try:
        user_id = get_user_id()
        _project, err = _verify_project_access(project_id, user_id)
        if err:
            return err
        data = load_starter_example()
        return jsonify({"success": True, "data": data, "source": "starter"})
    except Exception as e:
        logger.error("pattern-lab-defaults GET error: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


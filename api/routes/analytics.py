"""
Analytics API Routes

REST API endpoints for CPE analytics powered by DuckDB read-only queries.
Provides fleet-level insights, WiFi STA issues, and SelfHeal signals.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from typing import Dict, Any
import logging

from logai.analytics.duckdb_query import (
    get_fleet_summary,
    get_sta_issues_analysis,
    get_sta_issues_grouped_analysis,
    get_selfheal_insights_analysis,
    execute_custom_query,
    get_analytics_schema
)

logger = logging.getLogger(__name__)

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


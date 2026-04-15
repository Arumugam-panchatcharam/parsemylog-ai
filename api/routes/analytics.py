"""
Analytics API Routes

REST API endpoints for CPE analytics powered by DuckDB read-only queries.
Provides fleet-level insights, device health, reboot analysis, and error patterns.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from typing import Dict, Any
import logging

from logai.analytics.duckdb_query import (
    get_fleet_summary,
    get_device_health_summary,
    get_reboot_analysis,
    get_error_templates_analysis,
    get_signals_analysis,
    get_sta_issues_analysis,
    get_sta_issues_grouped_analysis,
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
    
    Returns comprehensive fleet statistics, reboot distribution, 
    firmware analysis, and device health overview.
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


@analytics_bp.route('/projects/<project_id>/analytics/device-health', methods=['GET'])
@jwt_required()
def get_project_device_health(project_id: str):
    """
    Get device health analytics for all CPEs in a project.
    
    Query parameters:
    - limit: Maximum number of devices to return (default: 100)
    """
    try:
        user_id = str(get_jwt_identity())
        
        limit = request.args.get('limit', 100, type=int)
        
        device_health = get_device_health_summary(user_id, project_id, limit)
        
        return jsonify({
            "success": True,
            "data": device_health,
            "count": len(device_health)
        })
        
    except Exception as e:
        logger.error(f"Device health error for project {project_id}: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/reboots', methods=['GET'])
@jwt_required()
def get_project_reboot_analysis(project_id: str):
    """
    Get reboot analysis for a project.
    
    Query parameters:
    - serial: Optional device serial to filter by specific device
    """
    try:
        user_id = str(get_jwt_identity())
        
        serial = request.args.get('serial')
        
        reboot_data = get_reboot_analysis(user_id, project_id, serial)
        
        return jsonify({
            "success": True,
            "data": reboot_data
        })
        
    except Exception as e:
        logger.error(f"Reboot analysis error for project {project_id}: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/error-templates', methods=['GET'])
@jwt_required()
def get_project_error_templates(project_id: str):
    """
    Get error templates analysis for a project.
    
    Query parameters:
    - domain: Optional domain filter (cellular, wireless, common, etc.)
    - limit: Maximum number of templates to return (default: 50)
    """
    try:
        user_id = str(get_jwt_identity())
        
        domain = request.args.get('domain')
        limit = request.args.get('limit', 50, type=int)
        
        error_data = get_error_templates_analysis(user_id, project_id, domain, limit)
        
        return jsonify({
            "success": True,
            "data": error_data,
            "count": len(error_data)
        })
        
    except Exception as e:
        logger.error(f"Error templates analysis error for project {project_id}: {e}", exc_info=True)
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


@analytics_bp.route('/projects/<project_id>/analytics/signals', methods=['GET'])
@jwt_required()
def get_project_signals(project_id: str):
    """
    Get signals analysis for a project.
    
    Query parameters:
    - signal_type: Optional signal type filter (memory_pressure, cpu_usage, wifi_instability)
    - limit: Maximum number of signal records to return (default: 1000)
    """
    try:
        user_id = str(get_jwt_identity())
        
        signal_type = request.args.get('signal_type')
        limit = request.args.get('limit', 1000, type=int)
        
        signals_data = get_signals_analysis(user_id, project_id, signal_type, limit)
        
        return jsonify({
            "success": True,
            "data": signals_data,
            "count": len(signals_data)
        })
        
    except Exception as e:
        logger.error(f"Signals analysis error for project {project_id}: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
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


@analytics_bp.route('/projects/<project_id>/analytics/domains', methods=['GET'])
@jwt_required()
def get_project_analytics_domains(project_id: str):
    """
    Get list of available domains for error analysis.
    """
    try:
        user_id = str(get_jwt_identity())
        
        # Get unique domains from error templates
        from logai.analytics.duckdb_query import DuckDBQueryEngine
        
        with DuckDBQueryEngine(user_id, project_id) as db:
            views = db.get_available_views()
            
            if "error_templates_view" in views:
                result = db.query("SELECT DISTINCT domain FROM error_templates_view ORDER BY domain")
                domains = [row["domain"] for row in result]
            else:
                domains = []
        
        return jsonify({
            "success": True,
            "data": {
                "domains": domains,
                "available_views": views
            }
        })
        
    except Exception as e:
        logger.error(f"Analytics domains error for project {project_id}: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@analytics_bp.route('/projects/<project_id>/analytics/signal-types', methods=['GET'])
@jwt_required()
def get_project_analytics_signal_types(project_id: str):
    """
    Get list of available signal types for signals analysis.
    """
    try:
        user_id = str(get_jwt_identity())
        
        # Get unique signal types
        from logai.analytics.duckdb_query import DuckDBQueryEngine
        
        with DuckDBQueryEngine(user_id, project_id) as db:
            views = db.get_available_views()
            
            if "signals_view" in views:
                result = db.query("SELECT DISTINCT signal_type FROM signals_view ORDER BY signal_type")
                signal_types = [row["signal_type"] for row in result]
            else:
                signal_types = []
        
        return jsonify({
            "success": True,
            "data": {
                "signal_types": signal_types
            }
        })
        
    except Exception as e:
        logger.error(f"Analytics signal types error for project {project_id}: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
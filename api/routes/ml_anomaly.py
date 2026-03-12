"""
ML Anomaly Detection API Routes
=================================

REST endpoints for:
- Per-CPE log anomaly detection (single domain or all domains)
- Per-CPE telemetry anomaly detection and summarization
- Fleet-level analysis across 500+ CPEs
- Health scoring and fleet overview
"""

import logging
import numpy as np
from dataclasses import asdict
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm, get_embedding_model
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

ml_anomaly_bp = Blueprint("ml_anomaly", __name__)


def _convert_to_json_serializable(obj):
    """Convert numpy types to Python native types for JSON serialization."""
    if isinstance(obj, (np.integer, np.int32, np.int64)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: _convert_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_convert_to_json_serializable(item) for item in obj]
    return obj


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _project_dir(user_id, project_id, cpe_id=None) -> Path:
    base = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    return base / cpe_id if cpe_id else base


def _anomaly_result_to_dict(result):
    """Safely convert dataclass to JSON-serialisable dict."""
    if hasattr(result, "__dataclass_fields__"):
        d = asdict(result)
        return d
    return result


# ---------------------------------------------------------------------------
# Per-CPE Log Anomaly Detection
# ---------------------------------------------------------------------------

@ml_anomaly_bp.route(
    "/<project_id>/ml/log-anomalies", methods=["POST"]
)
@jwt_required()
def detect_log_anomalies(project_id):
    """
    Run ML anomaly detection on log template patterns for a single CPE.

    Query params:
        cpe_id: CPE identifier (subdirectory name)
        domain: Specific domain (e.g. "wireless"). Default: all domains.
        top_n: Max anomalies to return (default 50).
        enable_vector_similarity: Enable vector similarity (KNN+cluster+temporal) (default true). **RECOMMENDED**
        enable_gru: Enable GRU on embeddings (default true). **RECOMMENDED**
        enable_isolation_forest: Enable IsolationForest on embeddings (default true). **RECOMMENDED**

    Returns:
        JSON with anomaly report including ensemble scores, per-method
        breakdowns, and human-readable explanations.
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id", "")
    domain = request.args.get("domain", "")
    top_n = int(request.args.get("top_n", "50"))
    
    # NEW: Vector-based parameters
    enable_vector_similarity = request.args.get("enable_vector_similarity", "true").lower() == "true"
    enable_gru = request.args.get("enable_gru", "true").lower() == "true"
    enable_isolation_forest = request.args.get("enable_isolation_forest", "true").lower() == "true"

    proj_dir = _project_dir(user_id, project_id, cpe_id if cpe_id else None)
    if not proj_dir.exists():
        return jsonify({"error": "Project/CPE directory not found"}), 404

    try:
        from logai.ml.log_anomaly import LogAnomalyPipeline
        import pandas as pd
        import os

        # Setup model cache directory
        cache_dir = proj_dir / ".ml_cache"
        
        # Qdrant configuration
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        qdrant_collection = f"project_{project_id}"
        
        pipeline = LogAnomalyPipeline(
            # NEW: Vector-based parameters
            enable_vector_similarity=enable_vector_similarity,
            enable_gru=enable_gru,
            enable_isolation_forest=enable_isolation_forest,
            qdrant_url=qdrant_url,
            qdrant_collection=qdrant_collection,
            cache_dir=cache_dir,
        )

        if domain:
            parquet_path = proj_dir / f"{domain}_rg.parquet"
            if not parquet_path.exists():
                return jsonify({"error": f"No parquet found for domain '{domain}'"}), 404
            report = pipeline.analyze(
                parquet_path=str(parquet_path),
                cpe_id=cpe_id, domain=domain, top_n=top_n,
            )
        else:
            parquet_files = list(proj_dir.glob("*_rg.parquet"))
            if not parquet_files:
                return jsonify({"error": "No parsed log data found"}), 404

            all_dfs = []
            for pf in parquet_files:
                try:
                    df = pd.read_parquet(pf)
                    if not df.empty:
                        # Extract domain from filename (e.g., wireless_rg.parquet -> wireless)
                        domain_name = pf.stem.replace("_rg", "")
                        df["domain"] = domain_name
                        all_dfs.append(df)
                except Exception:
                    continue

            if not all_dfs:
                return jsonify({"error": "No valid parquet data found"}), 404

            combined = pd.concat(all_dfs, ignore_index=True)
            report = pipeline.analyze(
                df=combined, cpe_id=cpe_id, domain="all", top_n=top_n,
            )

        return jsonify(_anomaly_result_to_dict(report)), 200

    except Exception as e:
        logger.error(f"[ML] Log anomaly detection failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Per-CPE Telemetry Anomaly Detection
# ---------------------------------------------------------------------------

@ml_anomaly_bp.route(
    "/<project_id>/ml/telemetry-anomalies", methods=["POST"]
)
@jwt_required()
def detect_telemetry_anomalies(project_id):
    """
    Run ML anomaly detection on telemetry time-series data for a single CPE.

    Query params:
        cpe_id: CPE identifier.

    Returns:
        JSON with telemetry anomaly report including health score,
        metric anomalies, change points, and auto-generated summary.
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id", "")
    proj_dir = _project_dir(user_id, project_id, cpe_id if cpe_id else None)

    if not proj_dir.exists():
        return jsonify({"error": "Project/CPE directory not found"}), 404

    cache_path = proj_dir / "raw_telemetry_cache.json"
    if not cache_path.exists():
        return jsonify({"error": "No telemetry cache found. Parse telemetry first."}), 404

    try:
        from logai.ml.telemetry_anomaly import TelemetryAnomalyPipeline

        pipeline = TelemetryAnomalyPipeline()
        report = pipeline.analyze(
            cache_path=str(cache_path), cpe_id=cpe_id,
        )

        return jsonify(_anomaly_result_to_dict(report)), 200

    except Exception as e:
        logger.error(f"[ML] Telemetry anomaly detection failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Fleet-Level Analysis
# ---------------------------------------------------------------------------

@ml_anomaly_bp.route(
    "/<project_id>/ml/fleet-analysis", methods=["POST"]
)
@jwt_required()
def run_fleet_analysis(project_id):
    """
    Run fleet-level ML anomaly analysis across all CPEs in the project.

    Designed to scale to 500+ CPEs with parallel processing.

    Query params:
        max_workers: Thread pool size (default 8).
        enable_vector_similarity: Enable vector similarity per CPE (default true). **RECOMMENDED**
        enable_gru: Enable GRU per CPE (default true). **RECOMMENDED**
        enable_isolation_forest: Enable IsolationForest per CPE (default true). **RECOMMENDED**
        enable_log: Enable log analysis (default true).
        enable_telemetry: Enable telemetry analysis (default true).

    Request body (optional):
        {"cpe_ids": ["cpe_001", "cpe_002", ...]}

    Returns:
        JSON with fleet report including per-CPE results, health
        distribution, CPE clusters, systemic patterns, and outliers.
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    max_workers = int(request.args.get("max_workers", "8"))
    
    # NEW: Vector-based parameters
    enable_vector_similarity = request.args.get("enable_vector_similarity", "true").lower() == "true"
    enable_gru = request.args.get("enable_gru", "true").lower() == "true"
    enable_isolation_forest = request.args.get("enable_isolation_forest", "true").lower() == "true"
    
    enable_log = request.args.get("enable_log", "true").lower() == "true"
    enable_telemetry = request.args.get("enable_telemetry", "true").lower() == "true"

    body = request.get_json(silent=True) or {}
    cpe_ids = body.get("cpe_ids")

    proj_dir = _project_dir(user_id, project_id)
    if not proj_dir.exists():
        return jsonify({"error": "Project directory not found"}), 404

    try:
        from logai.ml.fleet_anomaly import FleetAnalyzer
        import os

        # Qdrant configuration
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        qdrant_collection = f"project_{project_id}"

        analyzer = FleetAnalyzer(
            max_workers=max_workers,
            # NEW: Vector-based parameters
            enable_vector_similarity=enable_vector_similarity,
            enable_gru=enable_gru,
            enable_isolation_forest=enable_isolation_forest,
            qdrant_url=qdrant_url,
            qdrant_collection=qdrant_collection,
            enable_log_analysis=enable_log,
            enable_telemetry_analysis=enable_telemetry,
        )

        report = analyzer.analyze_fleet(
            project_dir=proj_dir,
            cpe_ids=cpe_ids,
        )

        response = {
            "total_cpes": report.total_cpes,
            "analyzed_cpes": report.analyzed_cpes,
            "failed_cpes": report.failed_cpes,
            "health_distribution": report.health_distribution,
            "health_histogram": report.health_histogram,
            "fleet_anomaly_patterns": report.fleet_anomaly_patterns[:50],
            "outlier_cpes": report.outlier_cpes[:30],
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "size": c.size,
                    "label": c.label,
                    "cpe_ids": c.cpe_ids[:20],
                    "common_templates": c.common_templates[:5],
                }
                for c in report.clusters
            ],
            "fleet_summary": report.fleet_summary,
            "processing_time_ms": report.processing_time_ms,
            "per_cpe_summary": {
                cpe_id: {
                    "health_label": r.health_label,
                    "overall_score": r.overall_score,
                    "log_anomaly_count": (
                        r.log_report.anomaly_count if r.log_report else 0
                    ),
                    "telemetry_anomaly_count": (
                        len(r.telemetry_report.anomalies)
                        if r.telemetry_report else 0
                    ),
                    "error": r.error,
                }
                for cpe_id, r in report.cpe_results.items()
            },
        }

        # Convert numpy types to Python native types
        response = _convert_to_json_serializable(response)

        return jsonify(response), 200

    except Exception as e:
        logger.error(f"[ML] Fleet analysis failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Health Score Endpoint
# ---------------------------------------------------------------------------

@ml_anomaly_bp.route(
    "/<project_id>/ml/health-score", methods=["GET"]
)
@jwt_required()
def get_health_score(project_id):
    """
    Get the ML-computed health score for a single CPE.

    Query params:
        cpe_id: CPE identifier.

    Returns:
        JSON with health score, category breakdowns, and risk factors.
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id", "")
    proj_dir = _project_dir(user_id, project_id, cpe_id if cpe_id else None)

    if not proj_dir.exists():
        return jsonify({"error": "Project/CPE directory not found"}), 404

    cache_path = proj_dir / "raw_telemetry_cache.json"
    if not cache_path.exists():
        return jsonify({"error": "No telemetry data available"}), 404

    try:
        from logai.ml.telemetry_anomaly import TelemetryAnomalyPipeline

        pipeline = TelemetryAnomalyPipeline()
        report = pipeline.analyze(cache_path=str(cache_path), cpe_id=cpe_id)

        return jsonify({
            "cpe_id": cpe_id,
            "health": _anomaly_result_to_dict(report.health),
            "summary": {
                "anomaly_count": report.summary.anomaly_count,
                "key_findings": report.summary.key_findings,
                "recommendations": report.summary.recommendations,
                "narrative": report.summary.narrative,
            },
        }), 200

    except Exception as e:
        logger.error(f"[ML] Health score failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

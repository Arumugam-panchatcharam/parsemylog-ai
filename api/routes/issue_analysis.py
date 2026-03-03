"""
Issue Analysis API Routes
==========================

Endpoints for triggering and retrieving graph-driven issue analysis.
Supports both batch-job scoped analysis and direct project-level
analysis (for single / few-CPE projects without a batch job).
"""

import json
import logging
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

issue_analysis_bp = Blueprint("issue_analysis", __name__)


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _get_project_dir(user_id: int, project_id: str) -> Path:
    return Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")


# ---------------------------------------------------------------------------
# Trigger analysis
# ---------------------------------------------------------------------------

@issue_analysis_bp.route(
    "/<project_id>/batch-jobs/<job_id>/issue-analysis",
    methods=["POST"],
)
@jwt_required()
def trigger_issue_analysis(project_id, job_id):
    """
    Trigger graph-driven issue analysis for a batch job.

    Request body:
        { "graph_id": "<knowledge-graph-uuid>" }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    job = dbm.get_batch_job(job_id)
    if not job or job.project_id != project_id:
        return jsonify({"error": "Job not found"}), 404

    data = request.get_json(silent=True) or {}
    graph_id = data.get("graph_id")
    if not graph_id:
        return jsonify({"error": "graph_id is required"}), 400

    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    if not graph:
        return jsonify({"error": "Knowledge graph not found"}), 404

    from services.celery_worker.tasks import run_issue_analysis

    task = run_issue_analysis.apply_async(
        args=(job_id, user_id, project_id, graph_id),
        priority=5,
    )

    return jsonify({
        "message": "Issue analysis started",
        "celery_task_id": task.id,
        "graph_name": graph.name,
    }), 202


# ---------------------------------------------------------------------------
# Retrieve results
# ---------------------------------------------------------------------------

@issue_analysis_bp.route(
    "/<project_id>/batch-jobs/<job_id>/issue-analysis",
    methods=["GET"],
)
@jwt_required()
def get_issue_analysis(project_id, job_id):
    """Fetch the generated issue analysis results (fleet overview + CPE list)."""
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    job = dbm.get_batch_job(job_id)
    if not job or job.project_id != project_id:
        return jsonify({"error": "Job not found"}), 404

    from logai.graph_analyzer import load_analysis_outputs

    project_dir = _get_project_dir(user_id, project_id)
    outputs = load_analysis_outputs(project_dir)

    if not outputs.get("available"):
        return jsonify({"available": False}), 200

    return jsonify(outputs), 200


@issue_analysis_bp.route(
    "/<project_id>/batch-jobs/<job_id>/issue-analysis/cpe/<cpe_serial>",
    methods=["GET"],
)
@jwt_required()
def get_issue_analysis_cpe(project_id, job_id, cpe_serial):
    """Fetch per-CPE issue analysis with causal chains and telemetry."""
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    job = dbm.get_batch_job(job_id)
    if not job or job.project_id != project_id:
        return jsonify({"error": "Job not found"}), 404

    from logai.graph_analyzer import load_cpe_analysis

    project_dir = _get_project_dir(user_id, project_id)
    record = load_cpe_analysis(project_dir, cpe_serial)

    if not record:
        return jsonify({"error": "CPE analysis not found"}), 404

    return jsonify(record), 200


# ---------------------------------------------------------------------------
# Direct project-level analysis (no batch job required)
# ---------------------------------------------------------------------------

@issue_analysis_bp.route("/<project_id>/issue-analysis", methods=["POST"])
@jwt_required()
def trigger_direct_analysis(project_id):
    """Trigger graph-driven analysis directly on a project's CPE data."""
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    graph_id = data.get("graph_id")
    if not graph_id:
        return jsonify({"error": "graph_id is required"}), 400

    graph = dbm.db.session.get(dbm.KnowledgeGraph, graph_id)
    if not graph:
        return jsonify({"error": "Knowledge graph not found"}), 404

    from services.celery_worker.tasks import run_issue_analysis

    task = run_issue_analysis.apply_async(
        args=("__direct__", user_id, project_id, graph_id),
        priority=5,
    )

    return jsonify({
        "message": "Issue analysis started",
        "celery_task_id": task.id,
        "graph_name": graph.name,
    }), 202


@issue_analysis_bp.route("/<project_id>/issue-analysis", methods=["GET"])
@jwt_required()
def get_direct_analysis(project_id):
    """Fetch analysis results for a project (non-batch)."""
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    from logai.graph_analyzer import load_analysis_outputs

    project_dir = _get_project_dir(user_id, project_id)
    outputs = load_analysis_outputs(project_dir)

    if not outputs.get("available"):
        return jsonify({"available": False}), 200

    return jsonify(outputs), 200


@issue_analysis_bp.route(
    "/<project_id>/issue-analysis/cpe/<cpe_serial>",
    methods=["GET"],
)
@jwt_required()
def get_direct_analysis_cpe(project_id, cpe_serial):
    """Fetch per-CPE issue analysis (non-batch)."""
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    from logai.graph_analyzer import load_cpe_analysis

    project_dir = _get_project_dir(user_id, project_id)
    record = load_cpe_analysis(project_dir, cpe_serial)

    if not record:
        return jsonify({"error": "CPE analysis not found"}), 404

    return jsonify(record), 200

"""
Batch Job API Routes
====================

Endpoints for managing batch CPE processing jobs:
- Create batch jobs from CPE zip files
- Monitor job progress and status
- List CPE processing records
- Retry failed CPEs
- Cancel running jobs
"""

import json
import logging
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from services.celery_worker.celery_app import celery

logger = logging.getLogger(__name__)

batch_jobs_bp = Blueprint("batch_jobs", __name__)


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


# ---------------------------------------------------------------------------
# Create Batch Job
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs/create", methods=["POST"])
@jwt_required()
def create_batch_job(project_id):
    """
    Create a new batch processing job for CPE zip files.
    
    Request body:
        {
            "cpe_folder_path": "test10",  # Relative to /app/batch_cpe_logs/
            "job_type": "cpe_processing"  # optional
        }
    
    Returns:
        {
            "job_id": "uuid",
            "status": "queued",
            "total_cpes": 471,
            "message": "Batch job created"
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    try:
        data = request.get_json()
        cpe_folder_input = data.get("cpe_folder_path")
        job_type = data.get("job_type", "cpe_processing")
        
        if not cpe_folder_input:
            return jsonify({"error": "cpe_folder_path is required"}), 400
        
        # If input is a relative path (no leading /), prepend the batch logs root
        BATCH_CPE_LOGS_ROOT = "/app/batch_cpe_logs"
        if not cpe_folder_input.startswith("/"):
            cpe_folder_path = f"{BATCH_CPE_LOGS_ROOT}/{cpe_folder_input}"
        else:
            cpe_folder_path = cpe_folder_input
        
        # Validate folder exists
        folder = Path(cpe_folder_path)
        if not folder.exists():
            return jsonify({"error": f"Folder not found: {cpe_folder_path}"}), 404
        
        # Count zip files
        zip_files = list(folder.glob("*.zip"))
        if not zip_files:
            return jsonify({"error": "No .zip files found in folder"}), 400
        
        # Create batch job
        job_id = dbm.create_batch_job(project_id, user_id, len(zip_files), job_type)
        
        # Dispatch Celery task
        from services.celery_worker.tasks import process_cpe_batch_job
        task = process_cpe_batch_job.apply_async(
            args=(job_id, user_id, project_id, cpe_folder_path),
            priority=10,
        )
        
        logger.info(f"[BatchJob {job_id}] Created for project {project_id} with {len(zip_files)} CPEs (task {task.id})")
        
        return jsonify({
            "job_id": job_id,
            "status": "queued",
            "total_cpes": len(zip_files),
            "message": f"Batch job created with {len(zip_files)} CPEs",
            "celery_task_id": task.id,
        }), 201
        
    except Exception as e:
        logger.error(f"[CreateBatchJob] Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Get Batch Job Status
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs/<job_id>", methods=["GET"])
@jwt_required()
def get_batch_job(project_id, job_id):
    """
    Get batch job details and status.
    
    Returns:
        {
            "job_id": "uuid",
            "status": "processing",
            "total_cpes": 471,
            "processed_cpes": 125,
            "failed_cpes": 2,
            "progress_percent": 26.9,
            "created_at": "2026-02-19T10:30:00",
            "started_at": "2026-02-19T10:30:05",
            "completed_at": null,
            "elapsed_sec": 450.5,
            "eta_sec": 1200.0
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    job = dbm.get_batch_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    if job.project_id != project_id:
        return jsonify({"error": "Job does not belong to this project"}), 403
    
    # Calculate progress
    total = job.total_cpes
    processed = job.processed_cpes + job.failed_cpes
    progress_percent = (processed / total * 100) if total > 0 else 0
    
    # Calculate elapsed time and ETA (stop elapsed when job is done)
    elapsed_sec = None
    eta_sec = None
    if job.started_at:
        from datetime import datetime
        if job.completed_at and job.status in ("completed", "failed", "cancelled"):
            elapsed = (job.completed_at - job.started_at).total_seconds()
        else:
            now = datetime.now()
            elapsed = (now - job.started_at).total_seconds()
        elapsed_sec = elapsed

        if processed > 0 and job.status == "processing":
            avg_time_per_cpe = elapsed / processed
            remaining_cpes = total - processed
            eta_sec = avg_time_per_cpe * remaining_cpes
    
    return jsonify({
        "job_id": job.id,
        "status": job.status,
        "job_type": job.job_type,
        "total_cpes": job.total_cpes,
        "processed_cpes": job.processed_cpes,
        "failed_cpes": job.failed_cpes,
        "progress_percent": round(progress_percent, 1),
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "elapsed_sec": round(elapsed_sec, 1) if elapsed_sec else None,
        "eta_sec": round(eta_sec, 1) if eta_sec else None,
    }), 200


# ---------------------------------------------------------------------------
# List Project Batch Jobs
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs", methods=["GET"])
@jwt_required()
def list_batch_jobs(project_id):
    """
    List all batch jobs for a project.
    
    Query params:
        - limit: Max jobs to return (default: 50)
    
    Returns:
        {
            "jobs": [
                {
                    "job_id": "uuid",
                    "status": "completed",
                    ...
                }
            ]
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    limit = request.args.get("limit", 50, type=int)
    jobs = dbm.get_project_batch_jobs(project_id, limit=limit)

    from datetime import datetime
    now = datetime.now()
    result = []
    for job in jobs:
        processed = job.processed_cpes + job.failed_cpes
        progress_percent = (processed / job.total_cpes * 100) if job.total_cpes > 0 else 0

        elapsed_sec = None
        eta_sec = None
        if job.started_at:
            if job.completed_at and job.status in ("completed", "failed", "cancelled"):
                elapsed_sec = (job.completed_at - job.started_at).total_seconds()
            else:
                elapsed_sec = (now - job.started_at).total_seconds()
            if processed > 0 and job.status == "processing":
                eta_sec = (elapsed_sec / processed) * (job.total_cpes - processed)

        result.append({
            "job_id": job.id,
            "status": job.status,
            "job_type": job.job_type,
            "total_cpes": job.total_cpes,
            "processed_cpes": job.processed_cpes,
            "failed_cpes": job.failed_cpes,
            "progress_percent": round(progress_percent, 1),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "elapsed_sec": round(elapsed_sec, 1) if elapsed_sec is not None else None,
            "eta_sec": round(eta_sec, 1) if eta_sec is not None else None,
            "error_message": job.error_message,
        })

    return jsonify({"jobs": result}), 200


# ---------------------------------------------------------------------------
# List CPE Processing Records
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs/<job_id>/cpes", methods=["GET"])
@jwt_required()
def list_cpe_records(project_id, job_id):
    """
    List all CPE processing records for a batch job.
    
    Query params:
        - status: Filter by status (pending, processing, completed, failed)
    
    Returns:
        {
            "cpes": [
                {
                    "serial": "CP2318ADA7F",
                    "status": "completed",
                    "logs_extracted": 15,
                    "patterns_indexed": 45,
                    "processing_time_sec": 12.5,
                    ...
                }
            ]
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    # Verify job belongs to project
    job = dbm.get_batch_job(job_id)
    if not job or job.project_id != project_id:
        return jsonify({"error": "Job not found"}), 404
    
    status_filter = request.args.get("status")
    records = dbm.get_job_cpe_records(job_id, status=status_filter)
    
    result = []
    for record in records:
        result.append({
            "record_id": record.id,
            "serial": record.serial,
            "status": record.status,
            "celery_task_id": record.celery_task_id,
            "logs_extracted": record.logs_extracted,
            "patterns_indexed": record.patterns_indexed,
            "processing_time_sec": round(record.processing_time_sec, 1) if record.processing_time_sec else None,
            "error_message": record.error_message,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        })
    
    return jsonify({"cpes": result}), 200


# ---------------------------------------------------------------------------
# Retry Failed CPEs
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs/<job_id>/retry", methods=["POST"])
@jwt_required()
def retry_failed_cpes(project_id, job_id):
    """
    Retry all failed CPE processing tasks.
    
    Returns:
        {
            "message": "Retrying 5 failed CPEs",
            "retried_count": 5
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    # Verify job belongs to project
    job = dbm.get_batch_job(job_id)
    if not job or job.project_id != project_id:
        return jsonify({"error": "Job not found"}), 404
    
    # Get failed CPE records
    failed_records = dbm.get_job_cpe_records(job_id, status="failed")
    
    if not failed_records:
        return jsonify({"message": "No failed CPEs to retry", "retried_count": 0}), 200
    
    # Retry each failed CPE
    from services.celery_worker.tasks import process_single_cpe
    
    retried = 0
    for record in failed_records:
        # Reset status to pending
        dbm.update_cpe_record_status(record.id, "pending", error_message=None)
        
        # Dispatch new Celery task
        task = process_single_cpe.apply_async(
            args=(job_id, user_id, project_id, record.serial, f"/path/to/{record.serial}.zip"),
            priority=7,
        )
        
        # Update task ID
        record.celery_task_id = task.id
        dbm.db.session.commit()
        
        retried += 1
        logger.info(f"[BatchJob {job_id}] Retrying CPE {record.serial} (task {task.id})")
    
    return jsonify({
        "message": f"Retrying {retried} failed CPEs",
        "retried_count": retried,
    }), 200


# ---------------------------------------------------------------------------
# Cancel Batch Job
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs/<job_id>/cancel", methods=["POST"])
@jwt_required()
def cancel_batch_job(project_id, job_id):
    """
    Cancel a running batch job.
    
    Note: Already processing CPEs will complete, but no new ones will start.
    
    Returns:
        {
            "message": "Job cancelled",
            "status": "cancelled"
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    job = dbm.get_batch_job(job_id)
    if not job or job.project_id != project_id:
        return jsonify({"error": "Job not found"}), 404
    
    if job.status in ("completed", "failed", "cancelled"):
        return jsonify({"error": f"Job already {job.status}"}), 400
    
    # Update job status first so running tasks can detect it
    dbm.update_batch_job_status(job_id, "cancelled")
    
    revoked = 0
    terminated = 0
    
    all_records = dbm.get_job_cpe_records(job_id)
    for record in all_records:
        if record.celery_task_id:
            is_active = record.status in ("pending", "processing")
            celery.control.revoke(
                record.celery_task_id,
                terminate=is_active,
                signal="SIGTERM" if is_active else None,
            )
            if record.status == "pending":
                revoked += 1
            elif record.status == "processing":
                terminated += 1
        if record.status in ("pending", "processing"):
            dbm.update_cpe_record_status(
                record.id, "skipped", error_message="Job cancelled by user"
            )
    
    logger.info(
        f"[BatchJob {job_id}] Cancelled "
        f"(revoked {revoked} pending, terminated {terminated} processing)"
    )
    
    return jsonify({
        "message": "Job cancelled",
        "status": "cancelled",
        "revoked_tasks": revoked,
        "terminated_tasks": terminated,
    }), 200


# ---------------------------------------------------------------------------
# Delete Batch Job
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs/<job_id>", methods=["DELETE"])
@jwt_required()
def delete_batch_job(project_id, job_id):
    """
    Delete a batch job and all its CPE records.
    
    Note: Only completed/failed/cancelled jobs can be deleted.
    
    Returns:
        {
            "message": "Job deleted"
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    job = dbm.get_batch_job(job_id)
    if not job or job.project_id != project_id:
        return jsonify({"error": "Job not found"}), 404
    
    if job.status in ("queued", "processing"):
        return jsonify({"error": "Cannot delete active job. Cancel it first."}), 400
    
    # Revoke any lingering tasks in Redis before deleting DB rows
    all_records = dbm.get_job_cpe_records(job_id)
    revoked = 0
    for record in all_records:
        if record.celery_task_id:
            celery.control.revoke(record.celery_task_id, terminate=True)
            revoked += 1
    if revoked:
        logger.info(f"[BatchJob {job_id}] Revoked {revoked} tasks before delete")
    
    success, error = dbm.delete_batch_job(job_id)
    if not success:
        return jsonify({"error": error}), 500
    
    return jsonify({"message": "Job deleted"}), 200

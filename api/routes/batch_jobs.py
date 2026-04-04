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

import fcntl
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from services.celery_worker.celery_app import celery
from logai.utils.constants import BASE_DIR

logger = logging.getLogger(__name__)

batch_jobs_bp = Blueprint("batch_jobs", __name__)


def _get_upload_dir() -> Path:
    """Get the temporary upload directory."""
    upload_dir = Path("/tmp/batch_uploads")
    upload_dir.mkdir(exist_ok=True)
    return upload_dir


def _upload_meta_path(upload_id: str) -> Path:
    """JSON metadata for chunked uploads (shared across Gunicorn workers)."""
    return _get_upload_dir() / f"{upload_id}.upload.json"


def _upload_not_found() -> dict:
    return {
        "status": "not_found",
        "progress": 0,
        "total_size": 0,
        "uploaded_size": 0,
        "error": "Upload not found",
    }


def _set_upload_status(upload_id: str, **kwargs) -> None:
    """Persist upload status so any Gunicorn worker can read it."""
    path = _upload_meta_path(upload_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            raw = f.read()
            if raw.strip():
                existing = json.loads(raw)
            else:
                existing = {}
            if not existing:
                existing = {
                    "status": "uploading",
                    "progress": 0,
                    "total_size": 0,
                    "uploaded_size": 0,
                    "error": None,
                }
            existing.update(kwargs)
            f.seek(0)
            f.truncate()
            json.dump(existing, f)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _get_upload_status(upload_id: str) -> dict:
    path = _upload_meta_path(upload_id)
    if not path.exists():
        return dict(_upload_not_found())
    try:
        with open(path, "r", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return dict(data)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[ChunkedUpload] Failed to read upload meta {upload_id}: {e}")
        return dict(_upload_not_found())

def _get_batch_logs_dir():
    """Get the batch CPE logs directory, supporting both local dev and Docker deployment."""
    # Check if running in Docker (presence of /app directory)
    docker_path = Path("/app/batch_cpe_logs")
    if docker_path.parent.exists():
        return docker_path
    
    # Local development path
    local_path = Path(BASE_DIR) / "batch_cpe_logs"
    return local_path


_BATCH_UPLOAD_ROOT_MAX_DEPTH = 8


def _is_noise_batch_path(name: str) -> bool:
    """Skip macOS / archive metadata when detecting a single wrapper folder."""
    return name == "__MACOSX" or name == ".DS_Store" or name.startswith("._")


def _resolve_batch_cleanup_root(extract_dir: Path) -> Path:
    """Descend single-child wrapper dirs so the cleanup script sees CPE subfolders with .tgz.

    ``process_cpe_logs.py`` only scans *immediate* subdirectories. Many uploads are zipped as
    ``outer/CPExxx/*.tgz``; running against ``outer`` would see no .tgz in ``CPExxx`` at the
    wrong level without this step.
    """
    cur = extract_dir.resolve()
    for _ in range(_BATCH_UPLOAD_ROOT_MAX_DEPTH):
        try:
            entries = [
                p
                for p in cur.iterdir()
                if p.name != "archive" and not _is_noise_batch_path(p.name)
            ]
        except OSError:
            break
        subdirs = [p for p in entries if p.is_dir()]
        files = [p for p in entries if p.is_file()]
        if len(subdirs) == 1 and len(files) == 0:
            cur = subdirs[0]
            continue
        break
    return cur


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


# ---------------------------------------------------------------------------
# Script Download Endpoint
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs/cleanup-directories", methods=["POST"])
@jwt_required()
def cleanup_batch_directories(project_id):
    """
    Manual cleanup of batch job directories for a project.
    This is useful for cleaning up orphaned batch upload directories.
    """
    try:
        user_id = get_user_id()
        project, err = _verify_project(project_id, user_id)
        if err:
            return err
        
        # Get batch logs directory
        batch_dir = _get_batch_logs_dir()
        if not batch_dir.exists():
            return jsonify({"message": "No batch directories found"}), 200
        
        # Get all batch jobs for this project
        batch_jobs = dbm.get_project_batch_jobs(project_id)
        if not batch_jobs:
            return jsonify({"message": "No batch jobs found for this project"}), 200
        
        cleanup_count = 0
        
        # Clean up old batch upload directories
        import time
        import re
        uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        
        for upload_dir in batch_dir.iterdir():
            if upload_dir.is_dir() and uuid_pattern.match(upload_dir.name):
                # Check if directory is old (more than 2 hours)
                dir_age = time.time() - upload_dir.stat().st_mtime
                if dir_age > 7200:  # 2 hours
                    try:
                        logger.info(f"Manual cleanup of batch directory: {upload_dir}")
                        import shutil
                        shutil.rmtree(upload_dir, ignore_errors=True)
                        cleanup_count += 1
                        
                    except Exception as e:
                        logger.warning(f"Failed to clean up {upload_dir}: {e}")
        
        return jsonify({
            "message": f"Cleaned up {cleanup_count} batch directories",
            "cleanup_count": cleanup_count
        }), 200
        
    except Exception as e:
        logger.error(f"Error in manual batch cleanup: {e}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500


@batch_jobs_bp.route("/<project_id>/batch-jobs/download-script", methods=["GET"])
@jwt_required()
def download_processing_script(project_id):
    """
    Download the CPE log processing script for local use.
    
    Returns the process_cpe_logs.py script as a downloadable file.
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    try:
        # Get the script path
        script_path = Path(__file__).parent.parent.parent / "scripts" / "process_cpe_logs.py"
        
        if not script_path.exists():
            return jsonify({"error": "Script not found"}), 404
        
        from flask import send_file
        return send_file(
            str(script_path),
            as_attachment=True,
            download_name="process_cpe_logs.py",
            mimetype="text/x-python",
        )
        
    except Exception as e:
        logger.error(f"[ScriptDownload] Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Chunked Upload Endpoints
# ---------------------------------------------------------------------------

@batch_jobs_bp.route("/<project_id>/batch-jobs/upload/init", methods=["POST"])
@jwt_required()
def init_chunked_upload(project_id):
    """
    Initialize a chunked upload session.
    
    Request body:
        {
            "filename": "batch_logs.zip",
            "total_size": 2147483648
        }
    
    Returns:
        {
            "upload_id": "uuid",
            "chunk_size": 52428800,  # 50MB recommended
            "message": "Upload session initialized"
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    try:
        data = request.get_json() or {}
        filename = data.get("filename")
        total_size = data.get("total_size", 0)
        
        if not filename:
            return jsonify({"error": "filename is required"}), 400
        
        if total_size <= 0:
            return jsonify({"error": "total_size must be positive"}), 400
        
        # Generate upload session
        upload_id = str(uuid.uuid4())
        upload_dir = _get_upload_dir()
        temp_file = upload_dir / f"{upload_id}.tmp"
        
        # Initialize empty file
        temp_file.touch()
        
        _set_upload_status(
            upload_id,
            status="uploading",
            filename=filename,
            total_size=total_size,
            uploaded_size=0,
            progress=0,
            temp_file=str(temp_file),
            project_id=project_id,
            user_id=user_id,
        )
        
        logger.info(f"[ChunkedUpload] Initialized upload {upload_id} for {filename} ({total_size} bytes)")
        
        return jsonify({
            "upload_id": upload_id,
            "chunk_size": 52428800,  # 50MB
            "message": "Upload session initialized",
        }), 201
        
    except Exception as e:
        logger.error(f"[ChunkedUpload] Init error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@batch_jobs_bp.route("/<project_id>/batch-jobs/upload/<upload_id>/chunk", methods=["POST"])
@jwt_required()
def upload_chunk(project_id, upload_id):
    """
    Upload a file chunk.
    
    Request body: binary chunk data
    Headers:
        Content-Range: bytes start-end/total
    
    Returns:
        {
            "message": "Chunk uploaded",
            "progress": 45.2,
            "uploaded_size": 1073741824
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    try:
        upload_info = _get_upload_status(upload_id)
        if upload_info["status"] == "not_found":
            return jsonify({"error": "Upload session not found"}), 404
        
        if upload_info["status"] != "uploading":
            return jsonify({"error": f"Upload session is {upload_info['status']}"}), 400
        
        # Parse Content-Range header
        content_range = request.headers.get("Content-Range")
        if not content_range:
            return jsonify({"error": "Content-Range header required"}), 400
        
        # Expected format: "bytes start-end/total"
        try:
            parts = content_range.replace("bytes ", "").split("/")
            range_part = parts[0]
            start, end = map(int, range_part.split("-"))
            total = int(parts[1])
        except (ValueError, IndexError):
            return jsonify({"error": "Invalid Content-Range format"}), 400
        
        chunk_data = request.get_data()
        expected_size = end - start + 1
        
        if len(chunk_data) != expected_size:
            return jsonify({"error": f"Chunk size mismatch: got {len(chunk_data)}, expected {expected_size}"}), 400
        
        # Append chunk to temp file
        temp_file = Path(upload_info["temp_file"])
        with open(temp_file, "r+b") as f:
            f.seek(start)
            f.write(chunk_data)
        
        uploaded_size = start + len(chunk_data)
        progress = (uploaded_size / upload_info["total_size"]) * 100
        
        _set_upload_status(
            upload_id,
            uploaded_size=uploaded_size,
            progress=progress,
        )
        
        logger.info(f"[ChunkedUpload] {upload_id}: chunk {start}-{end} ({len(chunk_data)} bytes)")
        
        return jsonify({
            "message": "Chunk uploaded",
            "progress": round(progress, 1),
            "uploaded_size": uploaded_size,
        }), 200
        
    except Exception as e:
        logger.error(f"[ChunkedUpload] Chunk upload error: {e}", exc_info=True)
        _set_upload_status(upload_id, status="error", error=str(e))
        return jsonify({"error": str(e)}), 500


@batch_jobs_bp.route("/<project_id>/batch-jobs/upload/<upload_id>/complete", methods=["POST"])
@jwt_required()
def complete_chunked_upload(project_id, upload_id):
    """
    Complete the chunked upload and start processing.
    
    Returns:
        {
            "message": "Upload completed, processing started",
            "job_id": "uuid"
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    try:
        upload_info = _get_upload_status(upload_id)
        if upload_info["status"] == "not_found":
            return jsonify({"error": "Upload session not found"}), 404
        
        if upload_info["status"] != "uploading":
            return jsonify({"error": f"Upload session is {upload_info['status']}"}), 400
        
        temp_file = Path(upload_info["temp_file"])
        if not temp_file.exists():
            return jsonify({"error": "Upload file not found"}), 404
        
        # Verify file size
        actual_size = temp_file.stat().st_size
        expected_size = upload_info["total_size"]
        
        if actual_size != expected_size:
            _set_upload_status(upload_id, status="error", error=f"File size mismatch: {actual_size} != {expected_size}")
            return jsonify({"error": f"File size mismatch: got {actual_size}, expected {expected_size}"}), 400
        
        _set_upload_status(upload_id, status="processing", progress=100)
        
        # Launch background processing
        from flask import current_app
        flask_app = current_app._get_current_object()
        
        t = threading.Thread(
            target=_process_uploaded_archive,
            args=(flask_app, upload_id, project_id, user_id, temp_file, upload_info["filename"]),
            daemon=True,
        )
        t.start()
        
        logger.info(f"[ChunkedUpload] {upload_id}: upload completed, processing started")
        
        return jsonify({
            "message": "Upload completed, processing started",
            "upload_id": upload_id,
        }), 200
        
    except Exception as e:
        logger.error(f"[ChunkedUpload] Complete error: {e}", exc_info=True)
        _set_upload_status(upload_id, status="error", error=str(e))
        return jsonify({"error": str(e)}), 500


@batch_jobs_bp.route("/<project_id>/batch-jobs/upload/<upload_id>/status", methods=["GET"])
@jwt_required()
def get_upload_status(project_id, upload_id):
    """
    Get the status of a chunked upload.
    
    Returns:
        {
            "status": "uploading|processing|completed|error",
            "progress": 45.2,
            "uploaded_size": 1073741824,
            "total_size": 2147483648,
            "error": null,
            "job_id": "uuid"  # Only present when completed
        }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    status = _get_upload_status(upload_id)
    return jsonify(status), 200


def _process_uploaded_archive(flask_app, upload_id, project_id, user_id, temp_file, filename):
    """
    Background thread: extract uploaded archive, run cleaning script, create batch job.
    """
    try:
        with flask_app.app_context():
            _set_upload_status(upload_id, status="processing", progress=100, 
                             message="Extracting archive...")
            
            # Create extraction directory
            batch_dir = _get_batch_logs_dir()
            batch_dir.mkdir(parents=True, exist_ok=True)
            extract_dir = batch_dir / upload_id
            extract_dir.mkdir(exist_ok=True)
            
            # Extract archive
            logger.info(f"[ChunkedUpload] {upload_id}: Extracting {filename} to {extract_dir}")
            
            import zipfile
            with zipfile.ZipFile(temp_file, 'r') as zf:
                zf.extractall(extract_dir)
            
            cleanup_root = _resolve_batch_cleanup_root(extract_dir)
            if cleanup_root != extract_dir.resolve():
                logger.info(
                    f"[ChunkedUpload] {upload_id}: Cleanup root normalized "
                    f"{extract_dir} -> {cleanup_root}"
                )
            
            _set_upload_status(upload_id, message="Running log cleanup script...")
            
            project_stem = Path(filename).stem
            
            # Run cleaning script (auto single-CPE merge is detected inside process_cpe_logs.py)
            script_path = Path(__file__).parent.parent.parent / "scripts" / "process_cpe_logs.py"
            cmd = [
                "python3", str(script_path),
                "--target-dir", str(cleanup_root),
                "--project-name", project_stem,
            ]
            
            logger.info(f"[ChunkedUpload] {upload_id}: Running cleanup: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                error_msg = f"Cleanup script failed: {result.stderr}"
                _set_upload_status(upload_id, status="error", error=error_msg)
                logger.error(f"[ChunkedUpload] {upload_id}: {error_msg}")
                return
            
            _set_upload_status(upload_id, message="Creating batch job...")
            
            # Per-CPE zips live under cleanup_root/archive/ (see process_cpe_logs.py)
            archive_dir = cleanup_root / "archive"
            zip_files = list(archive_dir.glob("*.zip")) if archive_dir.exists() else []
            
            if not zip_files:
                zip_files = list(cleanup_root.glob("*.zip"))
            
            if not zip_files:
                detail = (result.stdout or "").strip() or (result.stderr or "").strip() or "no script output"
                error_msg = (
                    "No .zip files found after cleanup (expected CPE folders with .tgz under the "
                    f"upload root; checked {archive_dir} and {cleanup_root}). Script output: {detail[:2000]}"
                )
                _set_upload_status(upload_id, status="error", error=error_msg)
                logger.error(f"[ChunkedUpload] {upload_id}: {error_msg}")
                return
            
            # Create batch job
            job_id = dbm.create_batch_job(project_id, user_id, len(zip_files), "cpe_processing", job_id=upload_id)
            
            zip_dir = archive_dir if (archive_dir.exists() and list(archive_dir.glob("*.zip"))) else cleanup_root
            
            # Dispatch Celery task
            from services.celery_worker.tasks import process_cpe_batch_job
            task = process_cpe_batch_job.apply_async(
                args=(job_id, user_id, project_id, str(zip_dir)),
                priority=10,
            )
            
            _set_upload_status(
                upload_id,
                status="completed",
                message=f"Batch job created with {len(zip_files)} CPE(s)",
                job_id=job_id,
                celery_task_id=task.id,
            )
            
            # Clean up temp file
            temp_file.unlink(missing_ok=True)
            
            logger.info(f"[ChunkedUpload] {upload_id}: Processing complete, batch job {job_id} created")
            
    except Exception as e:
        logger.exception(f"[ChunkedUpload] {upload_id}: Processing failed: {e}")
        _set_upload_status(upload_id, status="error", error=str(e))
        # Clean up temp file on error
        temp_file.unlink(missing_ok=True)


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
            "cpe_folder_path": "test10",  # Relative to batch logs directory
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
        batch_logs_root = _get_batch_logs_dir()
        if not cpe_folder_input.startswith("/"):
            cpe_folder_path = str(batch_logs_root / cpe_folder_input)
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
        
    # Attempt to clean up the associated batch_cpe_logs directory if it exists.
    # For chunked uploads, the job_id matches the upload directory name.
    try:
        import shutil
        batch_logs_root = _get_batch_logs_dir()
        job_dir = batch_logs_root / job_id
        if job_dir.exists() and job_dir.is_dir():
            shutil.rmtree(job_dir, ignore_errors=True)
            logger.info(f"[BatchJob {job_id}] Cleaned up uploaded batch directory.")
    except Exception as e:
        logger.warning(f"[BatchJob {job_id}] Failed to clean up batch directory: {e}")
        
    # Run a general cleanup of any old/abandoned batch upload directories
    try:
        dbm._cleanup_batch_job_directories(project_id)
    except Exception:
        pass
    
    return jsonify({"message": "Job deleted"}), 200

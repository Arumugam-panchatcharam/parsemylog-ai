"""
Celery Tasks for Batch CPE Processing
======================================

Handles asynchronous processing of CPE logs in batches:
- Extracts CPE zip files
- Merges log files
- Indexes patterns with Drain3
- Parses telemetry data
- Updates Qdrant vector database

Multi-CPE Strategy:
- Uses single Qdrant collection per project with CPE metadata
- Rate limits concurrent Qdrant writes to avoid overload
- Sequential processing per CPE to ensure data consistency
"""

import os
import sys
import time
import logging
import zipfile
import uuid
from sqlalchemy.exc import IntegrityError
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure project root is on sys.path (needed for prefork/spawn workers on macOS)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _ensure_project_root_on_syspath() -> None:
    """Re-assert repo root on sys.path inside tasks (handles odd Celery prefork/import orders)."""
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)

from celery import Task

# Import app before logai.constants so celery_app bootstrap (dotenv + QDRANT_URL rewrite) runs first.
from .celery_app import celery

from logai.utils.constants import SKIP_WALK_DIRECTORY_NAMES, is_os_junk_filename

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Maximum concurrent CPE processing tasks (to avoid overwhelming Qdrant)
MAX_CONCURRENT_CPE_TASKS = 4


class JobCancelled(Exception):
    """Raised when the parent batch job has been cancelled."""
    pass


def _check_job_cancelled(dbm, job_id: str):
    """Raise JobCancelled if the batch job has been cancelled or deleted."""
    job = dbm.get_batch_job(job_id)
    if not job:
        raise JobCancelled(f"Batch job {job_id} no longer exists")
    if job.status == "cancelled":
        raise JobCancelled(f"Batch job {job_id} was cancelled")


class CPEProcessTask(Task):
    """Base task class with retry logic and error handling."""
    autoretry_for = (Exception,)
    dont_autoretry_for = (JobCancelled, IntegrityError)
    retry_kwargs = {'max_retries': 3, 'countdown': 60}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True


@celery.task(base=CPEProcessTask, bind=True, name="process_cpe_batch_job")
def process_cpe_batch_job(self, job_id: str, user_id: int, project_id: str, 
                          cpe_folder_path: str):
    """
    Process a batch of CPE zip files.
    
    This is the master task that:
    1. Scans folder for CPE zip files
    2. Creates CPE processing records in DB
    3. Dispatches individual CPE processing tasks
    4. Updates batch job status
    
    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID
        cpe_folder_path: Path to folder containing CPE zip files
    """
    logger.info(f"[BatchJob {job_id}] Starting batch processing from {cpe_folder_path}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    try:
        from api.user_db_mngr import DBManager
        from flask import Flask
        
        # Create minimal Flask app for DB context
        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        
        dbm = DBManager()
        dbm.init_app(app)
        
        with app.app_context():
            # Update job status to processing
            dbm.update_batch_job_status(job_id, "processing")
            
            # Scan for CPE zip files
            folder = Path(cpe_folder_path)
            if not folder.exists():
                raise FileNotFoundError(f"CPE folder not found: {cpe_folder_path}")
            
            zip_files = list(folder.glob("*.zip"))
            logger.info(f"[BatchJob {job_id}] Found {len(zip_files)} zip files")
            
            if not zip_files:
                dbm.update_batch_job_status(job_id, "completed", "No zip files found")
                return {"status": "completed", "message": "No zip files found"}
            
            # Dispatch individual CPE processing tasks
            for zip_file in zip_files:
                # Stop dispatching if the job was cancelled mid-way
                job = dbm.get_batch_job(job_id)
                if job and job.status == "cancelled":
                    logger.info(f"[BatchJob {job_id}] Job cancelled — stopping dispatch")
                    break
                
                serial = zip_file.stem  # Filename without .zip extension
                
                # Create CPE processing record
                task = process_single_cpe.apply_async(
                    args=(job_id, user_id, project_id, serial, str(zip_file)),
                    priority=5,
                )
                
                record_id = dbm.create_cpe_record(job_id, serial, task.id)
                logger.info(f"[BatchJob {job_id}] Dispatched task {task.id} for CPE {serial}")
            
            logger.info(f"[BatchJob {job_id}] Dispatched {len(zip_files)} CPE processing tasks")
            
            return {
                "status": "processing",
                "total_cpes": len(zip_files),
                "message": f"Processing {len(zip_files)} CPEs"
            }
            
    except Exception as e:
        logger.error(f"[BatchJob {job_id}] Error: {e}", exc_info=True)
        try:
            with app.app_context():
                dbm.update_batch_job_status(job_id, "failed", str(e))
        except:
            pass
        raise


@celery.task(base=CPEProcessTask, bind=True, name="extract_upload")
def extract_upload(self, job_id: str, user_id: int, project_id: str, 
                  serial: str, zip_path: str):
    """
    Extract CPE zip file and flatten to staging directory.
    
    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID
        serial: CPE serial number
        zip_path: Path to CPE zip file
    """
    logger.info(f"[CPE {serial}] Starting extraction for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from logai.utils.constants import UPLOAD_DIRECTORY
        import hashlib
        
        def _file_hash(file_path):
            """Generate MD5 hash of file content."""
            hasher = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        
        # Setup paths
        project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
        cpe_dir = project_dir / serial
        cpe_dir.mkdir(parents=True, exist_ok=True)
        
        raw_dir = cpe_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        
        staging_dir = cpe_dir / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        
        # Step 1: Extract zip file to raw_dir
        logger.info(f"[CPE {serial}] Extracting {zip_path}")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(raw_dir)
        
        # Step 2: Flatten raw_dir to staging_dir with deduplication
        file_hashes = {}  # hash -> filename mapping
        
        for root, dirs, files in os.walk(raw_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_WALK_DIRECTORY_NAMES]
            for file in files:
                if is_os_junk_filename(file):
                    continue
                src = Path(root) / file
                dst = staging_dir / file
                
                # Calculate file hash for deduplication
                try:
                    file_hash = _file_hash(src)
                except Exception as e:
                    logger.warning(f"[CPE {serial}] Could not hash {src}: {e}")
                    # Fallback to original collision handling
                    if dst.exists():
                        base, ext = os.path.splitext(file)
                        dst = staging_dir / f"{base}_{int(time.time()*1000)}{ext}"
                    shutil.move(str(src), str(dst))
                    continue
                
                # Check if we've seen this file content before
                if file_hash in file_hashes:
                    existing_file = file_hashes[file_hash]
                    logger.info(f"[CPE {serial}] Skipping duplicate file: {file} (same content as {existing_file})")
                    src.unlink()  # Remove the duplicate
                    continue
                
                # Handle filename collisions (but content is different)
                if dst.exists():
                    base, ext = os.path.splitext(file)
                    counter = 1
                    while dst.exists():
                        dst = staging_dir / f"{base}_{counter}{ext}"
                        counter += 1
                    logger.info(f"[CPE {serial}] Renamed file to avoid collision: {file} -> {dst.name}")
                
                # Move the file and record its hash
                shutil.move(str(src), str(dst))
                file_hashes[file_hash] = dst.name
        
        # Cleanup raw directory
        if raw_dir.exists():
            shutil.rmtree(raw_dir)
        
        logger.info(f"[CPE {serial}] Processed files: {len(file_hashes)} unique files moved to staging")
        
        return {
            "status": "completed",
            "serial": serial,
            "files_extracted": len(file_hashes),
            "staging_dir": str(staging_dir)
        }
        
    except Exception as e:
        logger.error(f"[CPE {serial}] Extraction error: {e}", exc_info=True)
        return {"status": "error", "serial": serial, "error": str(e)}


@celery.task(base=CPEProcessTask, bind=True, name="merge_cpe_logs_task")
def merge_cpe_logs_task(self, job_id: str, user_id: int, project_id: str, 
                       serial: str, staging_dir: str):
    """
    Merge CPE logs from staging directory.
    
    Args:
        job_id: Batch job ID
        user_id: User ID  
        project_id: Project ID
        serial: CPE serial number
        staging_dir: Path to staging directory
    """
    logger.info(f"[CPE {serial}] Starting log merge for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from api.file_manager import merge_cpe_logs
        from logai.utils.constants import UPLOAD_DIRECTORY
        
        project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
        cpe_dir = project_dir / serial
        staging_path = Path(staging_dir)
        
        logger.info(f"[CPE {serial}] Merging logs from {staging_dir}")
        merge_cpe_logs(staging_path, cpe_dir)
        
        # Cleanup staging directory
        if staging_path.exists():
            shutil.rmtree(staging_path)
        
        return {
            "status": "completed",
            "serial": serial,
            "cpe_dir": str(cpe_dir)
        }
        
    except Exception as e:
        logger.error(f"[CPE {serial}] Log merge error: {e}", exc_info=True)
        return {"status": "error", "serial": serial, "error": str(e)}


@celery.task(base=CPEProcessTask, bind=True, name="process_single_cpe_rg_drain3")
def process_single_cpe_rg_drain3(
    self,
    job_id: str,
    user_id: int,
    project_id: str,
    serial: str,
    cpe_dir: str,
    fallback_date_from: Optional[str] = None,
    fallback_date_to: Optional[str] = None,
):
    """
    Process CPE for RG patterns and Drain3 templates.
    Includes info extraction, telemetry parsing, and file registration.

    fallback_date_*: When telemetry does not yield ``date_from`` / ``date_to`` (common for crash
    portal bundles), use the user's requested fetch window so project CPE CSV and overview match device JSON.

    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID
        serial: CPE serial number
        cpe_dir: Path to CPE directory
        fallback_date_from: YYYY-MM-DD from device JSON ranges (minimum start)
        fallback_date_to: YYYY-MM-DD from device JSON ranges (maximum end)
    """
    logger.info(f"[CPE {serial}] Starting RG+Drain3 processing for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from api.user_db_mngr import DBManager
        from api.file_manager import register_cpe_files
        from logai.info_extractor import refresh_cpe_disk_caches
        from logai.telemetry_parser import parse_telemetry_file
        from flask import Flask
        
        # Create Flask app context
        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        
        dbm = DBManager()
        dbm.init_app(app)
        
        with app.app_context():
            # Check job cancellation
            _check_job_cancelled(dbm, job_id)
            
            cpe_path = Path(cpe_dir)
            
            # Info extraction (.version_cache.json / .device_info_cache.json); merge_cpe_logs_task
            # already runs refresh after merge — this is a fast cache hit or covers alternate entrypoints.
            mac = None
            date_from = None
            date_to = None

            try:
                fallback_info = refresh_cpe_disk_caches(cpe_path, force=False)
                if fallback_info:
                    mac = fallback_info.get("mac")
            except Exception:
                pass

            # Telemetry parsing (cached to disk)
            try:
                t2_path = cpe_path / "telemetry2_0.txt"
                dcm_path = cpe_path / "dcmscript.log"
                tel_reports, _, tel_summary, _ = parse_telemetry_file(
                    t2_path, dcmscript_path=dcm_path, cpe_dir=cpe_path,
                )
                if tel_summary:
                    otr = tel_summary.get("overall_time_range") or {}
                    date_from = otr.get("first")
                    date_to = otr.get("last")
                    if not date_from or not date_to:
                        legacy = tel_summary.get("date_range") or {}
                        date_from = date_from or legacy.get("from")
                        date_to = date_to or legacy.get("to")
                    if date_from:
                        ds = str(date_from).strip()
                        date_from = ds[:10] if len(ds) >= 10 and ds[4:5] == "-" and ds[7:8] == "-" else ds
                    if date_to:
                        ds = str(date_to).strip()
                        date_to = ds[:10] if len(ds) >= 10 and ds[4:5] == "-" and ds[7:8] == "-" else ds
                if not mac and tel_reports:
                    for r in tel_reports:
                        m = r.get("mac", "")
                        if m:
                            mac = m.replace(":", "").lower()
                            break
            except Exception:
                pass

            # Remote fetch: device-list JSON specifies requested ranges; telemetry may omit dates.
            ff = _iso_yyyy_mm_dd_or_none(fallback_date_from)
            tt = _iso_yyyy_mm_dd_or_none(fallback_date_to)
            if ff and (not date_from or not str(date_from).strip()):
                date_from = ff
            if tt and (not date_to or not str(date_to).strip()):
                date_to = tt

            # Build telemetry API cache
            try:
                from api.routes.telemetry import _parse_and_build as _telemetry_parse_and_build
                _telemetry_parse_and_build(cpe_path)
                logger.info(f"[CPE {serial}] Built telemetry API cache")
            except Exception as e:
                logger.warning(f"[CPE {serial}] Telemetry cache build error: {e}")

            # Build selfheal API cache
            try:
                from api.routes.selfheal import _parse_and_build as _selfheal_parse_and_build
                _selfheal_parse_and_build(cpe_path, cpe_serial=serial, force=False, persist_api_cache=True)
                logger.info(f"[CPE {serial}] Built selfheal API cache")
            except Exception as e:
                logger.warning(f"[CPE {serial}] Selfheal cache build error: {e}")

            # Save CPE + register files
            dbm.save_cpe(project_id, serial, mac, date_from, date_to)
            log_files = register_cpe_files(cpe_path, project_id, serial, dbm)
            logger.info(f"[CPE {serial}] Registered {len(log_files)} files")
            
            return {
                "status": "completed",
                "serial": serial,
                "log_files": len(log_files),
                "cpe_dir": str(cpe_path)
            }
            
    except JobCancelled:
        logger.info(f"[CPE {serial}] Skipped RG+Drain3 — job {job_id} was cancelled")
        return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
    except Exception as e:
        logger.error(f"[CPE {serial}] RG+Drain3 error: {e}", exc_info=True)
        return {"status": "error", "serial": serial, "error": str(e)}


@celery.task(base=CPEProcessTask, bind=True, name="run_indexer_async_task")
def run_indexer_async_task(self, job_id: str, project_id: str, serial: str, cpe_dir: str):
    """
    Run indexer (Drain3 + Qdrant) for a single CPE.
    
    Args:
        job_id: Batch job ID
        project_id: Project ID
        serial: CPE serial number
        cpe_dir: Path to CPE directory
    """
    logger.info(f"[CPE {serial}] Starting indexing for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from api.indexer import run_indexer_async
        import pandas as pd
        
        # Check job cancellation
        from api.user_db_mngr import DBManager
        from flask import Flask
        
        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        
        dbm = DBManager()
        dbm.init_app(app)
        
        with app.app_context():
            _check_job_cancelled(dbm, job_id)
        
        cpe_path = Path(cpe_dir)
        
        # Run indexing synchronously  
        logger.info(f"[CPE {serial}] Starting pattern indexing on {cpe_path}")
        run_indexer_async(cpe_path, project_id, cpe_id=serial)
        
        # Count patterns from parquet files
        patterns_indexed = 0
        for parquet_file in cpe_path.glob("*_rg.parquet"):
            try:
                df = pd.read_parquet(parquet_file)
                patterns_indexed += len(df)
            except Exception as e:
                logger.warning(f"[CPE {serial}] Could not read {parquet_file.name}: {e}")
        
        logger.info(f"[CPE {serial}] Indexed {patterns_indexed} patterns")
        
        return {
            "status": "completed",
            "serial": serial,
            "patterns_indexed": patterns_indexed,
            "cpe_dir": str(cpe_path)
        }
        
    except JobCancelled:
        logger.info(f"[CPE {serial}] Skipped indexing — job {job_id} was cancelled")
        return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
    except Exception as e:
        logger.error(f"[CPE {serial}] Indexing error: {e}", exc_info=True)
        return {"status": "error", "serial": serial, "error": str(e)}


@celery.task(base=CPEProcessTask, bind=True, name="polars_etl_per_cpe_task")
def polars_etl_per_cpe_task(self, job_id: str, user_id: str, project_id: str, 
                           serial: str, cpe_dir: str):
    """
    Run Polars ETL for a single CPE.
    
    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID
        serial: CPE serial number
        cpe_dir: Path to CPE directory
    """
    logger.info(f"[CPE {serial}] Starting Polars ETL for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from logai.analytics.polars_etl import polars_etl_per_cpe
        
        # Check job cancellation
        from api.user_db_mngr import DBManager
        from flask import Flask
        
        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        
        dbm = DBManager()
        dbm.init_app(app)
        
        with app.app_context():
            _check_job_cancelled(dbm, job_id)
        
        # Run Polars ETL
        result = polars_etl_per_cpe(user_id, project_id, serial)
        
        return result
        
    except JobCancelled:
        logger.info(f"[CPE {serial}] Skipped Polars ETL — job {job_id} was cancelled")
        return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
    except Exception as e:
        logger.error(f"[CPE {serial}] Polars ETL error: {e}", exc_info=True)
        return {"status": "error", "serial": serial, "error": str(e)}


@celery.task(base=CPEProcessTask, bind=True, name="mark_cpe_complete")
def mark_cpe_complete(self, job_id: str, user_id: int, project_id: str, 
                     serial: str, logs_extracted: int = 0, patterns_indexed: int = 0):
    """
    Mark CPE as complete and update batch progress.
    
    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID
        serial: CPE serial number
        logs_extracted: Number of log files extracted
        patterns_indexed: Number of patterns indexed
    """
    logger.info(f"[CPE {serial}] Marking complete for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from api.user_db_mngr import DBManager
        from flask import Flask
        
        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        
        dbm = DBManager()
        dbm.init_app(app)
        
        with app.app_context():
            # Get CPE record
            records = dbm.get_job_cpe_records(job_id)
            record = next((r for r in records if r.serial == serial), None)
            
            if record:
                # Mark as completed
                dbm.update_cpe_record_status(
                    record.id,
                    "completed",
                    logs_extracted=logs_extracted,
                    patterns_indexed=patterns_indexed
                )
                
                # Update batch job progress
                dbm.increment_batch_job_progress(job_id, success=True)
                
                # Check if batch is complete
                job = dbm.get_batch_job(job_id)
                if job and (job.processed_cpes + job.failed_cpes) >= job.total_cpes:
                    # Trigger fleet analytics finalization
                    finalize_project_analytics.delay(job_id, user_id, project_id)
                    logger.info(f"[BatchJob {job_id}] Triggering fleet analytics finalization")
                
                return {
                    "status": "completed",
                    "serial": serial,
                    "batch_complete": job and (job.processed_cpes + job.failed_cpes) >= job.total_cpes
                }
            else:
                return {"status": "error", "serial": serial, "error": "CPE record not found"}
                
    except Exception as e:
        logger.error(f"[CPE {serial}] Mark complete error: {e}", exc_info=True)
        return {"status": "error", "serial": serial, "error": str(e)}


@celery.task(base=CPEProcessTask, bind=True, name="finalize_project_analytics")
def finalize_project_analytics(self, job_id: str, user_id: int, project_id: str):
    """
    Finalize project analytics by running fleet-level aggregation.
    
    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID
    """
    logger.info(f"[BatchJob {job_id}] Starting fleet analytics finalization")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from logai.analytics.fleet_summary import generate_fleet_summary
        
        # Generate fleet summary
        result = generate_fleet_summary(user_id, project_id)
        
        # Update batch job status to completed
        from api.user_db_mngr import DBManager
        from flask import Flask
        
        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        
        dbm = DBManager()
        dbm.init_app(app)
        
        with app.app_context():
            dbm.update_batch_job_status(job_id, "completed")
        
        logger.info(f"[BatchJob {job_id}] Fleet analytics finalization completed")
        
        return result
        
    except Exception as e:
        logger.error(f"[BatchJob {job_id}] Fleet finalization error: {e}", exc_info=True)
        
        # Mark batch as completed even if fleet analytics failed
        try:
            from api.user_db_mngr import DBManager
            from flask import Flask
            
            app = Flask(__name__)
            db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
            app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
            app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
            
            dbm = DBManager()
            dbm.init_app(app)
            
            with app.app_context():
                dbm.update_batch_job_status(job_id, "completed", f"Fleet analytics failed: {e}")
        except:
            pass
        
        return {"status": "error", "error": str(e)}


def run_batch_cpe_pipeline_sync(
    *,
    task_self_id: Optional[str],
    job_id: str,
    user_id: int,
    project_id: str,
    serial: str,
    zip_path: str,
    fallback_date_from: Optional[str] = None,
    fallback_date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the extract→merge→RG→index→polars→mark pipeline synchronously inside a Celery worker.
    Used by process_single_cpe and remote-log ingestion (no nested Celery `.get`).

    fallback_date_*: Passed into RG phase so ``save_cpe`` gets requested fetch bounds when telemetry
    has no usable date span (e.g. crash portal bundles).
    """
    from api.user_db_mngr import DBManager
    from flask import Flask

    app = Flask(__name__)
    db_path_resolved = os.getenv("DB_PATH", "/app/data/logai_users.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    dbm = DBManager()
    dbm.init_app(app)

    record_id: str | None = None

    with app.app_context():
        _check_job_cancelled(dbm, job_id)

        records = dbm.get_job_cpe_records(job_id)
        record = next((r for r in records if r.serial == serial), None)

        rid_for_create = task_self_id or str(uuid.uuid4())
        if record:
            record_id = record.id
            dbm.update_cpe_record_status(record_id, "processing")
        else:
            record_id = dbm.create_cpe_record(job_id, serial, celery_task_id=rid_for_create)
            dbm.update_cpe_record_status(record_id, "processing")

    start_time = time.time()

    result1 = extract_upload(job_id, user_id, project_id, serial, zip_path)
    if result1["status"] != "completed":
        raise RuntimeError(result1.get("error", "Extract upload failed"))

    result2 = merge_cpe_logs_task(job_id, user_id, project_id, serial, result1["staging_dir"])
    if result2["status"] != "completed":
        raise RuntimeError(result2.get("error", "Log merge failed"))

    result3 = process_single_cpe_rg_drain3(
        job_id,
        user_id,
        project_id,
        serial,
        result2["cpe_dir"],
        fallback_date_from=fallback_date_from,
        fallback_date_to=fallback_date_to,
    )
    if result3["status"] == "skipped":
        return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
    if result3["status"] not in ["completed"]:
        raise RuntimeError(result3.get("error", "RG+Drain3 failed"))

    result4 = run_indexer_async_task(job_id, project_id, serial, result3["cpe_dir"])
    if result4["status"] == "skipped":
        return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
    if result4["status"] not in ["completed"]:
        raise RuntimeError(result4.get("error", "Indexing failed"))

    result5 = polars_etl_per_cpe_task(job_id, str(user_id), project_id, serial, result4["cpe_dir"])
    if result5["status"] == "skipped":
        return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
    if result5["status"] not in ["success"]:
        raise RuntimeError(result5.get("error", "Polars ETL failed"))

    result6 = mark_cpe_complete(
        job_id,
        user_id,
        project_id,
        serial,
        logs_extracted=result3.get("log_files", 0),
        patterns_indexed=result4.get("patterns_indexed", 0),
    )

    elapsed = time.time() - start_time
    logger.info(
        f"[CPE {serial}] Pipeline completed in {elapsed:.1f}s — "
        f"{result3.get('log_files', 0)} logs, {result4.get('patterns_indexed', 0)} patterns"
    )

    return {
        "status": "completed",
        "serial": serial,
        "logs_extracted": result3.get("log_files", 0),
        "patterns_indexed": result4.get("patterns_indexed", 0),
        "elapsed_sec": elapsed,
        "batch_complete": result6.get("batch_complete", False),
    }


# New orchestration task that chains the pipeline steps
@celery.task(base=CPEProcessTask, bind=True, name="process_single_cpe",
             rate_limit=f'{MAX_CONCURRENT_CPE_TASKS}/m')  
def process_single_cpe(self, job_id: str, user_id: int, project_id: str, 
                      serial: str, zip_path: str):
    """
    Orchestrate the new CPE processing pipeline.
    """
    logger.info(f"[CPE {serial}] Starting new pipeline orchestration for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    record_id = None

    try:
        from api.user_db_mngr import DBManager
        from flask import Flask

        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        dbm = DBManager()
        dbm.init_app(app)

        with app.app_context():
            records = dbm.get_job_cpe_records(job_id)
            record = next((r for r in records if r.serial == serial), None)
            if record:
                record_id = record.id

        try:
            out = run_batch_cpe_pipeline_sync(
                task_self_id=self.request.id if self.request else None,
                job_id=job_id,
                user_id=user_id,
                project_id=project_id,
                serial=serial,
                zip_path=zip_path,
            )
        except JobCancelled:
            raise
        if out.get("status") == "skipped":
            return out
        return out

    except JobCancelled:
        logger.info(f"[CPE {serial}] Pipeline cancelled for job {job_id}")
        try:
            app2 = Flask(__name__)
            app2.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.getenv('DB_PATH', '/app/data/logai_users.db')}"
            app2.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
            dbm2 = __import__("api.user_db_mngr", fromlist=["DBManager"]).DBManager()
            dbm2.init_app(app2)
            with app2.app_context():
                if record_id:
                    dbm2.update_cpe_record_status(
                        record_id, "skipped",
                        error_message="Job cancelled by user"
                    )
        except Exception:
            pass
        return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}

    except Exception as e:
        logger.error(f"[CPE {serial}] Pipeline error: {e}", exc_info=True)

        try:
            from api.user_db_mngr import DBManager
            from flask import Flask

            app = Flask(__name__)
            db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
            app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
            app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

            dbm = DBManager()
            dbm.init_app(app)

            with app.app_context():
                if not record_id:
                    records = dbm.get_job_cpe_records(job_id)
                    record = next((r for r in records if r.serial == serial), None)
                    if record:
                        record_id = record.id
                if record_id:
                    dbm.update_cpe_record_status(record_id, "failed", error_message=str(e))
                dbm.increment_batch_job_progress(job_id, success=False)

                job = dbm.get_batch_job(job_id)
                if job and (job.processed_cpes + job.failed_cpes) >= job.total_cpes:
                    if job.failed_cpes == job.total_cpes:
                        dbm.update_batch_job_status(job_id, "failed", "All CPEs failed")
                    else:
                        dbm.update_batch_job_status(job_id, "completed")
        except Exception:
            pass

        return {"status": "failed", "serial": serial, "error": str(e)}


@celery.task(bind=True, name="run_issue_analysis")
def run_issue_analysis(self, job_id: str, user_id: int, project_id: str,
                       graph_id: str, force: bool = False):
    """
    Run graph-driven issue analysis for a completed batch job.
    Uses the specified knowledge graph to detect patterns and causal chains.
    """
    logger.info(
        f"[IssueAnalysis] Task started for job={job_id}, graph={graph_id}, "
        f"force_reparse={force}"
    )
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    try:
        from logai.utils.constants import UPLOAD_DIRECTORY
        from logai.graph_analyzer import load_graph_definition, generate_batch_analysis
        from api.user_db_mngr import DBManager
        from flask import Flask

        project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
        if not project_dir.exists():
            logger.error(f"[IssueAnalysis] Project dir not found: {project_dir}")
            return {"status": "error", "message": "Project directory not found"}

        # Load graph definition inside Flask app context (Celery has no app context)
        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        dbm = DBManager()
        dbm.init_app(app)

        with app.app_context():
            graph_def = load_graph_definition(graph_id)

        result = generate_batch_analysis(
            project_dir=project_dir,
            project_id=project_id,
            job_id=job_id,
            graph_def=graph_def,
            force=force,
        )

        logger.info(
            f"[IssueAnalysis] Completed for job={job_id}: "
            f"{result['total_cpes']} CPEs in {result['elapsed_sec']}s"
        )
        return {"status": "completed", **result}

    except Exception as exc:
        logger.error(f"[IssueAnalysis] Error for job={job_id}: {exc}", exc_info=True)
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Remote CPE bundle fetch → ingest (serial per ordinal)
# ---------------------------------------------------------------------------

def _project_staging_abs(user_id: int, project_id: str, staging_relpath: str) -> Path:
    from logai.utils.constants import UPLOAD_DIRECTORY

    return Path(UPLOAD_DIRECTORY) / str(user_id) / str(project_id) / Path(staging_relpath)


def _parse_ranges_bounds(ranges: list[dict[str, str]]) -> tuple[str, str]:
    dates: list[str] = []
    for r in ranges:
        s = str(r.get("start") or "").strip()[:10]
        e = str(r.get("end") or "").strip()[:10]
        if len(s) == 10:
            dates.append(s)
        if len(e) == 10:
            dates.append(e)
    if not dates:
        return "", ""
    return min(dates), max(dates)


def _iso_yyyy_mm_dd_or_none(val: object) -> Optional[str]:
    if val is None:
        return None
    ds = str(val).strip()
    if len(ds) >= 10 and ds[4:5] == "-" and ds[7:8] == "-":
        return ds[:10]
    return ds if len(ds) == 10 else None


def _finalize_remote_fetch_job(dbm: Any, fj: Any, units: list[Any]) -> None:
    failed_ordinals: list[int] = []
    success_count = 0
    pending_like = []
    for u in units:
        dl_ok = u.download_status == "downloaded" and u.bundle_relpath
        if u.process_status == "completed":
            success_count += 1
            continue
        if u.download_status == "failed" or u.process_status == "failed":
            failed_ordinals.append(u.ordinal)
            continue
        pending_like.append(u.ordinal)
    if pending_like:
        return
    if failed_ordinals and success_count > 0:
        dbm.patch_remote_log_fetch_job(
            fj.id,
            status="completed",
            error_message=f"Completed with failures — ordinals {failed_ordinals}. Use retry failed.",
        )
        return
    if failed_ordinals:
        dbm.patch_remote_log_fetch_job(
            fj.id, status="failed", error_message="All remote-fetch units failed"
        )
        return
    dbm.patch_remote_log_fetch_job(fj.id, status="completed", error_message=None)


@celery.task(bind=True, name="advance_remote_log_fetch_job")
def advance_remote_log_fetch_job(self, fetch_job_id: str, credentials: Dict[str, str]):
    """Process the next actionable RemoteLogFetchUnit (download phase or ingest phase)."""
    _ensure_project_root_on_syspath()
    import json as _json

    from api.file_manager import FileManager
    from api.services.cpe_remote_log.errors import RemoteLogFetchError, remote_log_failure_to_stored_text
    from api.services.cpe_remote_log.pipeline import download_serial_bundle_to_zip

    keys = {"device_registry_bearer", "crash_portal_bearer", "tenant_id", "natco_code"}
    if not keys.issubset(set(credentials.keys())):
        logger.error("[RemoteFetch] Missing credential keys for fetch job %s", fetch_job_id)
        return {"status": "error", "reason": "invalid_credentials"}

    from flask import Flask
    from api.user_db_mngr import DBManager

    app = Flask(__name__)
    db_path_resolved = os.getenv("DB_PATH", "/app/data/logai_users.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    dbm = DBManager()
    dbm.init_app(app)

    with app.app_context():
        fj = dbm.get_remote_log_fetch_job(fetch_job_id)
        if not fj:
            return {"status": "missing"}
        proj = dbm.get_project_by_id(fj.project_id)
        if not proj:
            return {"status": "no_project"}

        if fj.batch_job_id:
            bk = dbm.get_batch_job(fj.batch_job_id)
            if bk and bk.status == "queued":
                dbm.update_batch_job_status(fj.batch_job_id, "processing")

        units = dbm.get_remote_log_fetch_units_ordered(fetch_job_id)

        next_unit = None
        phase = ""
        for u in units:
            if u.download_status == "failed" or u.process_status == "failed":
                continue
            dl_done = u.download_status == "downloaded" and u.bundle_relpath
            proc_done = u.process_status == "completed"
            if dl_done and proc_done:
                continue
            if not dl_done:
                next_unit = u
                phase = "download"
                break
            if dl_done and u.process_status != "completed":
                next_unit = u
                phase = "process"
                break

        if not next_unit:
            _finalize_remote_fetch_job(dbm, fj, units)
            return {"status": "idle_done"}

        staging_abs = _project_staging_abs(fj.user_id, fj.project_id, fj.staging_relpath)
        staging_abs.mkdir(parents=True, exist_ok=True)

        if phase == "download":
            dbm.patch_remote_log_fetch_unit(
                next_unit.id,
                download_status="downloading",
                last_error=None,
            )
            ranges: list[Any] = []
            try:
                raw_r = _json.loads(next_unit.ranges_json)
                if isinstance(raw_r, list):
                    ranges = [dict(x) for x in raw_r]
            except (_json.JSONDecodeError, TypeError, ValueError):
                ranges = []
            dbm.patch_remote_log_fetch_job(fj.id, status="processing")

            try:
                zp = download_serial_bundle_to_zip(
                    serial=next_unit.serial_number,
                    ranges=ranges,
                    tenant_id=credentials["tenant_id"].strip(),
                    natco_code=credentials["natco_code"].strip(),
                    device_registry_bearer=credentials["device_registry_bearer"],
                    crash_portal_bearer=credentials["crash_portal_bearer"],
                    staging_dir=staging_abs,
                    bundle_filename=f"{next_unit.serial_number}.zip",
                )
                dbm.patch_remote_log_fetch_unit(
                    next_unit.id,
                    download_status="downloaded",
                    bundle_relpath=zp.name,
                    last_error=None,
                )
            except RemoteLogFetchError as exc:
                msg = remote_log_failure_to_stored_text(exc)
                logger.warning("[RemoteFetch] Download failed ordinal %s: %s", next_unit.ordinal, msg)
                dbm.patch_remote_log_fetch_unit(
                    next_unit.id,
                    download_status="failed",
                    last_error=msg,
                )
                rec_id = next_unit.cpe_record_id
                if rec_id and fj.batch_job_id:
                    dbm.update_cpe_record_status(rec_id, "failed", error_message=msg)
                    dbm.increment_batch_job_progress(fj.batch_job_id, success=False)
                    job_inner = dbm.get_batch_job(fj.batch_job_id)
                    if job_inner and (job_inner.processed_cpes + job_inner.failed_cpes) >= job_inner.total_cpes:
                        dbm.update_batch_job_status(fj.batch_job_id, "completed")

            advance_remote_log_fetch_job.delay(fetch_job_id, credentials)
            return {"status": "advanced_after_download"}

        if not next_unit.bundle_relpath:
            dbm.patch_remote_log_fetch_unit(
                next_unit.id,
                download_status="failed",
                last_error="Missing bundle path after download",
            )
            advance_remote_log_fetch_job.delay(fetch_job_id, credentials)
            return {"status": "bundle_missing"}

        zip_path_str = str(staging_abs / next_unit.bundle_relpath)

        if proj.project_type == "batch" and fj.batch_job_id:
            dbm.patch_remote_log_fetch_unit(
                next_unit.id,
                process_status="processing",
                last_error=None,
            )
            batch_rng: list[Any] = []
            try:
                raw_br = _json.loads(next_unit.ranges_json)
                if isinstance(raw_br, list):
                    batch_rng = [dict(x) for x in raw_br]
            except (_json.JSONDecodeError, TypeError, ValueError):
                batch_rng = []
            bmn, bmx = _parse_ranges_bounds(batch_rng if isinstance(batch_rng, list) else [])
            fb_from = bmn if len(bmn) == 10 else None
            fb_to = bmx if len(bmx) == 10 else None
            try:
                out = run_batch_cpe_pipeline_sync(
                    task_self_id=getattr(self.request, "id", None),
                    job_id=fj.batch_job_id,
                    user_id=fj.user_id,
                    project_id=fj.project_id,
                    serial=next_unit.serial_number,
                    zip_path=zip_path_str,
                    fallback_date_from=fb_from,
                    fallback_date_to=fb_to,
                )
                if isinstance(out, dict) and out.get("status") == "skipped":
                    dbm.patch_remote_log_fetch_unit(
                        next_unit.id,
                        process_status="skipped",
                        last_error=out.get("reason"),
                    )
                else:
                    dbm.patch_remote_log_fetch_unit(
                        next_unit.id,
                        process_status="completed",
                        last_error=None,
                    )
            except JobCancelled:
                dbm.patch_remote_log_fetch_unit(
                    next_unit.id,
                    process_status="skipped",
                    last_error="cancelled",
                )
            except Exception as exc_proc:
                logger.error("[RemoteFetch] Process ordinal %s: %s", next_unit.ordinal, exc_proc)
                dbm.patch_remote_log_fetch_unit(
                    next_unit.id,
                    process_status="failed",
                    last_error=str(exc_proc),
                )
                if next_unit.cpe_record_id:
                    dbm.update_cpe_record_status(
                        next_unit.cpe_record_id,
                        "failed",
                        error_message=str(exc_proc),
                    )
                dbm.increment_batch_job_progress(fj.batch_job_id, success=False)
                job_inner = dbm.get_batch_job(fj.batch_job_id)
                if (
                    job_inner
                    and (job_inner.processed_cpes + job_inner.failed_cpes) >= job_inner.total_cpes
                ):
                    dbm.update_batch_job_status(fj.batch_job_id, "completed")
        else:
            from logai.utils.constants import UPLOAD_DIRECTORY as _ULD
            from api.file_manager import REMOTE_CPE_ARCHIVES_DIRNAME, register_cpe_files
            from api.routes.files import _launch_async_indexer_batch

            project_dir = Path(_ULD) / str(fj.user_id) / fj.project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            dbm.patch_remote_log_fetch_unit(
                next_unit.id,
                process_status="processing",
                last_error=None,
            )
            rng_local: list[Any] = []
            try:
                raw_r = _json.loads(next_unit.ranges_json)
                if isinstance(raw_r, list):
                    rng_local = [dict(x) for x in raw_r]
            except (_json.JSONDecodeError, TypeError, ValueError):
                rng_local = []
            mn, mx = _parse_ranges_bounds(rng_local if isinstance(rng_local, list) else [])
            if len(mn) != 10 or len(mx) != 10:
                mn, mx = "1970-01-01", "1970-01-01"

            branded = "".join(
                ch if ch.isalnum() or ch == "-" else "_" for ch in next_unit.serial_number
            )[:220]
            target_name = f"{branded}_{mn}_{mx}.zip"
            target_path = project_dir / target_name
            try:
                try:
                    shutil.move(zip_path_str, target_path)
                except OSError:
                    shutil.copy2(zip_path_str, target_path)

                fm = FileManager()
                cpe_results = fm.process_multi_cpe_upload(project_dir, proj.name)
                indexer_batch = []
                for cpe in cpe_results:
                    ser = cpe["serial"]
                    d_from = cpe.get("date_from")
                    d_to = cpe.get("date_to")
                    if (not d_from or not str(d_from).strip()) and len(mn) == 10:
                        d_from = mn
                    if (not d_to or not str(d_to).strip()) and len(mx) == 10:
                        d_to = mx
                    dbm.save_cpe(
                        project_id=fj.project_id,
                        serial=ser,
                        mac=cpe.get("mac"),
                        date_from=d_from,
                        date_to=d_to,
                    )
                    cpe_dir = project_dir / ser
                    if cpe_dir.exists():
                        register_cpe_files(cpe_dir, fj.project_id, ser, dbm)
                        indexer_batch.append((cpe_dir, fj.project_id, ser))
                try:
                    _launch_async_indexer_batch(indexer_batch)
                except Exception as idx_exc:
                    logger.warning("[RemoteFetch] Indexer kick failed: %s", idx_exc)

                dbm.patch_remote_log_fetch_unit(next_unit.id, process_status="completed")
                archive_dir = project_dir / REMOTE_CPE_ARCHIVES_DIRNAME
                archive_dir.mkdir(parents=True, exist_ok=True)
                archived = archive_dir / target_path.name
                if archived.exists():
                    archived.unlink()
                shutil.move(str(target_path), str(archived))
            except Exception as exc_n:
                logger.error("[RemoteFetch] Normal ingest failed: %s", exc_n)
                dbm.patch_remote_log_fetch_unit(
                    next_unit.id,
                    process_status="failed",
                    last_error=str(exc_n),
                )
                target_path.unlink(missing_ok=True)

        advance_remote_log_fetch_job.delay(fetch_job_id, credentials)
        return {"status": "advanced_after_process"}


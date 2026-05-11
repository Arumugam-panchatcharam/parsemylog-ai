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
from sqlalchemy.exc import IntegrityError
import shutil
from pathlib import Path
from typing import Dict, Any

# Ensure project root is on sys.path (needed for prefork/spawn workers on macOS)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from celery import Task
from logai.utils.constants import SKIP_WALK_DIRECTORY_NAMES, is_os_junk_filename
from .celery_app import celery

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
def process_single_cpe_rg_drain3(self, job_id: str, user_id: int, project_id: str, 
                                 serial: str, cpe_dir: str):
    """
    Process CPE for RG patterns and Drain3 templates.
    Includes info extraction, telemetry parsing, and file registration.
    
    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID
        serial: CPE serial number
        cpe_dir: Path to CPE directory
    """
    logger.info(f"[CPE {serial}] Starting RG+Drain3 processing for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from api.user_db_mngr import DBManager
        from api.file_manager import register_cpe_files
        from logai.info_extractor import find_and_parse_version_txt, find_and_build_fallback_device_info
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
            
            # Info extraction (cached to disk)
            mac = None
            date_from = None
            date_to = None

            try:
                find_and_parse_version_txt(cpe_path)
            except Exception:
                pass

            try:
                fallback_info = find_and_build_fallback_device_info(cpe_path)
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
                    date_from = tel_summary.get("date_range", {}).get("from")
                    date_to = tel_summary.get("date_range", {}).get("to")
                if not mac and tel_reports:
                    for r in tel_reports:
                        m = r.get("mac", "")
                        if m:
                            mac = m.replace(":", "").lower()
                            break
            except Exception:
                pass

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


# New orchestration task that chains the pipeline steps
@celery.task(base=CPEProcessTask, bind=True, name="process_single_cpe",
             rate_limit=f'{MAX_CONCURRENT_CPE_TASKS}/m')  
def process_single_cpe(self, job_id: str, user_id: int, project_id: str, 
                      serial: str, zip_path: str):
    """
    Orchestrate the new CPE processing pipeline.
    
    Pipeline:
    1. extract_upload
    2. merge_cpe_logs_task
    3. process_single_cpe_rg_drain3
    4. run_indexer_async_task
    5. polars_etl_per_cpe_task
    6. mark_cpe_complete
    
    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID  
        serial: CPE serial number
        zip_path: Path to CPE zip file
    """
    logger.info(f"[CPE {serial}] Starting new pipeline orchestration for job {job_id}")
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    
    try:
        from api.user_db_mngr import DBManager
        from flask import Flask
        
        # Create Flask app context for DB operations
        app = Flask(__name__)
        db_path_resolved = os.getenv('DB_PATH', '/app/data/logai_users.db')
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path_resolved}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        
        dbm = DBManager()
        dbm.init_app(app)
        
        with app.app_context():
            # Check cancellation
            _check_job_cancelled(dbm, job_id)
            
            # Get or create CPE record
            records = dbm.get_job_cpe_records(job_id)
            record = next((r for r in records if r.serial == serial), None)
            
            if record:
                record_id = record.id
                dbm.update_cpe_record_status(record_id, "processing")
            else:
                record_id = dbm.create_cpe_record(job_id, serial, self.request.id)
                dbm.update_cpe_record_status(record_id, "processing")
        
        # Pipeline execution
        start_time = time.time()
        
        # Step 1: Extract upload
        result1 = extract_upload(job_id, user_id, project_id, serial, zip_path)
        if result1["status"] != "completed":
            raise Exception(f"Extract upload failed: {result1.get('error', 'Unknown error')}")
        
        # Step 2: Merge logs
        result2 = merge_cpe_logs_task(job_id, user_id, project_id, serial, result1["staging_dir"])
        if result2["status"] != "completed":
            raise Exception(f"Log merge failed: {result2.get('error', 'Unknown error')}")
        
        # Step 3: RG + Drain3
        result3 = process_single_cpe_rg_drain3(job_id, user_id, project_id, serial, result2["cpe_dir"])
        if result3["status"] not in ["completed", "skipped"]:
            raise Exception(f"RG+Drain3 failed: {result3.get('error', 'Unknown error')}")
        
        if result3["status"] == "skipped":
            return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
        
        # Step 4: Indexing
        result4 = run_indexer_async_task(job_id, project_id, serial, result3["cpe_dir"])
        if result4["status"] not in ["completed", "skipped"]:
            raise Exception(f"Indexing failed: {result4.get('error', 'Unknown error')}")
        
        if result4["status"] == "skipped":
            return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
        
        # Step 5: Polars ETL
        result5 = polars_etl_per_cpe_task(job_id, str(user_id), project_id, serial, result4["cpe_dir"])
        if result5["status"] not in ["success", "skipped"]:
            raise Exception(f"Polars ETL failed: {result5.get('error', 'Unknown error')}")
        
        if result5["status"] == "skipped":
            return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
        
        # Step 6: Mark complete
        result6 = mark_cpe_complete(
            job_id, user_id, project_id, serial,
            logs_extracted=result3.get("log_files", 0),
            patterns_indexed=result4.get("patterns_indexed", 0)
        )
        
        elapsed = time.time() - start_time
        logger.info(f"[CPE {serial}] Pipeline completed in {elapsed:.1f}s - " + 
                   f"{result3.get('log_files', 0)} logs, {result4.get('patterns_indexed', 0)} patterns")
        
        return {
            "status": "completed",
            "serial": serial,
            "logs_extracted": result3.get("log_files", 0),
            "patterns_indexed": result4.get("patterns_indexed", 0),
            "elapsed_sec": elapsed,
            "batch_complete": result6.get("batch_complete", False)
        }
        
    except JobCancelled:
        logger.info(f"[CPE {serial}] Pipeline cancelled for job {job_id}")
        try:
            with app.app_context():
                dbm.update_cpe_record_status(
                    record_id, "skipped", 
                    error_message="Job cancelled by user"
                )
        except:
            pass
        return {"status": "skipped", "serial": serial, "reason": "job_cancelled"}
    
    except Exception as e:
        logger.error(f"[CPE {serial}] Pipeline error: {e}", exc_info=True)
        
        try:
            with app.app_context():
                dbm.update_cpe_record_status(record_id, "failed", error_message=str(e))
                dbm.increment_batch_job_progress(job_id, success=False)
                
                # Check if batch should be marked as failed
                job = dbm.get_batch_job(job_id)
                if job and (job.processed_cpes + job.failed_cpes) >= job.total_cpes:
                    if job.failed_cpes == job.total_cpes:
                        dbm.update_batch_job_status(job_id, "failed", "All CPEs failed")
                    else:
                        dbm.update_batch_job_status(job_id, "completed")
        except:
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



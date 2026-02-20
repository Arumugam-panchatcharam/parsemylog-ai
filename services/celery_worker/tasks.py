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
import time
import logging
import zipfile
import tarfile
import shutil
from pathlib import Path
from typing import Dict, Any

from celery import Task
from .celery_app import celery

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Maximum concurrent CPE processing tasks (to avoid overwhelming Qdrant)
MAX_CONCURRENT_CPE_TASKS = 4


class CPEProcessTask(Task):
    """Base task class with retry logic and error handling."""
    autoretry_for = (Exception,)
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
    
    try:
        # Import here to avoid circular dependencies
        from api.user_db_mngr import DBManager
        from flask import Flask
        
        # Create minimal Flask app for DB context
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.getenv('DB_PATH', '/app/data/logai_users.db')}"
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


@celery.task(base=CPEProcessTask, bind=True, name="process_single_cpe",
             rate_limit=f'{MAX_CONCURRENT_CPE_TASKS}/m')
def process_single_cpe(self, job_id: str, user_id: int, project_id: str, 
                      serial: str, zip_path: str):
    """
    Process a single CPE zip file.
    
    Pipeline:
    1. Extract zip file to project_dir/<serial>/raw
    2. Flatten to project_dir/<serial>/staging
    3. Merge logs to project_dir/<serial>/merged_logs using LogMerger
    4. Index patterns from merged_logs with Drain3
    5. Save files and metrics to DB
    
    Args:
        job_id: Batch job ID
        user_id: User ID
        project_id: Project ID
        serial: CPE serial number
        zip_path: Path to CPE zip file
    """
    logger.info(f"[CPE {serial}] Starting processing for job {job_id}")
    start_time = time.time()
    
    try:
        # Import dependencies
        from api.user_db_mngr import DBManager
        from api.file_manager import FileManager
        from api.log_merger import LogMerger
        from logai.info_extractor import find_and_parse_version_txt, find_and_build_fallback_device_info
        from logai.utils.constants import UPLOAD_DIRECTORY
        from flask import Flask
        
        # Create Flask app context
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.getenv('DB_PATH', '/app/data/logai_users.db')}"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        
        dbm = DBManager()
        dbm.init_app(app)
        
        with app.app_context():
            # Get or create CPE record
            records = dbm.get_job_cpe_records(job_id)
            record = next((r for r in records if r.serial == serial), None)
            
            if record:
                record_id = record.id
                dbm.update_cpe_record_status(record_id, "processing")
            else:
                record_id = dbm.create_cpe_record(job_id, serial, self.request.id)
                dbm.update_cpe_record_status(record_id, "processing")
            
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
            
            # Step 2: Flatten raw_dir to staging_dir
            # (Move all files recursively to staging, ignoring dirs)
            for root, dirs, files in os.walk(raw_dir):
                for file in files:
                    src = Path(root) / file
                    dst = staging_dir / file
                    
                    # Handle filename collisions by appending timestamp
                    if dst.exists():
                        base, ext = os.path.splitext(file)
                        dst = staging_dir / f"{base}_{int(time.time()*1000)}{ext}"
                    
                    shutil.move(str(src), str(dst))
            
            # Step 3: Merge logs directly into cpe_dir (not a subdirectory)
            logger.info(f"[CPE {serial}] Merging logs...")
            # LogMerger expects directory with archives/logs and output directory
            merger = LogMerger(str(staging_dir), str(cpe_dir))
            merger.merge_logs()
            
            # Count merged files in cpe_dir
            log_files = [f for f in cpe_dir.rglob('*') if f.is_file() and f.suffix in ('.log', '.txt') and not f.name.startswith('.')]
            logger.info(f"[CPE {serial}] Merged into {len(log_files)} files")
            
            # Step 4: Quick metadata scan
            mac = None
            date_from = None
            date_to = None
            
            try:
                version_info = find_and_parse_version_txt(cpe_dir)
                if version_info:
                    # Extract dates if available
                    pass
            except:
                pass
            
            try:
                fallback_info = find_and_build_fallback_device_info(cpe_dir)
                if fallback_info:
                    mac = fallback_info.get("mac")
            except:
                pass
            
            # Step 5: Save CPE record in DB
            dbm.save_cpe(project_id, serial, mac, date_from, date_to)
            
            # Register merged files in DB
            for log_file in log_files:
                dbm.save_cpe_file(project_id, serial, log_file, log_file.name)
            
            # Step 6: Index patterns (uses shared Qdrant collection with CPE metadata)
            patterns_indexed = 0
            try:
                from api.indexer import run_indexer_async
                import pandas as pd
                
                # Run indexing synchronously
                logger.info(f"[CPE {serial}] Starting pattern indexing on {cpe_dir}")
                run_indexer_async(cpe_dir, project_id, cpe_id=serial)
                
                # Count actual patterns from all parquet files
                patterns_indexed = 0
                for parquet_file in cpe_dir.glob("*_rg.parquet"):
                    try:
                        df = pd.read_parquet(parquet_file)
                        patterns_indexed += len(df)
                    except Exception as e:
                        logger.warning(f"[CPE {serial}] Could not read {parquet_file.name}: {e}")
                
            except Exception as e:
                logger.warning(f"[CPE {serial}] Indexing error: {e}")
                patterns_indexed = 0
            
            # Cleanup temp dirs
            try:
                if raw_dir.exists(): shutil.rmtree(raw_dir)
                if staging_dir.exists(): shutil.rmtree(staging_dir)
            except Exception as e:
                logger.warning(f"[CPE {serial}] Cleanup error: {e}")
            
            # Step 7: Mark as completed
            elapsed = time.time() - start_time
            dbm.update_cpe_record_status(
                record_id, 
                "completed",
                logs_extracted=len(log_files),
                patterns_indexed=patterns_indexed
            )
            
            # Update batch job progress
            dbm.increment_batch_job_progress(job_id, success=True)
            
            # Check if batch is complete
            job = dbm.get_batch_job(job_id)
            if job and (job.processed_cpes + job.failed_cpes) >= job.total_cpes:
                dbm.update_batch_job_status(job_id, "completed")
                logger.info(f"[BatchJob {job_id}] All CPEs processed!")
            
            logger.info(f"[CPE {serial}] Completed in {elapsed:.1f}s - {len(log_files)} logs, {patterns_indexed} patterns")
            
            return {
                "status": "completed",
                "serial": serial,
                "logs_extracted": len(log_files),
                "patterns_indexed": patterns_indexed,
                "elapsed_sec": elapsed,
            }
            
    except Exception as e:
        logger.error(f"[CPE {serial}] Error: {e}", exc_info=True)
        
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
        
        raise


# Legacy task (keep for backward compatibility)
import requests

LLAMA_API_URL = os.environ.get("LLAMA_API_URL", "http://localhost:41030/generate")

@celery.task
def process_llama_query(self, embed_templates, max_tokens=256):
    prompt_parts = []
    prompt_parts = [
            {
                "LOG_FILENAME": r.get("filename", "-"),
                "LOG_TEMPLATE": r.get("template", ""),
                "LOG_FREQUENCY": r.get("frequency", "-"),
            }
            for r in embed_templates
        ]
    prompt = (
        "You are an assistant that summarizes RDK log groups.\n"
        "For each LOG_TEMPLATES and LOG_FREQUENCY block below, provide a short summary of what these logs indicate, probable causes, and suggested next steps.\n\n"
        + "\n\n".join(prompt_parts)
        + "\n\nRespond clearly and label each summary with the LOG_FILENAME it corresponds to."
    )
    try:
        print("Promt is ", prompt)
        resp = requests.post(LLAMA_API_URL, json={"prompt": prompt, "max_tokens": max_tokens})
        resp.raise_for_status()
        return {"state": "done", "result": resp.json().get("response")}
    except Exception as e:
        return {"state": "error", "message": str(e)}
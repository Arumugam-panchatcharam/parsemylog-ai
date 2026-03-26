"""
Files API Routes
=================

Endpoints for file upload, listing, content viewing, search, download, and notes.
"""

import io
import json
import os
import re
import glob
import shutil
import logging
import subprocess
import threading
import zipfile
from collections import defaultdict
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from api.file_manager import FileManager, register_cpe_files
from api.log_viewer_dedup import (
    dedup_patterns_path,
    user_dedup_patterns_path,
    ensure_dedup_materialized,
    enabled_invert_patterns,
    line_to_content_pages,
    load_dedup_config,
    materialized_paths,
    read_alias_view,
    validate_patterns_json,
)
from api.log_pattern_extractor import (
    generate_dedup_pattern,
    validate_pattern,
)
from logai.utils.constants import (
    UPLOAD_DIRECTORY,
    MERGED_LOGS_DIR_NAME,
    LINES_PER_PAGE,
    NON_TEXT_EXTENSIONS,
    QDRANT_URL,
)

logger = logging.getLogger(__name__)

files_bp = Blueprint("files", __name__)


def _verify_project_access(project_id, user_id):
    """Verify the user owns the project. Returns (project, error_response)."""
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _get_project_dir(user_id, project_id, cpe_id=None):
    """Get the project directory path, optionally scoped to a CPE."""
    base = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    if cpe_id:
        return base / cpe_id
    return base


def _get_user_dir(user_id):
    """Get the user directory path (for storing user-level settings like dedup patterns)."""
    return Path(f"{UPLOAD_DIRECTORY}/{user_id}")


# ---------- In-memory processing status tracker ----------

_processing_status: dict = {}  # project_id -> status dict
_status_lock = threading.Lock()


def _set_status(project_id: str, **kwargs):
    """Update the processing status for a project (thread-safe)."""
    with _status_lock:
        if project_id not in _processing_status:
            _processing_status[project_id] = {
                "status": "pending",
                "message": "",
                "progress": 0,
                "total": 0,
                "cpes": [],
                "error": None,
            }
        _processing_status[project_id].update(kwargs)


def _get_status(project_id: str) -> dict:
    """Get the processing status for a project (thread-safe)."""
    with _status_lock:
        return dict(_processing_status.get(project_id, {
            "status": "idle",
            "message": "Processing logs in the background...",
            "progress": 0,
            "total": 0,
            "cpes": [],
            "error": None,
        }))


def _clear_status(project_id: str):
    """Remove completed status after a delay."""
    with _status_lock:
        _processing_status.pop(project_id, None)


# ---------- Upload ----------

@files_bp.route("/<project_id>/files/upload", methods=["POST"])
@jwt_required()
def upload_files(project_id):
    """
    Upload files to a project (multipart/form-data).

    Saves files to disk immediately and returns 202. Heavy processing
    (CPE extraction, log merging, indexing) runs in a background thread.
    Poll ``GET /<project_id>/files/processing-status`` for progress.

    Returns: { "message": str, "files": [str], "processing": bool }
    """
    user_id = get_user_id()
    project, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    uploaded_files = request.files.getlist("files")
    if not uploaded_files:
        return jsonify({"error": "No files provided"}), 400

    project_dir = _get_project_dir(user_id, project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    # ---- Phase 1: Save files to disk (synchronous, fast) ----
    saved_filenames = []
    total_bytes = 0
    for f in uploaded_files:
        if f.filename:
            filepath = project_dir / f.filename
            f.save(str(filepath))
            fsize = filepath.stat().st_size
            total_bytes += fsize
            saved_filenames.append(f.filename)
            logger.info(f"[Upload] Saved {f.filename} ({fsize} bytes)")

    logger.info(f"[Upload] {len(saved_filenames)} file(s) saved ({total_bytes / (1024*1024):.1f} MB)")

    # ---- Phase 2: Detect CPE zips (fast) ----
    cpe_zips = FileManager.detect_cpe_zips(project_dir)

    # ---- Phase 2.5: Detect regular zip files that might contain logs ----
    # If no CPE zips detected, check for any regular zip files
    regular_zips = []
    if not cpe_zips:
        for f in project_dir.iterdir():
            if f.is_file() and f.name.endswith('.zip'):
                regular_zips.append(f)
        if regular_zips:
            logger.info(f"[Upload] Detected {len(regular_zips)} regular zip file(s) to extract")

    if cpe_zips:
        # ---- Multi-CPE: launch background processing ----
        cpe_count = len(set(z["serial"] for z in cpe_zips))
        logger.info(f"[Upload] Detected {len(cpe_zips)} CPE zip(s) for {cpe_count} CPE(s) — processing in background")
        _set_status(project_id,
                    status="processing",
                    message=f"Starting extraction of {cpe_count} CPE(s)...",
                    progress=0,
                    total=cpe_count,
                    cpes=[],
                    error=None)

        # Capture values for the background thread
        from flask import current_app
        flask_app = current_app._get_current_object()
        project_name = project.name
        t = threading.Thread(
            target=_process_multi_cpe_background,
            args=(flask_app, project_id, user_id, project_dir, project_name, cpe_zips),
            daemon=True,
        )
        t.start()

        return jsonify({
            "message": f"Uploaded {len(saved_filenames)} file(s) — processing {cpe_count} CPE(s) in background",
            "files": saved_filenames,
            "processing": True,
        }), 202

    elif regular_zips:
        # ---- Extract regular zip files in background ----
        logger.info(f"[Upload] Processing {len(regular_zips)} regular zip file(s) in background")
        _set_status(project_id,
                    status="processing",
                    message=f"Extracting {len(regular_zips)} archive(s)...",
                    progress=0,
                    total=len(regular_zips),
                    cpes=[],
                    error=None)

        # Capture values for the background thread
        from flask import current_app
        flask_app = current_app._get_current_object()
        project_name = project.name
        t = threading.Thread(
            target=_process_regular_archives_background,
            args=(flask_app, project_id, user_id, project_dir, project_name, regular_zips),
            daemon=True,
        )
        t.start()

        return jsonify({
            "message": f"Uploaded {len(saved_filenames)} file(s) — extracting archives in background",
            "files": saved_filenames,
            "processing": True,
        }), 202

    else:
        # ---- Legacy single-upload path (usually small, keep synchronous) ----
        logger.info(f"[Upload] Processing uploaded files in {project_dir}")
        file_manager = FileManager()
        file_manager.process_uploaded_files(project_dir, project.name)

        # Save merged log files to DB
        merged_dir = project_dir / MERGED_LOGS_DIR_NAME
        merged_count = 0
        if merged_dir.exists():
            for fname in os.listdir(merged_dir):
                dbm.save_local_file(Path(merged_dir / fname), project_id)
                merged_count += 1
            logger.info(f"[Upload] Saved {merged_count} merged log files to DB")

        # Save archive files to DB
        for archive_path in glob.glob(str(project_dir / "*.zip")):
            if os.path.exists(archive_path):
                dbm.save_local_file(Path(archive_path), project_id)

        # Clean up merged_logs directory
        if merged_dir.exists():
            shutil.rmtree(merged_dir)

        # Launch async rg+Drain3 indexing
        _launch_async_indexer(project_dir, project_id)

        return jsonify({
            "message": f"Uploaded {len(saved_filenames)} file(s)",
            "files": saved_filenames,
            "processing": False,
        }), 201


# ---------- Background CPE Processing ----------

def _process_regular_archives_background(flask_app, project_id, user_id, project_dir, project_name, archive_files):
    """
    Background thread: extract regular zip/tar files, merge logs, save to DB, launch indexing.

    This handles generic archive uploads that don't match CPE naming conventions.
    """
    try:
        with flask_app.app_context():
            total = len(archive_files)
            _set_status(project_id,
                        message=f"Extracting {total} archive(s)...",
                        total=total)

            # Extract archives
            for idx, archive_path in enumerate(archive_files, 1):
                _set_status(project_id,
                            message=f"Extracting archive {idx}/{total}: {archive_path.name}",
                            progress=idx)
                
                try:
                    # Create temporary extraction directory
                    extract_dir = project_dir / f"_extract_{archive_path.stem}"
                    extract_dir.mkdir(exist_ok=True)
                    
                    # Extract the archive
                    if archive_path.name.endswith('.zip'):
                        import zipfile
                        with zipfile.ZipFile(archive_path, 'r') as zf:
                            zf.extractall(extract_dir)
                    elif archive_path.name.endswith(('.tar', '.tgz', '.tar.gz', '.tar.bz2')):
                        import tarfile
                        with tarfile.open(archive_path, 'r:*') as tf:
                            tf.extractall(extract_dir)
                    
                    # Move extracted files to project root
                    for item in extract_dir.rglob('*'):
                        if item.is_file():
                            # Try to preserve directory structure, but flatten if there are conflicts
                            rel_path = item.relative_to(extract_dir)
                            dest = project_dir / rel_path
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            if not dest.exists():
                                shutil.move(str(item), str(dest))
                            else:
                                # File exists, use unique name
                                counter = 1
                                while dest.exists():
                                    dest = project_dir / f"{rel_path.stem}_{counter}{rel_path.suffix}"
                                    counter += 1
                                shutil.move(str(item), str(dest))
                    
                    # Clean up extraction directory
                    shutil.rmtree(extract_dir, ignore_errors=True)
                    
                    # Remove the archive file
                    archive_path.unlink()
                    
                except Exception as e:
                    logger.error(f"[Upload] Failed to extract {archive_path.name}: {e}")

            _set_status(project_id,
                        message="Processing extracted files...")

            # Process the extracted files using legacy path
            file_manager = FileManager()
            file_manager.process_uploaded_files(project_dir, project_name)

            # Save merged log files to DB
            merged_dir = project_dir / MERGED_LOGS_DIR_NAME
            merged_count = 0
            if merged_dir.exists():
                for fname in os.listdir(merged_dir):
                    dbm.save_local_file(Path(merged_dir / fname), project_id)
                    merged_count += 1
                logger.info(f"[Upload] Saved {merged_count} merged log files to DB")

            # Clean up merged_logs directory
            if merged_dir.exists():
                shutil.rmtree(merged_dir)

            # Launch async indexing
            _launch_async_indexer(project_dir, project_id)

            _set_status(project_id,
                        status="completed",
                        message=f"Done! Archives extracted and processed, indexing in background",
                        progress=total)

            logger.info(f"[Upload] Background archive processing complete: {total} archive(s)")

    except Exception as e:
        logger.exception(f"[Upload] Background archive processing failed: {e}")
        _set_status(project_id,
                    status="error",
                    message=f"Processing failed: {str(e)}",
                    error=str(e))


def _process_multi_cpe_background(flask_app, project_id, user_id, project_dir, project_name, cpe_zips):
    """
    Background thread: extract zips, merge logs, save to DB, launch indexing.

    Updates ``_processing_status[project_id]`` so the frontend can poll for progress.
    """
    try:
        with flask_app.app_context():
            file_manager = FileManager()

            # Group by serial to count unique CPEs
            serial_set = set(z["serial"] for z in cpe_zips)
            total = len(serial_set)

            _set_status(project_id,
                        message=f"Extracting and merging {total} CPE(s)...",
                        total=total)

            cpe_results = file_manager.process_multi_cpe_upload(
                project_dir, project_name,
                progress_callback=lambda done, serial: _set_status(
                    project_id,
                    message=f"Processing CPE {done}/{total}: {serial}",
                    progress=done,
                ),
            )

            _set_status(project_id,
                        message=f"Saving metadata for {len(cpe_results)} CPE(s)...")

            # Save CPE metadata + files to DB
            indexer_batch = []
            processed_cpes = []
            for cpe in cpe_results:
                serial = cpe["serial"]
                dbm.save_cpe(
                    project_id=project_id,
                    serial=serial,
                    mac=cpe.get("mac"),
                    date_from=cpe.get("date_from"),
                    date_to=cpe.get("date_to"),
                )
                cpe_dir = project_dir / serial
                if cpe_dir.exists():
                    register_cpe_files(cpe_dir, project_id, serial, dbm)
                    indexer_batch.append((cpe_dir, project_id, serial))
                processed_cpes.append(serial)

            # Launch indexing (already runs in its own background thread)
            _launch_async_indexer_batch(indexer_batch)

            # Clean up source archives
            for cpe_info in cpe_zips:
                try:
                    cpe_info["path"].unlink()
                except Exception:
                    pass

            _set_status(project_id,
                        status="completed",
                        message=f"Done! {len(cpe_results)} CPE(s) processed, indexing in background",
                        progress=total,
                        cpes=processed_cpes)

            logger.info(f"[Upload] Background processing complete: {len(cpe_results)} CPE(s)")

    except Exception as e:
        logger.exception(f"[Upload] Background processing failed: {e}")
        _set_status(project_id,
                    status="error",
                    message=f"Processing failed: {str(e)}",
                    error=str(e))


# ---------- Processing Status ----------

@files_bp.route("/<project_id>/files/processing-status", methods=["GET"])
@jwt_required()
def get_processing_status(project_id):
    """
    Poll for background processing progress.

    Returns: { "status": "idle|processing|completed|error",
               "message": str, "progress": int, "total": int,
               "cpes": [str], "error": str|null }
    """
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    status = _get_status(project_id)

    # Auto-clear completed/error status after it's been read
    if status["status"] in ("completed", "error"):
        # Schedule cleanup after a short delay so multiple polls can read it
        threading.Timer(10.0, _clear_status, args=[project_id]).start()

    return jsonify(status), 200


# ---------- Helpers ----------

def _launch_async_indexer(project_dir, project_id, cpe_id=None):
    """Launch background rg+Drain3 indexer thread (single CPE or legacy)."""
    try:
        from api.indexer import launch_async_indexer
        launch_async_indexer(project_dir, project_id, cpe_id=cpe_id)
    except Exception as e:
        logger.warning(f"[Upload] Could not launch async indexer: {e}")


def _launch_async_indexer_batch(batch):
    """Launch a single background thread that indexes multiple CPEs sequentially."""
    try:
        from api.indexer import launch_async_indexer_batch
        launch_async_indexer_batch(batch)
    except Exception as e:
        logger.warning(f"[Upload] Could not launch batch indexer: {e}")


# ---------- List Files ----------

@files_bp.route("/<project_id>/files", methods=["GET"])
@jwt_required()
def list_files(project_id):
    """
    List all files in a project.

    Query params: cpe_id (optional)
    Returns: [ { "filename", "original_name", "file_size", "uploaded_at" } ]
    """
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")
    files = dbm.get_project_files(project_id, cpe_id=cpe_id)
    result = []
    for f in files:
        filename, file_path, original_name, file_size, uploaded_at = f
        if file_size == 0:
            continue
        is_viewable = not any(filename.lower().endswith(ext) for ext in NON_TEXT_EXTENSIONS)
        result.append({
            "filename": filename,
            "file_path": file_path,  # Add unique path for React keys
            "original_name": original_name,
            "file_size": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size else 0,
            "uploaded_at": str(uploaded_at) if uploaded_at else None,
            "is_viewable": is_viewable,
        })

    return jsonify(result), 200


# ---------- File Content (Paginated) ----------

@files_bp.route("/<project_id>/files/<filename>/content", methods=["GET"])
@jwt_required()
def get_file_content(project_id, filename):
    """
    Get paginated file content.

    Query params: page (default 1), lines_per_page (default 1000)
    Returns: { "lines": [...], "page", "total_pages", "total_lines", "start_line", "end_line" }
    """
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    page = request.args.get("page", 1, type=int)
    lpp = request.args.get("lines_per_page", LINES_PER_PAGE, type=int)
    cpe_id = request.args.get("cpe_id")

    file_info = dbm.get_project_file_info(project_id, filename, cpe_id=cpe_id)
    if not file_info:
        return jsonify({"error": "File not found"}), 404

    _, filepath, _, _, _ = file_info
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found on disk"}), 404

    _dedup_raw = request.args.get("dedup")
    apply_dedup = (
        str(_dedup_raw).strip().lower() in ("true", "1", "yes", "on")
        if _dedup_raw is not None
        else False
    )
    dedup_cfg = load_dedup_config(user_dedup_patterns_path(_get_user_dir(user_id)))
    inv_pats = enabled_invert_patterns(dedup_cfg, filename) if dedup_cfg.get("dedup_active") else []
    use_dedup = apply_dedup and bool(inv_pats)

    if use_dedup:
        orig_path = Path(filepath).resolve()
        ensure_dedup_materialized(orig_path, dedup_cfg)
        lines, total_lines_raw = read_alias_view(orig_path)
        n = len(lines)
        total_pages = max(1, (n + lpp - 1) // lpp)
        page = max(1, min(page, total_pages))
        start_idx = (page - 1) * lpp
        end_idx = min(start_idx + lpp, n)
        page_lines = lines[start_idx:end_idx]
        line_numbers = list(range(start_idx + 1, start_idx + 1 + len(page_lines)))
        start_line = line_numbers[0] if line_numbers else 1
        end_line = line_numbers[-1] if line_numbers else 0
        return jsonify({
            "lines": page_lines,
            "line_numbers": line_numbers,
            "page": page,
            "total_pages": total_pages,
            "total_lines": n,
            "total_lines_raw": total_lines_raw,
            "start_line": start_line,
            "end_line": end_line,
            "filename": filename,
            "dedup_applied": True,
        }), 200

    # Read in binary mode and split on \n only to match ripgrep/wc -l behavior
    with open(filepath, "rb") as f:
        content = f.read()
    lines = [line.decode('utf-8', errors='ignore').rstrip("\r\n") for line in content.split(b'\n')]
    if lines and lines[-1] == '':
        lines = lines[:-1]

    total_lines_raw = len(lines)
    total_lines = total_lines_raw
    total_pages = max(1, (total_lines + lpp - 1) // lpp)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * lpp
    end_idx = min(start_idx + lpp, total_lines)
    page_lines = lines[start_idx:end_idx]
    line_numbers = list(range(start_idx + 1, start_idx + 1 + len(page_lines)))

    return jsonify({
        "lines": page_lines,
        "line_numbers": line_numbers,
        "page": page,
        "total_pages": total_pages,
        "total_lines": total_lines,
        "start_line": start_idx + 1,
        "end_line": end_idx,
        "filename": filename,
    }), 200


# ---------- File Download ----------

@files_bp.route("/<project_id>/files/<filename>/download", methods=["GET"])
@jwt_required()
def download_file(project_id, filename):
    """Download a file from the project."""
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")
    file_info = dbm.get_project_file_info(project_id, filename, cpe_id=cpe_id)
    if not file_info:
        return jsonify({"error": "File not found"}), 404

    _, filepath, original_name, _, _ = file_info
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found on disk"}), 404

    import mimetypes
    mime_type, _ = mimetypes.guess_type(original_name)
    if not mime_type:
        mime_type = "application/octet-stream"

    return send_file(
        filepath,
        as_attachment=True,
        download_name=original_name,
        mimetype=mime_type,
    )


# ---------- Merged logs archive download ----------

def _safe_zip_name(s: str) -> str:
    """Replace characters that are unsafe in ZIP filenames."""
    if not s:
        return ""
    return re.sub(r'[^\w\-.]', "_", s).strip("_") or "unknown"


@files_bp.route("/<project_id>/files/merged-logs/download", methods=["GET"])
@jwt_required()
def download_merged_logs_archive(project_id):
    """
    Download a ZIP of all log files shown in the log viewer for this project (and optional CPE).

    Query params: cpe_id (optional)
    Returns: ZIP attachment with filename merged_logs-<cpe>-<mac>.zip or merged_logs-<mac>.zip
    """
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")
    files = dbm.get_project_files(project_id, cpe_id=cpe_id)
    file_records = [f for f in files if getattr(f, "file_size", 0) and getattr(f, "file_path", None)]
    if not file_records:
        return jsonify({"error": "No files to include in archive"}), 404

    # Resolve CPE label and MAC for download filename
    cpe_label = _safe_zip_name(cpe_id) if cpe_id else ""
    mac_label = ""
    if cpe_id:
        cpes = dbm.list_project_cpes(project_id)
        cpe = next((c for c in cpes if getattr(c, "serial", None) == cpe_id), None)
        if cpe and getattr(cpe, "mac", None):
            mac_label = _safe_zip_name(cpe.mac.replace(":", ""))
    if not mac_label and cpe_id:
        mac_label = _safe_zip_name(cpe_id)

    if cpe_label and mac_label:
        zip_name = f"merged_logs-{cpe_label}-{mac_label}.zip"
    elif mac_label:
        zip_name = f"merged_logs-{mac_label}.zip"
    elif cpe_label:
        zip_name = f"merged_logs-{cpe_label}.zip"
    else:
        zip_name = "merged_logs.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in file_records:
            path = getattr(f, "file_path", None)
            name = getattr(f, "original_name", None) or getattr(f, "filename", "file")
            if not path or not os.path.isfile(path):
                continue
            try:
                zf.write(path, arcname=name)
            except Exception as e:
                logger.warning(f"[Files] Skip adding to ZIP {path}: {e}")

    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=zip_name,
        mimetype="application/zip",
    )


# ---------- Search ----------


def _rg_collect_matches(
    file_paths: list[str],
    pattern: str,
    timeout: int = 60,
) -> list[tuple[str, int, str]]:
    """
    Run ripgrep on files. Returns list of (resolved_path_str, 1-based line number, line text).
    """
    rg_binary = shutil.which("rg")
    if not rg_binary or not file_paths:
        return []
    cmd = [
        rg_binary,
        "-n",
        "-H",  # Always show filename
        "-i",
        "--max-filesize",
        "50M",
        "-e",
        pattern,
    ] + file_paths
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.warning("[Files] ripgrep: %s", e)
        return []
    
    out: list[tuple[str, int, str]] = []
    for line in (result.stdout or "").strip().splitlines():
        if not line:
            continue
        idx = line.find(":")
        if idx == -1:
            continue
        path_part = line[:idx]
        rest = line[idx + 1:]
        colon2 = rest.find(":")
        if colon2 == -1:
            continue
        try:
            line_no = int(rest[:colon2])
        except ValueError:
            continue
        text = rest[colon2 + 1:]
        try:
            abs_path = str(Path(path_part).resolve())
        except OSError:
            continue
        out.append((abs_path, line_no, text.rstrip("\r\n")))
    return out


@files_bp.route("/<project_id>/files/search-all", methods=["POST"])
@jwt_required()
def search_all_files(project_id):
    """
    Search all files for the project/CPE with regex using ripgrep.

    Body: { "pattern": str, "cpe_id": str | null }
    Returns: { "matches": [ { "filename", "line_number", "text" } ], "total": int, "pattern": str }
    """
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    pattern = data.get("pattern", "").strip()
    if not pattern:
        return jsonify({"error": "Search pattern is required"}), 400
    apply_dedup = bool(data.get("dedup"))
    try:
        lpp = int(data.get("lines_per_page", LINES_PER_PAGE))
    except (TypeError, ValueError):
        lpp = LINES_PER_PAGE
    if lpp < 1:
        lpp = LINES_PER_PAGE

    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")
    search_dir = _get_project_dir(user_id, project_id, cpe_id)
    if not search_dir.exists():
        return jsonify({"matches": [], "total": 0, "pattern": pattern}), 200

    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return jsonify({"error": f"Invalid regex: {str(e)}"}), 400

    dedup_cfg = load_dedup_config(user_dedup_patterns_path(_get_user_dir(user_id)))
    inv_pats = (
        enabled_invert_patterns(dedup_cfg, filename)
        if apply_dedup and dedup_cfg.get("dedup_active")
        else []
    )
    search_alias = bool(inv_pats)

    files = dbm.get_project_files(project_id, cpe_id=cpe_id)
    path_to_filename: dict[str, str] = {}
    file_paths_to_search: list[str] = []
    for f in files:
        fp = getattr(f, "file_path", None)
        fn = getattr(f, "filename", None)
        if fp and fn:
            resolved_path = Path(fp).resolve()
            if not resolved_path.exists():
                continue
            if search_alias:
                ensure_dedup_materialized(resolved_path, dedup_cfg)
                body, _ = materialized_paths(resolved_path)
                alias_p = str(body.resolve())
                file_paths_to_search.append(alias_p)
                path_to_filename[alias_p] = fn
            else:
                key = str(resolved_path)
                file_paths_to_search.append(key)
                path_to_filename[key] = fn

    if not file_paths_to_search:
        return jsonify({"matches": [], "total": 0, "pattern": pattern}), 200

    rg_binary = shutil.which("rg")
    if not rg_binary:
        return jsonify({"error": "ripgrep (rg) not found on server"}), 503

    rg_rows = _rg_collect_matches(file_paths_to_search, pattern)
    matches = []
    for abs_path, line_no, text in rg_rows:
        if len(matches) >= 500:
            break
        filename = path_to_filename.get(abs_path)
        if filename is None:
            filename = Path(abs_path).name
        matches.append({
            "filename": filename,
            "line_number": line_no,
            "text": text,
        })

    if matches:
        by_fn = defaultdict(list)
        for m in matches:
            by_fn[m["filename"]].append(m)
        for fn, lst in by_fn.items():
            f_info = dbm.get_project_file_info(project_id, fn, cpe_id=cpe_id)
            if not f_info or not f_info.file_path or not os.path.exists(f_info.file_path):
                for m in lst:
                    m["content_page"] = (m["line_number"] - 1) // lpp + 1
                continue
            fp = f_info.file_path
            if search_alias:
                for m in lst:
                    ln = m["line_number"]
                    m["content_page"] = (ln - 1) // lpp + 1 if ln > 0 else 1
            else:
                with open(fp, "rb") as f:
                    raw = f.read()
                file_lines = [
                    line.decode("utf-8", errors="ignore").rstrip("\r\n")
                    for line in raw.split(b"\n")
                ]
                if file_lines and file_lines[-1] == "":
                    file_lines = file_lines[:-1]
                cmap = line_to_content_pages(file_lines, lpp)
                for m in lst:
                    m["content_page"] = cmap.get(m["line_number"], 1)

    return jsonify({
        "matches": matches,
        "total": len(matches),
        "pattern": pattern,
        "truncated": len(matches) >= 500,
    }), 200


@files_bp.route("/<project_id>/files/<filename>/search", methods=["POST"])
@jwt_required()
def search_file(project_id, filename):
    """
    Search a file with regex pattern.

    Body: { "pattern": str }
    Returns: { "matches": [ { "line_number", "text", "page" } ], "total": int }
    """
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    pattern = data.get("pattern", "")
    if not pattern:
        return jsonify({"error": "Search pattern is required"}), 400
    apply_dedup = bool(data.get("dedup"))

    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")
    file_info = dbm.get_project_file_info(project_id, filename, cpe_id=cpe_id)
    if not file_info:
        return jsonify({"error": "File not found"}), 404

    _, filepath, _, _, _ = file_info
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found on disk"}), 404

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return jsonify({"error": f"Invalid regex: {str(e)}"}), 400

    try:
        lpp = int(data.get("lines_per_page", LINES_PER_PAGE))
    except (TypeError, ValueError):
        lpp = LINES_PER_PAGE
    if lpp < 1:
        lpp = LINES_PER_PAGE

    dedup_cfg = load_dedup_config(user_dedup_patterns_path(_get_user_dir(user_id)))
    inv_pats = enabled_invert_patterns(dedup_cfg, filename) if apply_dedup and dedup_cfg.get("dedup_active") else []
    use_dedup = bool(inv_pats)

    matches: list[dict] = []
    if use_dedup:
        orig_path = Path(filepath).resolve()
        ensure_dedup_materialized(orig_path, dedup_cfg)
        body, meta_p = materialized_paths(orig_path)
        alias_path = str(body.resolve())
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        an = int(meta.get("alias_line_count", 0))
        page_map = {ln: ((ln - 1) // lpp + 1) for ln in range(1, an + 1)}
        if shutil.which("rg"):
            for _, ln, text in _rg_collect_matches([alias_path], pattern):
                matches.append({
                    "line_number": ln,
                    "text": text,
                    "content_page": page_map.get(ln, (ln - 1) // lpp + 1 if ln > 0 else 1),
                })
        else:
            alias_lines, _ = read_alias_view(orig_path)
            for ln, text in enumerate(alias_lines, 1):
                if regex.search(text):
                    matches.append({
                        "line_number": ln,
                        "text": text,
                        "content_page": page_map.get(ln, 1),
                    })
    else:
        with open(filepath, "rb") as f:
            content = f.read()
        lines = [
            line.decode("utf-8", errors="ignore").rstrip("\r\n")
            for line in content.split(b"\n")
        ]
        if lines and lines[-1] == "":
            lines = lines[:-1]
        page_map = line_to_content_pages(lines, lpp)
        for line_num, text in enumerate(lines, 1):
            if regex.search(text):
                matches.append({
                    "line_number": line_num,
                    "text": text,
                    "content_page": page_map[line_num],
                })
    
    logger.info(f"[Files] search_file: found {len(matches)} matches for pattern '{pattern}' in {filename}")
    return jsonify({
        "matches": matches,
        "total": len(matches),
        "pattern": pattern,
    }), 200


# ---------- Log viewer deduplication patterns (project file: log_viewer_dedup_patterns.json) ----------


@files_bp.route("/<project_id>/log-viewer-dedup-patterns", methods=["GET"])
@jwt_required()
def get_log_viewer_dedup_patterns(project_id):
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err
    path = user_dedup_patterns_path(_get_user_dir(user_id))
    cfg = load_dedup_config(path)
    return jsonify(cfg), 200


@files_bp.route("/<project_id>/log-viewer-dedup-patterns", methods=["PUT"])
@jwt_required()
def save_log_viewer_dedup_patterns(project_id):
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    dedup_active = bool(data.get("dedup_active", False))
    patterns_in = data.get("patterns")
    err_msg, patterns = validate_patterns_json(patterns_in)
    if err_msg:
        return jsonify({"error": err_msg}), 400

    user_dir = _get_user_dir(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dedup_patterns_path(user_dir)
    out = {"dedup_active": dedup_active, "patterns": patterns}
    try:
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("[Files] save log-viewer dedup patterns: %s", e)
        return jsonify({"error": "Could not save settings. Check server write permissions."}), 500
    return jsonify(out), 200


@files_bp.route("/<project_id>/dedup-from-line", methods=["POST"])
@jwt_required()
def dedup_from_line(project_id):
    """
    Generate a deduplication pattern from a raw log line.

    This endpoint:
    1. Takes a raw log line
    2. Automatically strips timestamp
    3. Replaces variable patterns with regex wildcards
    4. Returns the generated pattern + preview of matching lines

    Body: { "line": str, "file_path": str (optional) }
    Returns: {
        "success": bool,
        "original_line": str,
        "stripped_line": str,
        "generated_pattern": str,
        "pattern_valid": bool,
        "pattern_error": str or null,
        "preview_count": int,
        "preview_lines": [str, ...],
        "error": str or null
    }
    """
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    line = data.get("line", "").strip()
    file_path = data.get("file_path", "")

    if not line:
        return jsonify({
            "success": False,
            "error": "No log line provided"
        }), 400

    try:
        # Generate the pattern
        generated_pattern = generate_dedup_pattern(line)

        # Validate the pattern
        is_valid, pattern_error = validate_pattern(generated_pattern)

        # Try to get preview of matching lines if file_path provided
        preview_lines = []
        preview_count = 0

        if file_path and is_valid:
            try:
                project_dir = _get_project_dir(user_id, project_id)
                full_path = project_dir / file_path
                if full_path.exists() and full_path.is_file():
                    # Read lines from file
                    try:
                        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                            all_lines = f.readlines()

                        # Compile pattern and find matches
                        compiled_pattern = re.compile(generated_pattern, re.IGNORECASE)
                        matched_lines = []
                        for line_content in all_lines:
                            line_content = line_content.rstrip("\r\n")
                            if compiled_pattern.search(line_content):
                                matched_lines.append(line_content)
                                if len(matched_lines) >= 10:  # Limit to 10 preview lines
                                    break

                        preview_lines = matched_lines
                        preview_count = len(matched_lines)
                    except (OSError, UnicodeDecodeError) as e:
                        logger.warning(f"[Files] dedup_from_line: could not read file {full_path}: {e}")
            except Exception as e:
                logger.warning(f"[Files] dedup_from_line: could not generate preview: {e}")

        # Strip timestamp for display
        from api.log_pattern_extractor import strip_timestamp
        stripped_line = strip_timestamp(line)

        return jsonify({
            "success": True,
            "original_line": line,
            "stripped_line": stripped_line,
            "generated_pattern": generated_pattern,
            "pattern_valid": is_valid,
            "pattern_error": pattern_error,
            "preview_count": preview_count,
            "preview_lines": preview_lines,
            "error": None
        }), 200

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "original_line": line
        }), 400
    except Exception as e:
        logger.error(f"[Files] dedup_from_line: unexpected error: {e}")
        return jsonify({
            "success": False,
            "error": "Internal server error"
        }), 500

@files_bp.route("/<project_id>/notes", methods=["GET"])
@jwt_required()
def get_notes(project_id):
    """Get project notes."""
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    project_dir = _get_project_dir(user_id, project_id)
    notes_path = project_dir / "notes.txt"

    content = ""
    if notes_path.exists():
        with open(notes_path, "r") as f:
            content = f.read()

    return jsonify({"content": content}), 200


@files_bp.route("/<project_id>/notes", methods=["PUT"])
@jwt_required()
def save_notes(project_id):
    """
    Save project notes.

    Body: { "content": str }
    Returns: { "message": str }
    """
    user_id = get_user_id()
    _, err = _verify_project_access(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    content = data.get("content", "")

    project_dir = _get_project_dir(user_id, project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    notes_path = project_dir / "notes.txt"

    with open(notes_path, "w") as f:
        f.write(content)

    return jsonify({"message": "Notes saved"}), 200

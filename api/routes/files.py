"""
Files API Routes
=================

Endpoints for file upload, listing, content viewing, search, download, and notes.
"""

import io
import os
import re
import glob
import shutil
import logging
import subprocess
import threading
import zipfile
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from api.file_manager import FileManager, register_cpe_files
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
            "message": "No processing in progress",
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

    # Read in binary mode and split on \n only to match ripgrep/wc -l behavior
    # This prevents Python from treating standalone \r as line separators
    with open(filepath, "rb") as f:
        content = f.read()
    lines = [line.decode('utf-8', errors='ignore').rstrip("\r\n") for line in content.split(b'\n')]
    # Remove the last empty line if file ends with \n
    if lines and lines[-1] == '':
        lines = lines[:-1]

    total_lines = len(lines)
    total_pages = max(1, (total_lines + lpp - 1) // lpp)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * lpp
    end_idx = min(start_idx + lpp, total_lines)
    page_lines = lines[start_idx:end_idx]

    return jsonify({
        "lines": page_lines,
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

    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")
    search_dir = _get_project_dir(user_id, project_id, cpe_id)
    if not search_dir.exists():
        return jsonify({"matches": [], "total": 0, "pattern": pattern}), 200

    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return jsonify({"error": f"Invalid regex: {str(e)}"}), 400

    files = dbm.get_project_files(project_id, cpe_id=cpe_id)
    path_to_filename = {}
    file_paths_to_search = []
    for f in files:
        fp = getattr(f, "file_path", None)
        fn = getattr(f, "filename", None)
        if fp and fn:
            resolved_path = Path(fp).resolve()
            path_to_filename[resolved_path] = fn
            if resolved_path.exists():
                file_paths_to_search.append(str(resolved_path))

    if not file_paths_to_search:
        return jsonify({"matches": [], "total": 0, "pattern": pattern}), 200

    rg_binary = shutil.which("rg")
    if not rg_binary:
        return jsonify({"error": "ripgrep (rg) not found on server"}), 503

    cmd = [
        rg_binary,
        "-n",
        "-i",
        "--max-filesize", "50M",
        "-e", pattern,
    ] + file_paths_to_search
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Search timed out"}), 504
    except Exception as e:
        logger.warning(f"[Files] search-all rg error: {e}")
        return jsonify({"error": str(e)}), 500

    matches = []
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
        abs_path = Path(path_part).resolve()
        filename = path_to_filename.get(abs_path)
        if filename is None:
            filename = Path(path_part).name
        matches.append({
            "filename": filename,
            "line_number": line_no,
            "text": text.rstrip("\r\n"),
        })
        if len(matches) >= 500:
            break

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

    matches = []
    lpp = LINES_PER_PAGE
    with open(filepath, "r", errors="ignore") as f:
        for line_num, line in enumerate(f, 1):
            if regex.search(line):
                matches.append({
                    "line_number": line_num,
                    "text": line.rstrip("\r\n"),
                })

    return jsonify({
        "matches": matches,
        "total": len(matches),
        "pattern": pattern,
    }), 200


# ---------- Notes ----------

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

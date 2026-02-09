"""
Files API Routes
=================

Endpoints for file upload, listing, content viewing, search, download, and notes.
"""

import os
import re
import glob
import shutil
import logging
import threading
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from api.file_manager import FileManager
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


# ---------- Upload ----------

@files_bp.route("/<project_id>/files/upload", methods=["POST"])
@jwt_required()
def upload_files(project_id):
    """
    Upload files to a project (multipart/form-data).

    Accepts multiple files. After saving, processes tarballs,
    merges logs, and launches async indexing.

    Returns: { "message": str, "files": [str] }
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

    saved_filenames = []
    for f in uploaded_files:
        if f.filename:
            filepath = project_dir / f.filename
            f.save(str(filepath))
            saved_filenames.append(f.filename)
            logger.info(f"[Upload] Saved {f.filename} ({filepath.stat().st_size} bytes)")

    # Detect multi-CPE zip uploads
    file_manager = FileManager()
    cpe_zips = FileManager.detect_cpe_zips(project_dir)

    if cpe_zips:
        # ---- Multi-CPE upload path ----
        logger.info(f"[Upload] Detected {len(cpe_zips)} CPE zip(s)")
        cpe_results = file_manager.process_multi_cpe_upload(project_dir, project.name)

        # Collect indexing jobs — launched as a single sequential batch
        # to avoid shared-model corruption and I/O contention.
        indexer_batch = []

        for cpe in cpe_results:
            serial = cpe["serial"]
            # Save CPE metadata to DB
            dbm.save_cpe(
                project_id=project_id,
                serial=serial,
                mac=cpe.get("mac"),
                date_from=cpe.get("date_from"),
                date_to=cpe.get("date_to"),
            )
            # Save CPE files to DB
            cpe_dir = project_dir / serial
            if cpe_dir.exists():
                for f in cpe_dir.iterdir():
                    if f.is_file() and f.stat().st_size > 0:
                        dbm.save_cpe_file(project_id, serial, f, f.name)
                # Queue per-CPE indexer (processed sequentially)
                indexer_batch.append((cpe_dir, project_id, serial))

        # Launch all CPEs in a single background thread (sequential)
        _launch_async_indexer_batch(indexer_batch)

        # Clean up zip files after processing
        for cpe_info in cpe_zips:
            try:
                cpe_info["path"].unlink()
            except Exception:
                pass

        return jsonify({
            "message": f"Uploaded {len(saved_filenames)} file(s), processed {len(cpe_results)} CPE(s)",
            "files": saved_filenames,
            "cpes": [c["serial"] for c in cpe_results],
        }), 201
    else:
        # ---- Legacy single-upload path ----
        logger.info(f"[Upload] Processing uploaded files in {project_dir}")
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
        }), 201


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

    file_info = dbm.get_project_file_info(project_id, filename)
    if not file_info:
        return jsonify({"error": "File not found"}), 404

    _, filepath, _, _, _ = file_info
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found on disk"}), 404

    with open(filepath, "r", errors="ignore") as f:
        lines = [line.rstrip("\r\n") for line in f]

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

    file_info = dbm.get_project_file_info(project_id, filename)
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


# ---------- Search ----------

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

    file_info = dbm.get_project_file_info(project_id, filename)
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
                    "page": (line_num - 1) // lpp + 1,
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

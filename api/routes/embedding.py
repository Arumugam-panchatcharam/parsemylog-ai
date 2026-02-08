"""
Embedding/Indexing API Routes
==============================

Endpoints for pipeline status and template download.
"""

import os
import re
import logging
from pathlib import Path
from io import BytesIO

import pandas as pd
from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY, NON_TEXT_EXTENSIONS, IGNORE_FILENAME_LIST
from logai.embedding import read_status

logger = logging.getLogger(__name__)

embedding_bp = Blueprint("embedding", __name__)


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


# ---------- Pipeline Status ----------

@embedding_bp.route("/<project_id>/pipeline/status", methods=["GET"])
@jwt_required()
def pipeline_status(project_id):
    """
    Get embedding pipeline status for all files.

    Returns: { "files": { filename: { "state", ... } } }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    status = read_status(project_dir)

    return jsonify({"files": status}), 200


# ---------- Templates for File ----------

@embedding_bp.route("/<project_id>/files/<filename>/templates", methods=["GET"])
@jwt_required()
def file_templates(project_id, filename):
    """
    Get extracted templates for a specific file.

    Returns: { "templates": [ { "template", "count" } ] }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    file_info = dbm.get_project_file_info(project_id, filename)
    if not file_info:
        return jsonify({"error": "File not found"}), 404

    _, filepath, _, file_size, _ = file_info
    if not filepath or not os.path.exists(filepath) or file_size == 0:
        return jsonify({"templates": []}), 200

    parquet_path = Path(filepath + ".parquet")
    if not parquet_path.exists():
        # Try domain parquets
        project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
        from logai.pattern import Pattern
        parser = Pattern(project_dir=project_dir)
        result_df, _ = parser.parse_logs(filepath)
        if result_df is None or result_df.empty:
            return jsonify({"templates": []}), 200
    else:
        result_df = pd.read_parquet(parquet_path)

    if "template" not in result_df.columns:
        return jsonify({"templates": []}), 200

    template_counts = result_df["template"].value_counts().reset_index()
    template_counts.columns = ["template", "count"]

    templates = []
    for _, row in template_counts.iterrows():
        templates.append({
            "template": str(row["template"]),
            "count": int(row["count"]),
        })

    return jsonify({"templates": templates}), 200


# ---------- Download Templates ----------

@embedding_bp.route("/<project_id>/templates/download", methods=["GET"])
@jwt_required()
def download_templates(project_id):
    """
    Download all templates as Excel file.

    Returns: Excel file download.
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    try:
        files = dbm.get_project_files(project_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
    df_list = []

    for filename, file_path, original_name, file_size, _ in files:
        if not file_path or not os.path.exists(file_path) or file_size == 0:
            continue
        if any(filename.endswith(ext) for ext in NON_TEXT_EXTENSIONS):
            continue
        if any(ign.lower() in original_name.lower() for ign in IGNORE_FILENAME_LIST):
            continue

        parquet_path = Path(file_path + ".parquet")
        if not parquet_path.exists():
            continue

        df = pd.read_parquet(parquet_path)
        df = df.drop(columns=["timestamp", "loglines", "parameter_list"], errors="ignore")
        df["template"] = df["template"].astype(str)
        df["template"] = df["template"].apply(lambda x: ANSI_RE.sub("", x))
        df["template"] = df["template"].apply(lambda x: re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', x))

        result_df = df["template"].value_counts().reset_index()
        result_df.columns = ["template", "count"]
        result_df["filename"] = original_name
        result_df = result_df[["filename", "count", "template"]]
        df_list.append(result_df)

    if not df_list:
        return jsonify({"error": "No templates available for download"}), 404

    combined_df = pd.concat(df_list, ignore_index=True)

    # Write to Excel in memory
    output = BytesIO()
    combined_df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"Unique-Patterns-{project.name}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

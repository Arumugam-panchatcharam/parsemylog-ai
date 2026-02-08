"""
Pattern Analysis API Routes
=============================

Endpoints for domain-based Drain3 pattern analysis.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY
from logai.pattern import extract_parameters

logger = logging.getLogger(__name__)

patterns_bp = Blueprint("patterns", __name__)

# Expected domains
_ALL_DOMAINS = ["wireless", "platform", "core_router", "cellular", "mesh"]

_DOMAIN_LABELS = {
    "wireless": "Wireless",
    "platform": "Platform",
    "core_router": "Core Router",
    "cellular": "Cellular",
    "mesh": "Mesh",
}


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _project_dir(user_id, project_id):
    return Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")


def _load_domain_parquet(project_dir, domain):
    parquet_path = project_dir / f"{domain}_rg.parquet"
    if not parquet_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(parquet_path)


# ---------- List Domains ----------

@patterns_bp.route("/<project_id>/domains", methods=["GET"])
@jwt_required()
def list_domains(project_id):
    """
    List indexed domains for a project.

    Returns: [ { "domain", "label", "indexed", "file_count" } ]
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    pdir = _project_dir(user_id, project_id)
    result = []
    for domain in _ALL_DOMAINS:
        pq_path = pdir / f"{domain}_rg.parquet"
        indexed = pq_path.exists()
        file_count = 0
        if indexed:
            try:
                df = pd.read_parquet(pq_path, columns=["source_file"] if "source_file" in pd.read_parquet(pq_path, columns=[]).columns else [])
                if "source_file" in df.columns:
                    file_count = df["source_file"].nunique()
            except Exception:
                pass
        result.append({
            "domain": domain,
            "label": _DOMAIN_LABELS.get(domain, domain),
            "indexed": indexed,
            "file_count": file_count,
        })

    return jsonify(result), 200


# ---------- Analyze Domain ----------

@patterns_bp.route("/<project_id>/domains/<domain>/analyze", methods=["POST"])
@jwt_required()
def analyze_domain(project_id, domain):
    """
    Run pattern analysis on a domain.

    Body: { "file_filter"?: [str] }
    Returns: { "summary", "chart_data" }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    file_filter = data.get("file_filter")

    pdir = _project_dir(user_id, project_id)
    df = _load_domain_parquet(pdir, domain)

    if df.empty:
        return jsonify({"error": f"No patterns found for domain '{domain}'"}), 404

    if "template" not in df.columns:
        return jsonify({"error": "Parquet cache is missing 'template' column"}), 500

    # Apply file filter
    if file_filter and "source_file" in df.columns:
        df = df[df["source_file"].isin(file_filter)]
        if df.empty:
            return jsonify({"error": "No patterns found for selected files"}), 404

    # Summary
    total_loglines = len(df)
    total_patterns = int(df["template"].nunique())

    # Chart data: template frequency
    count_table = df["template"].value_counts()
    chart_data = []
    for idx, (template, count) in enumerate(count_table.items()):
        chart_data.append({
            "order": idx,
            "template": str(template),
            "count": int(count),
            "ratio": float(count / count_table.sum()),
        })

    # Source files in this domain
    source_files = []
    if "source_file" in df.columns:
        source_files = sorted(df["source_file"].dropna().unique().tolist())

    return jsonify({
        "summary": {
            "total_loglines": total_loglines,
            "total_patterns": total_patterns,
        },
        "chart_data": chart_data,
        "source_files": source_files,
        "parquet_path": str(pdir / f"{domain}_rg.parquet"),
    }), 200


# ---------- Time Series ----------

@patterns_bp.route("/<project_id>/domains/<domain>/timeseries", methods=["GET"])
@jwt_required()
def get_timeseries(project_id, domain):
    """
    Get time-series data for a template.

    Query params: template (str), interval (0-3), file_filter (comma-separated)
    Returns: { "data": [ { "timestamp", "count" } ] }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    template = request.args.get("template", "")
    interval = request.args.get("interval", 0, type=int)
    file_filter_str = request.args.get("file_filter", "")
    file_filter = [f.strip() for f in file_filter_str.split(",") if f.strip()] or None

    if not template:
        return jsonify({"error": "template parameter is required"}), 400

    pdir = _project_dir(user_id, project_id)
    df = _load_domain_parquet(pdir, domain)
    if df.empty or "timestamp" not in df.columns:
        return jsonify({"data": []}), 200

    if file_filter and "source_file" in df.columns:
        df = df[df["source_file"].isin(file_filter)]

    interval_map = {0: "1s", 1: "1min", 2: "1h", 3: "1D"}
    freq = interval_map.get(interval, "1min")

    df_pattern = df.loc[df["template"] == template, ["timestamp"]].dropna()
    if df_pattern.empty:
        return jsonify({"data": []}), 200

    df_pattern["timestamp"] = pd.to_datetime(df_pattern["timestamp"])
    ts_df = (
        df_pattern.groupby(pd.Grouper(key="timestamp", freq=freq))
        .size()
        .reset_index(name="count")
    )

    # Downsample if too many points
    max_points = 5000
    if len(ts_df) > max_points:
        ts_df = ts_df.iloc[:: len(ts_df) // max_points + 1]

    result = []
    for _, row in ts_df.iterrows():
        result.append({
            "timestamp": str(row["timestamp"]),
            "count": int(row["count"]),
        })

    return jsonify({"data": result, "freq": freq}), 200


# ---------- Parameters ----------

@patterns_bp.route("/<project_id>/domains/<domain>/parameters", methods=["GET"])
@jwt_required()
def get_parameters(project_id, domain):
    """
    Extract parameters for a template.

    Query params: template (str), file_filter (comma-separated)
    Returns: { "parameters": [ { "position", "count", "values" } ] }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    template = request.args.get("template", "")
    file_filter_str = request.args.get("file_filter", "")
    file_filter = [f.strip() for f in file_filter_str.split(",") if f.strip()] or None

    if not template:
        return jsonify({"error": "template parameter is required"}), 400

    pdir = _project_dir(user_id, project_id)
    df = _load_domain_parquet(pdir, domain)
    if df.empty:
        return jsonify({"parameters": []}), 200

    if file_filter and "source_file" in df.columns:
        df = df[df["source_file"].isin(file_filter)]

    matching = df[df["template"] == template]
    if matching.empty:
        return jsonify({"parameters": []}), 200

    # Extract parameters
    if "parameter_list" in df.columns:
        parameters = matching["parameter_list"]
    else:
        loglines = matching["loglines"].tolist()
        parquet_path = str(pdir / f"{domain}_rg.parquet")
        param_values = extract_parameters(
            template, loglines,
            project_dir=str(pdir),
            domain=domain,
        )
        parameters = pd.Series(param_values)

    if parameters.empty:
        return jsonify({"parameters": []}), 200

    try:
        params_df = pd.DataFrame(parameters.tolist())
        if params_df.empty or params_df.shape[1] == 0:
            return jsonify({"parameters": []}), 200

        result = []
        for col_idx in range(params_df.shape[1]):
            col_values = params_df.iloc[:, col_idx].dropna().tolist()
            unique_values = list(set(str(v) for v in col_values if v))
            result.append({
                "position": f"POSITION_{col_idx}",
                "count": len([v for v in col_values if v]),
                "values": unique_values[:100],  # Limit to 100 unique values
            })
        return jsonify({"parameters": result}), 200
    except Exception as e:
        logger.warning(f"[Pattern Params] Error: {e}")
        return jsonify({"parameters": []}), 200


# ---------- Log Lines ----------

@patterns_bp.route("/<project_id>/domains/<domain>/loglines", methods=["GET"])
@jwt_required()
def get_loglines(project_id, domain):
    """
    Get matching log lines for a template.

    Query params: template (str), file_filter (comma-separated), page (int), page_size (int)
    Returns: { "lines": [...], "total": int }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    template = request.args.get("template", "")
    file_filter_str = request.args.get("file_filter", "")
    file_filter = [f.strip() for f in file_filter_str.split(",") if f.strip()] or None
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 20, type=int)

    if not template:
        return jsonify({"error": "template parameter is required"}), 400

    pdir = _project_dir(user_id, project_id)
    df = _load_domain_parquet(pdir, domain)
    if df.empty:
        return jsonify({"lines": [], "total": 0}), 200

    if file_filter and "source_file" in df.columns:
        df = df[df["source_file"].isin(file_filter)]

    matching = df[df["template"] == template]
    cols_to_drop = [c for c in ["parameter_list", "template", "source_file"] if c in matching.columns]
    matching = matching.drop(columns=cols_to_drop, errors="ignore")

    total = len(matching)
    start = (page - 1) * page_size
    end = start + page_size
    page_data = matching.iloc[start:end]

    lines = []
    for _, row in page_data.iterrows():
        lines.append({
            "timestamp": str(row.get("timestamp", "")),
            "loglines": str(row.get("loglines", "")),
        })

    return jsonify({
        "lines": lines,
        "total": total,
        "page": page,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }), 200


# ---------- Indexing Status ----------

@patterns_bp.route("/<project_id>/indexing/status", methods=["GET"])
@jwt_required()
def indexing_status(project_id):
    """
    Get domain indexing status.

    Returns: { "domains": { domain: { "indexed", "label" } }, "all_done": bool, "is_indexing": bool }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    pdir = _project_dir(user_id, project_id)
    domains = {}
    for domain in _ALL_DOMAINS:
        indexed = (pdir / f"{domain}_rg.parquet").exists()
        domains[domain] = {
            "indexed": indexed,
            "label": _DOMAIN_LABELS.get(domain, domain),
        }

    all_done = all(d["indexed"] for d in domains.values())

    # Check if indexer is running
    is_indexing_flag = False
    try:
        from api.indexer import is_indexing as _is_indexing
        is_indexing_flag = _is_indexing(project_id)
    except Exception:
        pass

    return jsonify({
        "domains": domains,
        "all_done": all_done,
        "is_indexing": is_indexing_flag,
    }), 200

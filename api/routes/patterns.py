"""
Pattern Analysis API Routes
=============================

Endpoints for domain-based Drain3 pattern analysis.
"""

import json
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

# Core domains (used for all_done check -- always expected to be indexed)
_CORE_DOMAINS = ["wireless", "platform", "core_router", "cellular", "mesh"]

# All domains including newer additions
_ALL_DOMAINS = _CORE_DOMAINS + ["telemetry", "common", "voice"]

_DOMAIN_LABELS = {
    "wireless": "Wireless",
    "platform": "Platform",
    "core_router": "Core Router",
    "cellular": "Cellular",
    "mesh": "Mesh",
    "telemetry": "Telemetry",
    "common": "Common",
    "voice": "Voice",
}


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _project_dir(user_id, project_id, cpe_id=None):
    base = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    if cpe_id:
        return base / cpe_id
    return base


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

    When ``cpe_id`` is provided, checks that specific CPE directory.
    Otherwise scans all CPE directories so the aggregated (ALL CPEs)
    view correctly reports domain availability.

    Returns: [ { "domain", "label", "indexed", "file_count" } ]
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")

    # Collect directories to probe for parquet files
    if cpe_id:
        probe_dirs = [_project_dir(user_id, project_id, cpe_id)]
    else:
        # No CPE specified — check project root first, then all CPE dirs
        project_root = _project_dir(user_id, project_id)
        cpes = dbm.list_project_cpes(project_id)
        probe_dirs = [project_root] + [
            project_root / cpe.serial for cpe in (cpes or [])
        ]

    result = []
    for domain in _ALL_DOMAINS:
        indexed = False
        file_count = 0
        for pdir in probe_dirs:
            pq_path = pdir / f"{domain}_rg.parquet"
            if pq_path.exists():
                indexed = True
                try:
                    df = pd.read_parquet(
                        pq_path,
                        columns=["source_file"]
                        if "source_file"
                        in pd.read_parquet(pq_path, columns=[]).columns
                        else [],
                    )
                    if "source_file" in df.columns:
                        file_count += df["source_file"].nunique()
                except Exception:
                    pass
                break  # found an indexed parquet — no need to check more
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
    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")

    pdir = _project_dir(user_id, project_id, cpe_id)
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
    cpe_id = request.args.get("cpe_id")

    if not template:
        return jsonify({"error": "template parameter is required"}), 400

    pdir = _project_dir(user_id, project_id, cpe_id)
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
    cpe_id = request.args.get("cpe_id")

    if not template:
        return jsonify({"error": "template parameter is required"}), 400

    pdir = _project_dir(user_id, project_id, cpe_id)
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
    cpe_id = request.args.get("cpe_id")

    if not template:
        return jsonify({"error": "template parameter is required"}), 400

    pdir = _project_dir(user_id, project_id, cpe_id)
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

    When ``cpe_id`` is provided, checks that specific CPE directory.
    Otherwise scans all CPE directories for parquet presence.

    Returns: { "domains": { domain: { "indexed", "label" } }, "all_done": bool, "is_indexing": bool }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")

    if cpe_id:
        probe_dirs = [_project_dir(user_id, project_id, cpe_id)]
    else:
        project_root = _project_dir(user_id, project_id)
        cpes = dbm.list_project_cpes(project_id)
        probe_dirs = [project_root] + [
            project_root / cpe.serial for cpe in (cpes or [])
        ]

    domains = {}
    for domain in _ALL_DOMAINS:
        indexed = any(
            (pdir / f"{domain}_rg.parquet").exists() for pdir in probe_dirs
        )
        domains[domain] = {
            "indexed": indexed,
            "label": _DOMAIN_LABELS.get(domain, domain),
        }

    all_done = all(
        domains[d]["indexed"] for d in _CORE_DOMAINS if d in domains
    )

    # Check if indexer is running
    is_indexing_flag = False
    try:
        from api.indexer import is_indexing as _is_indexing
        is_indexing_flag = _is_indexing(project_id, cpe_id=cpe_id)
    except Exception:
        pass

    return jsonify({
        "domains": domains,
        "all_done": all_done,
        "is_indexing": is_indexing_flag,
    }), 200


# ---------- Multi-CPE Aggregated Patterns ----------

@patterns_bp.route("/<project_id>/domains/<domain>/aggregated", methods=["GET"])
@jwt_required()
def get_aggregated_patterns(project_id, domain):
    """
    Get unique patterns aggregated across ALL CPEs in a project for a specific domain.
    
    Query params: 
        - page: Page number (default 1)
        - page_size: Items per page (default 50)
        - sort: 'frequency' or 'alphabetical' (default 'frequency')
        - file_filter: Comma-separated list of filenames to filter
        - with_baseline: if true, each pattern includes in_baseline and prevalence (vs project baseline)
    
    Returns: {
        "domain": str,
        "total_cpes": int,
        "total_unique_patterns": int,
        "page": int,
        "page_size": int,
        "total_pages": int,
        "source_files": [str],  # Available files in this domain
        "patterns": [
            {
                "template": str,
                "occurrence_count": int,  # Total occurrences across all CPEs
                "cpe_count": int,         # Number of CPEs with this pattern
                "cpe_details": {          # Per-CPE occurrence counts
                    "CPE_SERIAL": count
                }
            }
        ]
    }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 50, type=int)
    sort_by = request.args.get("sort", "frequency")
    file_filter_str = request.args.get("file_filter", "")
    file_filter = [f.strip() for f in file_filter_str.split(",") if f.strip()] if file_filter_str else None
    with_baseline = request.args.get("with_baseline", "").lower() in ("1", "true", "yes")

    # Build list of (label, directory) pairs to scan
    cpes = dbm.list_project_cpes(project_id)
    scan_entries: list[tuple[str, Path]] = []
    if cpes:
        for cpe in cpes:
            scan_entries.append((cpe.serial, _project_dir(user_id, project_id, cpe.serial)))
    else:
        # No CPE records — fall back to project root (single-CPE uploads)
        project_root = _project_dir(user_id, project_id)
        pq = project_root / f"{domain}_rg.parquet"
        if pq.exists():
            scan_entries.append(("root", project_root))
    
    if not scan_entries:
        return jsonify({
            "domain": domain,
            "total_cpes": 0,
            "total_unique_patterns": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 0,
            "source_files": [],
            "patterns": []
        }), 200
    
    # Aggregate patterns from all entries
    pattern_data = {}  # template -> {occurrence_count, cpe_details: {serial: count}}
    all_source_files = set()
    
    for label, entry_dir in scan_entries:
        df = _load_domain_parquet(entry_dir, domain)
        
        if df.empty or "template" not in df.columns:
            continue
        
        if "source_file" in df.columns:
            all_source_files.update(df["source_file"].dropna().unique().tolist())
        
        # Apply file filter
        if file_filter and "source_file" in df.columns:
            df = df[df["source_file"].isin(file_filter)]
            if df.empty:
                continue
        
        # Count occurrences per template for this entry
        template_counts = df["template"].value_counts()
        
        for template, count in template_counts.items():
            template_str = str(template)
            if template_str not in pattern_data:
                pattern_data[template_str] = {
                    "occurrence_count": 0,
                    "cpe_details": {}
                }
            
            pattern_data[template_str]["occurrence_count"] += int(count)
            pattern_data[template_str]["cpe_details"][label] = int(count)
    
    # Convert to list format
    patterns_list = []
    for template, data in pattern_data.items():
        patterns_list.append({
            "template": template,
            "occurrence_count": data["occurrence_count"],
            "cpe_count": len(data["cpe_details"]),
            "cpe_details": data["cpe_details"]
        })
    
    # Sort
    if sort_by == "frequency":
        patterns_list.sort(key=lambda x: x["occurrence_count"], reverse=True)
    else:  # alphabetical
        patterns_list.sort(key=lambda x: x["template"])
    
    # Pagination
    total_patterns = len(patterns_list)
    total_pages = (total_patterns + page_size - 1) // page_size if total_patterns > 0 else 0
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_patterns = patterns_list[start_idx:end_idx]
    total_cpes = len(scan_entries)

    if with_baseline:
        row = dbm.get_template_pattern_baseline(project_id=project_id)
        baseline_set: set = set()
        if row:
            try:
                baseline_set = set(json.loads(row.templates_json or "[]"))
            except json.JSONDecodeError:
                baseline_set = set()
        for p in paginated_patterns:
            p["in_baseline"] = p["template"] in baseline_set
            p["prevalence"] = (
                round(len(p["cpe_details"]) / total_cpes, 4) if total_cpes else 0.0
            )

    return jsonify({
        "domain": domain,
        "total_cpes": total_cpes,
        "total_unique_patterns": total_patterns,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "source_files": sorted(list(all_source_files)),
        "patterns": paginated_patterns
    }), 200


@patterns_bp.route("/<project_id>/domains/<domain>/aggregated/<path:template>/sample-logs", methods=["GET"])
@jwt_required()
def get_aggregated_sample_logs(project_id, domain, template):
    """
    Get sample log lines for a specific pattern template from the FIRST CPE.
    
    Query params:
        - limit: Maximum number of sample logs to return (default 3)
    
    Returns: {
        "template": str,
        "samples": [
            {
                "cpe_serial": str,
                "timestamp": str,
                "logline": str
            }
        ]
    }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    limit = request.args.get("limit", 3, type=int)
    limit = min(max(1, limit), 10)  # Clamp between 1 and 10
    
    # Build list of (label, directory) pairs to scan
    cpes = dbm.list_project_cpes(project_id)
    scan_entries: list[tuple[str, Path]] = []
    if cpes:
        for cpe in cpes:
            scan_entries.append((cpe.serial, _project_dir(user_id, project_id, cpe.serial)))
    else:
        project_root = _project_dir(user_id, project_id)
        pq = project_root / f"{domain}_rg.parquet"
        if pq.exists():
            scan_entries.append(("root", project_root))
    
    if not scan_entries:
        return jsonify({
            "template": template,
            "samples": []
        }), 200
    
    samples = []
    
    # Find the FIRST entry with this pattern and get samples from it only
    for label, entry_dir in scan_entries:
        df = _load_domain_parquet(entry_dir, domain)
        
        if df.empty or "template" not in df.columns:
            continue
        
        matching = df[df["template"] == template]
        
        if matching.empty:
            continue
        
        for _, row in matching.head(limit).iterrows():
            samples.append({
                "cpe_serial": label,
                "filename": str(row.get("source_file", "")),
                "timestamp": str(row.get("timestamp", "")),
                "logline": str(row.get("loglines", ""))
            })
        
        break
    
    return jsonify({
        "template": template,
        "samples": samples
    }), 200


# ---------- Template baseline (novelty vs known patterns) ----------

@patterns_bp.route("/<project_id>/patterns/template-baseline", methods=["GET"])
@jwt_required()
def get_template_pattern_baseline_route(project_id):
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err
    scope = (request.args.get("scope") or "project").lower()
    if scope == "global":
        row = dbm.get_template_pattern_baseline()
    else:
        row = dbm.get_template_pattern_baseline(project_id=project_id)
    if not row:
        return jsonify({"scope_type": scope, "templates": [], "count": 0}), 200
    try:
        templates = json.loads(row.templates_json or "[]")
    except json.JSONDecodeError:
        templates = []
    return jsonify({
        "scope_type": row.scope_type,
        "project_id": row.project_id,
        "templates": templates,
        "count": len(templates),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }), 200


@patterns_bp.route("/<project_id>/patterns/template-baseline", methods=["PUT"])
@jwt_required()
def put_template_pattern_baseline_route(project_id):
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    templates = body.get("templates")
    if templates is None or not isinstance(templates, list):
        return jsonify({"error": "Body must include templates: string[]"}), 400
    merge = bool(body.get("merge", False))
    scope = (body.get("scope") or "project").lower()
    if scope == "global":
        row = dbm.set_template_pattern_baseline(
            [str(t) for t in templates], merge=merge,
        )
    else:
        row = dbm.set_template_pattern_baseline(
            [str(t) for t in templates],
            project_id=project_id,
            merge=merge,
        )
    out = json.loads(row.templates_json or "[]")
    return jsonify({
        "scope_type": row.scope_type,
        "count": len(out),
        "message": "baseline saved",
    }), 200


# ---------- Fleet template transitions (Drain3 bigrams) ----------

@patterns_bp.route("/<project_id>/patterns/template-flow-fleet", methods=["GET"])
@jwt_required()
def get_template_flow_fleet(project_id):
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err
    from logai.template_flow import aggregate_fleet_template_bigrams

    cpes = dbm.list_project_cpes(project_id)
    scan_entries: list[tuple[str, Path]] = []
    if cpes:
        for cpe in cpes:
            scan_entries.append((cpe.serial, _project_dir(user_id, project_id, cpe.serial)))
    else:
        project_root = _project_dir(user_id, project_id)
        scan_entries.append(("root", project_root))

    rows, stats = aggregate_fleet_template_bigrams(scan_entries)
    return jsonify({
        "total_cpes": stats.get("total_cpes", 0),
        "bigrams": rows,
    }), 200


# ---------- Global Export ----------

@patterns_bp.route("/<project_id>/patterns/export-global", methods=["GET"])
@jwt_required()
def export_global_patterns(project_id):
    """
    Export ALL domain patterns across all CPEs to Excel.
    Creates one sheet per source filename with an index sheet.
    
    Returns: Excel file (.xlsx) with:
        - Index sheet: Domain groups, files, and navigation links
        - Data sheets: One per source filename with columns:
          Domain Name | File Name | Pattern | Frequency | CPE Count | Sample Log Lines
    """
    import re
    from datetime import datetime
    from io import BytesIO
    from flask import send_file
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    
    # Helper function to clean strings for Excel
    ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
    
    def clean_for_excel(text):
        """Remove ANSI codes and illegal characters for Excel."""
        if not isinstance(text, str):
            text = str(text)
        # Remove ANSI color codes
        text = ANSI_RE.sub("", text)
        # Remove control characters (except newline, tab, carriage return)
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)
        return text
    
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    # Build list of (label, directory) pairs to scan
    cpes = dbm.list_project_cpes(project_id)
    scan_entries: list[tuple[str, Path]] = []
    if cpes:
        for cpe in cpes:
            scan_entries.append((cpe.serial, _project_dir(user_id, project_id, cpe.serial)))
    else:
        # No CPE records — fall back to project root (single-CPE uploads)
        project_root = _project_dir(user_id, project_id)
        scan_entries.append(("root", project_root))
    
    if not scan_entries:
        return jsonify({"error": "No CPE data found"}), 404
    
    total_cpes = len(scan_entries)
    
    # Data structure: { filename: { domain: [pattern_records] } }
    file_data = {}
    # Track which domains have which files
    domain_files = {}
    
    # Iterate through all domains and collect pattern data
    for domain in _ALL_DOMAINS:
        domain_label = _DOMAIN_LABELS.get(domain, domain)
        domain_files[domain_label] = set()
        
        # Aggregate patterns from all CPEs for this domain
        pattern_data = {}  # template -> {occurrence_count, cpe_details: {serial: count}}
        
        for label, entry_dir in scan_entries:
            df = _load_domain_parquet(entry_dir, domain)
            
            if df.empty or "template" not in df.columns:
                continue
            
            # Track source files
            if "source_file" in df.columns:
                source_files = df["source_file"].dropna().unique()
                domain_files[domain_label].update(source_files)
            
            # Count occurrences per template for this CPE
            template_counts = df["template"].value_counts()
            
            for template, count in template_counts.items():
                template_str = str(template)
                
                # Get source file(s) for this template
                if "source_file" in df.columns:
                    template_df = df[df["template"] == template]
                    source_file = template_df["source_file"].iloc[0] if len(template_df) > 0 else "unknown"
                else:
                    source_file = "unknown"
                
                # Initialize structure
                if source_file not in file_data:
                    file_data[source_file] = {}
                if domain_label not in file_data[source_file]:
                    file_data[source_file][domain_label] = {}
                
                if template_str not in file_data[source_file][domain_label]:
                    file_data[source_file][domain_label][template_str] = {
                        "occurrence_count": 0,
                        "cpe_details": {},
                        "sample_logs": []
                    }
                
                file_data[source_file][domain_label][template_str]["occurrence_count"] += int(count)
                file_data[source_file][domain_label][template_str]["cpe_details"][label] = int(count)
                
                # Get sample logs (up to 3) from first CPE
                if len(file_data[source_file][domain_label][template_str]["sample_logs"]) == 0:
                    template_df = df[df["template"] == template]
                    for _, row in template_df.head(3).iterrows():
                        sample_log = str(row.get("loglines", ""))
                        if sample_log:
                            file_data[source_file][domain_label][template_str]["sample_logs"].append(sample_log)
    
    if not file_data:
        return jsonify({"error": "No pattern data found"}), 404

    min_prevalence = request.args.get("min_prevalence", type=float)
    include_prevalence_sheet = request.args.get(
        "include_prevalence_sheet", "true"
    ).lower() not in ("0", "false", "no")
    high_prevalence_rows: list[dict] = []

    # Create Excel workbook
    wb = Workbook()
    wb.remove(wb.active)  # Remove default sheet
    
    # Create Index sheet
    index_sheet = wb.create_sheet("INDEX", 0)
    
    # Style definitions
    header_font = Font(bold=True, size=12, color="FFFFFF")
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
    link_font = Font(color="0563C1", underline="single")
    
    # Index sheet headers
    index_sheet["A1"] = "DOMAIN"
    index_sheet["B1"] = "FILES"
    
    for cell in ["A1", "B1"]:
        index_sheet[cell].font = header_font
        index_sheet[cell].fill = header_fill
        index_sheet[cell].alignment = Alignment(horizontal="center", vertical="center")
    
    # Build index data
    index_row = 2
    for domain_label in sorted(domain_files.keys()):
        files = sorted(domain_files[domain_label])
        if not files:
            continue
        
        # First file row - include domain name
        first_file = True
        for filename in files:
            if filename in file_data and domain_label in file_data[filename]:
                # Sanitize sheet name
                sheet_name = filename[:31].replace("/", "_").replace("\\", "_").replace("*", "_").replace("?", "_").replace("[", "_").replace("]", "_")
                
                if first_file:
                    index_sheet[f"A{index_row}"] = domain_label
                    index_sheet[f"A{index_row}"].font = Font(bold=True)
                    first_file = False
                
                # Merge filename and hyperlink into single cell
                index_sheet[f"B{index_row}"] = f'=HYPERLINK("#{sheet_name}!A1", "{filename}")'
                index_sheet[f"B{index_row}"].font = link_font
                
                index_row += 1
    
    # Adjust column widths for index
    index_sheet.column_dimensions["A"].width = 20
    index_sheet.column_dimensions["B"].width = 50
    
    # Create data sheets (one per file)
    for filename in sorted(file_data.keys()):
        # Sanitize sheet name (max 31 chars, no special chars)
        sheet_name = filename[:31].replace("/", "_").replace("\\", "_").replace("*", "_").replace("?", "_").replace("[", "_").replace("]", "_")
        
        data_sheet = wb.create_sheet(sheet_name)

        headers = [
            "File Name",
            "Pattern",
            "Frequency",
            "CPE Count",
            "Prevalence",
            "Sample Log Lines",
        ]
        for col_idx, header in enumerate(headers, start=1):
            cell = data_sheet.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        row = 2
        for domain_label in sorted(file_data[filename].keys()):
            patterns = file_data[filename][domain_label]

            sorted_patterns = sorted(
                patterns.items(),
                key=lambda x: x[1]["occurrence_count"],
                reverse=True,
            )

            for template, data in sorted_patterns:
                cpe_count = len(data["cpe_details"])
                prevalence_f = cpe_count / total_cpes if total_cpes else 0.0
                if min_prevalence is not None and prevalence_f < min_prevalence:
                    continue

                cpe_count_str = f"{cpe_count}/{total_cpes}"
                sample_logs_str = "\n".join(data["sample_logs"][:3])

                if prevalence_f >= 0.5:
                    high_prevalence_rows.append({
                        "domain": domain_label,
                        "filename": filename,
                        "template": clean_for_excel(str(template)),
                        "frequency": data["occurrence_count"],
                        "cpe_count_str": cpe_count_str,
                        "prevalence": prevalence_f,
                        "samples": clean_for_excel(sample_logs_str),
                    })

                data_sheet.cell(row=row, column=1, value=clean_for_excel(filename))
                data_sheet.cell(row=row, column=2, value=clean_for_excel(template))
                data_sheet.cell(row=row, column=3, value=data["occurrence_count"])
                data_sheet.cell(row=row, column=4, value=cpe_count_str)
                prev_cell = data_sheet.cell(row=row, column=5, value=prevalence_f)
                prev_cell.number_format = "0.00%"
                data_sheet.cell(row=row, column=6, value=clean_for_excel(sample_logs_str))
                data_sheet.cell(row=row, column=6).alignment = Alignment(
                    wrap_text=True, vertical="top"
                )

                row += 1

        data_sheet.column_dimensions["A"].width = 30
        data_sheet.column_dimensions["B"].width = 80
        data_sheet.column_dimensions["C"].width = 12
        data_sheet.column_dimensions["D"].width = 12
        data_sheet.column_dimensions["E"].width = 14
        data_sheet.column_dimensions["F"].width = 100

        data_sheet.freeze_panes = "A2"
        last_row = max(1, row - 1)
        data_sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"

    if include_prevalence_sheet and high_prevalence_rows:
        ps = wb.create_sheet("Prevalence_ge_50pct")
        ph = [
            "Domain",
            "File Name",
            "Pattern",
            "Frequency",
            "CPE Count",
            "Prevalence",
            "Sample Log Lines",
        ]
        for col_idx, header in enumerate(ph, start=1):
            c = ps.cell(row=1, column=col_idx, value=header)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
        high_prevalence_rows.sort(key=lambda r: (-r["prevalence"], -r["frequency"]))
        pr = 2
        for rec in high_prevalence_rows:
            ps.cell(row=pr, column=1, value=rec["domain"])
            ps.cell(row=pr, column=2, value=rec["filename"])
            ps.cell(row=pr, column=3, value=rec["template"])
            ps.cell(row=pr, column=4, value=rec["frequency"])
            ps.cell(row=pr, column=5, value=rec["cpe_count_str"])
            pc = ps.cell(row=pr, column=6, value=rec["prevalence"])
            pc.number_format = "0.00%"
            ps.cell(row=pr, column=7, value=rec["samples"])
            ps.cell(row=pr, column=7).alignment = Alignment(wrap_text=True, vertical="top")
            pr += 1
        for col, w in zip("ABCDEFG", (14, 28, 60, 12, 12, 14, 100)):
            ps.column_dimensions[col].width = w
        ps.freeze_panes = "A2"
        ps.auto_filter.ref = f"A1:{get_column_letter(len(ph))}{max(1, pr - 1)}"
    
    # Save to BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    # Generate filename in format: project_name-patterns-YYYYMMDD.xlsx
    timestamp = datetime.now().strftime("%Y%m%d")
    # Sanitize project name for filename (replace spaces and special chars)
    safe_project_name = re.sub(r'[^\w\-]', '_', project.name)
    filename = f"{safe_project_name}-patterns-{timestamp}.xlsx"
    
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


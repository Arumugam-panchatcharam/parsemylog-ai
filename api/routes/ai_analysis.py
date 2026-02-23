"""
AI Analysis API Routes
=======================

Endpoints for semantic search and log context viewing.
Embedding model is lazy-loaded on first use.
"""

import logging
from pathlib import Path

import pandas as pd
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm, get_embedding_model
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY, LINES_PER_PAGE, QDRANT_URL
from logai.embedding import quick_search
from logai.pattern import extract_parameters

logger = logging.getLogger(__name__)

ai_bp = Blueprint("ai_analysis", __name__)


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


# ---------- Semantic Search ----------

@ai_bp.route("/<project_id>/ai/search", methods=["POST"])
@jwt_required()
def ai_search(project_id):
    """
    Semantic search against the Qdrant vector store.

    Body: { "query": str, "top_k"?: int }
    Returns: { "results": [ { "filename", "template", "frequency", "similarity", "domain", "parquet_path" } ] }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    top_k = data.get("top_k", 10)
    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")

    if not query:
        return jsonify({"error": "Query is required"}), 400

    # Lazy-load embedding model
    try:
        model = get_embedding_model()
    except Exception as e:
        logger.error(f"[AI Search] Failed to load embedding model: {e}")
        return jsonify({"error": "Embedding model not available"}), 503

    # STRATEGY: Single collection per project with CPE metadata filtering
    # The indexer stores all CPEs in project_{id} with cpe_serial metadata
    collection_name = f"project_{project_id}"
    
    # Build metadata filter if searching within a specific CPE
    metadata_filter = None
    if cpe_id:
        metadata_filter = {"cpe_serial": cpe_id}
    
    logger.info(f"[AI Search] query='{query}', collection='{collection_name}', cpe_filter={cpe_id or 'all'}")

    try:
        embedding_results = quick_search(
            query=query,
            collection=collection_name,
            model=model,
            qdrant_url=QDRANT_URL,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )
    except Exception as e:
        err_str = str(e)
        logger.error(f"[AI Search] Qdrant error: {err_str}")
        if "doesn't exist" in err_str or "Not found" in err_str:
            return jsonify({
                "results": [],
                "error": f"Vector index not yet built for this CPE. "
                         f"Please wait for background indexing to complete, "
                         f"then try again.",
            }), 200
        return jsonify({"error": f"Search failed: {err_str}"}), 500

    if not embedding_results:
        return jsonify({"results": [], "message": "No similar templates found"}), 200

    # Build UUID -> original_name lookup
    uuid_to_original = {}
    try:
        files = dbm.get_project_files(project_id)
        for fname, fpath, orig_name, fsize, _ in files:
            uuid_to_original[fname] = orig_name
            uuid_to_original[Path(fname).stem] = orig_name
    except Exception as e:
        logger.warning(f"[AI Search] Could not build filename map: {e}")

    results = []
    for r in embedding_results:
        raw_filename = r.get("filename", "-")
        display_name = uuid_to_original.get(
            raw_filename,
            uuid_to_original.get(Path(raw_filename).stem, raw_filename),
        )
        results.append({
            "filename": display_name,
            "template": r.get("template", ""),
            "frequency": r.get("count", r.get("frequency", 0)),
            "similarity": round(r.get("similarity", 0.0), 4),
            "domain": r.get("domain", ""),
            "parquet_path": r.get("parquet_path", ""),
        })

    return jsonify({"results": results}), 200


# ---------- Log Context ----------

@ai_bp.route("/<project_id>/ai/context", methods=["POST"])
@jwt_required()
def ai_context(project_id):
    """
    Get log context window around a timestamp.

    Body: {
        "template": str,
        "timestamp": str,
        "window": int,
        "unit": "seconds" | "minutes",
        "filename"?: str,
        "parquet_path"?: str
    }
    Returns: { "lines": [ { "timestamp", "loglines", "is_match" } ] }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    template = data.get("template", "")
    timestamp_str = data.get("timestamp", "")
    window = data.get("window", 5)
    unit = data.get("unit", "seconds")
    filename = data.get("filename")
    parquet_path = data.get("parquet_path")
    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")

    if not template or not timestamp_str:
        return jsonify({"error": "template and timestamp are required"}), 400

    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir

    # Resolve parquet
    pq = Path(parquet_path) if parquet_path else None
    if pq is None or not pq.exists():
        # Try DB lookup
        if filename:
            try:
                file_info = dbm.get_project_file_info_orig_name(project_id, filename)
                if file_info:
                    _, filepath, _, _, _ = file_info
                    candidate = Path(str(filepath) + ".parquet")
                    if candidate.exists():
                        pq = candidate
            except Exception:
                pass
        # Fallback: domain parquets
        if pq is None or not pq.exists():
            for domain_pq in project_dir.glob("*_rg.parquet"):
                pq = domain_pq
                break

    if pq is None or not pq.exists():
        return jsonify({"error": "No parquet data available"}), 404

    try:
        df = pd.read_parquet(pq).reset_index(drop=True)
        if "timestamp" not in df.columns:
            return jsonify({"error": "No timestamp data in parquet"}), 400

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        ts = pd.to_datetime(timestamp_str)

        if unit == "seconds":
            delta = pd.Timedelta(seconds=window)
        else:
            delta = pd.Timedelta(minutes=window)

        context = df[(df["timestamp"] >= ts - delta) & (df["timestamp"] <= ts + delta)]

        lines = []
        for _, row in context.iterrows():
            is_match = row.get("template") == template
            lines.append({
                "timestamp": str(row["timestamp"]),
                "loglines": str(row.get("loglines", "")),
                "is_match": is_match,
            })

        return jsonify({"lines": lines, "total": len(lines)}), 200

    except Exception as e:
        logger.error(f"[AI Context] Error: {e}")
        return jsonify({"error": str(e)}), 500


# ---------- Template Parameters ----------

@ai_bp.route("/<project_id>/ai/parameters", methods=["POST"])
@jwt_required()
def ai_parameters(project_id):
    """
    Extract parameters for a template from AI search results.

    Body: { "template": str, "parquet_path"?: str, "domain"?: str }
    Returns: { "parameters": [...] }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    template = data.get("template", "")
    parquet_path = data.get("parquet_path")
    domain = data.get("domain")
    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")

    if not template:
        return jsonify({"error": "template is required"}), 400

    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir

    # Resolve parquet
    pq = Path(parquet_path) if parquet_path else None
    if pq is None or not pq.exists():
        if domain:
            pq = project_dir / f"{domain}_rg.parquet"
        else:
            for domain_pq in project_dir.glob("*_rg.parquet"):
                pq = domain_pq
                break

    if pq is None or not pq.exists():
        return jsonify({"parameters": []}), 200

    try:
        df = pd.read_parquet(pq).reset_index(drop=True)
        matching = df[df["template"] == template]
        if matching.empty:
            return jsonify({"parameters": []}), 200

        if "parameter_list" in df.columns:
            parameters = matching["parameter_list"]
        else:
            loglines = matching["loglines"].tolist()
            param_values = extract_parameters(template, loglines)
            parameters = pd.Series(param_values)

        if parameters.empty:
            return jsonify({"parameters": []}), 200

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
                "values": unique_values[:100],
            })

        return jsonify({"parameters": result}), 200

    except Exception as e:
        logger.error(f"[AI Params] Error: {e}")
        return jsonify({"parameters": []}), 200


# ---------- Matching Log Lines ----------

@ai_bp.route("/<project_id>/ai/loglines", methods=["POST"])
@jwt_required()
def ai_loglines(project_id):
    """
    Get matching log lines for a template from AI search.

    Body: { "template": str, "parquet_path"?: str, "domain"?: str, "page"?: int, "page_size"?: int }
    Returns: { "lines": [...], "total": int }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    template = data.get("template", "")
    parquet_path = data.get("parquet_path")
    domain = data.get("domain")
    page = data.get("page", 1)
    page_size = data.get("page_size", 20)
    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")

    if not template:
        return jsonify({"error": "template is required"}), 400

    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir

    pq = Path(parquet_path) if parquet_path else None
    if pq is None or not pq.exists():
        if domain:
            pq = project_dir / f"{domain}_rg.parquet"
        else:
            for domain_pq in project_dir.glob("*_rg.parquet"):
                pq = domain_pq
                break

    if pq is None or not pq.exists():
        return jsonify({"lines": [], "total": 0}), 200

    try:
        df = pd.read_parquet(pq).reset_index(drop=True)
        matching = df[df["template"] == template]

        total = len(matching)
        start = (page - 1) * page_size
        end = start + page_size

        lines = []
        for _, row in matching.iloc[start:end].iterrows():
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

    except Exception as e:
        logger.error(f"[AI Loglines] Error: {e}")
        return jsonify({"lines": [], "total": 0}), 200

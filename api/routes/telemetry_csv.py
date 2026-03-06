"""
Telemetry CSV Analyzer API Routes
===================================

Standalone endpoints for CSV file upload, listing, deletion, and parsing.
Not tied to the project system — files are stored per-user under a telemetry_csv/ directory.

Uses pandas for CSV parsing with automatic compression detection (zip, gzip).
"""

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from werkzeug.utils import secure_filename

from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

telemetry_csv_bp = Blueprint("telemetry_csv", __name__)

ALLOWED_EXTENSIONS = {".csv", ".zip", ".gz"}
MAX_CSV_SIZE = 500 * 1024 * 1024  # 500 MB per file
DEFAULT_PAGE_SIZE = 500
META_FILENAME = "_meta.json"

# In-memory cache for parsed DataFrames {user_id: {filename: DataFrame}}
_dataframe_cache = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _csv_dir(user_id: int) -> Path:
    """Get the CSV storage directory for a user."""
    return Path(UPLOAD_DIRECTORY) / str(user_id) / "telemetry_csv"


def _meta_path(user_id: int) -> Path:
    """Get path to the metadata sidecar file."""
    return _csv_dir(user_id) / META_FILENAME


def _load_meta(user_id: int) -> dict:
    """Load the per-user metadata sidecar (filename -> {tags})."""
    mp = _meta_path(user_id)
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            pass
    return {}


def _save_meta(user_id: int, meta: dict):
    """Save the metadata sidecar to disk."""
    mp = _meta_path(user_id)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(meta, indent=2))


def _get_file_info(filepath: Path, meta: dict) -> dict:
    """Build metadata dict for a CSV file."""
    stat = filepath.stat()
    file_info = meta.get(filepath.name, {})
    return {
        "filename": filepath.name,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "tags": file_info.get("tags", []),
    }


def _parse_csv_file(filepath: Path, user_id: int) -> 'pd.DataFrame':
    """Parse CSV file with pandas, using cache if available."""
    import pandas as pd
    import zipfile
    import gzip
    import io
    
    cache_key = filepath.name
    if user_id not in _dataframe_cache:
        _dataframe_cache[user_id] = {}
    
    if cache_key in _dataframe_cache[user_id]:
        logger.info(f"Using cached DataFrame for {filepath.name}")
        return _dataframe_cache[user_id][cache_key]
    
    logger.info(f"Parsing CSV file: {filepath.name}")
    
    # Handle ZIP files manually to filter out macOS metadata files
    if filepath.suffix.lower() == '.zip':
        with zipfile.ZipFile(filepath, 'r') as zf:
            # Get all CSV files, excluding macOS metadata
            csv_files = [name for name in zf.namelist() 
                        if name.lower().endswith('.csv') 
                        and not name.startswith('__MACOSX')
                        and not name.startswith('.')]
            
            if not csv_files:
                raise ValueError(f"No CSV files found in ZIP archive")
            
            if len(csv_files) > 1:
                logger.warning(f"Multiple CSV files in ZIP, using first: {csv_files[0]}")
            
            # Read the first valid CSV file
            with zf.open(csv_files[0]) as csv_file:
                df = pd.read_csv(csv_file, low_memory=False)
    
    # Handle gzip files
    elif filepath.suffix.lower() == '.gz':
        with gzip.open(filepath, 'rt') as f:
            df = pd.read_csv(f, low_memory=False)
    
    # Plain CSV files
    else:
        df = pd.read_csv(filepath, low_memory=False)
    
    # Cache the DataFrame
    _dataframe_cache[user_id][cache_key] = df
    logger.info(f"Cached DataFrame with shape {df.shape}")
    
    return df


def _get_dtype_info(df: 'pd.DataFrame') -> dict:
    """Extract column data type information for frontend."""
    import pandas as pd
    import numpy as np
    
    dtype_info = {}
    for col in df.columns:
        dtype = df[col].dtype
        if pd.api.types.is_numeric_dtype(dtype):
            dtype_info[col] = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            dtype_info[col] = "datetime"
        else:
            dtype_info[col] = "string"
    
    return dtype_info


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@telemetry_csv_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_csv():
    """Upload one or more CSV files (plain or compressed)."""
    user_id = get_user_id()

    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400

    csv_dir = _csv_dir(user_id)
    csv_dir.mkdir(parents=True, exist_ok=True)

    uploaded = []
    errors = []
    
    # Load existing metadata
    meta = _load_meta(user_id)

    for f in files:
        if not f.filename:
            continue

        name = secure_filename(f.filename)
        
        # Check for allowed extensions
        has_valid_ext = False
        for ext in ALLOWED_EXTENSIONS:
            if name.lower().endswith(ext):
                has_valid_ext = True
                break
        
        if not has_valid_ext:
            errors.append(f"{f.filename}: unsupported format (only .csv, .zip, .gz)")
            continue

        dest = csv_dir / name

        # Deduplicate: add numeric suffix if file exists
        counter = 1
        base_name = dest.stem
        suffix = dest.suffix
        while dest.exists():
            dest = csv_dir / f"{base_name}_{counter}{suffix}"
            counter += 1

        f.save(str(dest))

        if dest.stat().st_size > MAX_CSV_SIZE:
            dest.unlink()
            errors.append(f"{f.filename}: exceeds {MAX_CSV_SIZE // (1024*1024)} MB limit")
            continue

        # Initialize metadata for new file
        if dest.name not in meta:
            meta[dest.name] = {"tags": []}
        
        uploaded.append(_get_file_info(dest, meta))
        logger.info(f"Uploaded CSV file: {dest.name} ({dest.stat().st_size} bytes)")

    # Save updated metadata
    _save_meta(user_id, meta)

    return jsonify({
        "uploaded": uploaded,
        "errors": errors,
    }), 200


@telemetry_csv_bp.route("/files", methods=["GET"])
@jwt_required()
def list_files():
    """List all CSV files for the current user."""
    user_id = get_user_id()
    csv_dir = _csv_dir(user_id)

    if not csv_dir.exists():
        return jsonify({"files": []}), 200

    # Load metadata
    meta = _load_meta(user_id)
    
    files = []
    for filepath in sorted(csv_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if filepath.is_file() and filepath.name != META_FILENAME:
            files.append(_get_file_info(filepath, meta))

    return jsonify({"files": files}), 200


@telemetry_csv_bp.route("/files/<filename>", methods=["DELETE"])
@jwt_required()
def delete_file(filename: str):
    """Delete a specific CSV file."""
    user_id = get_user_id()
    csv_dir = _csv_dir(user_id)
    filepath = csv_dir / secure_filename(filename)

    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": "File not found"}), 404

    # Clear from cache
    if user_id in _dataframe_cache and filename in _dataframe_cache[user_id]:
        del _dataframe_cache[user_id][filename]

    # Remove from metadata
    meta = _load_meta(user_id)
    if filename in meta:
        del meta[filename]
        _save_meta(user_id, meta)

    filepath.unlink()
    logger.info(f"Deleted CSV file: {filename}")

    return jsonify({"message": "File deleted"}), 200


@telemetry_csv_bp.route("/files/<filename>/tags", methods=["PUT"])
@jwt_required()
def update_tags(filename: str):
    """Set tags for a CSV file. Body: { "tags": ["tag1", "tag2"] }"""
    user_id = get_user_id()
    safe_name = secure_filename(filename)
    filepath = _csv_dir(user_id) / safe_name

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    data = request.get_json() or {}
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return jsonify({"error": "tags must be a list of strings"}), 400

    # Sanitize: strip whitespace, remove empties, deduplicate, limit length
    clean_tags = list(dict.fromkeys(t.strip() for t in tags if isinstance(t, str) and t.strip()))[:20]

    meta = _load_meta(user_id)
    if safe_name not in meta:
        meta[safe_name] = {}
    meta[safe_name]["tags"] = clean_tags
    _save_meta(user_id, meta)

    return jsonify({"filename": safe_name, "tags": clean_tags})


@telemetry_csv_bp.route("/files/<filename>/metadata", methods=["GET"])
@jwt_required()
def get_metadata(filename: str):
    """
    Get lightweight metadata for a CSV file without returning row data.
    
    Response:
        {
            "columns": list of column names,
            "dtypes": dict mapping column names to types (numeric/string/datetime),
            "row_count": int,
            "column_count": int,
            "unique_values": dict mapping string column names to list of unique values (capped at 50),
            "ready": boolean
        }
    """
    user_id = get_user_id()
    csv_dir = _csv_dir(user_id)
    filepath = csv_dir / secure_filename(filename)
    
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": "File not found"}), 404
    
    try:
        df = _parse_csv_file(filepath, user_id)
        
        dtypes = _get_dtype_info(df)
        
        # Get unique values for string columns (cap at 50)
        unique_values = {}
        for col, dtype in dtypes.items():
            if dtype == "string":
                try:
                    unique_vals = df[col].dropna().unique().tolist()
                    # Convert to strings and sort, then cap at 50
                    unique_vals_str = sorted([str(v) for v in unique_vals])[:50]
                    unique_values[col] = unique_vals_str
                except Exception:
                    # If there's any issue getting unique values, skip this column
                    unique_values[col] = []
        
        return jsonify({
            "columns": list(df.columns),
            "dtypes": dtypes,
            "row_count": len(df),
            "column_count": len(df.columns),
            "unique_values": unique_values,
            "ready": True,
        }), 200
        
    except Exception as exc:
        logger.error(f"Failed to get metadata for {filename}: {exc}", exc_info=True)
        return jsonify({
            "error": f"Failed to get metadata: {str(exc)}",
            "ready": False,
        }), 500


@telemetry_csv_bp.route("/series", methods=["POST"])
@jwt_required()
def get_series():
    """
    Get selected column series data for plotting.
    
    Request body:
        {
            "filename": str,
            "x_column": str,
            "y_columns": list of str,
            "max_points": int (optional, for downsampling)
        }
    
    Response:
        {
            "x": list of values,
            "series": [{"name": str, "values": list}],
            "row_count": int,
            "downsampled": boolean
        }
    """
    user_id = get_user_id()
    data = request.get_json() or {}
    
    filename = data.get("filename")
    x_column = data.get("x_column")
    y_columns = data.get("y_columns", [])
    max_points = data.get("max_points")
    
    if not filename:
        return jsonify({"error": "filename is required"}), 400
    if not x_column:
        return jsonify({"error": "x_column is required"}), 400
    if not y_columns:
        return jsonify({"error": "y_columns is required"}), 400
    
    csv_dir = _csv_dir(user_id)
    filepath = csv_dir / secure_filename(filename)
    
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": "File not found"}), 404
    
    try:
        df = _parse_csv_file(filepath, user_id)
        
        # Validate columns exist
        if x_column not in df.columns:
            return jsonify({"error": f"Column '{x_column}' not found"}), 400
        
        missing_cols = [col for col in y_columns if col not in df.columns]
        if missing_cols:
            return jsonify({"error": f"Columns not found: {', '.join(missing_cols)}"}), 400
        
        # Extract required columns
        selected_cols = [x_column] + y_columns
        subset_df = df[selected_cols].copy()
        
        # Downsample if needed
        row_count = len(subset_df)
        downsampled = False
        
        if max_points and row_count > max_points:
            # Simple uniform downsampling: take every Nth row
            step = row_count // max_points
            if step > 1:
                subset_df = subset_df.iloc[::step]
                downsampled = True
                logger.info(f"Downsampled from {row_count} to {len(subset_df)} rows")
        
        # Convert to JSON-serializable format
        import math
        
        def clean_value(val):
            """Convert NaN/NaT to None for JSON serialization."""
            if isinstance(val, float) and math.isnan(val):
                return None
            if str(val) in ('nan', 'NaT'):
                return None
            return val
        
        x_values = [clean_value(v) for v in subset_df[x_column].tolist()]
        
        series = []
        for y_col in y_columns:
            series.append({
                "name": y_col,
                "values": [clean_value(v) for v in subset_df[y_col].tolist()],
            })
        
        return jsonify({
            "x": x_values,
            "series": series,
            "row_count": len(subset_df),
            "downsampled": downsampled,
        }), 200
        
    except Exception as exc:
        logger.error(f"Failed to get series data for {filename}: {exc}", exc_info=True)
        return jsonify({"error": f"Failed to get series data: {str(exc)}"}), 500


@telemetry_csv_bp.route("/parse", methods=["POST"])
@jwt_required()
def parse_csv():
    """
    DEPRECATED: Use /metadata and /series endpoints instead for better performance.
    
    Parse a CSV file and return paginated data with column metadata.
    
    Request body:
        {
            "filename": str,
            "page": int (optional, default 1),
            "page_size": int (optional, default 500)
        }
    
    Response:
        {
            "columns": list of column names,
            "rows": list of row dicts,
            "total_rows": int,
            "total_columns": int,
            "dtypes": dict mapping column names to types (numeric/string/datetime),
            "page": current page number,
            "page_size": rows per page,
            "has_more": boolean
        }
    """
    user_id = get_user_id()
    data = request.get_json() or {}
    
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "filename is required"}), 400
    
    page = data.get("page", 1)
    page_size = data.get("page_size", DEFAULT_PAGE_SIZE)
    
    csv_dir = _csv_dir(user_id)
    filepath = csv_dir / secure_filename(filename)
    
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": "File not found"}), 404
    
    try:
        df = _parse_csv_file(filepath, user_id)
        
        total_rows = len(df)
        total_columns = len(df.columns)
        
        # Calculate pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        
        # Get page of data
        page_df = df.iloc[start_idx:end_idx]
        
        # Convert to list of dicts, handling NaN values
        rows = []
        for _, row in page_df.iterrows():
            row_dict = {}
            for col in df.columns:
                val = row[col]
                # Convert NaN/NaT to None for JSON serialization
                if isinstance(val, float):
                    import math
                    if math.isnan(val):
                        row_dict[col] = None
                    else:
                        row_dict[col] = val
                else:
                    row_dict[col] = None if str(val) == 'nan' or str(val) == 'NaT' else str(val)
            rows.append(row_dict)
        
        return jsonify({
            "columns": list(df.columns),
            "rows": rows,
            "total_rows": total_rows,
            "total_columns": total_columns,
            "dtypes": _get_dtype_info(df),
            "page": page,
            "page_size": page_size,
            "has_more": end_idx < total_rows,
        }), 200
        
    except Exception as exc:
        logger.error(f"Failed to parse CSV {filename}: {exc}", exc_info=True)
        return jsonify({"error": f"Failed to parse CSV: {str(exc)}"}), 500

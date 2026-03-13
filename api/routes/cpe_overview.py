"""
CPE Overview API Routes
========================

Endpoint that aggregates summary data across ALL CPEs in a project
for side-by-side comparison: device info, key metrics, reboot history,
pattern summary per domain, and log file statistics.
"""

import json
import logging
import re
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from flask import Blueprint, jsonify, send_file, request
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

cpe_overview_bp = Blueprint("cpe_overview", __name__)

# Core domains (same as patterns.py)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _find_telemetry_file(project_dir: Path) -> Optional[Path]:
    """Find telemetry2_0 file in project directory."""
    if project_dir.exists():
        for f in project_dir.iterdir():
            if f.is_file() and f.name.lower().startswith("telemetry2_0"):
                return f
    return None


def _find_dcmscript_file(project_dir: Path) -> Optional[Path]:
    """Find dcmscript.log in project directory (fallback telemetry source)."""
    if project_dir.exists():
        for f in project_dir.iterdir():
            if f.is_file() and "dcmscript" in f.name.lower() and f.name.lower().endswith(".log"):
                return f
    return None


def _collect_device_info(
    project_dir: Path,
    force: bool = False,
) -> Dict[str, Any]:
    """Parse telemetry and version.txt to collect device info and key metrics.

    When telemetry2_0 is missing or has no parsable reports, falls back to
    dcmscript.log CURL_CMD payloads, then to PARODUSlog.txt +
    telemetry_marker.txt + version.txt for device identity.
    """
    result: Dict[str, Any] = {"device_info": {}, "key_metrics": {}}

    telemetry_file = _find_telemetry_file(project_dir)
    dcmscript_file = _find_dcmscript_file(project_dir)
    telemetry_ok = False

    if telemetry_file or dcmscript_file:
        try:
            from logai.telemetry_parser import (
                parse_telemetry_file,
                extract_configured_fields,
                load_report_field_config,
            )

            primary = telemetry_file or dcmscript_file
            reports, merged, summary, _src = parse_telemetry_file(
                primary, dcmscript_path=dcmscript_file,
                cpe_dir=project_dir, force=force,
            )

            if reports and summary.get("parsed", 0) > 0:
                telemetry_ok = True

                # Device info
                device_info = summary.get("device_info", {})

                # Enrich with version.txt
                try:
                    from logai.info_extractor import find_and_parse_version_txt
                    version_info = find_and_parse_version_txt(project_dir, force=force)
                    if version_info:
                        if version_info.get("sdk_version"):
                            device_info["sdk_version"] = version_info["sdk_version"]
                        if version_info.get("sw_upgrade_detected"):
                            device_info["sw_upgrade"] = f"Yes ({version_info['sw_upgrade_detail']})"
                        else:
                            device_info["sw_upgrade"] = "No"
                except ImportError:
                    pass

                result["device_info"] = device_info

                # Key metrics
                field_config = load_report_field_config()
                configured_fields = extract_configured_fields(reports, field_config)

                result["key_metrics"] = _build_flat_metrics(configured_fields, summary)
                result["summary"] = {
                    "total_reports": summary.get("total", 0),
                    "parsed_reports": summary.get("parsed", 0),
                    "time_range": summary.get("overall_time_range", {}),
                }

        except Exception as e:
            logger.warning(f"[CPEOverview] Error collecting device info from {project_dir}: {e}")

    # Fallback: PARODUSlog + telemetry_marker + version.txt
    if not telemetry_ok:
        try:
            from logai.info_extractor import find_and_build_fallback_device_info
            fallback_info = find_and_build_fallback_device_info(project_dir, force=force)
            if fallback_info:
                result["device_info"] = fallback_info
                logger.info(
                    f"[CPEOverview] Using fallback device info for {project_dir.name}"
                )
        except Exception as e:
            logger.warning(
                f"[CPEOverview] Error collecting fallback device info "
                f"from {project_dir}: {e}"
            )

    return result


def _build_flat_metrics(
    configured_fields: Dict[str, Any],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build a flat dict of key metrics for comparison.

    Reuses the same logic as telemetry.py _build_key_metrics_data
    but returns a flat dict instead of a list of cards.
    """
    metrics: Dict[str, Any] = {}

    def _numerics(field_list, label_prefix):
        for fd in field_list:
            if fd["label"].startswith(label_prefix):
                nums = [v["numeric"] for v in fd["values"] if v["numeric"] is not None]
                return nums, fd.get("unit", "")
        return [], ""

    def _text_values(field_list, label_prefix):
        for fd in field_list:
            if fd["label"].startswith(label_prefix):
                return [v["raw"] for v in fd["values"]]
        return []

    # Reports
    metrics["reports_total"] = summary.get("total", 0)
    metrics["reports_parsed"] = summary.get("parsed", 0)

    # Memory
    mem_fields = configured_fields.get("Memory", [])
    if mem_fields:
        mem_vals, mem_unit = _numerics(mem_fields, "Memory Free")
        mem_total, _ = _numerics(mem_fields, "Memory Total")
        if mem_vals:
            metrics["memory_free_first"] = mem_vals[0]
            metrics["memory_free_last"] = mem_vals[-1]
            metrics["memory_free_min"] = min(mem_vals)
            metrics["memory_free_avg"] = round(sum(mem_vals) / len(mem_vals), 1)
            metrics["memory_total"] = mem_total[0] if mem_total else None
            metrics["memory_unit"] = mem_unit
            if mem_total and mem_total[0] and mem_total[0] > 0:
                usage_pcts = [round((mem_total[0] - mf) / mem_total[0] * 100, 1) for mf in mem_vals]
                metrics["memory_usage_pct_peak"] = max(usage_pcts)
                metrics["memory_usage_pct_avg"] = round(sum(usage_pcts) / len(usage_pcts), 1)

    # CPU
    cpu_fields = configured_fields.get("CPU", [])
    if cpu_fields:
        cpu_vals, cpu_unit = _numerics(cpu_fields, "CPU Usage")
        if cpu_vals:
            metrics["cpu_avg"] = round(sum(cpu_vals) / len(cpu_vals), 1)
            metrics["cpu_peak"] = round(max(cpu_vals), 1)
            metrics["cpu_unit"] = cpu_unit

    # System (Uptime, Process Count)
    sys_fields = configured_fields.get("System", [])
    if sys_fields:
        up_vals, up_unit = _numerics(sys_fields, "Uptime")
        if up_vals:
            resets = sum(1 for i in range(1, len(up_vals)) if up_vals[i] < up_vals[i - 1])
            metrics["uptime_first"] = up_vals[0]
            metrics["uptime_last"] = up_vals[-1]
            metrics["uptime_unit"] = up_unit
            metrics["uptime_resets"] = resets

    # DSL / WAN
    dsl_fields = configured_fields.get("DSL / WAN", [])
    if dsl_fields:
        ds_vals, ds_unit = _numerics(dsl_fields, "DSL Downstream")
        if ds_vals:
            metrics["dsl_down_min"] = min(ds_vals)
            metrics["dsl_down_max"] = max(ds_vals)
            metrics["dsl_down_unit"] = ds_unit
        us_vals, us_unit = _numerics(dsl_fields, "DSL Upstream")
        if us_vals:
            metrics["dsl_up_min"] = min(us_vals)
            metrics["dsl_up_max"] = max(us_vals)
            metrics["dsl_up_unit"] = us_unit

    # Device Info fields
    dev_fields = configured_fields.get("Device Info", [])
    if dev_fields:
        conn_vals, _ = _numerics(dev_fields, "Connected Devices")
        if conn_vals:
            metrics["connected_devices_avg"] = round(sum(conn_vals) / len(conn_vals), 1)
            metrics["connected_devices_peak"] = int(max(conn_vals))

    return metrics


def _collect_reboot_summary(project_dir: Path) -> Dict[str, Any]:
    """Collect reboot data for a CPE directory."""
    result: Dict[str, Any] = {"total": 0, "reasons": {}, "types": {"soft": 0, "hard": 0}}

    try:
        from logai.info_extractor import find_and_extract_reboots
        reboots = find_and_extract_reboots(project_dir)
        if reboots:
            result["total"] = len(reboots)
            reasons = [r.get("reason", "unknown") for r in reboots]
            result["reasons"] = dict(Counter(reasons))
            result["events"] = reboots
            
            # Count reboot types
            soft_count = sum(1 for r in reboots if r.get("reboot_type") == "soft")
            hard_count = len(reboots) - soft_count
            result["types"] = {"soft": soft_count, "hard": hard_count}
    except Exception as e:
        logger.warning(f"[CPEOverview] Error collecting reboots from {project_dir}: {e}")

    return result


def _collect_pattern_summary(project_dir: Path) -> Dict[str, Any]:
    """Collect pattern analysis summary per domain for a CPE directory."""
    pattern_summary: Dict[str, Any] = {}

    for domain in _ALL_DOMAINS:
        pq_path = project_dir / f"{domain}_rg.parquet"
        if not pq_path.exists():
            pattern_summary[domain] = {
                "label": _DOMAIN_LABELS.get(domain, domain),
                "indexed": False,
                "total_loglines": 0,
                "unique_patterns": 0,
            }
            continue

        try:
            df = pd.read_parquet(pq_path)
            total_loglines = len(df)
            unique_patterns = int(df["template"].nunique()) if "template" in df.columns else 0
            pattern_summary[domain] = {
                "label": _DOMAIN_LABELS.get(domain, domain),
                "indexed": True,
                "total_loglines": total_loglines,
                "unique_patterns": unique_patterns,
            }
        except Exception as e:
            logger.warning(f"[CPEOverview] Error reading {pq_path}: {e}")
            pattern_summary[domain] = {
                "label": _DOMAIN_LABELS.get(domain, domain),
                "indexed": False,
                "total_loglines": 0,
                "unique_patterns": 0,
            }

    return pattern_summary


def _collect_log_stats(project_dir: Path) -> Dict[str, Any]:
    """Collect basic log file statistics for a CPE directory."""
    file_count = 0
    total_size_bytes = 0

    if project_dir.exists():
        for f in project_dir.iterdir():
            if f.is_file() and not f.name.startswith("."):
                # Exclude parquet caches, drain3 state, json caches
                if f.suffix in (".parquet", ".json", ".bin"):
                    continue
                file_count += 1
                total_size_bytes += f.stat().st_size

    return {
        "file_count": file_count,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
    }


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@cpe_overview_bp.route("/<project_id>/cpe-overview", methods=["GET"])
@jwt_required()
def get_cpe_overview(project_id):
    """
    Aggregate summary data for CPEs in a project with pagination and filtering.
    
    Query Parameters:
        - page: Page number (default: 1)
        - per_page: Items per page (default: 50, max: 100)
        - sort_by: Field to sort by (serial, model, date_from, reboot_count, log_size)
        - order: Sort order (asc, desc, default: asc)
        - model: Filter by device model (exact match)
        - serial: Filter by serial (partial match)
        - status: Filter by processing status (parsed, not_parsed, failed)

    Returns:
        {
            "cpes": [...],
            "pagination": {
                "page": 1,
                "per_page": 50,
                "total_items": 471,
                "total_pages": 10,
                "has_next": true,
                "has_prev": false
            }
        }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    # Parse query parameters
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 100)
    sort_by = request.args.get("sort_by", "serial")
    order = request.args.get("order", "asc")
    
    # Filters
    filter_model = request.args.get("model")
    filter_serial = request.args.get("serial")
    filter_status = request.args.get("status")
    force = request.args.get("force", "0") in ("1", "true")

    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")

    # Get all CPEs for this project
    cpes = dbm.list_project_cpes(project_id)

    if not cpes:
        # Legacy project (no CPEs) -- treat the base dir as a single CPE
        info = _collect_device_info(base_dir, force=force)
        reboot_summary = _collect_reboot_summary(base_dir)
        pattern_summary = _collect_pattern_summary(base_dir)
        log_stats = _collect_log_stats(base_dir)

        return jsonify({
            "cpes": [{
                "serial": "default",
                "mac": info.get("device_info", {}).get("mac", "N/A"),
                "date_from": None,
                "date_to": None,
                "device_info": info.get("device_info", {}),
                "key_metrics": info.get("key_metrics", {}),
                "summary": info.get("summary", {}),
                "reboot_summary": reboot_summary,
                "pattern_summary": pattern_summary,
                "log_stats": log_stats,
            }],
            "pagination": {
                "page": 1,
                "per_page": 1,
                "total_items": 1,
                "total_pages": 1,
                "has_next": False,
                "has_prev": False,
            }
        }), 200

    # Multi-CPE project: collect data for all CPEs
    result_cpes = []
    for cpe in cpes:
        cpe_dir = base_dir / cpe.serial
        logger.info(f"[CPEOverview] Processing CPE {cpe.serial} at {cpe_dir}")

        info = _collect_device_info(cpe_dir, force=force)
        reboot_summary = _collect_reboot_summary(cpe_dir)
        pattern_summary = _collect_pattern_summary(cpe_dir)
        log_stats = _collect_log_stats(cpe_dir)

        # Determine processing status
        status = "parsed" if info.get("summary", {}).get("parsed_reports", 0) > 0 else "not_parsed"
        
        cpe_data = {
            "serial": cpe.serial,
            "mac": cpe.mac or info.get("device_info", {}).get("mac", "N/A"),
            "model": info.get("device_info", {}).get("model", "N/A"),
            "date_from": cpe.date_from,
            "date_to": cpe.date_to,
            "device_info": info.get("device_info", {}),
            "key_metrics": info.get("key_metrics", {}),
            "summary": info.get("summary", {}),
            "reboot_summary": reboot_summary,
            "pattern_summary": pattern_summary,
            "log_stats": log_stats,
            "status": status,
            "reboot_count": reboot_summary.get("total", 0),
            "log_size_mb": log_stats.get("total_size_mb", 0),
        }
        
        result_cpes.append(cpe_data)

    # Apply filters
    filtered_cpes = result_cpes
    
    if filter_model:
        filtered_cpes = [c for c in filtered_cpes if c.get("model", "").lower() == filter_model.lower()]
    
    if filter_serial:
        filtered_cpes = [c for c in filtered_cpes if filter_serial.lower() in c.get("serial", "").lower()]
    
    if filter_status:
        filtered_cpes = [c for c in filtered_cpes if c.get("status") == filter_status]

    # Apply sorting
    reverse = (order == "desc")
    sort_key_map = {
        "serial": lambda x: x.get("serial", ""),
        "model": lambda x: x.get("model", ""),
        "date_from": lambda x: x.get("date_from") or "",
        "reboot_count": lambda x: x.get("reboot_count", 0),
        "log_size": lambda x: x.get("log_size_mb", 0),
    }
    
    if sort_by in sort_key_map:
        filtered_cpes.sort(key=sort_key_map[sort_by], reverse=reverse)

    # Calculate pagination
    total_items = len(filtered_cpes)
    total_pages = (total_items + per_page - 1) // per_page if per_page > 0 else 1
    page = max(1, min(page, total_pages))  # Clamp page to valid range
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_cpes = filtered_cpes[start_idx:end_idx]

    return jsonify({
        "cpes": paginated_cpes,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }), 200


# ---------------------------------------------------------------------------
# Pattern Analyzer Scan (cross-CPE comparison)
# ---------------------------------------------------------------------------

_PATTERN_SCAN_CACHE = ".cpe_overview_pattern_scan.json"

# Timestamp regex (same as regex_analyzer.py)
_LOG_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def _run_rg_count(rg_binary: str, regex: str, search_dir: Path) -> int:
    """Run ``rg -c`` and return total match count across all files."""
    cmd = [
        rg_binary,
        "-c",
        "-i",
        "--max-filesize", "500M",
        "--no-filename",
        "-e", regex,
        str(search_dir),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[CPEOverview] rg -c timed out for regex: {regex[:80]}")
        return 0
    except Exception as e:
        logger.warning(f"[CPEOverview] rg -c error: {e}")
        return 0

    if result.returncode not in (0, 1):
        return 0

    total = 0
    for line in result.stdout.strip().splitlines():
        # rg -c --no-filename outputs one count per file
        try:
            total += int(line.strip())
        except ValueError:
            pass
    return total


def _run_rg_count_all_cpes(
    rg_binary: str,
    regex: str,
    base_dir: Path,
    cpe_serials: List[str],
) -> Dict[str, int]:
    """Run a single ``rg -c`` over the whole project dir and attribute counts
    to individual CPEs by parsing the file paths.

    Returns a dict mapping ``serial -> total_match_count``.
    For 500 CPEs this is ~500x faster than one subprocess per CPE.
    """
    counts: Dict[str, int] = {s: 0 for s in cpe_serials}

    cmd = [
        rg_binary,
        "-c",
        "-i",
        "--max-filesize", "500M",
        "-e", regex,
        str(base_dir),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        logger.warning(f"[CPEOverview] rg -c (all CPEs) timed out for: {regex[:80]}")
        return counts
    except Exception as e:
        logger.warning(f"[CPEOverview] rg -c (all CPEs) error: {e}")
        return counts

    if result.returncode not in (0, 1):
        return counts

    base_str = str(base_dir)
    for line in result.stdout.strip().splitlines():
        # Output format: /path/to/base_dir/SERIAL/file.log:42
        sep = line.rfind(":")
        if sep == -1:
            continue
        fpath = line[:sep]
        try:
            cnt = int(line[sep + 1:])
        except ValueError:
            continue
        # Extract relative path and grab first component (the CPE serial)
        if fpath.startswith(base_str):
            rel = fpath[len(base_str):].lstrip("/\\")
            serial = rel.split("/", 1)[0].split("\\", 1)[0]
            if serial in counts:
                counts[serial] += cnt

    return counts


def _run_rg_count_all_cpes_filtered(
    rg_binary: str,
    regex: str,
    base_dir: Path,
    cpe_serials: List[str],
    maintenance_window: Optional[Dict[str, str]] = None,
    reboot_proximity_minutes: Optional[int] = None,
    cpe_reboots: Optional[Dict[str, List[Dict[str, str]]]] = None,
) -> Dict[str, int]:
    """Like :func:`_run_rg_count_all_cpes` but excludes matches based on
    maintenance window and/or reboot proximity.

    Uses full ``rg`` output (not ``-c``) so that timestamps can be parsed,
    while still issuing a single subprocess for all CPEs.
    """
    counts: Dict[str, int] = {s: 0 for s in cpe_serials}
    serial_set = set(cpe_serials)

    mw_start = None
    mw_end = None
    if maintenance_window:
        mw_start = datetime.strptime(maintenance_window["start"], "%H:%M").time()
        mw_end = datetime.strptime(maintenance_window["end"], "%H:%M").time()

    rp_delta = None
    if reboot_proximity_minutes and cpe_reboots:
        from datetime import timedelta
        rp_delta = timedelta(minutes=reboot_proximity_minutes)

    cmd = [
        rg_binary,
        "--no-heading",
        "--no-line-number",
        "-i",
        "--max-filesize", "500M",
        "--max-count", "1000",
        "-e", regex,
        str(base_dir),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            f"[CPEOverview] rg (filtered) timed out for: {regex[:80]}"
        )
        return counts
    except Exception as e:
        logger.warning(f"[CPEOverview] rg (filtered) error: {e}")
        return counts

    if result.returncode not in (0, 1):
        return counts

    base_str = str(base_dir)
    for line in result.stdout.splitlines():
        if not line.startswith(base_str):
            continue

        rel = line[len(base_str):].lstrip("/\\")
        serial = rel.split("/", 1)[0].split("\\", 1)[0]
        if serial not in serial_set:
            continue

        ts_match = _LOG_TS_RE.search(line)
        if not ts_match:
            counts[serial] += 1
            continue

        try:
            ts_dt = datetime.fromisoformat(ts_match.group(1))
        except ValueError:
            counts[serial] += 1
            continue

        # Maintenance window filter
        if mw_start is not None and mw_end is not None:
            match_time = ts_dt.time()
            if mw_start <= mw_end:
                if mw_start <= match_time <= mw_end:
                    continue
            else:
                if match_time >= mw_start or match_time <= mw_end:
                    continue

        # Reboot proximity filter
        if rp_delta is not None and cpe_reboots:
            reboots = cpe_reboots.get(serial, [])
            skip = False
            for r in reboots:
                try:
                    rt = datetime.fromisoformat(r["timestamp"])
                except (ValueError, KeyError):
                    continue
                if abs(ts_dt - rt) <= rp_delta:
                    skip = True
                    break
            if skip:
                continue

        counts[serial] += 1

    return counts


@cpe_overview_bp.route("/<project_id>/cpe-overview/pattern-scan", methods=["GET"])
@jwt_required()
def get_pattern_scan_cache(project_id):
    """
    Return cached pattern-analyzer scan results for the CPE overview, or
    ``{"cached": false}`` if no cache exists yet.
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    cache_path = base_dir / _PATTERN_SCAN_CACHE

    if not cache_path.exists():
        return jsonify({"cached": False}), 200

    return send_file(
        cache_path,
        mimetype="application/json",
        as_attachment=False,
    )


@cpe_overview_bp.route("/<project_id>/cpe-overview/pattern-scan", methods=["POST"])
@jwt_required()
def run_pattern_scan(project_id):
    """
    Run the project's regex patterns against every CPE and cache the result.

    For each domain / pattern / CPE the endpoint runs ``rg -c`` (count-only)
    which is very fast.  Results are written to
    ``<project_dir>/.cpe_overview_pattern_scan.json`` so subsequent page
    loads can use the GET endpoint above.

    Returns:
        {
            "cached": true,
            "scanned_at": "2026-02-12T10:30:00",
            "elapsed_ms": int,
            "domains": {
                "<domain>": {
                    "patterns": [str, ...],
                    "cpes": [{"serial": str, "counts": [int, ...]}, ...]
                }
            }
        }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    rg_binary = shutil.which("rg")
    if not rg_binary:
        return jsonify({"error": "ripgrep (rg) binary not found on server"}), 500

    # Load project patterns
    from api.routes.regex_analyzer import load_project_patterns

    all_domains = load_project_patterns(user_id, project_id)

    if not all_domains:
        return jsonify({
            "error": "No patterns configured for this project. "
                     "Add patterns on the Pattern Analyzer page first."
        }), 400

    # Resolve CPE directories
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    cpes = dbm.list_project_cpes(project_id)

    cpe_dirs: List[Dict[str, Any]] = []
    is_multi_cpe = bool(cpes)
    if cpes:
        for cpe in cpes:
            cpe_dir = base_dir / cpe.serial
            if cpe_dir.exists():
                cpe_dirs.append({"serial": cpe.serial, "dir": cpe_dir})
    else:
        cpe_dirs.append({"serial": "default", "dir": base_dir})

    if not cpe_dirs:
        return jsonify({"error": "No CPE directories found"}), 404

    cpe_serials = [c["serial"] for c in cpe_dirs]

    start_time = time.perf_counter()

    # Collect all (domain, pattern_index, pattern) tuples for parallel dispatch
    all_tasks: List[Dict[str, Any]] = []
    result_domains: Dict[str, Any] = {}

    for domain_name, patterns in all_domains.items():
        enabled = [
            p for p in patterns
            if isinstance(p, dict)
            and p.get("enabled", True)
            and p.get("regex", "").strip()
        ]
        if not enabled:
            continue

        result_domains[domain_name] = {
            "patterns": [p["name"] for p in enabled],
            "cpes": [],
        }
        for idx, pat in enumerate(enabled):
            task: Dict[str, Any] = {
                "domain": domain_name,
                "idx": idx,
                "regex": pat["regex"],
            }
            if pat.get("maintenance_window"):
                task["maintenance_window"] = pat["maintenance_window"]
            if pat.get("reboot_proximity_minutes"):
                task["reboot_proximity_minutes"] = pat["reboot_proximity_minutes"]
            all_tasks.append(task)

    # Check if any task needs timestamp-level filtering
    any_needs_filtering = any(
        t.get("maintenance_window") or t.get("reboot_proximity_minutes")
        for t in all_tasks
    )

    # Pre-load per-CPE reboots if any pattern uses reboot proximity
    any_needs_reboots = any(t.get("reboot_proximity_minutes") for t in all_tasks)
    cpe_reboots: Dict[str, List[Dict[str, str]]] = {}
    if any_needs_reboots and is_multi_cpe:
        from logai.info_extractor import find_and_extract_reboots as _extract_reboots
        for cpe_info in cpe_dirs:
            try:
                cpe_reboots[cpe_info["serial"]] = _extract_reboots(cpe_info["dir"])
            except Exception:
                cpe_reboots[cpe_info["serial"]] = []

    if is_multi_cpe and len(cpe_dirs) > 1:
        # Fast path: one rg call per pattern over the whole project dir,
        # then split counts by CPE serial from file paths.
        per_pattern_counts: Dict[str, Dict[str, int]] = {}

        def _scan_pattern(task: Dict[str, Any]) -> tuple:
            key = f"{task['domain']}::{task['idx']}"
            mw = task.get("maintenance_window")
            rp = task.get("reboot_proximity_minutes")
            if mw or rp:
                counts = _run_rg_count_all_cpes_filtered(
                    rg_binary, task["regex"], base_dir, cpe_serials,
                    maintenance_window=mw,
                    reboot_proximity_minutes=rp,
                    cpe_reboots=cpe_reboots if rp else None,
                )
            else:
                counts = _run_rg_count_all_cpes(
                    rg_binary, task["regex"], base_dir, cpe_serials,
                )
            return key, counts

        with ThreadPoolExecutor(max_workers=min(8, len(all_tasks))) as pool:
            futures = {pool.submit(_scan_pattern, t): t for t in all_tasks}
            for future in as_completed(futures):
                key, counts = future.result()
                per_pattern_counts[key] = counts

        for domain_name, dom_data in result_domains.items():
            n_patterns = len(dom_data["patterns"])
            cpe_results = []
            for serial in cpe_serials:
                counts = []
                for idx in range(n_patterns):
                    key = f"{domain_name}::{idx}"
                    counts.append(per_pattern_counts.get(key, {}).get(serial, 0))
                cpe_results.append({"serial": serial, "counts": counts})
            dom_data["cpes"] = cpe_results
    else:
        # Legacy single-CPE fallback
        for domain_name, dom_data in result_domains.items():
            cpe_info = cpe_dirs[0]
            counts = []
            for task in all_tasks:
                if task["domain"] == domain_name:
                    count = _run_rg_count(rg_binary, task["regex"], cpe_info["dir"])
                    counts.append(count)
            dom_data["cpes"] = [{"serial": cpe_info["serial"], "counts": counts}]

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)

    payload = {
        "cached": True,
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "elapsed_ms": elapsed_ms,
        "domains": result_domains,
    }

    cache_path = base_dir / _PATTERN_SCAN_CACHE
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    logger.info(
        f"[CPEOverview] Pattern scan complete for project {project_id}: "
        f"{len(result_domains)} domains, {len(cpe_dirs)} CPEs, {elapsed_ms}ms"
    )

    return jsonify(payload), 200

"""
CPE Overview API Routes
========================

Endpoint that aggregates summary data across ALL CPEs in a project
for side-by-side comparison: device info, key metrics, reboot history,
pattern summary per domain, and log file statistics.
"""

import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

cpe_overview_bp = Blueprint("cpe_overview", __name__)

# Expected domains (same as patterns.py)
_ALL_DOMAINS = ["wireless", "platform", "core_router", "cellular", "mesh"]

_DOMAIN_LABELS = {
    "wireless": "Wireless",
    "platform": "Platform",
    "core_router": "Core Router",
    "cellular": "Cellular",
    "mesh": "Mesh",
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


def _collect_device_info(project_dir: Path) -> Dict[str, Any]:
    """Parse telemetry and version.txt to collect device info and key metrics."""
    result: Dict[str, Any] = {"device_info": {}, "key_metrics": {}}

    telemetry_file = _find_telemetry_file(project_dir)
    if not telemetry_file:
        return result

    try:
        from logai.telemetry_parser import (
            parse_telemetry_file,
            extract_configured_fields,
            load_report_field_config,
        )

        reports, merged, summary = parse_telemetry_file(telemetry_file)

        if not reports or summary.get("parsed", 0) == 0:
            return result

        # Device info
        device_info = summary.get("device_info", {})

        # Enrich with version.txt
        try:
            from logai.info_extractor import find_and_parse_version_txt
            version_info = find_and_parse_version_txt(project_dir)
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

    # System Resources
    sys_fields = configured_fields.get("System Resources", [])
    if sys_fields:
        mem_vals, mem_unit = _numerics(sys_fields, "Memory Free")
        mem_total, _ = _numerics(sys_fields, "Memory Total")
        if mem_vals:
            metrics["memory_free_first"] = mem_vals[0]
            metrics["memory_free_last"] = mem_vals[-1]
            metrics["memory_total"] = mem_total[0] if mem_total else None
            metrics["memory_unit"] = mem_unit

        cpu_vals, cpu_unit = _numerics(sys_fields, "CPU Usage")
        if cpu_vals:
            metrics["cpu_avg"] = round(sum(cpu_vals) / len(cpu_vals), 1)
            metrics["cpu_peak"] = round(max(cpu_vals), 1)
            metrics["cpu_unit"] = cpu_unit

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
    result: Dict[str, Any] = {"total": 0, "reasons": {}}

    try:
        from logai.info_extractor import find_and_extract_reboots
        reboots = find_and_extract_reboots(project_dir)
        if reboots:
            result["total"] = len(reboots)
            reasons = [r.get("reason", "unknown") for r in reboots]
            result["reasons"] = dict(Counter(reasons))
            result["events"] = reboots
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
    Aggregate summary data for ALL CPEs in a project.

    Returns:
        {
            "cpes": [
                {
                    "serial": str,
                    "mac": str,
                    "date_from": str,
                    "date_to": str,
                    "device_info": {...},
                    "key_metrics": {...},
                    "reboot_summary": {"total": int, "reasons": {...}},
                    "pattern_summary": {"wireless": {...}, ...},
                    "log_stats": {"file_count": int, "total_size_mb": float}
                }
            ]
        }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")

    # Get all CPEs for this project
    cpes = dbm.list_project_cpes(project_id)

    if not cpes:
        # Legacy project (no CPEs) -- treat the base dir as a single CPE
        info = _collect_device_info(base_dir)
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
        }), 200

    # Multi-CPE project
    result_cpes = []
    for cpe in cpes:
        cpe_dir = base_dir / cpe.serial
        logger.info(f"[CPEOverview] Processing CPE {cpe.serial} at {cpe_dir}")

        info = _collect_device_info(cpe_dir)
        reboot_summary = _collect_reboot_summary(cpe_dir)
        pattern_summary = _collect_pattern_summary(cpe_dir)
        log_stats = _collect_log_stats(cpe_dir)

        result_cpes.append({
            "serial": cpe.serial,
            "mac": cpe.mac or info.get("device_info", {}).get("mac", "N/A"),
            "date_from": cpe.date_from,
            "date_to": cpe.date_to,
            "device_info": info.get("device_info", {}),
            "key_metrics": info.get("key_metrics", {}),
            "summary": info.get("summary", {}),
            "reboot_summary": reboot_summary,
            "pattern_summary": pattern_summary,
            "log_stats": log_stats,
        })

    return jsonify({"cpes": result_cpes}), 200

"""
Telemetry API Routes
=====================

Endpoints for telemetry parsing, device info, metrics, and chart data.
Parsed data is cached under ``<project_dir>/telemetry/`` so subsequent
requests are served instantly without re-parsing.
"""

import logging
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from api.reboot_bucketing import (
    bucket_reboot_events,
    aggregate_buckets,
    extract_reboot_events,
)
from logai.utils.constants import UPLOAD_DIRECTORY
from logai.telemetry_parser import (
    parse_telemetry_file,
    extract_configured_fields,
    load_report_field_config,
    discover_available_fields,
    save_telemetry_cache,
    load_telemetry_cache,
    load_available_fields_cache,
    extract_mesh_topology_timeline,
)

logger = logging.getLogger(__name__)

telemetry_bp = Blueprint("telemetry", __name__)

# Groups shown as status labels (multi-instance and single-instance)
_STATUS_LABEL_GROUPS = {
    "WiFi Radio", "WiFi SSID",
    "Cellular Backup", "SmartHome", "Deep Power Down",
    "WiFi Global", "CUJO Agent", "Airties Edge",
    "GPON", "PPP / WANoE",
}
_SKIP_CHART_GROUPS = {
    "Device Info",
    "Cellular Backup", "SmartHome", "Deep Power Down",
    "WiFi Global", "CUJO Agent", "Airties Edge",
    "GPON", "PPP / WANoE",
}


def _ts_to_str(ts: Any, fallback: str = "") -> str:
    """Convert timestamp to ISO string, handling both datetime and str."""
    if isinstance(ts, datetime):
        return ts.isoformat()
    if isinstance(ts, str):
        return ts
    return fallback


def _verify_project(project_id, user_id):
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _project_dir(user_id, project_id, cpe_id=None) -> Path:
    base = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    return base / cpe_id if cpe_id else base


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


def _auto_scale_unit(values, unit):
    """Auto-scale values to readable units."""
    if not values or not unit:
        return values, unit
    unit_lower = unit.strip().lower()
    max_val = max(abs(v) for v in values) if values else 0

    if unit_lower == "kb":
        if max_val >= 1_000_000:
            return [round(v / (1024 * 1024), 2) for v in values], "GB"
        elif max_val >= 1024:
            return [round(v / 1024, 2) for v in values], "MB"
    elif unit_lower == "b":
        if max_val >= 1_000_000_000:
            return [round(v / (1024 * 1024 * 1024), 2) for v in values], "GB"
        elif max_val >= 1_000_000:
            return [round(v / (1024 * 1024), 2) for v in values], "MB"
        elif max_val >= 1024:
            return [round(v / 1024, 2) for v in values], "KB"
    elif unit_lower in ("sec", "s"):
        if max_val >= 86400:
            return [round(v / 86400, 2) for v in values], "days"
        elif max_val >= 3600:
            return [round(v / 3600, 2) for v in values], "hours"
        elif max_val >= 120:
            return [round(v / 60, 2) for v in values], "min"
    elif unit_lower == "kbps":
        if max_val >= 1024:
            return [round(v / 1024, 2) for v in values], "Mbps"

    return values, unit


def _build_fallback_charts(marker_data):
    """
    Build chart data from marker_data (selfHeal + telemetry_marker) when
    telemetry2_0 is not present. Returns list of chart dicts in the same
    format as _build_charts_data: [{ "group": str, "traces": [...] }].
    """
    charts = []
    selfheal = marker_data.get("selfheal") or {}
    marker = marker_data.get("telemetry_marker") or {}

    # 1) CPU usage from selfHeal (timestamp_iso, cpu_usage_pct)
    cpu_samples = selfheal.get("cpu_usage_samples") or []
    if len(cpu_samples) >= 1:
        times = [s.get("timestamp_iso") or s.get("timestamp_raw") or "" for s in cpu_samples]
        values = [s.get("cpu_usage_pct", 0) for s in cpu_samples]
        if any(times):
            charts.append({
                "group": "CPU (selfHeal)",
                "traces": [{"label": "CPU usage", "unit": "%", "times": times, "values": values}],
            })

    # 2) Processor temperature from telemetry_marker
    proc_temp = marker.get("processor_temperature") or []
    if len(proc_temp) >= 1:
        times = [p.get("timestamp", "") for p in proc_temp]
        values = [p.get("value_c", 0) for p in proc_temp]
        if any(times):
            charts.append({
                "group": "Processor temperature",
                "traces": [{"label": "Temperature", "unit": "°C", "times": times, "values": values}],
            })

    # 3) Flash usage (Used M, Free M, Percentage %)
    flash = marker.get("flash_usage") or []
    if len(flash) >= 1:
        times = [f.get("timestamp", "") for f in flash]
        traces = []
        used_vals = [f.get("Used_M") for f in flash]
        if any(v is not None for v in used_vals):
            traces.append({"label": "Used", "unit": "MB", "times": times, "values": [v if v is not None else 0 for v in used_vals]})
        free_vals = [f.get("Free_M") for f in flash]
        if any(v is not None for v in free_vals):
            traces.append({"label": "Free", "unit": "MB", "times": times, "values": [v if v is not None else 0 for v in free_vals]})
        pct_vals = [f.get("Percentage") for f in flash]
        if any(v is not None for v in pct_vals):
            traces.append({"label": "Usage", "unit": "%", "times": times, "values": [v if v is not None else 0 for v in pct_vals]})
        if traces:
            charts.append({"group": "Flash usage", "traces": traces})

    # 4) Available memory (kB; optionally scale to MB in frontend or here)
    avail_mem = marker.get("available_memory") or []
    if len(avail_mem) >= 1:
        times = [a.get("timestamp", "") for a in avail_mem]
        values_kb = [a.get("value_kB", 0) for a in avail_mem]
        if any(times):
            # Show in MB for readability
            values_mb = [round(v / 1024, 2) for v in values_kb]
            charts.append({
                "group": "Available memory",
                "traces": [{"label": "Available", "unit": "MB", "times": times, "values": values_mb}],
            })

    # 5) Process memory by feature: one trace per feature (RSS sum per timestamp)
    proc_mem = marker.get("process_memory_by_feature") or []
    if proc_mem:
        from collections import defaultdict
        # (feature_name, timestamp) -> sum of rss_kb (in case of multiple lines per ts)
        by_feature_ts = defaultdict(int)
        for item in proc_mem:
            ts = item.get("timestamp", "")
            name = item.get("feature_name", "unknown")
            entries = item.get("entries") or []
            total_rss = sum(e.get("rss_kb") or 0 for e in entries if isinstance(e, dict))
            by_feature_ts[(name, ts)] += total_rss
        # Build list of (timestamp, sum_rss) per feature, then sort by time
        by_feature = defaultdict(list)
        for (name, ts), rss in by_feature_ts.items():
            by_feature[name].append((ts, rss))

        traces = []
        for feat_name, points in by_feature.items():
            if not points:
                continue
            points.sort(key=lambda x: x[0])
            times = [p[0] for p in points]
            values = [p[1] for p in points]
            label = feat_name.replace("_Memory_usage", "").replace("_Memory_Usage", "").strip() or feat_name
            traces.append({"label": label, "unit": "KB", "times": times, "values": values})
        if traces:
            charts.append({"group": "Process memory by feature", "traces": traces})

    return charts


# ---------------------------------------------------------------------------
# Core: parse fresh, build response, cache the result
# ---------------------------------------------------------------------------

def _parse_and_build(project_dir: Path, force: bool = False):
    """
    Parse the telemetry file, build the full API response, and cache it.

    Returns (response_dict, available_fields_dict, None) on success,
    or (None, None, error_message) on failure.

    When telemetry2_0 is missing or has no parsable reports, falls back to
    dcmscript.log CURL_CMD payloads first, then to PARODUSlog.txt +
    telemetry_marker.txt + version.txt to provide at least the device
    identity information.
    """
    telemetry_file = _find_telemetry_file(project_dir)
    dcmscript_file = _find_dcmscript_file(project_dir)
    telemetry_ok = False
    reports = None
    summary = None

    if telemetry_file or dcmscript_file:
        primary = telemetry_file or dcmscript_file
        reports, _merged, summary, _src = parse_telemetry_file(
            primary, dcmscript_path=dcmscript_file,
            cpe_dir=project_dir, force=force,
        )
        if reports and summary.get("parsed", 0) > 0:
            telemetry_ok = True

    # -- Fallback: build a partial response from PARODUSlog / parodusStart-log / marker / version / selfHeal
    if not telemetry_ok:
        try:
            from logai.info_extractor import (
                find_and_build_fallback_device_info,
                find_and_parse_selfheal,
                parse_telemetry_marker_extended,
            )
            fallback_info = find_and_build_fallback_device_info(project_dir)
        except Exception:
            fallback_info = {}

        if not fallback_info:
            return None, None, "No telemetry or device info found"

        # Enrich with selfHeal (IPv6, Telemetry 2.0, CPU, Mem) and telemetry_marker (temp, flash, process memory)
        marker_data = {}
        try:
            selfheal = find_and_parse_selfheal(project_dir)
            if selfheal:
                marker_data["selfheal"] = selfheal
                if selfheal.get("ipv6_present") is not None:
                    fallback_info["ipv6_support"] = "Yes" if selfheal["ipv6_present"] else "No"
                if selfheal.get("telemetry2_enabled") is not None:
                    fallback_info["telemetry2_enabled"] = "Yes" if selfheal["telemetry2_enabled"] else "No"
            marker_path = project_dir / "telemetry_marker.txt"
            if marker_path.exists() and marker_path.is_file():
                raw = marker_path.read_text(encoding="utf-8", errors="ignore")
                extended = parse_telemetry_marker_extended(raw)
                if extended:
                    marker_data["telemetry_marker"] = extended
        except Exception as e:
            logger.debug(f"[Telemetry] Fallback marker/selfheal parse: {e}")

        response = {
            "device_info": fallback_info,
            "summary": {"total": 0, "parsed": 0, "overall_time_range": {}},
            "key_metrics": [],
            "status_labels": [],
            "charts": [],
            "reboot_timeline": None,
            "mesh_topology": None,
            "available_fields": None,
            "cached": False,
        }
        if marker_data:
            response["marker_data"] = marker_data
            response["charts"] = _build_fallback_charts(marker_data)

        save_telemetry_cache(project_dir, response, {})
        return response, {}, None

    # -- Normal path: full telemetry parsing succeeded
    field_config = load_report_field_config()
    configured_fields = extract_configured_fields(reports, field_config)
    available_fields = discover_available_fields(reports, field_config)

    # Enrich device_info with version.txt
    try:
        from logai.info_extractor import find_and_parse_version_txt
        version_info = find_and_parse_version_txt(project_dir)
        if version_info:
            dev = summary.setdefault("device_info", {})
            if version_info.get("sdk_version"):
                dev["sdk_version"] = version_info["sdk_version"]
            if version_info.get("sw_upgrade_detected"):
                dev["sw_upgrade"] = f"Yes ({version_info['sw_upgrade_detail']})"
            else:
                dev["sw_upgrade"] = "No"
    except ImportError:
        pass

    # Build the full response (all values are JSON-native from here)
    device_info = summary.get("device_info", {})
    status_labels = _build_status_labels_data(configured_fields)
    charts = _build_charts_data(configured_fields)
    key_metrics = _build_key_metrics_data(configured_fields, summary)
    reboot_timeline = _build_reboot_timeline(reports, project_dir)
    mesh_topology = extract_mesh_topology_timeline(reports)

    response = {
        "device_info": device_info,
        "summary": {
            "total": summary.get("total", 0),
            "parsed": summary.get("parsed", 0),
            "overall_time_range": summary.get("overall_time_range", {}),
            "profile_stats": summary.get("profile_stats", {}),
        },
        "key_metrics": key_metrics,
        "status_labels": status_labels,
        "charts": charts,
        "reboot_timeline": reboot_timeline,
        "mesh_topology": mesh_topology,
        "available_fields": available_fields,
        "cached": False,
    }

    # Persist to cache (response + available_fields)
    save_telemetry_cache(project_dir, response, available_fields)

    return response, available_fields, None


# ---------- Parse (with cache) ----------

@telemetry_bp.route("/<project_id>/telemetry/parse", methods=["POST"])
@jwt_required()
def parse_telemetry(project_id):
    """
    Parse telemetry file and return all data.  Uses cached results when
    available; pass ``?force=1`` to re-parse from raw log.

    Returns: { "device_info", "summary", "key_metrics", "status_labels",
               "charts", "reboot_timeline", "available_fields", "cached" }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")
    force = request.args.get("force", "0") in ("1", "true")
    pdir = _project_dir(user_id, project_id, cpe_id)

    try:
        # Try cache first (unless forced re-parse)
        if not force:
            cached = load_telemetry_cache(pdir)
            if cached:
                cached["cached"] = True
                # Backfill fallback charts from marker_data if missing (e.g. cache from before charts were added)
                if cached.get("marker_data") and not cached.get("charts"):
                    cached["charts"] = _build_fallback_charts(cached["marker_data"])
                return jsonify(cached), 200

        # Parse fresh, build response, and cache
        response, _avail, error_msg = _parse_and_build(pdir, force=force)
        if response is None:
            return jsonify({"error": error_msg}), 404

        return jsonify(response), 200

    except Exception as e:
        logger.exception(f"[Telemetry] Error: {e}")
        return jsonify({"error": str(e)}), 500


# ---------- Available Fields (discovery) ----------

@telemetry_bp.route("/<project_id>/telemetry/available-fields", methods=["GET"])
@jwt_required()
def get_available_fields(project_id):
    """
    Return available (unconfigured) TR-181 fields found in the telemetry data.
    Uses cached data if present; otherwise parses fresh.

    Returns: { "configured_keys", "unconfigured": { group: [...] }, "stats" }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")
    pdir = _project_dir(user_id, project_id, cpe_id)

    try:
        avail = load_available_fields_cache(pdir)
        if avail:
            return jsonify(avail), 200

        # Parse fresh
        _response, available_fields, error_msg = _parse_and_build(pdir)
        if available_fields is None:
            return jsonify({"error": error_msg}), 404

        return jsonify(available_fields), 200

    except Exception as e:
        logger.exception(f"[Telemetry] Error: {e}")
        return jsonify({"error": str(e)}), 500


def _build_reboot_timeline(reports, project_dir=None):
    """
    Detect reboots from uptime drops and BootTime.log, return timeline data for charting.
    
    Returns reboot events from two sources:
    - B (BootTime): Actual reboot start time from BootTime.log (more accurate)
    - TR (Telemetry): When telemetry services came back online (uptime drop detection)
    
    Args:
        reports: List of telemetry reports
        project_dir: Path to project directory (optional, for BootTime.log access)
    """
    ok_reports = [r for r in reports if r.get("parse_ok") and r.get("time")]
    ok_reports.sort(key=lambda x: x["time"])

    uptime_key = "Device.DeviceInfo.UpTime"
    times = []
    reboot_counts = []  # cumulative reboot count at each timestamp
    reboot_events_telemetry = []  # telemetry-based reboot events (TR)
    cumulative = 0
    prev_uptime = None

    # Detect reboots from uptime drops (TR - Telemetry)
    for r in ok_reports:
        raw = r["fields"].get(uptime_key)
        if raw is None:
            continue
        # Resolve semicolons (take first sample)
        val_str = str(raw).split(";")[0].strip()
        try:
            uptime = float(val_str)
        except (ValueError, TypeError):
            continue

        ts = _ts_to_str(r["time"])

        if prev_uptime is not None and uptime < prev_uptime:
            cumulative += 1
            reboot_events_telemetry.append({
                "time": ts,
                "count": cumulative,
                "prev_uptime": prev_uptime,
                "new_uptime": uptime,
                "source": "telemetry",
                "label": "TR"
            })

        times.append(ts)
        reboot_counts.append(cumulative)
        prev_uptime = uptime

    # Get reboots from BootTime.log (B - BootTime) if available
    reboot_events_boottime = []
    boottime_reboots = []
    if project_dir:
        try:
            from logai.info_extractor import find_and_extract_reboots
            boottime_reboots = find_and_extract_reboots(project_dir)
            for idx, reboot in enumerate(boottime_reboots, start=1):
                reboot_events_boottime.append({
                    "time": reboot.get("timestamp", ""),
                    "reason": reboot.get("reason", "unknown"),
                    "reboot_type": reboot.get("reboot_type", "unknown"),
                    "source": "boottime",
                    "label": "B"
                })
        except Exception as e:
            logger.debug(f"[Telemetry] Could not load BootTime.log reboots: {e}")

    # Cross-reference telemetry-detected reboots with BootTime.log to add reboot_type
    # Match timestamps within ±30 minutes tolerance
    from datetime import datetime, timedelta
    REBOOT_MATCH_TOLERANCE = timedelta(minutes=30)
    
    for tr_event in reboot_events_telemetry:
        tr_event["reboot_type"] = None  # Default to None (unknown)
        
        try:
            tr_time = datetime.fromisoformat(tr_event["time"])
            
            # Find matching BootTime.log reboot
            for bt_reboot in boottime_reboots:
                try:
                    bt_time = datetime.fromisoformat(bt_reboot.get("timestamp", ""))
                    time_diff = abs(tr_time - bt_time)
                    
                    if time_diff <= REBOOT_MATCH_TOLERANCE:
                        tr_event["reboot_type"] = bt_reboot.get("reboot_type")
                        break
                except (ValueError, TypeError):
                    continue
        except (ValueError, TypeError):
            pass

    # Combine all reboot events
    all_events = reboot_events_boottime + reboot_events_telemetry
    all_events.sort(key=lambda e: e["time"])

    return {
        "times": times,
        "counts": reboot_counts,
        "total_reboots": cumulative,
        "events": reboot_events_telemetry,  # Now includes reboot_type when matched
        "boottime_events": reboot_events_boottime,  # BootTime.log based reboots
        "all_events": all_events,  # Combined list for comprehensive view
    }


def _build_status_labels_data(configured_fields):
    """Build status label cards for all status-label groups.

    Handles two layouts:
      * **Multi-instance** (WiFi Radio, WiFi SSID): fields contain numbered
        instances (Radio 1, SSID 2, …).  One card per instance.
      * **Single-instance** (Cellular Backup, SmartHome, …): all fields
        belong to a single logical entity.  One card per group.
    """
    import re
    labels = []

    # Multi-instance groups (contain numbered instances in field labels)
    _MULTI_INSTANCE_GROUPS = {"WiFi Radio", "WiFi SSID"}

    for group_label, field_list in configured_fields.items():
        if group_label not in _STATUS_LABEL_GROUPS:
            continue

        if group_label in _MULTI_INSTANCE_GROUPS:
            # ---- Multi-instance (Radio / SSID) ----
            is_radio = "Radio" in group_label
            type_label = "Radio" if is_radio else "SSID"

            instances = {}
            for fd in field_list:
                label = fd["label"]
                ftype = fd.get("type", "")
                latest = str(fd.get("latest", "N/A"))
                m = re.search(r"(\d+)", label)
                inst_id = m.group(1) if m else "0"
                if inst_id not in instances:
                    instances[inst_id] = {"status": None, "enable": None, "meta": {}}
                if ftype == "status":
                    instances[inst_id]["status"] = latest
                elif ftype == "bool":
                    instances[inst_id]["enable"] = latest
                else:
                    short = re.sub(r"(Radio|SSID)\s*\d+\s*", "", label).strip()
                    if short:
                        instances[inst_id]["meta"][short] = latest

            for inst_id in sorted(instances.keys()):
                data = instances[inst_id]
                status_val = data["status"] or data["enable"] or "N/A"
                labels.append({
                    "type": type_label,
                    "instance": inst_id,
                    "status": status_val,
                    "meta": data["meta"],
                })
        else:
            # ---- Single-instance group (one card per group) ----
            status_val = None
            meta = {}
            for fd in field_list:
                ftype = fd.get("type", "")
                latest = str(fd.get("latest", "N/A"))
                if ftype in ("status", "bool") and status_val is None:
                    status_val = latest
                else:
                    meta[fd["label"]] = latest

            labels.append({
                "type": group_label,
                "instance": "",
                "status": status_val or "N/A",
                "meta": meta,
            })

    return labels


_CHART_GROUP_ORDER = [
    "Memory",
    "CPU",
    "DSL / WAN",
    "WAN Traffic",
    "WiFi Radio Channel",
    "WiFi Radio Noise",
    "WiFi Radio Utilization",
    "WiFi SSID",
]


def _build_charts_data(configured_fields):
    """Build chart data for plottable fields (JSON, not rendered)."""
    charts_by_group = {}
    for group_label, field_list in configured_fields.items():
        if group_label in _SKIP_CHART_GROUPS:
            continue
        plottable = [fd for fd in field_list if fd.get("plot") and len(fd["values"]) >= 2]
        if not plottable:
            continue

        traces = []
        for fd in plottable:
            times = [v["time"] for v in fd["values"] if v["numeric"] is not None]
            values = [v["numeric"] for v in fd["values"] if v["numeric"] is not None]
            if len(times) < 2:
                continue
            raw_unit = fd.get("unit", "")
            scaled_values, display_unit = _auto_scale_unit(values, raw_unit)
            traces.append({
                "label": fd["label"],
                "unit": display_unit,
                "times": times,
                "values": scaled_values,
                "raw_unit": raw_unit,
            })

        # Special handling for Memory group: normalize time-based traces to memory scale
        if group_label == "Memory" and traces:
            # Identify memory traces (KB/MB/GB) and time traces (sec/min/hours/days)
            memory_traces = []
            time_traces = []
            for trace in traces:
                unit_lower = trace["unit"].strip().lower()
                if unit_lower in ("kb", "mb", "gb"):
                    memory_traces.append(trace)
                elif unit_lower in ("sec", "min", "hours", "days", "s"):
                    time_traces.append(trace)
            
            # If we have both memory and time traces, normalize time traces
            if memory_traces and time_traces:
                # Get min/max range of memory values
                all_mem_vals = []
                for mt in memory_traces:
                    all_mem_vals.extend(mt["values"])
                
                if all_mem_vals:
                    mem_min = min(all_mem_vals)
                    mem_max = max(all_mem_vals)
                    mem_range = mem_max - mem_min if mem_max != mem_min else 1.0
                    
                    # Normalize each time trace
                    for tt in time_traces:
                        if tt["values"]:
                            time_min = min(tt["values"])
                            time_max = max(tt["values"])
                            time_range = time_max - time_min if time_max != time_min else 1.0
                            
                            # Store pre-normalization values and display unit for hover
                            tt["raw_values"] = tt["values"][:]
                            tt["raw_unit_original"] = tt["unit"]
                            
                            # Normalize: map time range to memory range
                            normalized = []
                            for v in tt["values"]:
                                norm_0_1 = (v - time_min) / time_range
                                norm_mem = mem_min + (norm_0_1 * mem_range)
                                normalized.append(round(norm_mem, 2))
                            
                            tt["values"] = normalized
                            tt["unit"] = memory_traces[0]["unit"]  # Use same unit as memory
                            tt["normalized"] = True

        if traces:
            charts_by_group[group_label] = {
                "group": group_label,
                "traces": traces,
            }

    ordered = []
    for name in _CHART_GROUP_ORDER:
        if name in charts_by_group:
            ordered.append(charts_by_group.pop(name))
    for chart in charts_by_group.values():
        ordered.append(chart)

    return ordered


def _build_key_metrics_data(configured_fields, summary):
    """Build key metrics as JSON data."""
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

    metrics = []

    # Reports
    total = summary.get("total", 0)
    parsed = summary.get("parsed", 0)
    tr = summary.get("overall_time_range", {})
    time_range = ""
    if tr.get("first") and tr.get("last"):
        time_range = f"{tr['first'][:16]} to {tr['last'][:16]}"
    metrics.append({"label": "Reports", "value": f"{parsed}/{total}", "time_range": time_range, "icon": "chart-bar"})

    # Memory
    mem_fields = configured_fields.get("Memory", [])
    if mem_fields:
        mem_vals, mem_unit = _numerics(mem_fields, "Memory Free")
        mem_total, _ = _numerics(mem_fields, "Memory Total")
        if mem_vals:
            trend = "stable"
            if len(mem_vals) >= 2 and mem_vals[-1] < mem_vals[0] * 0.85:
                trend = "decreasing"
            elif len(mem_vals) >= 2 and mem_vals[-1] > mem_vals[0] * 1.15:
                trend = "increasing"
            metrics.append({
                "label": "Memory Free",
                "first": mem_vals[0], "last": mem_vals[-1],
                "total": mem_total[0] if mem_total else None,
                "unit": mem_unit, "trend": trend, "icon": "memory",
            })

    # CPU
    cpu_fields = configured_fields.get("CPU", [])
    if cpu_fields:
        cpu_vals, cpu_unit = _numerics(cpu_fields, "CPU Usage")
        if cpu_vals:
            metrics.append({
                "label": "CPU Usage",
                "avg": round(sum(cpu_vals) / len(cpu_vals), 1),
                "peak": round(max(cpu_vals), 1),
                "unit": cpu_unit, "icon": "microchip",
            })

    # System (Uptime, Process Count)
    sys_fields = configured_fields.get("System", [])
    if sys_fields:
        up_vals, up_unit = _numerics(sys_fields, "Uptime")
        if up_vals:
            resets = sum(1 for i in range(1, len(up_vals)) if up_vals[i] < up_vals[i - 1])
            metrics.append({
                "label": "Uptime",
                "first": up_vals[0], "last": up_vals[-1],
                "unit": up_unit, "resets": resets, "icon": "clock",
            })

    # DSL / WAN
    dsl_fields = configured_fields.get("DSL / WAN", [])
    if dsl_fields:
        ds_vals, ds_unit = _numerics(dsl_fields, "DSL Downstream")
        if ds_vals:
            metrics.append({
                "label": "DSL Downstream",
                "min": min(ds_vals), "max": max(ds_vals),
                "unit": ds_unit, "icon": "arrow-down",
            })
        us_vals, us_unit = _numerics(dsl_fields, "DSL Upstream")
        if us_vals:
            metrics.append({
                "label": "DSL Upstream",
                "min": min(us_vals), "max": max(us_vals),
                "unit": us_unit, "icon": "arrow-up",
            })

    # Reboot reasons
    dev_fields = configured_fields.get("Device Info", [])
    if dev_fields:
        reasons = _text_values(dev_fields, "Reboot Reason")
        if reasons:
            from collections import Counter
            metrics.append({
                "label": "Reboot Reasons",
                "counts": dict(Counter(reasons)),
                "icon": "redo",
            })
        conn_vals, _ = _numerics(dev_fields, "Connected Devices")
        if conn_vals:
            metrics.append({
                "label": "Connected Devices",
                "avg": round(sum(conn_vals) / len(conn_vals), 1),
                "peak": int(max(conn_vals)),
                "icon": "laptop",
            })

    return metrics


# ---------------------------------------------------------------------------
# Cross-CPE Overview
# ---------------------------------------------------------------------------

def _compute_reboot_analytics(cpe_results):
    """
    Compute reboot analytics bucketed by time-of-day and uptime categories.
    
    Args:
        cpe_results: List of CPE entries with reboot_timeline_data
    
    Returns:
        Dict with time_of_day_buckets, uptime_buckets, and total_reboot_events
    """
    all_time_of_day_buckets = []
    all_uptime_buckets = []
    
    for cpe in cpe_results:
        reboot_timeline = cpe.get("reboot_timeline_data")
        if not reboot_timeline:
            continue
        
        # Extract reboot events from timeline
        reboot_events = extract_reboot_events(reboot_timeline)
        if not reboot_events:
            continue
        
        # Prepare CPE info for device details
        cpe_info = {
            "serial": cpe.get("serial", "unknown"),
            "model": cpe.get("model", "N/A"),
        }
        
        # Bucket this CPE's reboot events
        time_buckets, uptime_buckets = bucket_reboot_events(reboot_events, cpe_info)
        all_time_of_day_buckets.append(time_buckets)
        all_uptime_buckets.append(uptime_buckets)
    
    # Aggregate all CPE buckets into fleet-wide analytics
    try:
        analytics = aggregate_buckets(all_time_of_day_buckets, all_uptime_buckets)
        return analytics
    except Exception as e:
        logger.error(f"[RebootAnalytics] Error computing analytics: {e}")
        return {
            "time_of_day_buckets": {},
            "uptime_buckets": {},
            "total_reboot_events": 0,
        }


def _analyze_reboot_correlation(cpe_results, window_minutes=10, min_cpes=2):
    """
    Analyze reboot events across CPEs to identify potential power outages.
    
    Args:
        cpe_results: List of CPE entries with reboot_events
        window_minutes: Time window in minutes for clustering (default: 10)
        min_cpes: Minimum CPEs to form a cluster (default: 2)
    
    Returns:
        Dict with clusters, statistics, and power outage indicators
    """
    from datetime import datetime, timedelta
    
    # Collect all reboot events with CPE serial
    all_events = []
    for cpe in cpe_results:
        serial = cpe.get("serial", "unknown")
        for event in cpe.get("reboot_events", []):
            try:
                timestamp_str = event.get("time")
                if not timestamp_str:
                    continue
                
                # Parse timestamp
                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                
                all_events.append({
                    "serial": serial,
                    "timestamp": timestamp_str,
                    "timestamp_dt": ts,
                    "reboot_type": event.get("reboot_type"),
                    "reason": event.get("reason"),
                })
            except (ValueError, AttributeError) as e:
                logger.warning(f"[RebootCorrelation] Failed to parse timestamp {timestamp_str}: {e}")
                continue
    
    # Sort events by timestamp
    all_events.sort(key=lambda x: x["timestamp_dt"])
    
    if len(all_events) < min_cpes:
        return {
            "clusters": [],
            "total_clusters": 0,
            "likely_power_outages": 0,
            "window_minutes": window_minutes,
        }
    
    # Find clusters using sliding window approach
    clusters = []
    processed_indices = set()
    
    for i, event in enumerate(all_events):
        if i in processed_indices:
            continue
        
        window_end = event["timestamp_dt"] + timedelta(minutes=window_minutes)
        cluster_events = [event]
        cluster_serials = {event["serial"]}
        cluster_indices = {i}
        
        # Find all events within the window from different CPEs
        for j in range(i + 1, len(all_events)):
            if j in processed_indices:
                continue
            
            other_event = all_events[j]
            
            # Stop if we're past the window
            if other_event["timestamp_dt"] > window_end:
                break
            
            # Only include events from different CPEs
            if other_event["serial"] not in cluster_serials:
                cluster_events.append(other_event)
                cluster_serials.add(other_event["serial"])
                cluster_indices.add(j)
        
        # Create cluster if we have enough CPEs
        if len(cluster_serials) >= min_cpes:
            # Calculate cluster statistics
            timestamps = [e["timestamp_dt"] for e in cluster_events]
            window_start = min(timestamps)
            window_end_actual = max(timestamps)
            
            # Count reboot types
            hard_count = sum(1 for e in cluster_events if e.get("reboot_type") == "hard")
            soft_count = sum(1 for e in cluster_events if e.get("reboot_type") == "soft")
            total_typed = hard_count + soft_count
            hard_percentage = (hard_count / total_typed * 100) if total_typed > 0 else 0
            
            # Determine if likely power outage
            time_span_minutes = (window_end_actual - window_start).total_seconds() / 60
            likely_power_outage = (
                hard_percentage > 50 and
                len(cluster_serials) >= 2 and
                time_span_minutes <= window_minutes
            )
            
            # Confidence level
            if len(cluster_serials) >= 3:
                confidence = "high"
            elif len(cluster_serials) == 2:
                confidence = "medium"
            else:
                confidence = "low"
            
            cluster = {
                "cluster_id": window_start.isoformat(),
                "window_start": window_start.isoformat(),
                "window_end": window_end_actual.isoformat(),
                "affected_cpes": sorted(list(cluster_serials)),
                "cpe_count": len(cluster_serials),
                "events": [
                    {
                        "serial": e["serial"],
                        "timestamp": e["timestamp"],
                        "reboot_type": e.get("reboot_type"),
                        "reason": e.get("reason"),
                    }
                    for e in cluster_events
                ],
                "likely_power_outage": likely_power_outage,
                "confidence": confidence,
                "hard_reboot_percentage": round(hard_percentage, 1),
                "time_span_minutes": round(time_span_minutes, 2),
            }
            
            clusters.append(cluster)
            processed_indices.update(cluster_indices)
    
    # Calculate summary statistics
    likely_power_outages = sum(1 for c in clusters if c["likely_power_outage"])
    
    return {
        "clusters": clusters,
        "total_clusters": len(clusters),
        "likely_power_outages": likely_power_outages,
        "window_minutes": window_minutes,
    }


@telemetry_bp.route("/<project_id>/telemetry/cross-cpe-overview", methods=["GET"])
@jwt_required()
def cross_cpe_overview(project_id):
    """
    Aggregate memory health and reboot data across ALL CPEs in a project.

    Query params:
        force (optional): Set to "1" or "true" to force re-parse all telemetry data
        correlation_window (optional): Time window in minutes for reboot clustering (default: 10)
        min_cpes (optional): Minimum CPEs to form a cluster (default: 2)

    Returns:
        {
            "cpes": [ { serial, model, memory_free_min, memory_free_avg,
                         memory_total, memory_usage_pct_peak, reboot_count,
                         reboot_events, low_memory, status } ],
            "fleet_summary": { total, with_reboots, with_low_memory, with_both },
            "reboot_correlation": {
                "clusters": [ { cluster_id, window_start, window_end, affected_cpes,
                               cpe_count, events, likely_power_outage, confidence } ],
                "total_clusters": int,
                "likely_power_outages": int,
                "window_minutes": int
            }
        }
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    force = request.args.get("force", "0") in ("1", "true")
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    cpes = dbm.list_project_cpes(project_id)

    def _to_mb(value, unit):
        """Convert a memory value to MB for threshold comparison."""
        u = unit.lower()
        if u == "kb":
            return value / 1024
        if u == "gb":
            return value * 1024
        return value

    def _process_cpe(serial, cpe_dir):
        """Extract memory + reboot data from cached telemetry for one CPE."""
        entry = {
            "serial": serial, "model": "N/A",
            "reboot_count": 0, "reboot_events": [],
            "low_memory": False, "memory_usage_pct_peak": None,
            "status": "OK",
            "reboot_timeline_data": None,  # For bucketing analysis
        }
        # Load from cache unless force re-parse is requested
        cached = None if force else load_telemetry_cache(cpe_dir)
        if not cached:
            try:
                resp, _avail, _err = _parse_and_build(cpe_dir, force=force)
                cached = resp
            except Exception:
                cached = None
        if not cached:
            return entry

        # Device info
        dev_info = cached.get("device_info") or {}
        entry["model"] = dev_info.get("model", "N/A")

        # Memory metrics from key_metrics
        # Priority 1: Get memory total from key_metrics (always available if Memory Free exists)
        km_unit = None
        for km in cached.get("key_metrics") or []:
            if km.get("label") == "Memory Free":
                entry["memory_trend"] = km.get("trend", "stable")
                # Memory total is included in the Memory Free key metric
                if "total" in km and km["total"]:
                    entry["memory_total"] = km["total"]
                    km_unit = km.get("unit", "KB")  # Track the original unit

        # Priority 2: Read memory stats from chart traces (for memory_free values)
        # Handle various group/label naming across config versions:
        #   New config:  group="Memory"            labels: Memory Free / Memory Total / Memory Available
        #   Old config:  group="System Resources"  labels: Memory Free (only)
        #   Alt config:  group="Available memory"  labels: Available / Free
        _MEM_GROUPS = {"Memory", "System Resources", "Available memory"}
        _FREE_LABELS = {"Memory Free", "Free"}
        _TOTAL_LABELS = {"Memory Total", "Total"}
        _AVAIL_LABELS = {"Memory Available", "Available"}

        chart_unit = "KB"
        for chart in cached.get("charts") or []:
            if chart.get("group") not in _MEM_GROUPS:
                continue
            for trace in chart.get("traces") or []:
                label = trace["label"]
                vals = [v for v in trace["values"] if v is not None]
                if not vals:
                    continue
                trace_unit = trace.get("unit", "KB")
                if label in _FREE_LABELS:
                    entry["memory_free_first"] = vals[0]
                    entry["memory_free_last"] = vals[-1]
                    entry["memory_free_min"] = min(vals)
                    entry["memory_free_avg"] = round(sum(vals) / len(vals), 2)
                    chart_unit = trace_unit
                elif label in _TOTAL_LABELS:
                    entry["memory_total"] = vals[0]
                elif label in _AVAIL_LABELS:
                    entry["memory_available_min"] = min(vals)
                    entry["memory_available_avg"] = round(sum(vals) / len(vals), 2)
                    if "memory_free_min" not in entry:
                        entry["memory_free_first"] = vals[0]
                        entry["memory_free_last"] = vals[-1]
                        entry["memory_free_min"] = min(vals)
                        entry["memory_free_avg"] = round(sum(vals) / len(vals), 2)
                        chart_unit = trace_unit
        entry["memory_unit"] = chart_unit

        # Convert memory_total to match chart_unit if it came from key_metrics
        if "memory_total" in entry and km_unit and km_unit != chart_unit:
            mem_total = entry["memory_total"]
            # Convert from km_unit to chart_unit
            if km_unit == "KB" and chart_unit == "MB":
                entry["memory_total"] = round(mem_total / 1024, 2)
            elif km_unit == "KB" and chart_unit == "GB":
                entry["memory_total"] = round(mem_total / (1024 * 1024), 2)
            elif km_unit == "MB" and chart_unit == "GB":
                entry["memory_total"] = round(mem_total / 1024, 2)
            elif km_unit == "MB" and chart_unit == "KB":
                entry["memory_total"] = round(mem_total * 1024, 2)
            elif km_unit == "GB" and chart_unit == "MB":
                entry["memory_total"] = round(mem_total * 1024, 2)
            elif km_unit == "GB" and chart_unit == "KB":
                entry["memory_total"] = round(mem_total * 1024 * 1024, 2)

        # Memory usage percentage
        mem_total = entry.get("memory_total")
        mem_min = entry.get("memory_free_min")
        if mem_total and mem_total > 0 and mem_min is not None:
            entry["memory_usage_pct_peak"] = round(
                (mem_total - mem_min) / mem_total * 100, 1
            )
        else:
            entry["memory_usage_pct_peak"] = None

        # Reboot data
        rt = cached.get("reboot_timeline") or {}
        entry["reboot_count"] = rt.get("total_reboots", 0)
        entry["reboot_events"] = rt.get("events") or []
        entry["reboot_timeline_data"] = rt  # Store full timeline for bucketing
        
        # Add reboot type breakdown
        events = entry["reboot_events"]
        entry["reboot_types"] = {
            "soft": sum(1 for e in events if e.get("reboot_type") == "soft"),
            "hard": sum(1 for e in events if e.get("reboot_type") == "hard"),
        }

        # Status: memory-threshold + reboot correlation
        free_min = entry.get("memory_free_min")
        has_reboots = entry["reboot_count"] > 0
        if free_min is not None:
            free_mb = _to_mb(free_min, chart_unit)
            entry["low_memory"] = free_mb < 50
            if free_mb < 50:
                entry["status"] = "REBOOT" if has_reboots else "LOW_MEM"
            elif free_mb < 100:
                entry["status"] = "MEMLEAK"
            else:
                entry["status"] = "OK"
        else:
            entry["low_memory"] = False
            entry["status"] = "OK"

        return entry

    # Build list of (serial, cpe_dir) pairs
    cpe_list = []
    if not cpes:
        cpe_list.append(("default", base_dir))
    else:
        for cpe in cpes:
            cpe_list.append((cpe.serial, base_dir / cpe.serial))

    # Process CPEs in parallel for scalability (500+ CPEs)
    cpe_results = []
    workers = min(16, max(1, len(cpe_list)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process_cpe, s, d): s for s, d in cpe_list}
        for future in as_completed(futures):
            try:
                cpe_results.append(future.result())
            except Exception as exc:
                serial = futures[future]
                logger.warning(f"[CrossCPE] Error processing {serial}: {exc}")
                cpe_results.append({
                    "serial": serial, "model": "N/A",
                    "reboot_count": 0, "reboot_events": [],
                    "low_memory": False, "memory_usage_pct_peak": None,
                    "status": "OK",
                })

    # Fleet summary
    total = len(cpe_results)
    with_reboots = sum(1 for c in cpe_results if c.get("reboot_count", 0) > 0)
    with_low_memory = sum(1 for c in cpe_results if c.get("low_memory"))
    with_both = sum(
        1 for c in cpe_results
        if c.get("reboot_count", 0) > 0 and c.get("low_memory")
    )

    # Reboot bucketing analysis (time-of-day and uptime categories)
    reboot_analytics = _compute_reboot_analytics(cpe_results)

    return jsonify({
        "cpes": cpe_results,
        "fleet_summary": {
            "total": total,
            "with_reboots": with_reboots,
            "with_low_memory": with_low_memory,
            "with_both": with_both,
        },
        "reboot_analytics": reboot_analytics,
    }), 200


# ---------- CSV Export ----------

@telemetry_bp.route("/<project_id>/telemetry/export-csv", methods=["GET"])
@jwt_required()
def export_telemetry_csv(project_id):
    """
    Export telemetry data to CSV format.
    
    Query params:
        - cpe_id: CPE identifier (required)
        - profiles: Comma-separated profile names (optional, exports all if not specified)
        - format: "combined" or "separate" (default: "combined")
    
    Returns:
        - If format=combined: Single CSV with all profiles
        - If format=separate and multiple profiles: ZIP file with one CSV per profile
        - If format=separate and single profile: Single CSV
    """
    from datetime import datetime
    from io import BytesIO, StringIO
    import zipfile
    
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err
    
    cpe_id = request.args.get("cpe_id")
    if not cpe_id:
        return jsonify({"error": "cpe_id is required"}), 400
    
    profiles_param = request.args.get("profiles", "")
    # Empty string or no parameter means export all profiles
    profile_filter = [p.strip() for p in profiles_param.split(",") if p.strip()] if profiles_param else None
    
    export_format = request.args.get("format", "combined").lower()
    if export_format not in ("combined", "separate"):
        export_format = "combined"
    
    pdir = _project_dir(user_id, project_id, cpe_id)
    
    try:
        # We need the raw reports, not the cached summary
        # Parse the telemetry file directly
        telemetry_file = _find_telemetry_file(pdir)
        dcmscript_file = _find_dcmscript_file(pdir)
        
        if not telemetry_file and not dcmscript_file:
            return jsonify({"error": "No telemetry data found"}), 404
        
        primary = telemetry_file or dcmscript_file
        reports, _merged, summary, _src = parse_telemetry_file(
            primary, dcmscript_path=dcmscript_file,
            cpe_dir=pdir, force=False,
        )
        
        if not reports:
            return jsonify({"error": "No telemetry reports found"}), 404
        
        # Convert to CSV DataFrames
        from logai.telemetry_parser import export_telemetry_to_csv
        csv_data = export_telemetry_to_csv(reports, profile_filter)
        
        dataframes = csv_data.get("dataframes", {})
        if not dataframes:
            return jsonify({"error": "No data to export for selected profiles"}), 404
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Generate CSV output based on format
        if export_format == "combined":
            # Combine all profiles into one CSV with Profile column
            import pandas as pd
            
            combined_rows = []
            for profile_name, df in dataframes.items():
                # Add Profile column
                df_copy = df.copy()
                
                # Check if Profile column already exists (can happen with TR-181 Profile field)
                if "Profile" in df_copy.columns:
                    # Replace existing Profile column value with profile name
                    df_copy["Profile"] = profile_name
                else:
                    # Insert new Profile column
                    df_copy.insert(1, "Profile", profile_name)
                combined_rows.append(df_copy)
            
            if combined_rows:
                combined_df = pd.concat(combined_rows, ignore_index=True)
                
                # Sort by timestamp
                if "Timestamp" in combined_df.columns:
                    combined_df = combined_df.sort_values("Timestamp")
                
                # Convert to CSV
                csv_buffer = StringIO()
                combined_df.to_csv(csv_buffer, index=False)
                csv_content = csv_buffer.getvalue()
                
                filename = f"telemetry_combined_{cpe_id}_{timestamp}.csv"
                
                from flask import Response
                return Response(
                    csv_content,
                    mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"}
                )
        
        else:  # separate
            if len(dataframes) == 1:
                # Single profile - return CSV directly
                profile_name = list(dataframes.keys())[0]
                df = dataframes[profile_name]
                
                csv_buffer = StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_content = csv_buffer.getvalue()
                
                # Sanitize profile name for filename
                safe_profile = profile_name.replace(" ", "_").replace("/", "_")
                filename = f"telemetry_{safe_profile}_{cpe_id}_{timestamp}.csv"
                
                from flask import Response
                return Response(
                    csv_content,
                    mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"}
                )
            
            else:
                # Multiple profiles - return ZIP
                zip_buffer = BytesIO()
                
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for profile_name, df in dataframes.items():
                        csv_buffer = StringIO()
                        df.to_csv(csv_buffer, index=False)
                        csv_content = csv_buffer.getvalue()
                        
                        # Sanitize profile name for filename
                        safe_profile = profile_name.replace(" ", "_").replace("/", "_")
                        csv_filename = f"telemetry_{safe_profile}_{cpe_id}_{timestamp}.csv"
                        
                        zip_file.writestr(csv_filename, csv_content)
                
                zip_buffer.seek(0)
                filename = f"telemetry_{cpe_id}_{timestamp}.zip"
                
                from flask import Response
                return Response(
                    zip_buffer.getvalue(),
                    mimetype="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={filename}"}
                )
    
    except Exception as e:
        logger.exception(f"[TelemetryExport] Error exporting CSV: {e}")
        return jsonify({"error": f"Export failed: {str(e)}"}), 500

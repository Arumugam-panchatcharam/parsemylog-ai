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
    "WiFi Radio", "WiFi SSID", "Device Info",
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
    reboot_timeline = _build_reboot_timeline(reports)
    mesh_topology = extract_mesh_topology_timeline(reports)

    response = {
        "device_info": device_info,
        "summary": {
            "total": summary.get("total", 0),
            "parsed": summary.get("parsed", 0),
            "overall_time_range": summary.get("overall_time_range", {}),
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


def _build_reboot_timeline(reports):
    """Detect reboots from uptime drops and return timeline data for charting."""
    ok_reports = [r for r in reports if r.get("parse_ok") and r.get("time")]
    ok_reports.sort(key=lambda x: x["time"])

    uptime_key = "Device.DeviceInfo.UpTime"
    times = []
    reboot_counts = []  # cumulative reboot count at each timestamp
    reboot_events = []  # individual reboot event markers
    cumulative = 0
    prev_uptime = None

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
            reboot_events.append({"time": ts, "count": cumulative, "prev_uptime": prev_uptime, "new_uptime": uptime})

        times.append(ts)
        reboot_counts.append(cumulative)
        prev_uptime = uptime

    return {
        "times": times,
        "counts": reboot_counts,
        "total_reboots": cumulative,
        "events": reboot_events,
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


def _build_charts_data(configured_fields):
    """Build chart data for plottable fields (JSON, not rendered)."""
    charts = []
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
            })

        if traces:
            charts.append({
                "group": group_label,
                "traces": traces,
            })

    return charts


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

    # System Resources
    sys_fields = configured_fields.get("System Resources", [])
    if sys_fields:
        mem_vals, mem_unit = _numerics(sys_fields, "Memory Free")
        mem_total, _ = _numerics(sys_fields, "Memory Total")
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

        cpu_vals, cpu_unit = _numerics(sys_fields, "CPU Usage")
        if cpu_vals:
            metrics.append({
                "label": "CPU Usage",
                "avg": round(sum(cpu_vals) / len(cpu_vals), 1),
                "peak": round(max(cpu_vals), 1),
                "unit": cpu_unit, "icon": "microchip",
            })

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

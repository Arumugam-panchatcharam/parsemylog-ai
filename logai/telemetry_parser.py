"""
RDK Telemetry 2.0 Report Parser
=================================

Parses ``telemetry2_0.txt`` log files to extract, reassemble, and merge the
periodic JSON telemetry reports emitted by the T2 module every 900 seconds.

The T2 module logs each JSON report across multiple lines:
  - First line:  ``<ts> telekom: T2.INFO [tid=<N>] cJSON Report = {"Report":[...]``
  - Continuation: ``<ts> telekom: T2.INFO [tid=<N>] <json_fragment>...``
  - End marker:   next line has different tid, or "Report Size =", etc.

Two profiles exist: "Advanced_dynamic" (large) and "Basic_dynamic" (smaller).
Each report embeds a wall-time ``"Time"`` field used for chronological ordering.

A YAML configuration file (``configs/telemetry_report_fields.yaml``) controls
which TR-181 fields are extracted, grouped, and plotted in the summary.

Usage:
    >>> from logai.telemetry_parser import (
    ...     parse_telemetry_reports,
    ...     merge_telemetry_reports,
    ...     extract_telemetry_summary,
    ...     extract_configured_fields,
    ...     load_report_field_config,
    ... )
    >>>
    >>> content = Path("telemetry2_0.txt").read_text()
    >>> reports = parse_telemetry_reports(content)
    >>> merged  = merge_telemetry_reports(reports)
    >>> summary = extract_telemetry_summary(reports)
    >>> fields  = extract_configured_fields(reports)
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for line parsing
# ---------------------------------------------------------------------------

# Matches the start of a cJSON Report line
_START_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+\S+:\s+T2\.\w+\s+\[tid=(\d+)\]\s+cJSON Report = (.+)"
)

# Matches any T2 log line (used for continuation detection)
_T2_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+\S+:\s+T2\.\w+\s+\[tid=(\d+)\]\s+(.+)"
)

# Matches "Report Size =" lines that signal end of a report dump
_REPORT_SIZE_RE = re.compile(r"Report Size\s*=\s*\d+")

# Fallback: matches the old log prefix format (used by legacy parser)
_OLD_PREFIX_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} [^ ]+ T\d\.\w+ \[tid=\d+\] ?",
    re.MULTILINE,
)

# Time format inside JSON reports
_REPORT_TIME_FMT = "%Y-%m-%d %H:%M:%S"

# Default config path
from logai.utils.constants import BASE_DIR
_DEFAULT_CONFIG_PATH = Path(BASE_DIR) / "configs" / "telemetry_report_fields.yaml"


# ---------------------------------------------------------------------------
# YAML config loading
# ---------------------------------------------------------------------------

def load_report_field_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load the telemetry report field configuration from YAML.

    Args:
        config_path: Path to YAML config. Defaults to the bundled
                     ``configs/telemetry_report_fields.yaml``.

    Returns:
        Parsed config dict with ``profile_filter`` and ``field_groups``.
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    if not path.exists():
        logger.warning(f"[TelemetryParser] Config not found at {path}, using empty config")
        return {"profile_filter": "Advanced_dynamic", "field_groups": []}

    try:
        import yaml
    except ImportError:
        logger.warning("[TelemetryParser] PyYAML not installed; cannot load YAML config")
        return {"profile_filter": "Advanced_dynamic", "field_groups": []}

    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    return cfg


def _expand_field_instances(
    fields_cfg: List[Dict[str, Any]],
    report_fields: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Expand ``{N}`` placeholders in field keys to concrete instance numbers
    found in the actual report data.

    E.g. ``Device.WiFi.Radio.{N}.Enable`` ->
         ``Device.WiFi.Radio.1.Enable``, ``Device.WiFi.Radio.2.Enable``

    Args:
        fields_cfg: List of field definitions from YAML config.
        report_fields: Union of all field keys found in reports.

    Returns:
        Expanded list of field definitions with concrete instance numbers.
    """
    expanded: List[Dict[str, Any]] = []

    for field_def in fields_cfg:
        key_template: str = field_def["key"]
        if "{N}" not in key_template:
            expanded.append(field_def)
            continue

        # Discover instance numbers from report data
        prefix = key_template.split("{N}")[0]
        suffix = key_template.split("{N}")[1]
        numbers_seen: set = set()
        pattern = re.compile(re.escape(prefix) + r"(\d+)" + re.escape(suffix))

        for rk in report_fields:
            m = pattern.fullmatch(rk)
            if m:
                numbers_seen.add(int(m.group(1)))

        for n in sorted(numbers_seen):
            concrete = dict(field_def)
            concrete["key"] = key_template.replace("{N}", str(n))
            concrete["label"] = field_def["label"].replace("{N}", str(n))
            concrete["_instance"] = n
            expanded.append(concrete)

    return expanded


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def _strip_log_prefix(line: str) -> Optional[Tuple[str, str, str]]:
    """
    Strip T2 log prefix and return (timestamp, tid, payload).

    Returns None if the line doesn't match T2 format.
    """
    m = _T2_LINE_RE.match(line)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


def _try_parse_json(json_str: str) -> Optional[dict]:
    """
    Attempt to parse a JSON string, with recovery for common truncation.

    Tries direct parse first, then attempts to repair unbalanced brackets.
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Try adding missing closing brackets/braces
    open_braces = json_str.count("{") - json_str.count("}")
    open_brackets = json_str.count("[") - json_str.count("]")

    if open_braces >= 0 and open_brackets >= 0:
        repaired = json_str + "]" * open_brackets + "}" * open_braces
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    return None


def _extract_report_fields(report_json: dict) -> Dict[str, Any]:
    """
    Extract key fields from the parsed Report JSON.

    The Report is an array of single-key dicts:
      {"Report": [{"Time": "..."}, {"Profile.Name": "..."}, ...]}
    """
    result: Dict[str, Any] = {}
    report_array = report_json.get("Report", [])

    for item in report_array:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            result[key] = value

    return result


def parse_telemetry_reports(content: str) -> List[Dict[str, Any]]:
    """
    Parse telemetry2_0.txt content and extract all cJSON Report entries.

    Each report spans multiple log lines sharing the same thread ID (tid).
    Lines are reassembled into valid JSON, parsed, and key fields extracted.

    Args:
        content: Raw text content of telemetry2_0.txt.

    Returns:
        List of parsed report dicts, each containing:
            - time: datetime from the report's "Time" field.
            - log_timestamp: str, the T2 log line timestamp.
            - profile: str, "Advanced_dynamic" or "Basic_dynamic".
            - mac: str, device MAC address.
            - version: str, firmware version.
            - uptime: int, device uptime in seconds.
            - fields: dict, all flattened key-value pairs from the report.
            - raw_json: dict, the original parsed JSON.
            - parse_ok: bool, whether JSON parsing succeeded.
    """
    lines = content.splitlines()
    reports: List[Dict[str, Any]] = []
    i = 0
    total_lines = len(lines)

    while i < total_lines:
        line = lines[i]

        # Look for cJSON Report start
        start_match = _START_RE.match(line)
        if not start_match:
            i += 1
            continue

        log_ts = start_match.group(1)
        tid = start_match.group(2)
        json_fragment = start_match.group(3)

        # Collect continuation lines with the same tid
        i += 1
        while i < total_lines:
            next_line = lines[i]
            parsed = _strip_log_prefix(next_line)
            if parsed is None:
                break

            next_ts, next_tid, next_payload = parsed
            if next_tid != tid:
                break
            if _REPORT_SIZE_RE.search(next_payload):
                i += 1
                break

            json_fragment += next_payload
            i += 1

        # Try to parse the reassembled JSON
        parsed_json = _try_parse_json(json_fragment)

        if parsed_json is not None:
            fields = _extract_report_fields(parsed_json)

            # Parse the embedded Time field
            time_str = fields.get("Time", "")
            try:
                report_time = datetime.strptime(time_str, _REPORT_TIME_FMT)
            except (ValueError, TypeError):
                report_time = None

            # Extract uptime as int
            uptime_raw = fields.get("Device.DeviceInfo.UpTime", "0")
            try:
                uptime = int(uptime_raw)
            except (ValueError, TypeError):
                uptime = 0

            reports.append({
                "time": report_time,
                "log_timestamp": log_ts,
                "profile": fields.get("Profile.Name", "unknown"),
                "mac": fields.get("mac", ""),
                "version": fields.get("Version", ""),
                "uptime": uptime,
                "fields": fields,
                "raw_json": parsed_json,
                "parse_ok": True,
            })
        else:
            logger.warning(
                f"[TelemetryParser] Failed to parse JSON at log_ts={log_ts}, tid={tid}"
            )
            reports.append({
                "time": None,
                "log_timestamp": log_ts,
                "profile": "unknown",
                "mac": "",
                "version": "",
                "uptime": 0,
                "fields": {},
                "raw_json": None,
                "parse_ok": False,
            })

    return reports


def parse_telemetry_legacy(content: str) -> List[Dict[str, Any]]:
    """
    Fallback parser using the old brace-counting method for non-T2-format logs.

    This handles telemetry files that don't follow the T2 tid-based format.

    Args:
        content: Raw text content of the telemetry file.

    Returns:
        List of parsed report dicts (same structure as parse_telemetry_reports).
    """
    # Strip T2 prefixes
    clean = _OLD_PREFIX_RE.sub("", content)

    inside_json = False
    open_braces = 0
    json_buffer = ""
    json_blocks = []

    for line in clean.splitlines():
        stripped = line.strip().replace('\n', '').replace('\r', '')
        if not inside_json:
            brace_pos = stripped.find("{")
            if brace_pos != -1:
                inside_json = True
                json_buffer = stripped[brace_pos:]
                open_braces = json_buffer.count("{") - json_buffer.count("}")
                if open_braces == 0:
                    json_blocks.append(json_buffer)
                    inside_json = False
                    json_buffer = ""
        else:
            json_buffer += stripped
            open_braces += stripped.count("{") - stripped.count("}")
            if open_braces == 0:
                json_blocks.append(json_buffer)
                inside_json = False
                json_buffer = ""

    reports = []
    for json_str in json_blocks:
        # Trim trailing noise
        m = re.search(r'(.*\}\]\})', json_str, re.DOTALL)
        if m:
            json_str = m.group(1)
        else:
            json_str = re.sub(r'[%\s]+$', '', json_str)

        parsed_json = _try_parse_json(json_str)
        if parsed_json:
            fields = _extract_report_fields(parsed_json)
            time_str = fields.get("Time", "")
            try:
                report_time = datetime.strptime(time_str, _REPORT_TIME_FMT)
            except (ValueError, TypeError):
                report_time = None

            reports.append({
                "time": report_time,
                "log_timestamp": "",
                "profile": fields.get("Profile.Name", "unknown"),
                "mac": fields.get("mac", ""),
                "version": fields.get("Version", ""),
                "uptime": 0,
                "fields": fields,
                "raw_json": parsed_json,
                "parse_ok": True,
            })

    return reports


# ---------------------------------------------------------------------------
# Merge & group
# ---------------------------------------------------------------------------

def merge_telemetry_reports(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Group reports by profile and sort chronologically.

    Args:
        reports: Output from parse_telemetry_reports().

    Returns:
        Dict with profiles, all_sorted, total, parse_failures.
    """
    by_profile: Dict[str, List[Dict]] = defaultdict(list)
    failures = 0

    for r in reports:
        if not r["parse_ok"]:
            failures += 1
            continue
        by_profile[r["profile"]].append(r)

    for profile in by_profile:
        by_profile[profile].sort(key=lambda x: x["time"] or datetime.min)

    ok_reports = [r for r in reports if r["parse_ok"]]
    ok_reports.sort(key=lambda x: x["time"] or datetime.min)

    return {
        "profiles": dict(by_profile),
        "all_sorted": ok_reports,
        "total": len(reports),
        "parse_failures": failures,
    }


# ---------------------------------------------------------------------------
# Summary extraction
# ---------------------------------------------------------------------------

def extract_telemetry_summary(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract a high-level summary from parsed telemetry reports.

    Args:
        reports: Output from parse_telemetry_reports().

    Returns:
        Dict with summary statistics including per-profile counts,
        time ranges, intervals, key metric trends, device info, and anomalies.
    """
    ok_reports = [r for r in reports if r["parse_ok"]]
    if not ok_reports:
        return {"total": len(reports), "parsed": 0, "parse_failures": len(reports)}

    failures = len(reports) - len(ok_reports)

    # Per-profile stats
    by_profile: Dict[str, List[Dict]] = defaultdict(list)
    for r in ok_reports:
        by_profile[r["profile"]].append(r)

    profile_stats: Dict[str, Dict[str, Any]] = {}
    for profile, reps in by_profile.items():
        reps.sort(key=lambda x: x["time"] or datetime.min)
        times = [r["time"] for r in reps if r["time"]]

        # Compute intervals
        intervals = []
        for j in range(1, len(times)):
            intervals.append((times[j] - times[j - 1]).total_seconds())

        avg_interval = sum(intervals) / len(intervals) if intervals else 0

        profile_stats[profile] = {
            "count": len(reps),
            "time_range": {
                "first": times[0].isoformat() if times else None,
                "last": times[-1].isoformat() if times else None,
            },
            "interval_stats": {
                "avg_seconds": round(avg_interval, 1),
                "expected_seconds": 900,
            },
        }

    # Overall time range
    all_times = sorted([r["time"] for r in ok_reports if r["time"]])
    overall_range = {
        "first": all_times[0].isoformat() if all_times else None,
        "last": all_times[-1].isoformat() if all_times else None,
    }

    # Device identity (from first OK report)
    first = ok_reports[0]
    device_info = {
        "mac": first.get("mac", ""),
        "version": first.get("version", ""),
        "serial": first["fields"].get("SerialNumber", ""),
        "model": first["fields"].get("Device.DeviceInfo.ModelName", ""),
        "manufacturer": first["fields"].get("Device.DeviceInfo.Manufacturer", ""),
        "hw_version": first["fields"].get("Device.DeviceInfo.HardwareVersion", ""),
    }

    # WAN Type: extract from 'wan_access_mode_split' telemetry marker.
    # Common values: "WANoE" (WAN over Ethernet / DSL), "GPON", "Ethernet", etc.
    wan_mode = ""
    for r in ok_reports:
        val = r["fields"].get("wan_access_mode_split", "")
        if val:
            wan_mode = str(val).strip()
            break
    device_info["wan_type"] = wan_mode

    return {
        "total": len(reports),
        "parsed": len(ok_reports),
        "parse_failures": failures,
        "device_info": device_info,
        "overall_time_range": overall_range,
        "profile_stats": profile_stats,
    }


# ---------------------------------------------------------------------------
# Configurable field extraction
# ---------------------------------------------------------------------------

def _resolve_sample(raw_value: str, sample_mode: str) -> str:
    """
    Resolve a potentially semicolon-separated value according to sample_mode.

    - "first": first sample (default)
    - "last":  last sample
    - "all":   average for numeric, otherwise first
    """
    if ";" not in str(raw_value):
        return str(raw_value)

    parts = [p.strip() for p in str(raw_value).split(";") if p.strip()]
    if not parts:
        return str(raw_value)

    if sample_mode == "last":
        return parts[-1]
    elif sample_mode == "all":
        try:
            nums = [float(p) for p in parts]
            return str(round(sum(nums) / len(nums), 2))
        except (ValueError, TypeError):
            return parts[0]
    else:
        return parts[0]


def _to_numeric(val: str) -> Optional[float]:
    """Try converting a string to a float. Returns None on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _status_to_numeric(val: str) -> Optional[float]:
    """Map status strings to 1/0 for plotting: Up/Enabled/true -> 1, else -> 0."""
    v = val.strip().lower()
    if v in ("up", "enabled", "true", "connected", "synchronized", "1"):
        return 1.0
    elif v in ("down", "disabled", "false", "disconnected", "0", "none"):
        return 0.0
    return None


def extract_configured_fields(
    reports: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Extract time-series data for every field defined in the YAML config.

    Args:
        reports: Output from parse_telemetry_reports().
        config: Loaded YAML config dict. Will load default if None.

    Returns:
        Dict keyed by group label, each containing a list of field results
        with keys: key, label, type, unit, plot, values, latest, change_count.
    """
    if config is None:
        config = load_report_field_config()

    profile_filter = config.get("profile_filter", "Advanced_dynamic")
    field_groups_cfg = config.get("field_groups", [])

    # Filter reports by profile
    filtered = [
        r for r in reports
        if r["parse_ok"] and r.get("profile") == profile_filter
    ]
    filtered.sort(key=lambda x: x["time"] or datetime.min)

    if not filtered:
        return {}

    # Collect all field keys present in the data
    all_field_keys: set = set()
    for r in filtered:
        all_field_keys.update(r["fields"].keys())

    result: Dict[str, List[Dict[str, Any]]] = {}

    for group_cfg in field_groups_cfg:
        group_label = group_cfg.get("label", "Unknown")
        fields_cfg = group_cfg.get("fields", [])

        # Expand {N} placeholders
        expanded = _expand_field_instances(fields_cfg, {k: None for k in all_field_keys})

        group_results: List[Dict[str, Any]] = []

        for fdef in expanded:
            fkey = fdef["key"]
            flabel = fdef["label"]
            ftype = fdef.get("type", "text")
            funit = fdef.get("unit", "")
            fplot = fdef.get("plot", False)
            fsample = fdef.get("sample", "first")

            values: List[Dict[str, Any]] = []
            prev_val: Optional[str] = None
            change_count = 0

            for r in filtered:
                raw = r["fields"].get(fkey)
                if raw is None:
                    continue

                ts_str = r["time"].isoformat() if r["time"] else r["log_timestamp"]
                resolved = _resolve_sample(str(raw), fsample)

                # Numeric conversion
                if ftype == "numeric":
                    num = _to_numeric(resolved)
                elif ftype in ("status", "bool"):
                    num = _status_to_numeric(resolved)
                else:
                    num = None

                values.append({
                    "time": ts_str,
                    "raw": resolved,
                    "numeric": num,
                })

                if prev_val is not None and resolved != prev_val:
                    change_count += 1
                prev_val = resolved

            if not values:
                continue

            group_results.append({
                "key": fkey,
                "label": flabel,
                "type": ftype,
                "unit": funit,
                "plot": fplot,
                "values": values,
                "latest": values[-1]["raw"],
                "change_count": change_count,
            })

        if group_results:
            result[group_label] = group_results

    return result


# ---------------------------------------------------------------------------
# Convenience: parse from file path
# ---------------------------------------------------------------------------

def parse_telemetry_file(file_path: Path) -> Tuple[List[Dict], Dict, Dict]:
    """
    Convenience function: parse a telemetry2_0.txt file end-to-end.

    Tries the T2 tid-based parser first, falls back to legacy brace-counting
    if no reports are found.

    Args:
        file_path: Path to telemetry2_0.txt.

    Returns:
        Tuple of (reports, merged, summary).
    """
    if not file_path.exists():
        logger.warning(f"[TelemetryParser] File not found: {file_path}")
        return [], {}, {}

    content = file_path.read_text(encoding="utf-8", errors="replace")

    # Try T2 format first
    reports = parse_telemetry_reports(content)

    # Fallback to legacy parser if no reports found
    if not reports:
        reports = parse_telemetry_legacy(content)

    merged = merge_telemetry_reports(reports)
    summary = extract_telemetry_summary(reports)

    logger.info(
        f"[TelemetryParser] Parsed {file_path.name}: "
        f"{summary.get('parsed', 0)}/{summary.get('total', 0)} reports OK"
    )

    return reports, merged, summary

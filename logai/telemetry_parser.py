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

from logai.config import LogAIConfig, default_config


# ---------------------------------------------------------------------------
# YAML config loading
# ---------------------------------------------------------------------------

def load_report_field_config(
    config_path: Optional[Path] = None,
    config: Optional[LogAIConfig] = None,
) -> Dict[str, Any]:
    """
    Load the telemetry report field configuration from YAML.

    Args:
        config_path: Path to YAML config. Overrides config when provided.
        config: Optional LogAIConfig for portable path resolution.

    Returns:
        Parsed config dict with ``profile_filter`` and ``field_groups``.
    """
    if config_path is not None:
        path = Path(config_path)
    else:
        path = (config or default_config()).resolve_telemetry_fields_config_path()
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
    Extract key fields from parsed telemetry JSON.

    Automatically detects and handles multiple telemetry formats:
    - T2 format: {"Report": [{"Time": "..."}, {"Profile.Name": "..."}, ...]}
    - dcmscript format: {"searchResult": [{"T2": "1.0"}, {"Profile": "..."}, ...]}
    - Custom formats: Any top-level array of single-key dicts

    For dcmscript format, automatically applies TR-181 key aliases to ensure
    compatibility with the rest of the telemetry pipeline.

    Args:
        report_json: Parsed JSON object from telemetry file.

    Returns:
        Flattened dict of all telemetry fields, with dcmscript keys mapped to
        TR-181 equivalents when applicable.
    """
    result: Dict[str, Any] = {}
    
    # Detect format by checking known array keys (in priority order)
    report_array = None
    source_format = None
    
    # Priority 1: T2 format (Report key)
    if "Report" in report_json:
        report_array = report_json["Report"]
        source_format = "t2"
    # Priority 2: dcmscript format (searchResult key)
    elif "searchResult" in report_json:
        report_array = report_json["searchResult"]
        source_format = "dcmscript"
    # Priority 3: Try to find any top-level array as fallback
    else:
        for key, value in report_json.items():
            if isinstance(value, list) and len(value) > 0:
                report_array = value
                source_format = "custom"
                break
    
    if not report_array:
        return result
    
    # Extract fields from array of single-key dicts
    for item in report_array:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            # Skip empty string values (common in dcmscript)
            if isinstance(value, str) and value == "":
                continue
            result[key] = value
    
    # Apply dcmscript -> TR-181 key mappings if from dcmscript format
    if source_format == "dcmscript" and result:
        _apply_dcm_tr181_aliases(result)
    
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
# dcmscript.log CURL_CMD parser (fallback when T2 is disabled)
# ---------------------------------------------------------------------------

# Matches CURL_CMD lines and captures the JSON payload between -d '...'
_DCM_CURL_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+\S+:\s+DCM_log\s+-\s+CURL_CMD:.*?-d\s+'(\{.*)"
)

# Mapping from dcmscript short keys to TR-181 paths used by charts/summary
_DCM_KEY_TO_TR181: Dict[str, str] = {
    # System / device identity
    "CPUUsage": "Device.DeviceInfo.ProcessStatus.CPUUsage",
    "DeviceUpTime": "Device.DeviceInfo.UpTime",
    "MemInfoFree": "Device.DeviceInfo.MemoryStatus.Free",
    "MemInfoTotal": "Device.DeviceInfo.MemoryStatus.Total",
    "meminfoavailable_split": "Device.DeviceInfo.MemoryStatus.Available",
    "shmem_split": "Device.DeviceInfo.MemoryStatus.SharedMemory",
    "slab_memory_split": "Device.DeviceInfo.MemoryStatus.SlabMemory",
    "ProcessNumberOfEntries": "Device.DeviceInfo.ProcessStatus.ProcessNumberOfEntries",
    "ModelName": "Device.DeviceInfo.ModelName",
    "ManufacturerOUI": "Device.DeviceInfo.ManufacturerOUI",
    "ProductClass": "Device.DeviceInfo.ProductClass",
    "description": "Device.DeviceInfo.Description",
    "hardwareversion": "Device.DeviceInfo.HardwareVersion",
    "manufacturer": "Device.DeviceInfo.Manufacturer",
    "hosts_connected_device_number": "Device.Hosts.X_CISCO_COM_ConnectedDeviceNumber",
    "last_reboot_reason_split": "Device.DeviceInfo.X_RDKCENTRAL-COM_LastRebootReason",
    # PPP (single-instance)
    "ppp_interface_1_status": "Device.PPP.Interface.1.ConnectionStatus",
    # Ethernet link
    "ethernet_link_1_status": "Device.Ethernet.Link.1.Status",
    # GPON
    "gpon_connectionStatus": "Device.GPON.ConnectionStatus",
    "gpon_operationalState": "Device.GPON.OperationalState",
    "gpon_registrationState": "Device.GPON.RegistrationState",
    "gpon_rxSignalLevel": "Device.GPON.RxSignalLevel",
    "gpon_txSignalLevel": "Device.GPON.TxSignalLevel",
    "gpon_downstreamSpeed": "Device.GPON.DownstreamSpeed",
    "gpon_upstreamSpeed": "Device.GPON.UpstreamSpeed",
    "gpon_framesLost": "Device.GPON.FramesLost",
    # WANoE
    "wanoe_connectionStatus": "Device.WANoE.ConnectionStatus",
    "wanoe_lastConnError": "Device.WANoE.LastConnError",
    "wanoe_downstreamSpeed": "Device.WANoE.DownstreamSpeed",
    "wanoe_upstreamSpeed": "Device.WANoE.UpstreamSpeed",
    # WAN traffic
    "wan_bytesReceived": "Device.WAN.BytesReceived",
    "wan_bytesSent": "Device.WAN.BytesSent",
    "wan_packetsReceived": "Device.WAN.PacketsReceived",
    "wan_packetsSent": "Device.WAN.PacketsSent",
    "wan_errorsReceived": "Device.WAN.ErrorsReceived",
    "wan_errorsSent": "Device.WAN.ErrorsSent",
}

# Pattern-based mappings for multi-instance dcmscript keys → TR-181 paths.
# Each tuple: (compiled regex, TR-181 template with ``{N}`` placeholder).
_DCM_PATTERN_TO_TR181 = [
    # WiFi Radio
    (re.compile(r"^wifi_radio_(\d+)_enable$"), "Device.WiFi.Radio.{N}.Enable"),
    (re.compile(r"^wifi_radio_(\d+)_status$"), "Device.WiFi.Radio.{N}.Status"),
    (re.compile(r"^wifi_radio_(\d+)_channel$"), "Device.WiFi.Radio.{N}.Channel"),
    (re.compile(r"^wifi_radio_(\d+)_operatingfrequencyband$"), "Device.WiFi.Radio.{N}.OperatingFrequencyBand"),
    (re.compile(r"^wifi_radio_(\d+)_operatingchannelbandwidth$"), "Device.WiFi.Radio.{N}.OperatingChannelBandwidth"),
    (re.compile(r"^wifi_radio_(\d+)_current_operating_channel_bandwith$"), "Device.WiFi.Radio.{N}.OperatingChannelBandwidth"),
    (re.compile(r"^wifi_radio_(\d+)_transmitpower$"), "Device.WiFi.Radio.{N}.TransmitPower"),
    (re.compile(r"^wifi_radio_(\d+)_stats_noise$"), "Device.WiFi.Radio.{N}.Stats.Noise"),
    (re.compile(r"^wifi_radio_(\d+)_stats_x_comcast_com_channelutilization$"), "Device.WiFi.Radio.{N}.Stats.X_COMCAST-COM_ChannelUtilization"),
    # WiFi SSID
    (re.compile(r"^wifi_ssid_(\d+)_ssid$"), "Device.WiFi.SSID.{N}.SSID"),
    (re.compile(r"^wifi_ssid_(\d+)_enable$"), "Device.WiFi.SSID.{N}.Enable"),
    (re.compile(r"^wifi_ssid_(\d+)_status$"), "Device.WiFi.SSID.{N}.Status"),
    (re.compile(r"^wifi_ssid_(\d+)_stats_bytesreceived$"), "Device.WiFi.SSID.{N}.Stats.BytesReceived"),
    (re.compile(r"^wifi_ssid_(\d+)_stats_bytessent$"), "Device.WiFi.SSID.{N}.Stats.BytesSent"),
    (re.compile(r"^wifi_ssid_(\d+)_stats_errorsreceived$"), "Device.WiFi.SSID.{N}.Stats.ErrorsReceived"),
    (re.compile(r"^wifi_ssid_(\d+)_stats_errorssent$"), "Device.WiFi.SSID.{N}.Stats.ErrorsSent"),
]


def _apply_dcm_tr181_aliases(fields: Dict[str, Any]) -> None:
    """Add TR-181 aliases to *fields* in-place (static + pattern-based)."""
    # Static 1:1 mappings
    for short_key, tr181_key in _DCM_KEY_TO_TR181.items():
        if short_key in fields and tr181_key not in fields:
            fields[tr181_key] = fields[short_key]

    # Pattern-based multi-instance mappings
    extra: Dict[str, Any] = {}
    for key, value in fields.items():
        for pattern, template in _DCM_PATTERN_TO_TR181:
            m = pattern.match(key)
            if m:
                tr181_key = template.replace("{N}", m.group(1))
                if tr181_key not in fields:
                    extra[tr181_key] = value
                break
    fields.update(extra)


def parse_dcmscript_curl_reports(content: str) -> List[Dict[str, Any]]:
    """
    Parse dcmscript.log content to extract telemetry from CURL_CMD payloads.

    Each CURL_CMD line posts a ``searchResult`` JSON array to the telemetry
    backend.  The array contains single-key dicts that we flatten into a
    fields dict.  Core keys are also mapped to their TR-181 equivalents so
    that existing chart / summary logic works transparently.

    Args:
        content: Raw text content of dcmscript.log.

    Returns:
        List of parsed report dicts (same schema as parse_telemetry_reports).
    """
    reports: List[Dict[str, Any]] = []

    for line in content.splitlines():
        m = _DCM_CURL_RE.match(line)
        if not m:
            continue

        log_ts = m.group(1)
        json_tail = m.group(2)

        # The payload may extend past the closing brace (URL, flags, etc.).
        # Find the outermost balanced JSON object.
        json_str = _extract_balanced_json(json_tail)
        if not json_str:
            continue

        parsed_json = _try_parse_json(json_str)
        if not parsed_json or "searchResult" not in parsed_json:
            continue

        fields = _flatten_search_result(parsed_json["searchResult"])

        # Inject TR-181 aliases for keys the rest of the pipeline expects
        _apply_dcm_tr181_aliases(fields)

        # Parse embedded Time field (same format as T2 reports)
        time_str = fields.get("Time", "")
        try:
            report_time = datetime.strptime(time_str, _REPORT_TIME_FMT)
        except (ValueError, TypeError):
            # Fall back to the log-line timestamp
            try:
                report_time = datetime.strptime(log_ts, "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                report_time = None

        uptime_raw = fields.get("Device.DeviceInfo.UpTime",
                                fields.get("DeviceUpTime", "0"))
        try:
            uptime = int(uptime_raw)
        except (ValueError, TypeError):
            uptime = 0

        reports.append({
            "time": report_time,
            "log_timestamp": log_ts,
            "profile": fields.get("Profile", "dcmscript"),
            "mac": fields.get("mac", ""),
            "version": fields.get("Version", ""),
            "uptime": uptime,
            "fields": fields,
            "raw_json": parsed_json,
            "parse_ok": True,
        })

    return reports


def _extract_balanced_json(s: str) -> Optional[str]:
    """Extract the first balanced ``{...}`` substring from *s*."""
    depth = 0
    start = None
    in_string = False
    escape_next = False

    for i, ch in enumerate(s):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                return s[start:i + 1]

    # Truncated: attempt repair
    if start is not None and depth > 0:
        open_brackets = s[start:].count("[") - s[start:].count("]")
        repair = s[start:] + "]" * max(open_brackets, 0) + "}" * depth
        return repair

    return None


def _flatten_search_result(search_result: list) -> Dict[str, Any]:
    """Flatten ``searchResult`` array of single-key dicts into one dict.

    Skips entries whose value is an empty string (no telemetry data).
    For duplicate keys the last value wins (matching T2 behaviour).
    """
    fields: Dict[str, Any] = {}
    for item in search_result:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if isinstance(value, str) and value == "":
                continue
            fields[key] = value
    return fields


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
            "parsed": len(reps),
            "time_range": {
                "first": times[0].isoformat() if times and isinstance(times[0], datetime) else (times[0] if times else None),
                "last": times[-1].isoformat() if times and isinstance(times[-1], datetime) else (times[-1] if times else None),
            },
            "interval_stats": {
                "avg_seconds": round(avg_interval, 1),
                "expected_seconds": 900,
            },
        }

    # Overall time range
    all_times = sorted([r["time"] for r in ok_reports if r["time"]])
    overall_range = {
        "first": all_times[0].isoformat() if all_times and isinstance(all_times[0], datetime) else (all_times[0] if all_times else None),
        "last": all_times[-1].isoformat() if all_times and isinstance(all_times[-1], datetime) else (all_times[-1] if all_times else None),
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
# CSV Export
# ---------------------------------------------------------------------------

def export_telemetry_to_csv(
    reports: List[Dict[str, Any]],
    profile_filter: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Convert telemetry reports to CSV-ready DataFrames grouped by profile.
    
    Args:
        reports: Parsed telemetry reports from parse_telemetry_reports()
        profile_filter: List of profile names to include, or None for all profiles
    
    Returns:
        Dict with:
            - "dataframes": Dict mapping profile names to pandas DataFrames
            - "profile_counts": Dict mapping profile names to row counts
    """
    try:
        import pandas as pd
    except ImportError:
        logger.error("[TelemetryExport] pandas not installed")
        return {"dataframes": {}, "profile_counts": {}}
    
    # Group reports by profile
    merged = merge_telemetry_reports(reports)
    by_profile = merged["profiles"]
    
    # Filter profiles if requested
    if profile_filter:
        by_profile = {p: reps for p, reps in by_profile.items() if p in profile_filter}
    
    if not by_profile:
        logger.warning("[TelemetryExport] No reports found matching profile filter")
        return {"dataframes": {}, "profile_counts": {}}
    
    dataframes = {}
    profile_counts = {}
    
    for profile_name, profile_reports in by_profile.items():
        if not profile_reports:
            continue
        
        # Build list of rows, one per report
        rows = []
        for report in profile_reports:
            if not report.get("parse_ok"):
                continue
            
            # Start with timestamp
            row = {}
            time_val = report.get("time")
            if isinstance(time_val, datetime):
                row["Timestamp"] = time_val.isoformat()
            else:
                row["Timestamp"] = str(time_val) if time_val else ""
            
            # Flatten all fields from the report
            fields = report.get("fields", {})
            for key, value in fields.items():
                # Convert value to string for CSV compatibility
                if value is None:
                    row[key] = ""
                elif isinstance(value, bool):
                    row[key] = str(value).lower()
                elif isinstance(value, (int, float)):
                    row[key] = value
                else:
                    row[key] = str(value)
            
            rows.append(row)
        
        if rows:
            # Create DataFrame
            df = pd.DataFrame(rows)
            
            # Sort by timestamp
            if "Timestamp" in df.columns:
                df = df.sort_values("Timestamp")
            
            dataframes[profile_name] = df
            profile_counts[profile_name] = len(df)
            logger.info(f"[TelemetryExport] Created DataFrame for profile '{profile_name}' with {len(df)} rows")
    
    return {
        "dataframes": dataframes,
        "profile_counts": profile_counts
    }


# ---------------------------------------------------------------------------
# Configurable field extraction
# ---------------------------------------------------------------------------

def _resolve_sample(raw_value: str, sample_mode: str) -> str:
    """
    Resolve a potentially multi-sample value according to sample_mode.

    Telemetry values can contain multiple sub-minute samples separated by
    semicolons (``;``) or commas (``,``).

    - "first": first sample (default)
    - "last":  last sample
    - "all":   average for numeric, otherwise first
    """
    s = str(raw_value)
    if ";" not in s and "," not in s:
        return s

    # Split on both semicolons and commas
    import re
    parts = [p.strip() for p in re.split(r"[;,]", s) if p.strip()]
    if not parts:
        return s

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

    field_groups_cfg = config.get("field_groups", [])

    # Use ALL successfully parsed reports regardless of profile name.
    # TR-181 keys are standardised; profile names are user-defined and vary
    # across firmware versions and deployments.
    # When different profiles report the same key at overlapping timestamps
    # we keep the entry with the most fields (richest data).
    ok_reports = [r for r in reports if r["parse_ok"]]
    ok_reports.sort(key=lambda x: x["time"] or datetime.min)

    # Deduplicate: if two reports share the exact same timestamp, merge
    # their fields (later report wins for duplicate keys).
    seen_times: Dict[Optional[datetime], Dict[str, Any]] = {}
    for r in ok_reports:
        t = r["time"]
        if t in seen_times:
            # Merge fields – keep the richer set
            seen_times[t]["fields"].update(r["fields"])
        else:
            # Copy fields dict so we don't mutate originals
            seen_times[t] = {**r, "fields": dict(r["fields"])}

    filtered = sorted(seen_times.values(), key=lambda x: x["time"] or datetime.min)

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

                ts_str = r["time"].isoformat() if isinstance(r["time"], datetime) else (r["time"] or r["log_timestamp"])
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

_TELEMETRY_CACHE_DIR = "telemetry"
_CACHE_RESPONSE = "response.json"
_CACHE_AVAILABLE = "available_fields.json"
_RAW_CACHE_FILE = "raw_telemetry_cache.json"


def _raw_cache_path(cpe_dir: Path) -> Path:
    return cpe_dir / _RAW_CACHE_FILE


def _raw_cache_is_fresh(cpe_dir: Path) -> bool:
    """Return True if raw cache exists and is newer than source files."""
    cache = _raw_cache_path(cpe_dir)
    if not cache.exists():
        return False
    cache_mtime = cache.stat().st_mtime
    for name in ("telemetry2_0.txt", "dcmscript.log"):
        src = cpe_dir / name
        if src.exists() and src.stat().st_mtime > cache_mtime:
            return False
    return True


def _save_raw_telemetry_cache(
    cpe_dir: Path,
    reports: List[Dict[str, Any]],
    merged: Dict[str, Any],
    summary: Dict[str, Any],
    source: str,
) -> None:
    try:
        payload = {
            "reports": reports,
            "merged": merged,
            "summary": summary,
            "source": source,
        }
        _raw_cache_path(cpe_dir).write_text(
            json.dumps(payload, default=_serialise_datetime, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug(f"[TelemetryParser] Raw cache saved to {cpe_dir}")
    except Exception as exc:
        logger.warning(f"[TelemetryParser] Failed to save raw cache: {exc}")


def _load_raw_telemetry_cache(
    cpe_dir: Path,
) -> Optional[Tuple[List[Dict], Dict, Dict, str]]:
    try:
        data = json.loads(
            _raw_cache_path(cpe_dir).read_text(encoding="utf-8")
        )
        reports = data["reports"]
        merged = data["merged"]
        summary = data["summary"]
        source = data["source"]
        logger.info(
            f"[TelemetryParser] Loaded raw cache ({len(reports)} reports, "
            f"source={source}) from {cpe_dir}"
        )
        return reports, merged, summary, source
    except Exception as exc:
        logger.warning(f"[TelemetryParser] Bad raw cache in {cpe_dir}: {exc}")
        return None


def _invalidate_api_response_cache(cpe_dir: Path) -> None:
    """Delete the Telemetry page's API response cache so it gets rebuilt.

    Called when ``force=True`` re-parses raw telemetry to ensure the
    higher-level API response cache (``telemetry/response.json``) does
    not serve stale data.
    """
    cache = cpe_dir / _TELEMETRY_CACHE_DIR
    for name in (_CACHE_RESPONSE, _CACHE_AVAILABLE):
        p = cache / name
        if p.exists():
            try:
                p.unlink()
                logger.debug(f"[TelemetryParser] Invalidated {p}")
            except Exception as exc:
                logger.warning(f"[TelemetryParser] Could not delete {p}: {exc}")


def parse_telemetry_file(
    file_path: Path,
    dcmscript_path: Optional[Path] = None,
    *,
    cpe_dir: Optional[Path] = None,
    force: bool = False,
) -> Tuple[List[Dict], Dict, Dict, str]:
    """
    Convenience function: parse a telemetry file end-to-end.

    Parser priority:
      1. T2 tid-based parser (telemetry2_0.txt cJSON Reports)
      2. Legacy brace-counting parser
      3. dcmscript.log CURL_CMD searchResult parser (when *dcmscript_path*
         is provided and the first two parsers yield no reports)

    Args:
        file_path: Path to the primary telemetry file (telemetry2_0.txt).
        dcmscript_path: Optional path to dcmscript.log used as a fallback
            when T2 is disabled or yields no parsable reports.
        cpe_dir: CPE directory for raw-cache read/write. When given the
            result is cached to ``<cpe_dir>/raw_telemetry_cache.json``.
        force: When True, bypass any cached result and re-parse.

    Returns:
        Tuple of (reports, merged, summary, source) where *source* is one
        of ``"telemetry2_0"``, ``"legacy"``, ``"dcmscript"``, or ``"none"``.
    """
    if cpe_dir and not force and _raw_cache_is_fresh(cpe_dir):
        cached = _load_raw_telemetry_cache(cpe_dir)
        if cached is not None:
            return cached

    if cpe_dir and force:
        _invalidate_api_response_cache(cpe_dir)

    reports: List[Dict[str, Any]] = []
    source = "none"

    if file_path.exists():
        content = file_path.read_text(encoding="utf-8", errors="replace")

        reports = parse_telemetry_reports(content)
        if reports:
            source = "telemetry2_0"

        if not reports:
            reports = parse_telemetry_legacy(content)
            if reports:
                source = "legacy"

    if not reports and dcmscript_path and dcmscript_path.exists():
        dcm_content = dcmscript_path.read_text(encoding="utf-8", errors="replace")
        reports = parse_dcmscript_curl_reports(dcm_content)
        if reports:
            source = "dcmscript"
            logger.info(
                f"[TelemetryParser] Using dcmscript fallback: "
                f"{len(reports)} reports from {dcmscript_path.name}"
            )

    merged = merge_telemetry_reports(reports)
    summary = extract_telemetry_summary(reports)

    logger.info(
        f"[TelemetryParser] Parsed source={source}: "
        f"{summary.get('parsed', 0)}/{summary.get('total', 0)} reports OK"
    )

    if cpe_dir:
        _save_raw_telemetry_cache(cpe_dir, reports, merged, summary, source)

    return reports, merged, summary, source


# ---------------------------------------------------------------------------
# Cache: save / load the final API response
# ---------------------------------------------------------------------------

# Legacy cache filenames (removed on next save)
_LEGACY_CACHE_FILES = ("reports.json", "summary.json", "configured_fields.json")


def _serialise_datetime(obj: Any) -> Any:
    """JSON-safe conversion for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _cache_dir(project_dir: Path) -> Path:
    """Return the telemetry cache directory for a project (or CPE)."""
    return project_dir / _TELEMETRY_CACHE_DIR


def save_telemetry_cache(
    project_dir: Path,
    response: Dict[str, Any],
    available_fields: Dict[str, Any],
) -> Path:
    """
    Persist the final API response and available-fields discovery data
    as JSON files under ``<project_dir>/telemetry/``.

    Args:
        project_dir: The project (or CPE) directory.
        response: The fully-built API response dict (device_info, summary,
                  charts, key_metrics, status_labels, reboot_timeline).
                  All values must be JSON-serialisable (no datetime objects).
        available_fields: Discovery data for unconfigured TR-181 fields.

    Returns the cache directory path.
    """
    cache = _cache_dir(project_dir)
    cache.mkdir(parents=True, exist_ok=True)

    _write_json(cache / _CACHE_RESPONSE, response)
    _write_json(cache / _CACHE_AVAILABLE, available_fields)

    # Clean up legacy cache files from the old format
    for legacy in _LEGACY_CACHE_FILES:
        lp = cache / legacy
        if lp.exists():
            lp.unlink()

    logger.info(f"[TelemetryCache] Saved to {cache}")
    return cache


def load_telemetry_cache(project_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Load cached API response if it exists.

    Returns the response dict (ready to send to the client), or *None* if
    no cache exists.  The dict also includes an ``available_fields`` key.
    """
    cache = _cache_dir(project_dir)
    response_path = cache / _CACHE_RESPONSE

    if not response_path.exists():
        return None

    try:
        response = json.loads(response_path.read_text(encoding="utf-8"))

        # Attach available_fields if present
        avail_path = cache / _CACHE_AVAILABLE
        if avail_path.exists():
            response["available_fields"] = json.loads(avail_path.read_text(encoding="utf-8"))

        logger.info(f"[TelemetryCache] Loaded from {cache}")
        return response
    except Exception as e:
        logger.warning(f"[TelemetryCache] Failed to load: {e}")
        return None


def load_available_fields_cache(project_dir: Path) -> Optional[Dict[str, Any]]:
    """Load only the available-fields discovery data from cache."""
    cache = _cache_dir(project_dir)
    avail_path = cache / _CACHE_AVAILABLE
    if not avail_path.exists():
        return None
    try:
        return json.loads(avail_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: Any) -> None:
    """Write data to a JSON file with pretty-printing."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=_serialise_datetime, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Discovery: find available TR-181 fields NOT in the YAML config
# ---------------------------------------------------------------------------

def discover_available_fields(
    reports: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Discover all TR-181 fields present in the telemetry data and classify them.

    For each unconfigured field, infer whether it's numeric, boolean/status, or
    text, along with sample values and data-point count.  Fields are grouped by
    their TR-181 prefix (e.g. ``Device.WiFi``, ``Device.Ethernet``).

    Args:
        reports: Output from parse_telemetry_reports().
        config: Loaded YAML config dict. Will load default if None.

    Returns:
        Dict with:
            - ``configured_keys``: list of keys already in the YAML config
            - ``unconfigured``: dict keyed by TR-181 group prefix, each value a
              list of field info dicts
            - ``stats``: total / configured / unconfigured counts
    """
    if config is None:
        config = load_report_field_config()

    # Collect configured keys (expand {N} to find all concrete keys)
    configured_keys: set = set()
    for group_cfg in config.get("field_groups", []):
        for fdef in group_cfg.get("fields", []):
            key = fdef["key"]
            if "{N}" not in key:
                configured_keys.add(key)
            else:
                # Will be expanded by concrete data below
                pass

    # Collect all fields from all OK reports
    ok_reports = [r for r in reports if r.get("parse_ok")]
    field_samples: Dict[str, List[str]] = defaultdict(list)
    field_counts: Dict[str, int] = defaultdict(int)

    for r in ok_reports:
        for key, val in r.get("fields", {}).items():
            field_counts[key] += 1
            if len(field_samples[key]) < 5:  # keep up to 5 samples
                field_samples[key].append(str(val)[:200])

    # Expand {N} patterns to mark concrete keys as configured
    for group_cfg in config.get("field_groups", []):
        for fdef in group_cfg.get("fields", []):
            key_template = fdef["key"]
            if "{N}" not in key_template:
                continue
            prefix = key_template.split("{N}")[0]
            suffix = key_template.split("{N}")[1]
            pattern = re.compile(re.escape(prefix) + r"\d+" + re.escape(suffix))
            for fk in field_counts:
                if pattern.fullmatch(fk):
                    configured_keys.add(fk)

    # Classify unconfigured fields
    # Skip meta fields like Time, Profile.Name, mac, etc.
    _META_KEYS = {"Time", "Profile.Name", "Profile.Version", "mac", "SerialNumber",
                  "erouterIpv4", "erouterIpv6", "PartnerId", "Version", "AccountId"}

    unconfigured: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for key in sorted(field_counts):
        if key in configured_keys or key in _META_KEYS:
            continue

        samples = field_samples[key]
        inferred_type = _infer_field_type(samples)
        plottable = inferred_type == "numeric"

        # Group by first two TR-181 path segments (e.g. Device.WiFi)
        parts = key.split(".")
        group_prefix = ".".join(parts[:2]) if len(parts) >= 2 else parts[0]

        unconfigured[group_prefix].append({
            "key": key,
            "type": inferred_type,
            "plottable": plottable,
            "count": field_counts[key],
            "samples": samples[:3],
        })

    total_keys = len(field_counts)
    configured_count = len(configured_keys & set(field_counts.keys()))

    return {
        "configured_keys": sorted(configured_keys & set(field_counts.keys())),
        "unconfigured": dict(unconfigured),
        "stats": {
            "total_fields": total_keys,
            "configured": configured_count,
            "unconfigured": total_keys - configured_count - len(_META_KEYS & set(field_counts.keys())),
        },
    }


def _infer_field_type(samples: List[str]) -> str:
    """Infer the most likely type from sample values."""
    if not samples:
        return "text"

    bool_vals = {"true", "false", "up", "down", "enabled", "disabled",
                 "connected", "disconnected", "synchronized", "1", "0"}
    numeric_count = 0
    bool_count = 0

    for s in samples:
        s_clean = s.split(";")[0].strip().lower()
        if s_clean in bool_vals:
            bool_count += 1
            continue
        try:
            float(s_clean)
            numeric_count += 1
        except (ValueError, TypeError):
            pass

    total = len(samples)
    if bool_count == total:
        return "status"
    if numeric_count >= total * 0.8:
        return "numeric"
    return "text"


# ---------------------------------------------------------------------------
# Mesh Topology Extraction
# ---------------------------------------------------------------------------

_DATAELEMENTS_KEY = "Device.WiFi.DataElements.Network.Device."

# Media-type strings that indicate WiFi backhaul
_WIFI_MEDIA_PATTERNS = ("802.11", "IEEE 802.11")


def _is_wifi_backhaul(media_type: str) -> bool:
    """Return True if the backhaul media type indicates WiFi (not Ethernet)."""
    if not media_type:
        return True  # default to WiFi if unknown
    return any(p in media_type for p in _WIFI_MEDIA_PATTERNS)


def _short_mac(mac: str) -> str:
    """Shorten a MAC-like ID for display: keep last 4 hex chars."""
    clean = mac.replace(":", "").replace("-", "")
    if len(clean) >= 4:
        return clean[-4:].upper()
    return mac.upper()


def _count_stas(radios: List[Dict[str, Any]]) -> int:
    """Count total connected stations across all radios/BSS."""
    total = 0
    for radio in radios:
        for bss in radio.get("BSS", []):
            sta_count = bss.get("STANumberOfEntries", "0")
            try:
                total += int(sta_count)
            except (ValueError, TypeError):
                # Fall back to counting STA array length
                total += len(bss.get("STA", []))
    return total


def _extract_radio_info(radios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract summarised radio info from the Radio array."""
    result = []
    for radio in radios:
        band = radio.get("X_AIRTIES_OperatingFrequencyBand", "")
        standards = radio.get("X_AIRTIES_OperatingStandards", "")
        channel = radio.get("X_AIRTIES_Channel", "")
        bandwidth = radio.get("X_AIRTIES_Bandwidth", "")
        temperature = radio.get("X_AIRTIES_Temperature", "")
        bss_list = radio.get("BSS", [])
        bss_count = len(bss_list)
        sta_count = 0
        for bss in bss_list:
            try:
                sta_count += int(bss.get("STANumberOfEntries", "0"))
            except (ValueError, TypeError):
                sta_count += len(bss.get("STA", []))

        result.append({
            "band": band,
            "standards": standards,
            "channel": channel,
            "bandwidth": bandwidth,
            "temperature": temperature,
            "bss_count": bss_count,
            "sta_count": sta_count,
        })
    return result


def _rcpi_to_rssi_dbm(signal_raw: str) -> str:
    """Convert semicolon-separated RCPI values to average RSSI in dBm.

    Formula: RSSI (dBm) = (RCPI / 2) - 110

    Handles mixed values like ``"110;112;NULL;NULL;108"`` by skipping
    non-numeric entries (e.g. ``NULL``).
    """
    if not signal_raw or signal_raw == "0":
        return ""
    try:
        rcpi_values: list[int] = []
        for v in signal_raw.split(";"):
            v = v.strip()
            if not v or v.upper() == "NULL":
                continue
            rcpi_values.append(int(v))
        if rcpi_values:
            avg_rcpi = sum(rcpi_values) / len(rcpi_values)
            rssi_dbm = round((avg_rcpi / 2) - 110, 1)
            return str(rssi_dbm)
    except (ValueError, ZeroDivisionError):
        pass
    return ""  # return empty if entirely unparseable


def _extract_clients(radios_raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract connected client (STA) details from Radio > BSS > STA hierarchy.

    Only includes STAs from fronthaul BSSes. Affiliated STAs (mesh backhaul
    connections) are marked but included so the UI can decide how to display them.
    """
    clients: List[Dict[str, Any]] = []
    for radio in radios_raw:
        band = radio.get("X_AIRTIES_OperatingFrequencyBand", "")
        for bss in radio.get("BSS", []):
            is_fronthaul = bss.get("FronthaulUse", "false") == "true"
            if not is_fronthaul:
                continue
            ssid = bss.get("SSID", "")
            for sta in bss.get("STA", []):
                mac = sta.get("MACAddress", "")
                if not mac:
                    # Skip incomplete STA entries (e.g. Basic_dynamic profile
                    # that only reports SignalStrength without MACAddress)
                    continue
                op_std = sta.get("X_AIRTIES_OperatingStandard", "")
                signal_raw = sta.get("SignalStrength", "")
                is_affiliated = sta.get("X_AIRTIES_Affiliated", "false") == "true"

                try:
                    max_phy = int(sta.get("X_AIRTIES_MaxPhyRate", "0"))
                except (ValueError, TypeError):
                    max_phy = 0
                try:
                    last_dl = int(sta.get("LastDataDownlinkRate", "0"))
                except (ValueError, TypeError):
                    last_dl = 0
                try:
                    last_ul = int(sta.get("LastDataUplinkRate", "0"))
                except (ValueError, TypeError):
                    last_ul = 0
                try:
                    bytes_rx = int(sta.get("BytesReceived", "0"))
                except (ValueError, TypeError):
                    bytes_rx = 0
                try:
                    bytes_tx = int(sta.get("BytesSent", "0"))
                except (ValueError, TypeError):
                    bytes_tx = 0
                try:
                    connect_time = int(sta.get("LastConnectTime", "0"))
                except (ValueError, TypeError):
                    connect_time = 0
                try:
                    retrans = int(sta.get("RetransCount", "0"))
                except (ValueError, TypeError):
                    retrans = 0

                rssi_dbm = _rcpi_to_rssi_dbm(signal_raw)

                clients.append({
                    "mac": mac,
                    "band": band,
                    "ssid": ssid,
                    "operating_standard": op_std,
                    "max_phy_rate": max_phy,
                    "last_dl_rate": last_dl,
                    "last_ul_rate": last_ul,
                    "signal_strength_dbm": rssi_dbm,
                    "bytes_rx": bytes_rx,
                    "bytes_tx": bytes_tx,
                    "connect_time": connect_time,
                    "retrans_count": retrans,
                    "is_affiliated": is_affiliated,
                })
    return clients


def _sanitize_mermaid_id(raw_id: str) -> str:
    """Create a valid mermaid node ID from a MAC/device ID."""
    return raw_id.replace(":", "").replace("-", "").replace(".", "_")


def _extract_single_topology(
    device_array: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Parse one ``Device.WiFi.DataElements.Network.Device.`` JSON array
    into a topology snapshot (nodes + edges + mermaid diagram).

    Args:
        device_array: The list of device dicts from the report.

    Returns:
        Dict with ``nodes``, ``edges``, ``mermaid``, ``device_count``.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    id_to_node: Dict[str, Dict[str, Any]] = {}

    for dev in device_array:
        idx = dev.get("index", "")
        device_id = dev.get("ID", "")
        backhaul_mac = dev.get("BackhaulMACAddress", "")
        backhaul_media = dev.get("BackhaulMediaType", "")
        backhaul_al_id = dev.get("BackhaulALID", "")

        try:
            phy_rate = int(dev.get("BackhaulPHYRate", "0"))
        except (ValueError, TypeError):
            phy_rate = 0

        is_gateway = (str(idx) == "1") or (not backhaul_mac and phy_rate == 0)

        manufacturer = dev.get("Manufacturer", "")
        model = dev.get("ManufacturerModel", "")
        serial = dev.get("SerialNumber", "")
        sw_version = dev.get("SoftwareVersion", "")

        # Radio info
        radios_raw = dev.get("Radio", [])
        radios = _extract_radio_info(radios_raw)
        connected_clients = _count_stas(radios_raw)

        # Device info (Airties)
        airties_info = dev.get("X_AIRTIES_DeviceInfo", {})
        mem_info = airties_info.get("MemoryStatus", {})
        proc_info = airties_info.get("ProcessStatus", {})

        memory = {
            "free": mem_info.get("Free", ""),
            "total": mem_info.get("Total", ""),
            "cached": mem_info.get("Cached", ""),
        }
        cpu = {
            "usage": proc_info.get("CPUUsage", ""),
            "temperature": proc_info.get("CPUTemperature", ""),
        }

        onboarded = dev.get("X_AIRTIES_Onboarded", "")
        service_active = dev.get("X_AIRTIES_ServiceActive", "")

        # Backhaul stats
        multi_ap = dev.get("MultiAPDevice", {})
        bh_stats = multi_ap.get("Backhaul", {}).get("Stats", {})
        bh_signal_raw = bh_stats.get("SignalStrength", "")
        bh_utilization = bh_stats.get("LinkUtilization", "")

        # Convert RCPI to average RSSI in dBm
        bh_signal = _rcpi_to_rssi_dbm(bh_signal_raw)

        # Extract connected clients from Radio > BSS > STA
        clients = _extract_clients(radios_raw)

        node = {
            "id": device_id,
            "index": str(idx),
            "is_gateway": is_gateway,
            "manufacturer": manufacturer,
            "model": model,
            "serial_number": serial,
            "software_version": sw_version,
            "backhaul_mac": backhaul_mac,
            "backhaul_media_type": backhaul_media,
            "backhaul_phy_rate": phy_rate,
            "backhaul_al_id": backhaul_al_id,
            "radios": radios,
            "connected_clients": connected_clients,
            "memory": memory,
            "cpu": cpu,
            "onboarded": onboarded,
            "service_active": service_active,
            "backhaul_signal_strength": bh_signal,
            "backhaul_link_utilization": bh_utilization,
            "clients": clients,
        }
        nodes.append(node)
        id_to_node[device_id] = node

    # Build auxiliary lookups for robust edge matching
    # Case-insensitive device ID lookup
    id_lower_map: Dict[str, str] = {did.lower(): did for did in id_to_node}

    # BSSID → device ID map: match backhaul_mac against BSS BSSIDs
    bssid_to_device: Dict[str, str] = {}
    for dev in device_array:
        dev_id = dev.get("ID", "")
        for radio in dev.get("Radio", []):
            for bss in radio.get("BSS", []):
                bssid = bss.get("BSSID", "")
                if bssid:
                    bssid_to_device[bssid.lower()] = dev_id

    gateway_node = next((n for n in nodes if n["is_gateway"]), None)

    # Build edges: match BackhaulALID -> parent device ID
    for node in nodes:
        if node["is_gateway"]:
            continue

        parent_id = node["backhaul_al_id"]
        matched_parent = None

        # 1) Direct BackhaulALID match
        if parent_id and parent_id in id_to_node:
            matched_parent = parent_id

        # 2) Case-insensitive BackhaulALID match
        if not matched_parent and parent_id:
            canonical = id_lower_map.get(parent_id.lower())
            if canonical:
                matched_parent = canonical

        # 3) BSSID match: find which device owns the BSS that this node
        #    is backhauled to (by matching backhaul_mac against BSS BSSIDs)
        if not matched_parent and node["backhaul_mac"]:
            bh_mac_lower = node["backhaul_mac"].lower()
            owner = bssid_to_device.get(bh_mac_lower)
            if owner and owner != node["id"]:
                matched_parent = owner

        # 4) Final fallback: connect to gateway if backhaul info exists
        if not matched_parent and gateway_node:
            has_backhaul_info = (
                node["backhaul_mac"]
                or node["backhaul_phy_rate"] > 0
                or node["backhaul_media_type"]
            )
            if has_backhaul_info:
                matched_parent = gateway_node["id"]

        if matched_parent:
            edges.append({
                "from_id": matched_parent,
                "to_id": node["id"],
                "media_type": node["backhaul_media_type"],
                "phy_rate": node["backhaul_phy_rate"],
                "signal_strength": node["backhaul_signal_strength"],
                "link_utilization": node["backhaul_link_utilization"],
                "is_wifi": _is_wifi_backhaul(node["backhaul_media_type"]),
            })

    # Generate mermaid diagram
    mermaid_lines = ["graph TD"]
    for node in nodes:
        mid = _sanitize_mermaid_id(node["id"])
        role = "Gateway" if node["is_gateway"] else "Extender"
        model_label = node["model"] or node["manufacturer"] or "Unknown"
        short_id = _short_mac(node["id"])
        label = f'{role}\\n{model_label}\\n{short_id}'
        if node["is_gateway"]:
            mermaid_lines.append(f'  {mid}["{label}"]')
        else:
            mermaid_lines.append(f'  {mid}("{label}")')

    for edge in edges:
        from_mid = _sanitize_mermaid_id(edge["from_id"])
        to_mid = _sanitize_mermaid_id(edge["to_id"])
        media_short = edge["media_type"].replace("IEEE ", "") if edge["media_type"] else "WiFi"
        rate_label = f"{edge['phy_rate']}Mbps" if edge["phy_rate"] else ""
        label = f"{media_short} {rate_label}".strip()
        if edge["is_wifi"]:
            mermaid_lines.append(f'  {from_mid} -."{label}".- {to_mid}')
        else:
            mermaid_lines.append(f'  {from_mid} --"{label}"--> {to_mid}')

    mermaid_str = "\n".join(mermaid_lines)

    return {
        "device_count": len(nodes),
        "nodes": nodes,
        "edges": edges,
        "mermaid": mermaid_str,
    }


def extract_mesh_topology_timeline(
    reports: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Extract mesh topology from **every** parsed telemetry report that contains
    ``Device.WiFi.DataElements.Network.Device.`` data.

    Each report snapshot captures the full mesh state at that point in time
    (devices, backhaul links, connected clients, signal strength, etc.).

    Args:
        reports: List of parsed report dicts (from ``parse_telemetry_reports``).

    Returns:
        Dict with:
          - ``snapshots``: list of topology snapshots sorted by time
          - ``total_snapshots``: count
          - ``time_range``: ``{start, end}`` ISO strings
    """
    snapshots: List[Dict[str, Any]] = []

    for report in reports:
        fields = report.get("fields", {})
        device_array = fields.get(_DATAELEMENTS_KEY)

        if not device_array or not isinstance(device_array, list):
            continue

        # Extract report timestamp
        report_time = report.get("time")
        log_ts = report.get("log_timestamp", "")
        profile = report.get("profile", "")

        time_str = ""
        if report_time:
            time_str = report_time.isoformat() if isinstance(report_time, datetime) else str(report_time)
        elif log_ts:
            time_str = str(log_ts)

        topology = _extract_single_topology(device_array)
        topology["time"] = time_str
        topology["log_timestamp"] = str(log_ts)
        topology["profile"] = profile

        snapshots.append(topology)

    # Sort by time
    snapshots.sort(key=lambda s: s.get("time", ""))

    time_range = {}
    if snapshots:
        time_range = {
            "start": snapshots[0].get("time", ""),
            "end": snapshots[-1].get("time", ""),
        }

    logger.info(
        f"[MeshTopology] Extracted {len(snapshots)} topology snapshots"
        + (f" from {time_range.get('start', '?')} to {time_range.get('end', '?')}"
           if time_range else "")
    )

    return {
        "snapshots": snapshots,
        "total_snapshots": len(snapshots),
        "time_range": time_range,
    }

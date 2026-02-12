"""
Device Info Extractor
======================

Parses key RDK log files to extract structured device metadata.

Adopted from dt-smart-cpe-agent/src/cpe_rdk_rag/core/info_extractor.py.

Currently supports:
    - version.txt: Firmware versions, build info, SDK version, SW upgrade detection
    - PARODUSlog.txt: Device model, serial number, MAC, reboot reason, network info
    - BootTime.log: Reboot history, boot cycle details, component uptimes

The extracted info is used by the Telemetry tab to enrich the Device Info card
and by the Regex Analyzer page for reboot boundary detection.
"""

from __future__ import annotations

import json
import logging
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# version.txt parser
# ---------------------------------------------------------------------------

# Fields in a single version block (10 lines per block)
_VERSION_FIELDS = [
    "MACHINE_NAME", "imagename", "BRANCH", "VERSION", "SPIN",
    "BUILD-TIME", "WORKFLOW-TYPE", "BUILD-ID", "Generated on", "SDK_VERSION",
]


def parse_version_txt(content: str) -> Dict[str, Any]:
    """
    Parse version.txt which may contain multiple repeated blocks.

    Each block is 10 lines::

        MACHINE_NAME=...
        imagename:...
        BRANCH=...
        VERSION=...
        SPIN=...
        BUILD-TIME="..."
        WORKFLOW-TYPE=...
        BUILD-ID=...
        Generated on ...
        SDK_VERSION=...

    Returns:
        Dict with:
            - machine_name, branch, sdk_version (from latest block)
            - firmware_versions: list of unique {version, build_id, build_time, ...}
            - sw_upgrade_detected: bool (True if more than one unique VERSION found)
            - sw_upgrade_detail: str description (e.g. "004.011.080 -> 004.011.082")
            - total_blocks: total version blocks found (approx log rotations)
    """
    if not content or not content.strip():
        return {}

    lines = [ln.strip() for ln in content.strip().splitlines() if ln.strip()]

    # Parse all lines into key=value blocks
    blocks: List[Dict[str, str]] = []
    current_block: Dict[str, str] = {}

    for line in lines:
        if line.startswith("MACHINE_NAME=") and current_block:
            blocks.append(current_block)
            current_block = {}

        if "=" in line:
            key, _, value = line.partition("=")
            current_block[key.strip()] = value.strip().strip('"')
        elif line.startswith("imagename:"):
            current_block["imagename"] = line.split(":", 1)[1].strip()
        elif line.startswith("Generated on"):
            current_block["Generated on"] = line.replace("Generated on", "").strip()

    if current_block:
        blocks.append(current_block)

    if not blocks:
        return {}

    # Deduplicate by VERSION+BUILD-ID
    seen_versions: OrderedDict[str, Dict[str, str]] = OrderedDict()
    for block in blocks:
        version = block.get("VERSION", "")
        build_id = block.get("BUILD-ID", "")
        key = f"{version}_{build_id}"
        if key not in seen_versions:
            seen_versions[key] = block

    unique_versions = list(seen_versions.values())
    latest = blocks[-1]

    firmware_versions = []
    for v in unique_versions:
        firmware_versions.append({
            "version": v.get("VERSION", ""),
            "build_id": v.get("BUILD-ID", ""),
            "build_time": v.get("BUILD-TIME", ""),
            "image_name": v.get("imagename", ""),
            "spin": v.get("SPIN", ""),
        })

    # SW upgrade detection
    sw_upgrade = len(unique_versions) > 1
    sw_detail = ""
    if sw_upgrade and firmware_versions:
        old_ver = firmware_versions[0]["version"]
        new_ver = firmware_versions[-1]["version"]
        sw_detail = f"{old_ver} → {new_ver}"

    return {
        "machine_name": latest.get("MACHINE_NAME", ""),
        "branch": latest.get("BRANCH", ""),
        "sdk_version": latest.get("SDK_VERSION", ""),
        "firmware_versions": firmware_versions,
        "sw_upgrade_detected": sw_upgrade,
        "sw_upgrade_detail": sw_detail,
        "total_blocks": len(blocks),
    }


def find_and_parse_version_txt(project_dir: Path) -> Dict[str, Any]:
    """
    Locate version.txt in the project's merged_logs directory and parse it.

    Searches in:
        1. {project_dir}/merged_logs/version.txt
        2. {project_dir}/version.txt (fallback)

    Args:
        project_dir: Path to the project directory.

    Returns:
        Parsed version info dict, or empty dict if not found.
    """
    search_paths = [
        project_dir / "merged_logs" / "version.txt",
        project_dir / "version.txt",
    ]

    for path in search_paths:
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                result = parse_version_txt(content)
                if result:
                    logger.info(
                        f"[InfoExtractor] Parsed {path}: "
                        f"SDK={result.get('sdk_version', 'N/A')}, "
                        f"upgrade={result.get('sw_upgrade_detected', False)}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"[InfoExtractor] Error parsing {path}: {e}")

    return {}


# ---------------------------------------------------------------------------
# PARODUSlog.txt parser
# ---------------------------------------------------------------------------

# Fields we want to extract from PARODUS startup blocks.
# Keys are normalised (hyphens → underscores) so that any mix of
# hw_serial_number / hw_serial-number / hw-serial-number all match.
_PARODUS_FIELDS_RAW = {
    "hw-model": "hw_model",
    "hw_serial-number": "serial_number",
    "hw_manufacturer": "manufacturer",
    "hw_last_reboot_reason": "last_reboot_reason",
    "fw_name": "fw_name",
    "boot_time": "boot_time_epoch",
    "hw_mac": "mac",
    "wan_ipv4_address": "wan_ipv4",
    "partner_id": "partner_id",
    "webpa_url": "webpa_url",
    "webpa_interface_used": "webpa_interface",
}
# Build a normalised lookup: replace all hyphens with underscores in the key
_PARODUS_FIELDS = {k.replace("-", "_"): v for k, v in _PARODUS_FIELDS_RAW.items()}


def _normalise_parodus_key(key: str) -> str:
    """Normalise a PARODUS field name so hyphens and underscores are equivalent."""
    return key.replace("-", "_")

# Mapping from X-WebPA-Convey JSON keys to our internal field names.
_WEBPA_CONVEY_FIELDS = {
    "hw-model": "hw_model",
    "hw-serial-number": "serial_number",
    "hw-manufacturer": "manufacturer",
    "fw-name": "fw_name",
    "boot-time": "boot_time_epoch",
    "hw-last-reboot-reason": "last_reboot_reason",
    "webpa-interface-used": "webpa_interface",
}

_PARODUS_RE = re.compile(
    r"PARODUS:\s+([\w_-]+)\s+is\s+(.+)$"
)

# Regex for X-WebPA-Convey Header JSON blob
_WEBPA_CONVEY_RE = re.compile(
    r"PARODUS:\s+X-WebPA-Convey Header:\s*\[\d+\](\{.+\})"
)

# Regex for Device_id mac line
_DEVICE_ID_MAC_RE = re.compile(
    r"PARODUS:\s+Device_id\s+mac:(\S+)"
)


def _parse_webpa_convey_json(json_str: str) -> Dict[str, str]:
    """Parse the X-WebPA-Convey JSON header and return mapped fields.

    The JSON values for string fields are sometimes double-quoted internally
    (e.g. ``"hw-model":"\\\"FGA2233\\\""``) so we strip surrounding quotes.
    """
    result: Dict[str, str] = {}
    try:
        raw = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return result

    for json_key, mapped_name in _WEBPA_CONVEY_FIELDS.items():
        val = raw.get(json_key)
        if val is None:
            continue
        val_str = str(val).strip().strip('"').strip("'")
        if val_str:
            result[mapped_name] = val_str

    return result


def parse_parodus_log(content: str) -> Dict[str, Any]:
    """
    Parse PARODUSlog.txt for device identity and network info.

    Scans for PARODUS startup blocks (lines like
    ``PARODUS: hw-model is DT-HGW01A-ARC``).  Multiple startup blocks
    may exist (one per reboot).  We collect ALL startup blocks to track
    changes (e.g. WAN IP changes, reboot reason changes).

    Also parses the ``X-WebPA-Convey Header`` JSON blob and
    ``Device_id mac:`` lines as secondary sources for device identity
    when the "field is value" lines are not present.

    Args:
        content: Raw text content of PARODUSlog.txt.

    Returns:
        Dict with latest device values plus:
            - parodus_reboot_history: list of {reason, timestamp}
            - wan_ip_history: list of {ip, timestamp}
            - parodus_startup_count: int
    """
    if not content or not content.strip():
        return {}

    startup_blocks: List[Dict[str, str]] = []
    current_block: Dict[str, str] = {}
    current_timestamp: str = ""

    # Collect X-WebPA-Convey and Device_id mac data per startup block
    current_convey: Dict[str, str] = {}
    current_device_mac: str = ""

    for line in content.splitlines():
        # Extract timestamp from the log line
        ts_match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)

        # --- Try "field is value" pattern ---
        m = _PARODUS_RE.search(line)
        if m:
            field_name_raw = m.group(1)
            field_value = m.group(2).strip()
            norm_key = _normalise_parodus_key(field_name_raw)

            if norm_key in _PARODUS_FIELDS:
                mapped_name = _PARODUS_FIELDS[norm_key]

                # Detect start of a new startup block (hw_model is always first)
                if norm_key == "hw_model" and current_block:
                    # Merge convey data into block (only fills gaps)
                    for k, v in current_convey.items():
                        current_block.setdefault(k, v)
                    if current_device_mac:
                        current_block.setdefault("mac", current_device_mac)

                    current_block["_timestamp"] = current_timestamp
                    startup_blocks.append(current_block)
                    current_block = {}
                    current_convey = {}
                    current_device_mac = ""

                # Clean up "updated with value: X" pattern for wan_ipv4_address
                if mapped_name == "wan_ipv4" and field_value.startswith("updated with value:"):
                    field_value = field_value.replace("updated with value:", "").strip()

                # Strip surrounding quotes from values like '"FGA2233"'
                field_value = field_value.strip('"').strip("'")

                current_block[mapped_name] = field_value

                if ts_match and not current_timestamp:
                    current_timestamp = ts_match.group(1)
                elif ts_match and norm_key == "hw_model":
                    current_timestamp = ts_match.group(1)

            continue

        # --- Try X-WebPA-Convey Header JSON ---
        convey_m = _WEBPA_CONVEY_RE.search(line)
        if convey_m:
            current_convey = _parse_webpa_convey_json(convey_m.group(1))
            if ts_match and not current_timestamp:
                current_timestamp = ts_match.group(1)
            continue

        # --- Try Device_id mac ---
        mac_m = _DEVICE_ID_MAC_RE.search(line)
        if mac_m:
            current_device_mac = mac_m.group(1).strip()
            if ts_match and not current_timestamp:
                current_timestamp = ts_match.group(1)
            continue

    # Don't forget the last block — merge convey + mac
    if current_block or current_convey or current_device_mac:
        for k, v in current_convey.items():
            current_block.setdefault(k, v)
        if current_device_mac:
            current_block.setdefault("mac", current_device_mac)
        if current_block:
            current_block["_timestamp"] = current_timestamp
            startup_blocks.append(current_block)

    if not startup_blocks:
        # Last resort: if we only found X-WebPA-Convey without any "field is"
        # lines, build a single block from convey data
        if current_convey:
            block = dict(current_convey)
            if current_device_mac:
                block.setdefault("mac", current_device_mac)
            block["_timestamp"] = current_timestamp
            startup_blocks.append(block)
        else:
            return {}

    # Latest startup block has the most recent info
    latest = startup_blocks[-1]

    result: Dict[str, Any] = {}
    all_mapped_keys = set(_PARODUS_FIELDS.values()) | set(_WEBPA_CONVEY_FIELDS.values())
    for key in all_mapped_keys:
        if key in latest:
            result[key] = latest[key]

    # Track WAN IP changes across restarts
    wan_ips = []
    for block in startup_blocks:
        ip = block.get("wan_ipv4", "")
        ts = block.get("_timestamp", "")
        if ip:
            wan_ips.append({"ip": ip, "timestamp": ts})
    if wan_ips:
        result["wan_ip_history"] = wan_ips

    # Track reboot reasons from PARODUS perspective
    reboot_reasons = []
    for block in startup_blocks:
        reason = block.get("last_reboot_reason", "")
        ts = block.get("_timestamp", "")
        if reason:
            reboot_reasons.append({"reason": reason, "timestamp": ts})
    if reboot_reasons:
        result["parodus_reboot_history"] = reboot_reasons

    result["parodus_startup_count"] = len(startup_blocks)

    return result


# ---------------------------------------------------------------------------
# telemetry_marker.txt — WAN Operating Mode
# ---------------------------------------------------------------------------

_WAN_MODE_RE = re.compile(r"WAN Operating Mode:(\S+)")


def parse_wan_mode_from_marker(content: str) -> str:
    """
    Extract the WAN Operating Mode from ``telemetry_marker.txt``.

    Looks for lines like::

        WAN Operating Mode:GPON

    Args:
        content: Raw text content of telemetry_marker.txt.

    Returns:
        The WAN mode string (e.g. ``"GPON"``, ``"WANoE"``, ``"Ethernet"``)
        or ``""`` if not found.
    """
    if not content:
        return ""
    m = _WAN_MODE_RE.search(content)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Fallback device info builder
# ---------------------------------------------------------------------------


def find_and_build_fallback_device_info(project_dir: Path) -> Dict[str, str]:
    """
    Build a ``device_info`` dict from non-telemetry sources.

    This is used as a fallback when ``telemetry2_0.txt`` has no parsable
    reports.  It combines data from:

        1. ``PARODUSlog.txt`` — device model, serial, manufacturer, MAC,
           firmware version, reboot reason (via both "field is value"
           lines and the X-WebPA-Convey JSON header).
        2. ``telemetry_marker.txt`` — WAN Operating Mode.
        3. ``version.txt`` — SDK version, SW upgrade detection.

    The returned dict uses the same keys as
    :func:`~logai.telemetry_parser.extract_telemetry_summary` so that
    the CPE Overview and Telemetry pages can render it without changes.

    Args:
        project_dir: Path to the CPE directory (e.g.
            ``UPLOAD_DIRECTORY/{user_id}/{project_id}/{cpe_serial}``).

    Returns:
        A dict with keys like ``model``, ``serial``, ``manufacturer``,
        ``mac``, ``version``, ``wan_type``, ``sdk_version``, ``sw_upgrade``.
        Returns an empty dict if no fallback data can be found.
    """
    device_info: Dict[str, str] = {}

    # --- 1. PARODUSlog.txt ---
    parodus_path = project_dir / "PARODUSlog.txt"
    if parodus_path.exists() and parodus_path.is_file():
        try:
            raw = parodus_path.read_text(encoding="utf-8", errors="ignore")
            parodus = parse_parodus_log(raw)
            if parodus:
                # Map PARODUS field names to the standard device_info keys
                _map = {
                    "hw_model": "model",
                    "serial_number": "serial",
                    "manufacturer": "manufacturer",
                    "mac": "mac",
                    "fw_name": "version",
                    "last_reboot_reason": "last_reboot_reason",
                    "boot_time_epoch": "boot_time_epoch",
                }
                for src_key, dst_key in _map.items():
                    val = parodus.get(src_key, "")
                    if val:
                        device_info[dst_key] = str(val)
                logger.debug(
                    f"[InfoExtractor] Fallback PARODUSlog: "
                    f"model={device_info.get('model', 'N/A')}, "
                    f"serial={device_info.get('serial', 'N/A')}"
                )
        except Exception as e:
            logger.warning(
                f"[InfoExtractor] Error reading fallback PARODUSlog "
                f"{parodus_path}: {e}"
            )

    # --- 2. telemetry_marker.txt — WAN mode ---
    marker_path = project_dir / "telemetry_marker.txt"
    if marker_path.exists() and marker_path.is_file():
        try:
            raw = marker_path.read_text(encoding="utf-8", errors="ignore")
            wan_mode = parse_wan_mode_from_marker(raw)
            if wan_mode:
                device_info["wan_type"] = wan_mode
                logger.debug(
                    f"[InfoExtractor] Fallback marker WAN mode: {wan_mode}"
                )
        except Exception as e:
            logger.warning(
                f"[InfoExtractor] Error reading fallback marker "
                f"{marker_path}: {e}"
            )

    # --- 3. version.txt — SDK version, SW upgrade ---
    try:
        version_info = find_and_parse_version_txt(project_dir)
        if version_info:
            if version_info.get("sdk_version"):
                device_info["sdk_version"] = version_info["sdk_version"]
            if version_info.get("sw_upgrade_detected"):
                device_info["sw_upgrade"] = (
                    f"Yes ({version_info['sw_upgrade_detail']})"
                )
            else:
                device_info["sw_upgrade"] = "No"
            # Use machine_name as a fallback for model if not set
            if not device_info.get("model") and version_info.get("machine_name"):
                device_info["model"] = version_info["machine_name"]
    except Exception as e:
        logger.warning(
            f"[InfoExtractor] Error reading fallback version.txt "
            f"in {project_dir}: {e}"
        )

    return device_info


# ---------------------------------------------------------------------------
# BootTime.log parser
# ---------------------------------------------------------------------------

_BOOTTIME_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
_BOOTTIME_UPTIME_RE = re.compile(r"\[BootUpTime\]\s+(\w+)=(\d+)")
_REBOOT_REASON_RE = re.compile(r"Received reboot_reason as:(.+)$")


_NTP_JUMP_THRESHOLD_SECONDS = 86400  # 24 hours — any forward jump bigger than
                                      # this indicates NTP sync corrected the clock


def _pick_ntp_timestamp(timestamps: List[str]) -> str:
    """
    Given the ordered list of ISO timestamps from a single boot cycle,
    return the first *post-NTP-sync* timestamp.

    Before NTP syncs the device clock shows the firmware **build time**.
    After NTP syncs there is a large forward jump (typically months/years).
    We detect that jump and return the first timestamp after it.

    If no jump is detected the last timestamp is returned (best guess).
    If the list is empty, returns ``""``.
    """
    if not timestamps:
        return ""
    if len(timestamps) == 1:
        return timestamps[0]

    from datetime import datetime as _dt

    parsed = []
    for ts in timestamps:
        try:
            parsed.append(_dt.fromisoformat(ts))
        except ValueError:
            parsed.append(None)

    for i in range(1, len(parsed)):
        if parsed[i] is None or parsed[i - 1] is None:
            continue
        delta = (parsed[i] - parsed[i - 1]).total_seconds()
        if delta > _NTP_JUMP_THRESHOLD_SECONDS:
            return timestamps[i]

    # No obvious NTP jump found — use last timestamp
    return timestamps[-1]


def parse_boottime_log(content: str) -> Dict[str, Any]:
    """
    Parse BootTime.log for reboot history and component boot times.

    Each boot cycle starts with a ``Lan_init_start`` line.  We detect
    cycles by looking for ``Lan_init_start`` entries.

    **Timestamp selection**: Early log lines in each boot cycle carry
    the firmware build timestamp (pre-NTP).  After NTP syncs the clock
    jumps to the real time.  We detect that jump and record the first
    post-NTP timestamp as the cycle's reboot time.

    Args:
        content: Raw text content of BootTime.log.

    Returns:
        Dict with:
            - total_reboots: number of boot cycles
            - reboot_history: list of {reason, timestamp, uptimes}
            - reboot_summary: {reason: count}
    """
    if not content or not content.strip():
        return {}

    lines = content.strip().splitlines()

    # Split into boot cycles (each starts with Lan_init_start)
    cycles: List[Dict[str, Any]] = []
    current_cycle: Optional[Dict[str, Any]] = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        ts_match = _BOOTTIME_TS_RE.match(line)

        # Check for Lan_init_start = start of new boot cycle
        uptime_match = _BOOTTIME_UPTIME_RE.search(line)
        if uptime_match and uptime_match.group(1) == "Lan_init_start":
            # Save previous cycle if exists
            if current_cycle is not None:
                # Resolve the real timestamp (post-NTP) before saving
                current_cycle["timestamp"] = _pick_ntp_timestamp(
                    current_cycle.pop("_timestamps")
                )
                cycles.append(current_cycle)
            # Start new cycle — collect ALL timestamps to detect NTP jump later
            current_cycle = {
                "_timestamps": [ts_match.group(1)] if ts_match else [],
                "timestamp": "",
                "reason": "",
                "uptimes": {"Lan_init_start": int(uptime_match.group(2))},
            }
            continue

        if current_cycle is None:
            continue

        # Collect every timestamp we see in this cycle
        if ts_match:
            current_cycle["_timestamps"].append(ts_match.group(1))

        # Check for reboot reason
        reason_match = _REBOOT_REASON_RE.search(line)
        if reason_match:
            current_cycle["reason"] = reason_match.group(1).strip()
            continue

        # Check for uptime entries
        if uptime_match:
            key = uptime_match.group(1)
            value = int(uptime_match.group(2))
            current_cycle["uptimes"][key] = value

    # Don't forget the last cycle
    if current_cycle is not None:
        current_cycle["timestamp"] = _pick_ntp_timestamp(
            current_cycle.pop("_timestamps")
        )
        cycles.append(current_cycle)

    if not cycles:
        return {}

    # Build reboot summary
    reason_counts: Dict[str, int] = {}
    for cycle in cycles:
        reason = cycle.get("reason", "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "total_reboots": len(cycles),
        "reboot_history": cycles,
        "reboot_summary": reason_counts,
    }


# ---------------------------------------------------------------------------
# Reboot extraction coordinator
# ---------------------------------------------------------------------------


def _reboots_cache_is_fresh(
    cache_path: Path,
    source_paths: List[Path],
) -> bool:
    """Return True if *cache_path* exists and is newer than all *source_paths*."""
    if not cache_path.exists():
        return False
    cache_mtime = cache_path.stat().st_mtime
    for src in source_paths:
        if src.exists() and src.stat().st_mtime > cache_mtime:
            return False
    return True


def find_and_extract_reboots(project_dir: Path) -> List[Dict[str, str]]:
    """
    Extract reboot timestamps from a project directory.

    Results are cached to ``{project_dir}/.reboots_cache.json``.
    The cache is automatically invalidated when the source log files
    (``BootTime.log`` or ``PARODUSlog.txt``) are modified (mtime check).

    Tries multiple sources in priority order:
        1. BootTime.log  (most reliable -- explicit boot-cycle markers)
        2. PARODUSlog.txt (fallback -- PARODUS startup blocks)

    Searches for files directly in *project_dir* (where merged logs
    are stored after upload processing).

    Args:
        project_dir: Path to the project directory
                     (e.g. ``UPLOAD_DIRECTORY/{user_id}/{project_id}``).

    Returns:
        Sorted list of ``{"timestamp": "<ISO-datetime>", "reason": "..."}``
        dicts.  Returns an empty list when no reboot data is found.
    """
    cache_path = project_dir / ".reboots_cache.json"
    bt_path = project_dir / "BootTime.log"
    p_path = project_dir / "PARODUSlog.txt"

    # --- Check cache ---
    if _reboots_cache_is_fresh(cache_path, [bt_path, p_path]):
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                logger.debug(
                    f"[InfoExtractor] Returning {len(cached)} cached reboots "
                    f"from {cache_path}"
                )
                return cached
        except Exception as e:
            logger.warning(f"[InfoExtractor] Bad cache file {cache_path}: {e}")

    # --- Parse fresh ---
    reboots: List[Dict[str, str]] = []

    # --- Try BootTime.log first ---
    if bt_path.exists() and bt_path.is_file():
        try:
            content = bt_path.read_text(encoding="utf-8", errors="ignore")
            bt_info = parse_boottime_log(content)
            for cycle in bt_info.get("reboot_history", []):
                ts = cycle.get("timestamp", "")
                reason = cycle.get("reason", "unknown")
                if ts:
                    reboots.append({"timestamp": ts, "reason": reason})
            if reboots:
                logger.info(
                    f"[InfoExtractor] Found {len(reboots)} reboots "
                    f"from {bt_path}"
                )
                reboots.sort(key=lambda r: r["timestamp"])
                _write_reboots_cache(cache_path, reboots)
                return reboots
        except Exception as e:
            logger.warning(f"[InfoExtractor] Error parsing {bt_path}: {e}")

    # --- Fallback: PARODUSlog.txt ---
    if p_path.exists() and p_path.is_file():
        try:
            content = p_path.read_text(encoding="utf-8", errors="ignore")
            p_info = parse_parodus_log(content)
            for entry in p_info.get("parodus_reboot_history", []):
                ts = entry.get("timestamp", "")
                reason = entry.get("reason", "unknown")
                if ts:
                    reboots.append({"timestamp": ts, "reason": reason})
            if reboots:
                logger.info(
                    f"[InfoExtractor] Found {len(reboots)} reboots "
                    f"from {p_path}"
                )
                reboots.sort(key=lambda r: r["timestamp"])
                _write_reboots_cache(cache_path, reboots)
                return reboots
        except Exception as e:
            logger.warning(f"[InfoExtractor] Error parsing {p_path}: {e}")

    logger.info(f"[InfoExtractor] No reboot data found in {project_dir}")
    # Cache the empty result too so we don't re-parse on every call
    _write_reboots_cache(cache_path, reboots)
    return reboots


def _write_reboots_cache(
    cache_path: Path,
    reboots: List[Dict[str, str]],
) -> None:
    """Write reboots list to the JSON cache file."""
    try:
        cache_path.write_text(
            json.dumps(reboots, indent=2),
            encoding="utf-8",
        )
        logger.debug(f"[InfoExtractor] Wrote reboots cache to {cache_path}")
    except Exception as e:
        logger.warning(f"[InfoExtractor] Failed to write cache {cache_path}: {e}")

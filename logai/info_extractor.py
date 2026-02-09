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

# Fields we want to extract from PARODUS startup blocks
_PARODUS_FIELDS = {
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

_PARODUS_RE = re.compile(
    r"PARODUS:\s+([\w_-]+)\s+is\s+(.+)$"
)


def parse_parodus_log(content: str) -> Dict[str, Any]:
    """
    Parse PARODUSlog.txt for device identity and network info.

    Scans for PARODUS startup blocks (lines like
    ``PARODUS: hw-model is DT-HGW01A-ARC``).  Multiple startup blocks
    may exist (one per reboot).  We collect ALL startup blocks to track
    changes (e.g. WAN IP changes, reboot reason changes).

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

    for line in content.splitlines():
        m = _PARODUS_RE.search(line)
        if not m:
            continue

        field_name = m.group(1)
        field_value = m.group(2).strip()

        if field_name not in _PARODUS_FIELDS:
            continue

        mapped_name = _PARODUS_FIELDS[field_name]

        # Detect start of a new startup block (hw-model is always first)
        if field_name == "hw-model" and current_block:
            current_block["_timestamp"] = current_timestamp
            startup_blocks.append(current_block)
            current_block = {}

        # Clean up "updated with value: X" pattern for wan_ipv4_address
        if mapped_name == "wan_ipv4" and field_value.startswith("updated with value:"):
            field_value = field_value.replace("updated with value:", "").strip()

        current_block[mapped_name] = field_value

        # Extract timestamp from the log line
        ts_match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
        if ts_match and not current_timestamp:
            current_timestamp = ts_match.group(1)
        elif ts_match and field_name == "hw-model":
            current_timestamp = ts_match.group(1)

    # Don't forget the last block
    if current_block:
        current_block["_timestamp"] = current_timestamp
        startup_blocks.append(current_block)

    if not startup_blocks:
        return {}

    # Latest startup block has the most recent info
    latest = startup_blocks[-1]

    result: Dict[str, Any] = {}
    for key in _PARODUS_FIELDS.values():
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

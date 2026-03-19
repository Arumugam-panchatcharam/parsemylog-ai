"""
Device Info Extractor
======================

Parses key RDK log files to extract structured device metadata.

Currently supports:
    - version.txt: Firmware versions, build info, SDK version, SW upgrade detection
    - PARODUSlog.txt: Device model, serial number, MAC, reboot reason, network info
    - parodusStart-log.txt: Fallback for device identity (modelName/serialNumber from hal, parodus command line)
    - BootTime.log: Reboot history, boot cycle details, component uptimes
    - selfHeal.txt: IPv6 support, Telemetry 2.0 flag, CPU usage samples, MemTotal/MemFree/MemAvailable
    - telemetry_marker.txt: WAN mode, Processor Temperature, Flash Usage, Available Memory, Process Memory by feature

Library usage (multi-agent / portable):
    All parse_* functions accept raw content strings. Use extract_device_info_from_paths()
    for explicit path-based extraction without assuming project structure.
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


_VERSION_CACHE_FILE = ".version_cache.json"
_DEVICE_INFO_CACHE_FILE = ".device_info_cache.json"


def _cache_is_fresh(cache_path: Path, source_paths: List[Path]) -> bool:
    """Return True if *cache_path* exists and is newer than all *source_paths*."""
    if not cache_path.exists():
        return False
    cache_mtime = cache_path.stat().st_mtime
    for src in source_paths:
        if src.exists() and src.stat().st_mtime > cache_mtime:
            return False
    return True


def _write_json_cache(cache_path: Path, data: Any) -> None:
    try:
        cache_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(f"[InfoExtractor] Failed to write cache {cache_path}: {exc}")


def _read_json_cache(cache_path: Path) -> Optional[Any]:
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[InfoExtractor] Bad cache {cache_path}: {exc}")
        return None


def find_and_parse_version_txt(
    project_dir: Path,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Locate version.txt in the project's merged_logs directory and parse it.

    Searches in:
        1. {project_dir}/version.txt
        2. {project_dir}/merged_logs/version.txt (fallback)

    Results are cached to ``<project_dir>/.version_cache.json`` with
    mtime-based invalidation.

    Args:
        project_dir: Path to the project directory.
        force: Bypass cache and re-parse.

    Returns:
        Parsed version info dict, or empty dict if not found.
    """
    cache_path = project_dir / _VERSION_CACHE_FILE
    search_paths = [
        project_dir / "version.txt",
        project_dir / "merged_logs" / "version.txt",
    ]

    if not force and _cache_is_fresh(cache_path, search_paths):
        cached = _read_json_cache(cache_path)
        if cached is not None:
            logger.debug(f"[InfoExtractor] version_txt cache hit for {project_dir}")
            return cached

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
                    _write_json_cache(cache_path, result)
                    return result
            except Exception as e:
                logger.warning(f"[InfoExtractor] Error parsing {path}: {e}")

    _write_json_cache(cache_path, {})
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

# parodusStart-log.txt: "[mod=PARODUS, lvl=Info] modelName returned from hal:DT-HGW01A-ARC"
_PARODUS_START_RETURNED_RE = re.compile(
    r"\]\s*(\w+)\s+returned\s+from\s+hal\s*:\s*(.+)$"
)
# "Manufacturer Name is Arcadyan", "lastRebootReason is hard-reboot", "BaseMacAddress is 34:19:4D:C5:9A:5F"
_PARODUS_START_IS_RE = re.compile(
    r"\]\s*(?:Modified\s+)?(lastRebootReason|Manufacturer Name|BaseMacAddress)\s+is\s+(.+)$"
)
# parodus command line: --hw-model="DT-HGW01A-ARC" or --hw-serial-number=901A...
_PARODUS_START_CMD_HW_MODEL_RE = re.compile(r"--hw-model=\"?([^\"\s]+)\"?")
_PARODUS_START_CMD_SERIAL_RE = re.compile(r"--hw-serial-number=(\S+)")
_PARODUS_START_CMD_MANUFACTURER_RE = re.compile(r"--hw-manufacturer=\"?([^\"\s]+)\"?")
_PARODUS_START_CMD_LAST_REBOOT_RE = re.compile(r"--hw-last-reboot-reason=(\S+)")
_PARODUS_START_CMD_FW_RE = re.compile(r"--fw-name=(\S+)")
_PARODUS_START_CMD_BOOT_TIME_RE = re.compile(r"--boot-time=(\d+)")
_PARODUS_START_CMD_MAC_RE = re.compile(r"--hw-mac=(\S+)")
_PARODUS_START_CMD_WAN_RE = re.compile(r"--wan-ipv4-address=(\S+)")

# parodusStart-log "X returned from hal:Y" key -> internal name
_PARODUS_START_HAL_KEYS = {
    "modelName": "hw_model",
    "serialNumber": "serial_number",
    "firmwareVersion": "fw_name",
    "bootTime": "boot_time_epoch",
}

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
# parodusStart-log.txt parser (fallback when PARODUSlog.txt not available)
# ---------------------------------------------------------------------------

def parse_parodus_start_log(content: str) -> Dict[str, Any]:
    """
    Parse parodusStart-log.txt for device identity.

    Lines like:
        [mod=PARODUS, lvl=Info] modelName returned from hal:DT-HGW01A-ARC
        [mod=PARODUS, lvl=Info] Manufacturer Name is Arcadyan
        parodus command formed is: /usr/bin/parodus --hw-model="DT-HGW01A-ARC" ...

    Returns a dict with the same keys as parse_parodus_log (hw_model, serial_number,
    manufacturer, last_reboot_reason, fw_name, boot_time_epoch, mac, wan_ipv4, etc.)
    so it can be used as a drop-in fallback in find_and_build_fallback_device_info.
    """
    if not content or not content.strip():
        return {}

    result: Dict[str, Any] = {}
    last_ts = ""

    for line in content.splitlines():
        # Timestamp at start of line
        ts_m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
        if ts_m:
            last_ts = ts_m.group(1)

        # "X returned from hal:Y"
        m = _PARODUS_START_RETURNED_RE.search(line)
        if m:
            key, value = m.group(1).strip(), m.group(2).strip()
            if key in _PARODUS_START_HAL_KEYS:
                result[_PARODUS_START_HAL_KEYS[key]] = value
            continue

        # "Manufacturer Name is X", "lastRebootReason is X", "BaseMacAddress is X"
        m2 = _PARODUS_START_IS_RE.search(line)
        if m2:
            key, value = m2.group(1).strip(), m2.group(2).strip()
            if key == "Manufacturer Name":
                result["manufacturer"] = value
            elif key == "lastRebootReason":
                result["last_reboot_reason"] = value
            elif key == "BaseMacAddress":
                result["mac"] = value
            continue

        # parodus command line (last occurrence wins)
        if "parodus command formed is:" in line or "parodus command formed is" in line:
            for regex, attr in [
                (_PARODUS_START_CMD_HW_MODEL_RE, "hw_model"),
                (_PARODUS_START_CMD_SERIAL_RE, "serial_number"),
                (_PARODUS_START_CMD_MANUFACTURER_RE, "manufacturer"),
                (_PARODUS_START_CMD_LAST_REBOOT_RE, "last_reboot_reason"),
                (_PARODUS_START_CMD_FW_RE, "fw_name"),
                (_PARODUS_START_CMD_BOOT_TIME_RE, "boot_time_epoch"),
                (_PARODUS_START_CMD_MAC_RE, "mac"),
                (_PARODUS_START_CMD_WAN_RE, "wan_ipv4"),
            ]:
                mo = regex.search(line)
                if mo and mo.group(1):
                    result[attr] = mo.group(1).strip()

    if result:
        if last_ts and "parodus_reboot_history" not in result and result.get("last_reboot_reason"):
            result["parodus_reboot_history"] = [
                {"reason": result["last_reboot_reason"], "timestamp": last_ts}
            ]
        result["parodus_startup_count"] = 1
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
# selfHeal.txt parser — IPv6, Telemetry 2.0, CPU usage, memory
# ---------------------------------------------------------------------------

_SELFHEAL_IPV6_RE = re.compile(r"\[?RDKB_SELFHEAL\]?\s*:\s*Global IPv6 is present", re.IGNORECASE)
_SELFHEAL_TELEMETRY2_RE = re.compile(
    r"Telemetry 2\.0 feature is (true|false)", re.IGNORECASE
)
_SELFHEAL_CPU_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}).*?RDKB_SELFHEAL.*?CPU usage is (\d+)\s+at timestamp\s+([\d:]+)",
    re.IGNORECASE,
)
_SELFHEAL_MEMTOTAL_RE = re.compile(r"MemTotal:\s*(\d+)\s*kB")
_SELFHEAL_MEMFREE_RE = re.compile(r"MemFree:\s*(\d+)\s*kB")
_SELFHEAL_MEMAVAIL_RE = re.compile(r"MemAvailable:\s*(\d+)\s*kB")


def parse_selfheal_txt(content: str) -> Dict[str, Any]:
    """
    Parse selfHeal.txt for IPv6 support, Telemetry 2.0 flag, CPU usage samples,
    and periodic memory (MemTotal/MemFree/MemAvailable).

    Returns:
        - ipv6_present: bool
        - telemetry2_enabled: bool or None if not found
        - cpu_usage_samples: list of {timestamp_iso, timestamp_raw, cpu_usage_pct}
        - mem_snapshot: {MemTotal_kB, MemFree_kB, MemAvailable_kB} from latest block
    """
    if not content or not content.strip():
        return {}

    out: Dict[str, Any] = {
        "ipv6_present": False,
        "telemetry2_enabled": None,
        "cpu_usage_samples": [],
        "mem_snapshot": {},
    }

    lines = content.splitlines()
    for i, line in enumerate(lines):
        if _SELFHEAL_IPV6_RE.search(line):
            out["ipv6_present"] = True
        m = _SELFHEAL_TELEMETRY2_RE.search(line)
        if m:
            out["telemetry2_enabled"] = m.group(1).lower() == "true"
        m = _SELFHEAL_CPU_RE.search(line)
        if m:
            out["cpu_usage_samples"].append({
                "timestamp_iso": m.group(1),
                "timestamp_raw": m.group(3),
                "cpu_usage_pct": int(m.group(2)),
            })
        if _SELFHEAL_MEMTOTAL_RE.search(line):
            mt = _SELFHEAL_MEMTOTAL_RE.search(line)
            if mt:
                out["mem_snapshot"]["MemTotal_kB"] = int(mt.group(1))
            for j in range(i + 1, min(i + 5, len(lines))):
                n = lines[j]
                if not n.strip():
                    break
                mf = _SELFHEAL_MEMFREE_RE.search(n)
                if mf:
                    out["mem_snapshot"]["MemFree_kB"] = int(mf.group(1))
                ma = _SELFHEAL_MEMAVAIL_RE.search(n)
                if ma:
                    out["mem_snapshot"]["MemAvailable_kB"] = int(ma.group(1))

    return out


def find_and_parse_selfheal(project_dir: Path) -> Dict[str, Any]:
    """Locate selfHeal.txt (or selfheal.txt) in project_dir and parse it."""
    for name in ("selfHeal.txt", "selfheal.txt", "SelfHeal.txt"):
        path = project_dir / name
        if path.exists() and path.is_file():
            try:
                raw = path.read_text(encoding="utf-8", errors="ignore")
                return parse_selfheal_txt(raw)
            except Exception as e:
                logger.warning(f"[InfoExtractor] Error reading {path}: {e}")
    return {}


# ---------------------------------------------------------------------------
# telemetry_marker.txt — extended (Processor Temp, Flash, Memory, Process summary)
# ---------------------------------------------------------------------------

_MARKER_PROC_TEMP_RE = re.compile(r"Processor Temperature:\s*(\d+)")
_MARKER_FLASH_TOTAL_RE = re.compile(r"Flash Usage:Total:([\d.]+)M")
_MARKER_FLASH_USED_RE = re.compile(r"Flash Usage:Used:([\d.]+)M")
_MARKER_FLASH_FREE_RE = re.compile(r"Flash Usage:Free:([\d.]+)M")
_MARKER_FLASH_PCT_RE = re.compile(r"Flash Usage:Percentage:(\d+)")
_MARKER_AVAIL_MEM_RE = re.compile(r"Available Memory:\s*(\d+)")
# Feature_Memory_usage: PID=...|NAME=...|RSS=...|VSZ=...; ...
_MARKER_PROCESS_LINE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\s+([A-Za-z0-9_]+_Memory_[uU]sage):\s*(.+)"
)


def parse_telemetry_marker_extended(content: str) -> Dict[str, Any]:
    """
    Parse telemetry_marker.txt for Processor Temperature, Flash Usage,
    Available Memory, and Device Process Memory Summary (per-feature).

    Returns:
        - wan_mode: str (from existing parse_wan_mode_from_marker)
        - processor_temperature: list of {timestamp, value_c}
        - flash_usage: list of {timestamp, Total_M, Used_M, Free_M, Percentage}
        - available_memory: list of {timestamp, value_kB}
        - process_memory_by_feature: list of {timestamp, feature_name, entries}
          where entries are list of {pid, name, rss_kb, vsz_kb} or raw string
    """
    if not content or not content.strip():
        return {}

    out: Dict[str, Any] = {
        "wan_mode": parse_wan_mode_from_marker(content),
        "processor_temperature": [],
        "flash_usage": [],
        "available_memory": [],
        "process_memory_by_feature": [],
    }

    lines = content.splitlines()
    current_ts = ""
    for i, line in enumerate(lines):
        ts_m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
        if ts_m:
            current_ts = ts_m.group(1)

        m = _MARKER_PROC_TEMP_RE.search(line)
        if m:
            out["processor_temperature"].append({
                "timestamp": current_ts,
                "value_c": int(m.group(1)),
            })

        if "Flash Usage:Total:" in line:
            mt = _MARKER_FLASH_TOTAL_RE.search(line)
            entry = {"timestamp": current_ts}
            if mt:
                entry["Total_M"] = float(mt.group(1))
            for j in range(i + 1, min(i + 5, len(lines))):
                n = lines[j]
                if re.match(r"^\d{4}-\d{2}-\d{2}T", n) and "Flash Usage" not in n:
                    break
                mu = _MARKER_FLASH_USED_RE.search(n)
                mf = _MARKER_FLASH_FREE_RE.search(n)
                mp = _MARKER_FLASH_PCT_RE.search(n)
                if mu:
                    entry["Used_M"] = float(mu.group(1))
                if mf:
                    entry["Free_M"] = float(mf.group(1))
                if mp:
                    entry["Percentage"] = int(mp.group(1))
            if len(entry) > 1:
                out["flash_usage"].append(entry)

        m = _MARKER_AVAIL_MEM_RE.search(line)
        if m and "Available Memory:" in line:
            out["available_memory"].append({
                "timestamp": current_ts,
                "value_kB": int(m.group(1)),
            })

        # Device Process Memory Summary: "2025-12-13T22:56:00 Mesh_Memory_usage: PID=9923|NAME=..."
        m = _MARKER_PROCESS_LINE_RE.match(line)
        if m:
            ts, feature, rest = m.group(1), m.group(2), m.group(3)
            entries = []
            for part in rest.split(";"):
                part = part.strip()
                if not part or " not running" in part:
                    continue
                # PID=123|NAME=proc|RSS=1000 KB|VSZ=2000 KB
                pid_m = re.search(r"PID=(\d+)", part)
                name_m = re.search(r"NAME=([^|]+)", part)
                rss_m = re.search(r"RSS=(\d+)\s*KB", part)
                vsz_m = re.search(r"VSZ=(\d+)\s*KB", part)
                if pid_m:
                    entries.append({
                        "pid": int(pid_m.group(1)),
                        "name": name_m.group(1).strip() if name_m else "",
                        "rss_kb": int(rss_m.group(1)) if rss_m else None,
                        "vsz_kb": int(vsz_m.group(1)) if vsz_m else None,
                    })
                else:
                    entries.append({"raw": part})
            out["process_memory_by_feature"].append({
                "timestamp": ts,
                "feature_name": feature,
                "entries": entries,
            })

    return out


# ---------------------------------------------------------------------------
# Fallback device info builder
# ---------------------------------------------------------------------------


def find_and_build_fallback_device_info(
    project_dir: Path,
    force: bool = False,
) -> Dict[str, str]:
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

    Results are cached to ``<project_dir>/.device_info_cache.json`` with
    mtime-based invalidation.

    Args:
        project_dir: Path to the CPE directory.
        force: Bypass cache and re-parse.

    Returns:
        A dict with keys like ``model``, ``serial``, ``manufacturer``,
        ``mac``, ``version``, ``wan_type``, ``sdk_version``, ``sw_upgrade``.
        Returns an empty dict if no fallback data can be found.
    """
    cache_path = project_dir / _DEVICE_INFO_CACHE_FILE
    source_files = [
        project_dir / "PARODUSlog.txt",
        project_dir / "parodusStart-log.txt",
        project_dir / "telemetry_marker.txt",
        project_dir / "version.txt",
        project_dir / "merged_logs" / "version.txt",
    ]

    if not force and _cache_is_fresh(cache_path, source_files):
        cached = _read_json_cache(cache_path)
        if cached is not None:
            logger.debug(f"[InfoExtractor] device_info cache hit for {project_dir}")
            return cached

    device_info: Dict[str, str] = {}

    # --- 1. PARODUSlog.txt, then parodusStart-log.txt fallback ---
    def _apply_parodus_result(parodus: Dict[str, Any]) -> None:
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

    parodus_path = project_dir / "PARODUSlog.txt"
    if parodus_path.exists() and parodus_path.is_file():
        try:
            raw = parodus_path.read_text(encoding="utf-8", errors="ignore")
            parodus = parse_parodus_log(raw)
            if parodus:
                _apply_parodus_result(parodus)
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

    # Fallback: parodusStart-log.txt when PARODUSlog missing or gave no identity
    if not device_info.get("model") or not device_info.get("serial"):
        start_path = project_dir / "parodusStart-log.txt"
        if start_path.exists() and start_path.is_file():
            try:
                raw = start_path.read_text(encoding="utf-8", errors="ignore")
                start_data = parse_parodus_start_log(raw)
                if start_data:
                    _apply_parodus_result(start_data)
                    logger.info(
                        f"[InfoExtractor] Fallback parodusStart-log: "
                        f"model={device_info.get('model', 'N/A')}, "
                        f"serial={device_info.get('serial', 'N/A')}"
                    )
            except Exception as e:
                logger.warning(
                    f"[InfoExtractor] Error reading parodusStart-log {start_path}: {e}"
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

    _write_json_cache(cache_path, device_info)
    return device_info


def extract_device_info_from_paths(
    paths: Dict[str, Path],
    *,
    use_cache: bool = False,
    cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Portable API: extract device info from explicit file paths.

    Use in multi-agent environments where log files are downloaded to
    arbitrary locations. No assumption about project_dir structure.

    Args:
        paths: Dict mapping logical names to file paths, e.g.:
            {"PARODUSlog": Path("/tmp/logs/PARODUSlog.txt")},
            {"version": Path("/tmp/logs/version.txt")},
            {"telemetry_marker": Path("/tmp/logs/telemetry_marker.txt")},
            {"parodusStart": Path("/tmp/logs/parodusStart-log.txt")},
            {"BootTime": Path("/tmp/logs/BootTime.log")},
            {"Consolelog": Path("/tmp/logs/Consolelog.txt")},
        use_cache: If True, read/write cache in cache_dir (for repeated calls).
        cache_dir: Required when use_cache=True.

    Returns:
        Dict with keys: model, serial, manufacturer, mac, version, wan_type,
        sdk_version, sw_upgrade, last_reboot_reason, reboots (if BootTime/Consolelog).
    """
    device_info: Dict[str, Any] = {}

    def _apply_parodus(parodus: Dict[str, Any]) -> None:
        mapping = {
            "hw_model": "model",
            "serial_number": "serial",
            "manufacturer": "manufacturer",
            "mac": "mac",
            "fw_name": "version",
            "last_reboot_reason": "last_reboot_reason",
        }
        for src_key, dst_key in mapping.items():
            if parodus.get(src_key):
                device_info[dst_key] = str(parodus[src_key])

    # PARODUSlog or parodusStart
    parodus_path = paths.get("PARODUSlog") or paths.get("parodus")
    if parodus_path and parodus_path.exists():
        try:
            raw = parodus_path.read_text(encoding="utf-8", errors="ignore")
            parodus = parse_parodus_log(raw)
            if parodus:
                _apply_parodus(parodus)
        except OSError as e:
            logger.warning(f"[InfoExtractor] Error reading PARODUSlog {parodus_path}: {e}")

    if not device_info.get("model") or not device_info.get("serial"):
        start_path = paths.get("parodusStart") or paths.get("parodus_start")
        if start_path and start_path.exists():
            try:
                raw = start_path.read_text(encoding="utf-8", errors="ignore")
                start_data = parse_parodus_start_log(raw)
                if start_data:
                    _apply_parodus(start_data)
            except OSError as e:
                logger.warning(f"[InfoExtractor] Error reading parodusStart {start_path}: {e}")

    # telemetry_marker — WAN mode
    marker_path = paths.get("telemetry_marker") or paths.get("telemetry_marker_txt")
    if marker_path and marker_path.exists():
        try:
            raw = marker_path.read_text(encoding="utf-8", errors="ignore")
            wan_mode = parse_wan_mode_from_marker(raw)
            if wan_mode:
                device_info["wan_type"] = wan_mode
        except OSError as e:
            logger.warning(f"[InfoExtractor] Error reading marker {marker_path}: {e}")

    # version.txt
    version_path = paths.get("version") or paths.get("version_txt")
    if version_path and version_path.exists():
        try:
            raw = version_path.read_text(encoding="utf-8", errors="ignore")
            version_info = parse_version_txt(raw)
            if version_info:
                if version_info.get("sdk_version"):
                    device_info["sdk_version"] = version_info["sdk_version"]
                device_info["sw_upgrade"] = (
                    f"Yes ({version_info['sw_upgrade_detail']})"
                    if version_info.get("sw_upgrade_detected")
                    else "No"
                )
                if not device_info.get("model") and version_info.get("machine_name"):
                    device_info["model"] = version_info["machine_name"]
        except OSError as e:
            logger.warning(f"[InfoExtractor] Error reading version {version_path}: {e}")

    # Reboots (BootTime + Consolelog for soft/hard classification)
    bt_path = paths.get("BootTime") or paths.get("BootTime_log")
    console_path = paths.get("Consolelog") or paths.get("Consolelog_txt")
    if bt_path and bt_path.exists():
        try:
            raw = bt_path.read_text(encoding="utf-8", errors="ignore")
            bt_info = parse_boottime_log(raw)
            reboots: List[Dict[str, str]] = []
            for cycle in bt_info.get("reboot_history", []):
                ts = cycle.get("timestamp", "")
                reason = cycle.get("reason", "unknown")
                if ts:
                    reboots.append({"timestamp": ts, "reason": reason})
            device_info["reboots"] = reboots
        except OSError as e:
            logger.warning(f"[InfoExtractor] Error reading BootTime {bt_path}: {e}")

    if device_info.get("reboots") and console_path and console_path.exists():
        try:
            from datetime import datetime, timedelta

            raw = console_path.read_text(encoding="utf-8", errors="ignore")
            soft_ts = parse_consolelog_for_soft_reboots(raw)
            tolerance = timedelta(minutes=30)
            for r in device_info.get("reboots", []):
                r["reboot_type"] = "hard"
                try:
                    r_dt = datetime.fromisoformat(r["timestamp"])
                    for st in soft_ts:
                        try:
                            st_dt = datetime.fromisoformat(st)
                            if abs(r_dt - st_dt) <= tolerance:
                                r["reboot_type"] = "soft"
                                break
                        except (ValueError, TypeError):
                            continue
                except (ValueError, TypeError):
                    pass
        except OSError as e:
            logger.warning(f"[InfoExtractor] Error reading Consolelog {console_path}: {e}")

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

    # SHIFT REBOOT REASONS BACKWARD
    # The "Received reboot_reason" logged in cycle N explains why cycle N-1 rebooted
    # So we assign cycle[i].reason to cycle[i-1]
    if len(cycles) > 0:
        # Collect all logged reasons first
        logged_reasons = [c.get("reason", "") for c in cycles]
        
        # Shift backward: cycle i gets the reason from cycle i+1
        for i in range(len(cycles)):
            if i + 1 < len(cycles):
                # This cycle's reboot was caused by what the NEXT cycle logged
                cycles[i]["reason"] = logged_reasons[i + 1] if logged_reasons[i + 1] else "unknown"
            else:
                # Last cycle is current boot - no reboot yet, so no reason
                cycles[i]["reason"] = ""

    # Build reboot summary (only for cycles that have been assigned a reason)
    reason_counts: Dict[str, int] = {}
    for cycle in cycles[:-1]:  # Exclude last cycle (current boot, no reboot)
        reason = cycle.get("reason", "unknown")
        if reason:  # Only count non-empty reasons
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "total_reboots": len(cycles),
        "reboot_history": cycles,
        "reboot_summary": reason_counts,
    }


# ---------------------------------------------------------------------------
# Console log parser for software reboot detection
# ---------------------------------------------------------------------------

_CONSOLELOG_BACKUP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}).*(?:==> Taking backup of logs before reboot|Taking a backup from /rdklogs/logs/)"
)


def parse_consolelog_for_soft_reboots(content: str) -> List[str]:
    """
    Parse Consolelog.txt to detect software-initiated reboots.

    Searches for backup log indicators that appear before software reboots:
        - "==> Taking backup of logs before reboot"
        - "Taking a backup from /rdklogs/logs/ to /nvram/logbackup/"

    Args:
        content: Raw text content of Consolelog.txt.

    Returns:
        List of ISO-formatted timestamp strings indicating soft reboot times.
    """
    if not content or not content.strip():
        return []

    soft_reboot_times: List[str] = []
    seen_timestamps: set = set()

    for line in content.splitlines():
        m = _CONSOLELOG_BACKUP_RE.match(line)
        if m:
            timestamp = m.group(1)
            # Deduplicate (both indicators may appear for same reboot)
            if timestamp not in seen_timestamps:
                soft_reboot_times.append(timestamp)
                seen_timestamps.add(timestamp)

    logger.info(
        f"[InfoExtractor] Found {len(soft_reboot_times)} soft reboot "
        f"indicators in Consolelog.txt"
    )
    return soft_reboot_times


# ---------------------------------------------------------------------------
# Reboot extraction coordinator
# ---------------------------------------------------------------------------

# Cache version - increment when reboot parsing logic changes
REBOOTS_CACHE_VERSION = 2


def _reboots_cache_is_fresh(
    cache_path: Path,
    source_paths: List[Path],
) -> bool:
    """Return True if *cache_path* exists and is newer than all *source_paths*."""
    if not cache_path.exists():
        return False
    
    # Check cache version
    try:
        cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
        # Handle old cache format (plain list) vs new format (dict with version)
        if isinstance(cache_data, list):
            logger.info(f"[InfoExtractor] Old cache format detected (plain list), invalidating")
            return False
        cache_version = cache_data.get("version", 1)
        if cache_version != REBOOTS_CACHE_VERSION:
            logger.info(f"[InfoExtractor] Cache version mismatch (cached: {cache_version}, expected: {REBOOTS_CACHE_VERSION}), invalidating")
            return False
    except Exception as e:
        logger.warning(f"[InfoExtractor] Error reading cache: {e}, invalidating")
        return False
    
    # Check mtime
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
    (``BootTime.log``, ``PARODUSlog.txt``, or ``Consolelog.txt``) are modified (mtime check).

    Tries multiple sources in priority order:
        1. BootTime.log  (most reliable -- explicit boot-cycle markers)
        2. PARODUSlog.txt (fallback -- PARODUS startup blocks)

    Then cross-references with Consolelog.txt to detect software-initiated
    reboots (marked as ``reboot_type: "soft"``). Reboots without console log
    backup indicators are marked as ``reboot_type: "hard"``.

    Searches for files directly in *project_dir* (where merged logs
    are stored after upload processing).

    Args:
        project_dir: Path to the project directory
                     (e.g. ``UPLOAD_DIRECTORY/{user_id}/{project_id}``).

    Returns:
        Sorted list of ``{"timestamp": "<ISO-datetime>", "reason": "...", "reboot_type": "soft"|"hard"}``
        dicts.  Returns an empty list when no reboot data is found.
    """
    cache_path = project_dir / ".reboots_cache.json"
    bt_path = project_dir / "BootTime.log"
    p_path = project_dir / "PARODUSlog.txt"
    p_start_path = project_dir / "parodusStart-log.txt"
    console_path = project_dir / "Consolelog.txt"

    # --- Check cache ---
    if _reboots_cache_is_fresh(cache_path, [bt_path, p_path, p_start_path, console_path]):
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            # Handle both old format (array) and new format (object with version)
            if isinstance(cached, dict) and "reboots" in cached:
                reboots_list = cached["reboots"]
                logger.debug(
                    f"[InfoExtractor] Returning {len(reboots_list)} cached reboots "
                    f"from {cache_path}"
                )
                return reboots_list
            elif isinstance(cached, list):
                # Old format - still supported for backward compatibility
                logger.debug(
                    f"[InfoExtractor] Returning {len(cached)} cached reboots "
                    f"from {cache_path} (old format)"
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
        except Exception as e:
            logger.warning(f"[InfoExtractor] Error parsing {bt_path}: {e}")

    # --- Fallback: PARODUSlog.txt ---
    if not reboots and p_path.exists() and p_path.is_file():
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
        except Exception as e:
            logger.warning(f"[InfoExtractor] Error parsing {p_path}: {e}")

    # --- Fallback: parodusStart-log.txt ---
    if not reboots and p_start_path.exists() and p_start_path.is_file():
        try:
            content = p_start_path.read_text(encoding="utf-8", errors="ignore")
            p_info = parse_parodus_start_log(content)
            for entry in p_info.get("parodus_reboot_history", []):
                ts = entry.get("timestamp", "")
                reason = entry.get("reason", "unknown")
                if ts:
                    reboots.append({"timestamp": ts, "reason": reason})
            if reboots:
                logger.info(
                    f"[InfoExtractor] Found {len(reboots)} reboots "
                    f"from {p_start_path}"
                )
        except Exception as e:
            logger.warning(f"[InfoExtractor] Error parsing {p_start_path}: {e}")

    # --- Cross-reference with Consolelog.txt for soft reboot detection ---
    soft_reboot_timestamps: List[str] = []
    if console_path.exists() and console_path.is_file():
        try:
            console_content = console_path.read_text(encoding="utf-8", errors="ignore")
            soft_reboot_timestamps = parse_consolelog_for_soft_reboots(console_content)
        except Exception as e:
            logger.warning(f"[InfoExtractor] Error parsing {console_path}: {e}")

    # Mark reboot types based on soft reboot timestamp correlation
    # Tolerance: ±30 minutes to handle time drift
    from datetime import datetime, timedelta
    
    SOFT_REBOOT_TOLERANCE = timedelta(minutes=30)
    
    for reboot in reboots:
        reboot_type = "hard"  # default
        
        try:
            reboot_dt = datetime.fromisoformat(reboot["timestamp"])
            
            # Check if any soft reboot timestamp is within tolerance
            for soft_ts in soft_reboot_timestamps:
                try:
                    soft_dt = datetime.fromisoformat(soft_ts)
                    time_diff = abs(reboot_dt - soft_dt)
                    
                    if time_diff <= SOFT_REBOOT_TOLERANCE:
                        reboot_type = "soft"
                        logger.debug(
                            f"[InfoExtractor] Matched soft reboot: {reboot['timestamp']} "
                            f"<-> {soft_ts} (delta: {time_diff.total_seconds():.0f}s)"
                        )
                        break
                except (ValueError, TypeError):
                    continue
        except (ValueError, TypeError):
            # If timestamp parsing fails, default to hard
            pass
        
        reboot["reboot_type"] = reboot_type

    if reboots:
        reboots.sort(key=lambda r: r["timestamp"])
        soft_count = sum(1 for r in reboots if r.get("reboot_type") == "soft")
        hard_count = len(reboots) - soft_count
        logger.info(
            f"[InfoExtractor] Classified {len(reboots)} reboots: "
            f"{soft_count} soft, {hard_count} hard"
        )
    else:
        logger.info(f"[InfoExtractor] No reboot data found in {project_dir}")
    
    # Cache the result (empty or not)
    _write_reboots_cache(cache_path, reboots)
    return reboots


def _write_reboots_cache(
    cache_path: Path,
    reboots: List[Dict[str, str]],
) -> None:
    """Write reboots list to the JSON cache file with version."""
    try:
        cache_data = {
            "version": REBOOTS_CACHE_VERSION,
            "reboots": reboots,
        }
        cache_path.write_text(
            json.dumps(cache_data, indent=2),
            encoding="utf-8",
        )
        logger.debug(f"[InfoExtractor] Wrote reboots cache to {cache_path}")
    except Exception as e:
        logger.warning(f"[InfoExtractor] Failed to write cache {cache_path}: {e}")

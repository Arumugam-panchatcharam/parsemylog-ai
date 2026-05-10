"""
Pattern Analyzer API Routes
=============================

Endpoints for per-project regex pattern management and ripgrep-based
log scanning with time-bucketed occurrence graphs and reboot boundaries.

Patterns are stored per-project as YAML files grouped by domain:
    ``UPLOAD_DIRECTORY/{user_id}/{project_id}/project_patterns.yaml``

Format::

    domains:
      WLAN_Issues:
        - {name: "...", regex: "...", enabled: true}
      Core_Router_Issues:
        - ...
"""

import copy
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from flask import Blueprint, jsonify, request, Response, send_file
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.user_db_mngr import global_pattern_row_to_entry, normalized_pattern_scan_filename
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY
from logai.info_extractor import find_and_extract_reboots
from logai.timestamp_parser import parse_timestamp, normalize_to_date_only

logger = logging.getLogger(__name__)

regex_analyzer_bp = Blueprint("regex_analyzer", __name__)

# Timestamp regex for RDK log lines (ISO-8601 prefix)
_LOG_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")

# HH:MM validation for maintenance window times
_HH_MM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Pattern config directory (domain presets from YAML files)
_RG_PATTERNS_DIR = Path(__file__).resolve().parent.parent.parent / "configs" / "rg_patterns"

# Rule parser config (domain presets from JSON)
_RULE_PARSER_CONFIG = Path(UPLOAD_DIRECTORY) / "rule_parser_config.json"

# Async Pattern Analyzer scan: ripgrep limits (multi‑GB CPE dumps need higher ceilings).
# LOGAI_PATTERN_ANALYZER_RG_TIMEOUT_SEC — per-pattern subprocess timeout (seconds, min 120, default 1800).
# LOGAI_PATTERN_ANALYZER_RG_MAX_FILESIZE — rg --max-filesize (e.g. 2G, 4G); larger files are skipped by rg.
_PATTERN_ANALYZER_RG_TIMEOUT_SEC = max(
    120,
    int(os.environ.get("LOGAI_PATTERN_ANALYZER_RG_TIMEOUT_SEC", "1800")),
)
_PATTERN_ANALYZER_RG_MAX_FILESIZE = (
    os.environ.get("LOGAI_PATTERN_ANALYZER_RG_MAX_FILESIZE", "4G").strip() or "4G"
)


# ---------------------------------------------------------------------------
# Maintenance window & reboot proximity helpers
# ---------------------------------------------------------------------------

def _validate_maintenance_window(mw: Any) -> Optional[str]:
    """Return an error message if *mw* is not a valid maintenance window, else None."""
    if mw is None:
        return None
    if not isinstance(mw, dict):
        return "maintenance_window must be an object with 'start' and 'end'"
    start = mw.get("start")
    end = mw.get("end")
    if not start or not end:
        return "maintenance_window requires both 'start' and 'end' (HH:MM)"
    if not _HH_MM_RE.match(str(start)) or not _HH_MM_RE.match(str(end)):
        return "maintenance_window start/end must be HH:MM (00:00 – 23:59)"
    if start == end:
        return "maintenance_window start and end must differ"
    return None


def _validate_reboot_proximity(val: Any) -> Optional[str]:
    """Return an error message if *val* is not a valid reboot proximity, else None."""
    if val is None:
        return None
    try:
        n = int(val)
    except (TypeError, ValueError):
        return "reboot_proximity_minutes must be an integer"
    if n < 1 or n > 60:
        return "reboot_proximity_minutes must be between 1 and 60"
    return None


def _is_in_maintenance_window(ts: datetime, mw: Dict[str, str]) -> bool:
    """Check whether *ts* falls inside a daily recurring maintenance window.

    Handles overnight windows (start > end) such as 23:00 – 03:00.
    """
    mw_start = datetime.strptime(mw["start"], "%H:%M").time()
    mw_end = datetime.strptime(mw["end"], "%H:%M").time()
    match_time = ts.time()
    if mw_start <= mw_end:
        return mw_start <= match_time <= mw_end
    else:
        return match_time >= mw_start or match_time <= mw_end


def _is_near_reboot(
    ts: datetime, reboots: List[Dict[str, str]], proximity_minutes: int, exclude_short_reboots: bool = False
) -> bool:
    """
    Check whether *ts* is within ±*proximity_minutes* of any reboot event.
    
    Args:
        ts: Timestamp to check
        reboots: List of reboot events with 'timestamp' and optional 'is_short_reboot'
        proximity_minutes: Time window in minutes
        exclude_short_reboots: If True, skip reboots marked as short (brief outages)
    
    Returns:
        True if within proximity of a matching reboot, False otherwise
    """
    delta = timedelta(minutes=proximity_minutes)
    for r in reboots:
        # Skip short reboots if requested
        if exclude_short_reboots and r.get("is_short_reboot"):
            continue
        
        try:
            rt = parse_timestamp(r["timestamp"])
            if not rt:
                rt = datetime.fromisoformat(r["timestamp"])
        except (ValueError, KeyError):
            continue
        if abs(ts - rt) <= delta:
            return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_project(project_id: str, user_id: int):
    """Verify project exists and belongs to the user."""
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _user_patterns_path(user_id: int) -> Path:
    """Return the path to the legacy per-user pattern YAML file (migration only)."""
    return Path(UPLOAD_DIRECTORY) / str(user_id) / "user_patterns.yaml"


def _natco_patterns_path(user_id: int, natco_code: str) -> Path:
    """Return the path to the per-user NATCO-specific pattern YAML file."""
    return Path(UPLOAD_DIRECTORY) / str(user_id) / f"user_patterns-{natco_code.lower()}.yaml"


def _project_patterns_path(user_id: int, project_id: str) -> Path:
    """Return the path to the per-project pattern YAML file."""
    return Path(UPLOAD_DIRECTORY) / str(user_id) / project_id / "project_patterns.yaml"


def _load_yaml_patterns(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Load domain-grouped patterns from a YAML file (internal helper)."""
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        if not data:
            return {}

        if "domains" in data and isinstance(data["domains"], dict):
            return data["domains"]

        # Backward compat: old flat format → migrate to "General" domain
        if "patterns" in data and isinstance(data["patterns"], list):
            return {"General": data["patterns"]}

        return {}
    except Exception as e:
        logger.warning(f"[PatternAnalyzer] Error loading patterns from {path}: {e}")
        return {}


def load_project_patterns(user_id: int, project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load per-project regex patterns from YAML, grouped by domain.

    Falls back through multiple sources in priority order:
    1. project_patterns.yaml (per-project working copy)
    2. user_patterns-{natco}.yaml (per-user NATCO defaults)
    3. DB GlobalPattern for that NATCO (admin-managed global)
    4. user_patterns.yaml (legacy migration fallback)
    5. empty

    When seeding from NATCO file or DB global, also writes to project_patterns.yaml.

    Returns:
        Dict mapping domain names to lists of pattern dicts.
        Example: {"WLAN_Issues": [{name, regex, enabled}, ...], ...}
    """
    # Try project-level file first
    project_path = _project_patterns_path(user_id, project_id)
    domains = _load_yaml_patterns(project_path)
    if domains:
        return domains

    # Look up project's NATCO to determine the fallback chain
    project = dbm.get_project_by_id(project_id)
    natco_code = None
    if project and project.natco_id:
        natco = dbm.db.session.get(dbm.Natco, project.natco_id)
        if natco:
            natco_code = natco.code

    # Try NATCO-specific user patterns file
    if natco_code:
        natco_path = _natco_patterns_path(user_id, natco_code)
        natco_domains = _load_yaml_patterns(natco_path)
        if natco_domains:
            logger.info(
                f"[PatternAnalyzer] Seeding project {project_id} from NATCO file "
                f"user_patterns-{natco_code.lower()}.yaml for user {user_id}"
            )
            save_project_patterns(user_id, project_id, natco_domains)
            return natco_domains

        # Try DB global patterns for this NATCO
        global_patterns = (
            dbm.db.session.query(dbm.GlobalPattern)
            .filter_by(natco_id=project.natco_id)
            .order_by(dbm.GlobalPattern.domain, dbm.GlobalPattern.name)
            .all()
        )
        if global_patterns:
            global_domains: Dict[str, List[Dict[str, Any]]] = {}
            for gp in global_patterns:
                if gp.domain not in global_domains:
                    global_domains[gp.domain] = []
                global_domains[gp.domain].append(global_pattern_row_to_entry(gp))
            
            logger.info(
                f"[PatternAnalyzer] Seeding project {project_id} from DB global "
                f"patterns for NATCO {natco_code} (user {user_id})"
            )
            save_project_patterns(user_id, project_id, global_domains)
            return global_domains

    # Migration fallback: copy from legacy per-user file
    legacy_path = _user_patterns_path(user_id)
    legacy_domains = _load_yaml_patterns(legacy_path)
    if legacy_domains:
        logger.info(
            f"[PatternAnalyzer] Migrating legacy per-user patterns to project "
            f"{project_id} for user {user_id}"
        )
        save_project_patterns(user_id, project_id, legacy_domains)
        return legacy_domains

    return {}


def save_project_patterns(
    user_id: int, project_id: str, domains: Dict[str, List[Dict[str, Any]]]
) -> None:
    """
    Save per-project regex patterns to YAML (domain-grouped).
    
    If the project has a NATCO assigned, also writes to the per-user NATCO file
    (user_patterns-{natco_code}.yaml) so future projects with the same NATCO
    will inherit these patterns.
    """
    # Always write to project file
    path = _project_patterns_path(user_id, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump({"domains": domains}, f, default_flow_style=False, sort_keys=False)
    
    # Also write to NATCO file if project has a NATCO
    project = dbm.get_project_by_id(project_id)
    if project and project.natco_id:
        natco = dbm.db.session.get(dbm.Natco, project.natco_id)
        if natco:
            natco_path = _natco_patterns_path(user_id, natco.code)
            natco_path.parent.mkdir(parents=True, exist_ok=True)
            with open(natco_path, "w") as f:
                yaml.dump({"domains": domains}, f, default_flow_style=False, sort_keys=False)
            logger.info(
                f"[PatternAnalyzer] Auto-saved patterns to NATCO file "
                f"user_patterns-{natco.code.lower()}.yaml for user {user_id}"
            )


def _load_domain_presets() -> Dict[str, List[Dict[str, Any]]]:
    """
    Load all domain preset patterns from two sources:

    1. ``configs/rg_patterns/*.yaml`` (existing YAML presets)
    2. ``UPLOAD_DIRECTORY/rule_parser_config.json`` (structured rule parser)

    Returns:
        Dict mapping domain name to list of {name, regex, enabled} patterns.
    """
    presets: Dict[str, List[Dict[str, Any]]] = {}

    # --- Source 1: YAML presets in configs/rg_patterns/ ---
    if _RG_PATTERNS_DIR.exists():
        for yaml_file in sorted(_RG_PATTERNS_DIR.glob("*.yaml")):
            try:
                with open(yaml_file, "r") as f:
                    raw = yaml.safe_load(f)
                if not raw or "domain" not in raw:
                    continue

                domain = raw["domain"]
                patterns: List[Dict[str, Any]] = []

                for rx in raw.get("regex", []):
                    name = rx[:50].replace("\\b", "").replace("\\s+", " ").strip("()?|")
                    patterns.append({
                        "name": name,
                        "regex": rx,
                        "enabled": True,
                    })

                presets[domain] = patterns
            except Exception as e:
                logger.warning(f"[PatternAnalyzer] Error loading preset {yaml_file}: {e}")

    # --- Source 2: rule_parser_config.json ---
    if _RULE_PARSER_CONFIG.exists():
        try:
            with open(_RULE_PARSER_CONFIG, "r") as f:
                rule_cfg = json.load(f)

            for domain_key, issues in rule_cfg.items():
                if not isinstance(issues, list):
                    continue
                patterns = []
                for issue in issues:
                    title = issue.get("Title", "")
                    for cpe_log in issue.get("CPELogs", []):
                        for rx_entry in cpe_log.get("Regex", []):
                            pattern = rx_entry.get("pattern", "")
                            desc = rx_entry.get("description", title)
                            if pattern:
                                patterns.append({
                                    "name": desc or pattern[:60],
                                    "regex": pattern,
                                    "enabled": True,
                                })

                if patterns:
                    # Merge with existing domain or create new
                    if domain_key in presets:
                        existing_regexes = {p["regex"] for p in presets[domain_key]}
                        for p in patterns:
                            if p["regex"] not in existing_regexes:
                                presets[domain_key].append(p)
                    else:
                        presets[domain_key] = patterns
        except Exception as e:
            logger.warning(f"[PatternAnalyzer] Error loading rule_parser_config: {e}")

    return presets


_MAX_POINTS_PER_PATTERN = 3000  # cap per-pattern to keep result file reasonable
_MAX_TEXT_LEN = 200  # truncate matched log lines for hover text
_SCAN_RESULT_PREFIX = ".scan_result_"  # cache file prefix
_SCAN_PROGRESS_PREFIX = ".scan_progress_"


def _scan_result_path(project_dir: Path, scan_id: str) -> Path:
    """Return the path to a scan result cache file."""
    return project_dir / f"{_SCAN_RESULT_PREFIX}{scan_id}.json"


def _scan_progress_path(project_dir: Path, scan_id: str) -> Path:
    """Return the path to a scan progress JSON file."""
    return project_dir / f"{_SCAN_PROGRESS_PREFIX}{scan_id}.json"


def _write_scan_progress(project_dir: Path, scan_id: str, payload: Dict[str, Any]) -> None:
    """Persist scan progress for polling (multi-worker safe on shared upload volume)."""
    path = _scan_progress_path(project_dir, scan_id)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _cleanup_old_scan_results(project_dir: Path) -> None:
    """Remove old scan result and progress cache files from a project directory."""
    for prefix in (_SCAN_RESULT_PREFIX, _SCAN_PROGRESS_PREFIX):
        for old_file in project_dir.glob(f"{prefix}*.json"):
            try:
                old_file.unlink()
            except OSError:
                pass


def _resolve_rg_paths(project_dir: Path, filename: Optional[str]) -> tuple[List[Path], Optional[str]]:
    """
    Resolve paths passed to ripgrep.

    When *filename* is empty, search the whole *project_dir* tree (single root path).
    Otherwise match files whose basename equals *filename* (case-insensitive).

    Returns:
        (paths_for_rg, error_message) — error_message set when filter finds no files.
    """
    if not filename or not str(filename).strip():
        return [project_dir], None

    raw = str(filename).strip()
    if ".." in raw or "/" in raw or "\\" in raw:
        return [], "Invalid filename: path separators and '..' are not allowed"

    wanted = Path(raw).name.lower()
    matches: List[Path] = []
    try:
        for p in project_dir.rglob("*"):
            if p.is_file() and p.name.lower() == wanted:
                try:
                    p.resolve().relative_to(project_dir.resolve())
                except ValueError:
                    continue
                matches.append(p)
    except OSError as e:
        return [], f"Could not scan directory for filename filter: {e}"

    if not matches:
        return [], f"No file matching basename '{raw}' under the scan directory"

    return matches, None


def _parse_iso_as_utc_naive(raw: Optional[str]) -> Optional[datetime]:
    """Parse scan_time_range boundary strings as UTC (returns naive UTC datetime)."""
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip()
    dt = parse_timestamp(s)
    if dt is None:
        try:
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s[:-1])
            else:
                dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _ts_as_utc_naive_for_scan_compare(ts: datetime) -> datetime:
    """Align log-line timestamps with naive UTC scan window boundaries."""
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(timezone.utc).replace(tzinfo=None)


def _validate_time_range_window(time_range: Dict[str, Any]) -> Optional[str]:
    """Return error if start/end are inconsistent (``scan_time_range`` uses UTC)."""
    if not time_range:
        return None
    start_raw = time_range.get("start")
    end_raw = time_range.get("end")
    if not start_raw or not end_raw:
        return None
    ts_start = _parse_iso_as_utc_naive(str(start_raw))
    ts_end = _parse_iso_as_utc_naive(str(end_raw))
    if ts_start is None or ts_end is None:
        return None
    if ts_start > ts_end:
        return "time_range.start must be before or equal to time_range.end"
    return None


def _calculate_adaptive_bucket_minutes(times: List[str], target_points: int = 600) -> int:
    """
    Calculate optimal bucket size for a pattern based on its time span.
    Returns bucket size in minutes to achieve ~target_points buckets.
    """
    if len(times) < 2:
        return 0
    
    # Get time span of matches
    first_ts = parse_timestamp(times[0])
    if not first_ts:
        first_ts = datetime.fromisoformat(times[0])
    last_ts = parse_timestamp(times[-1])
    if not last_ts:
        last_ts = datetime.fromisoformat(times[-1])
    duration_minutes = (last_ts - first_ts).total_seconds() / 60
    
    if duration_minutes <= 0:
        return 0
    
    # Calculate bucket size to achieve target points
    bucket_minutes = max(1, int(duration_minutes / target_points))
    
    # Round to sensible intervals: 1, 5, 10, 15, 30, 60, 120, 240, 1440
    sensible_intervals = [1, 5, 10, 15, 30, 60, 120, 240, 1440]
    for interval in sensible_intervals:
        if bucket_minutes <= interval:
            return interval
    return 1440  # Max 1 day


def _bucket_matches(times: List[str], texts: List[str], bucket_minutes: int) -> tuple:
    """Group matches into time buckets, return (bucket_times, sample_texts, counts)"""
    if bucket_minutes <= 0:
        return times, texts, [1] * len(times)
    
    buckets = {}  # timestamp -> (sample_text, count)
    for ts, txt in zip(times, texts):
        dt = parse_timestamp(ts)
        if not dt:
            dt = datetime.fromisoformat(ts)
        # Round down to bucket boundary
        bucket_dt = dt.replace(second=0, microsecond=0)
        bucket_minutes_offset = (bucket_dt.minute // bucket_minutes) * bucket_minutes
        bucket_dt = bucket_dt.replace(minute=bucket_minutes_offset)
        bucket_key = bucket_dt.isoformat()
        
        if bucket_key in buckets:
            buckets[bucket_key] = (buckets[bucket_key][0], buckets[bucket_key][1] + 1)
        else:
            buckets[bucket_key] = (txt, 1)
    
    sorted_buckets = sorted(buckets.items())
    return (
        [k for k, _ in sorted_buckets],
        [v[0] for _, v in sorted_buckets],
        [v[1] for _, v in sorted_buckets]
    )



def _get_build_timestamps(project_dir: Path) -> List[datetime]:
    """
    Extract ALL firmware build timestamps from version.txt, normalized to date-only.
    
    Handles firmware upgrades where multiple versions (v1 → v2) may exist.
    Each unique build date is normalized to 00:00:00 (date-only, no time component).
    
    All logs with dates <= any build_date are considered pre-NTP (unsynchronized clock).
    
    Returns:
        List of build timestamps (as datetime with time=00:00:00), sorted chronologically.
        Returns empty list if version.txt not found or no build times available.
    """
    build_dates: List[datetime] = []
    
    version_paths = [
        project_dir / "version.txt",
        project_dir / "merged_logs" / "version.txt",
    ]
    
    for version_path in version_paths:
        if not version_path.exists():
            continue
            
        try:
            from logai.info_extractor import parse_version_txt
            content = version_path.read_text(encoding="utf-8", errors="ignore")
            parsed = parse_version_txt(content)
            
            # Extract ALL unique firmware versions' build times
            if parsed.get("firmware_versions"):
                seen_dates = set()  # Deduplicate dates
                
                for fw in parsed["firmware_versions"]:
                    build_time_str = fw.get("build_time")
                    if build_time_str:
                        try:
                            # Use generic timestamp parser
                            build_ts = parse_timestamp(build_time_str)
                            
                            if build_ts is None:
                                logger.debug(f"[PatternAnalyzer] Could not parse build_time '{build_time_str}'")
                                continue
                            
                            # Normalize to date-only
                            build_date = normalize_to_date_only(build_ts)
                            date_key = build_date.date()
                            
                            if date_key not in seen_dates:
                                build_dates.append(build_date)
                                seen_dates.add(date_key)
                                logger.debug(f"[PatternAnalyzer] Build date from version.txt: {build_date}")
                                
                        except (ValueError, AttributeError) as e:
                            logger.debug(f"[PatternAnalyzer] Error processing build_time '{build_time_str}': {e}")
                            continue
                
                # Sort chronologically
                build_dates.sort()
                
                if build_dates and len(parsed["firmware_versions"]) > 1:
                    logger.info(f"[PatternAnalyzer] Found {len(build_dates)} unique build dates from {len(parsed['firmware_versions'])} firmware versions")
                
                return build_dates
                        
        except Exception as e:
            logger.debug(f"[PatternAnalyzer] Error reading version.txt from {version_path}: {e}")
            continue
    
    return []


def _pattern_scan_trace_echo(pat: Dict[str, Any]) -> Dict[str, Any]:
    """Copy per-pattern scan bounds onto trace payloads for client-side chart clipping."""
    extra: Dict[str, Any] = {}
    tr = pat.get("scan_time_range")
    if isinstance(tr, dict):
        st_raw = tr.get("start")
        en_raw = tr.get("end")
        if st_raw and en_raw:
            extra["scan_time_range"] = {
                "start": str(st_raw).strip(),
                "end": str(en_raw).strip(),
            }
    sf = pat.get("scan_filename")
    if sf is not None and str(sf).strip():
        extra["scan_filename"] = str(sf).strip()
    return extra


def _run_ripgrep_scan(
    project_dir: Path,
    patterns: List[Dict[str, Any]],
    bucket_minutes: int = 5,
    filter_pre_ntp: bool = False,
    reboots: Optional[List[Dict[str, str]]] = None,
    scan_id: Optional[str] = None,
    progress_writer: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Run ripgrep with combined patterns and return individual match points.

    Each match is returned with its timestamp and a truncated log line for
    hover display.

    Args:
        project_dir: Path used for version.txt / pre-NTP resolution.
        patterns: List of enabled patterns [{name, regex}, ...].
            Optional per pattern:
            - scan_filename: basename to restrict ripgrep paths (else whole tree).
            - scan_time_range: {"start", "end"} ISO instants interpreted as **UTC** (optional).
        bucket_minutes: (unused, kept for API compat)
        filter_pre_ntp: When True, exclude pre-NTP build-date lines.
        reboots: Reboot data for proximity filter.
        scan_id: Optional id for logging.
        progress_writer: Optional callback(completed_count, total, pattern_name_or_none).

    Returns:
        Dict with traces and total_matches.
    """
    rg_binary = shutil.which("rg")
    if not rg_binary:
        raise RuntimeError("ripgrep (rg) binary not found")

    if not patterns:
        return {"traces": [], "total_matches": 0}

    path_cache: Dict[str, Tuple[List[Path], Optional[str]]] = {}

    def paths_for_pattern(pat: Dict[str, Any]) -> List[Path]:
        raw_fn = pat.get("scan_filename")
        fn = str(raw_fn).strip() if raw_fn else ""
        key = fn.lower() if fn else "__ALL__"
        if key not in path_cache:
            path_cache[key] = _resolve_rg_paths(project_dir, fn or None)
        resolved, _err = path_cache[key]
        return resolved

    # Pre-NTP filter
    pre_ntp_dates: List[datetime] = []
    if filter_pre_ntp:
        pre_ntp_dates = _get_build_timestamps(project_dir)
        if pre_ntp_dates:
            date_list = ", ".join(dt.strftime("%Y-%m-%d") for dt in pre_ntp_dates)
            logger.info(f"[PatternAnalyzer] Pre-NTP filter active: excluding logs from build date(s): {date_list}")

    traces: List[Dict[str, Any]] = []
    total_matches = 0
    total_pat = len(patterns)
    sid = scan_id or ""

    for idx, pat in enumerate(patterns):
        regex = pat["regex"]
        name = pat["name"]

        pat_paths = paths_for_pattern(pat)
        path_args = [str(p) for p in pat_paths]
        if not path_args:
            if progress_writer:
                progress_writer(idx + 1, total_pat, name)
            continue

        ts_start = None
        ts_end = None
        tr = pat.get("scan_time_range")
        if isinstance(tr, dict):
            st_raw = tr.get("start")
            en_raw = tr.get("end")
            if st_raw and en_raw:
                ts_start = _parse_iso_as_utc_naive(str(st_raw))
                ts_end = _parse_iso_as_utc_naive(str(en_raw))

        if progress_writer:
            progress_writer(idx, total_pat, name)

        cmd = [
            rg_binary,
            "--no-heading",
            "--line-number",
            "--no-filename",
            "--max-count", "50000",
            "--max-filesize", _PATTERN_ANALYZER_RG_MAX_FILESIZE,
            "-i",
            "-e", regex,
            *path_args,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_PATTERN_ANALYZER_RG_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"[PatternAnalyzer] ripgrep timed out for pattern: {name}")
            if progress_writer:
                progress_writer(idx + 1, total_pat, name)
            continue
        except Exception as e:
            logger.warning(f"[PatternAnalyzer] ripgrep error for pattern {name}: {e}")
            if progress_writer:
                progress_writer(idx + 1, total_pat, name)
            continue

        if result.returncode not in (0, 1):
            logger.warning(
                f"[PatternAnalyzer] rg exit code {result.returncode} "
                f"for pattern '{name}': {result.stderr[:200]}"
            )
            if progress_writer:
                progress_writer(idx + 1, total_pat, name)
            continue

        times: List[str] = []
        texts: List[str] = []
        match_count = 0

        for line in result.stdout.splitlines():
            ts_match = _LOG_TS_RE.search(line)
            if not ts_match:
                continue

            ts_str = ts_match.group(1)
            try:
                ts = parse_timestamp(ts_str)
                if not ts:
                    ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue

            ts = _ts_as_utc_naive_for_scan_compare(ts)

            if pre_ntp_dates:
                ts_date = normalize_to_date_only(ts)
                if ts_date in pre_ntp_dates:
                    continue

            if ts_start and ts < ts_start:
                continue
            if ts_end and ts > ts_end:
                continue
            if pat.get("maintenance_window") and _is_in_maintenance_window(ts, pat["maintenance_window"]):
                continue
            if pat.get("reboot_proximity_minutes") and reboots and _is_near_reboot(ts, reboots, pat["reboot_proximity_minutes"]):
                continue

            match_count += 1

            if len(times) < _MAX_POINTS_PER_PATTERN:
                text = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
                if len(text) > _MAX_TEXT_LEN:
                    text = text[:_MAX_TEXT_LEN] + "..."
                times.append(ts_str)
                texts.append(text)

        total_matches += match_count

        trace_echo = _pattern_scan_trace_echo(pat)
        if times:
            if len(times) > 500:
                adaptive_bucket = _calculate_adaptive_bucket_minutes(times, target_points=300)
                bucket_times, bucket_texts, bucket_counts = _bucket_matches(times, texts, adaptive_bucket)
                traces.append({
                    **trace_echo,
                    "name": name,
                    "times": bucket_times,
                    "texts": bucket_texts,
                    "counts": bucket_counts,
                    "total": match_count,
                    "bucketed": True,
                    "bucket_minutes": adaptive_bucket,
                })
            else:
                traces.append({
                    **trace_echo,
                    "name": name,
                    "times": times,
                    "texts": texts,
                    "counts": [1] * len(times),
                    "total": match_count,
                    "bucketed": False,
                })

        if progress_writer:
            progress_writer(idx + 1, total_pat, name)

    logger.debug(f"[PatternAnalyzer] Scan {sid}: {total_matches} total matches, {len(traces)} traces")

    return {
        "traces": traces,
        "total_matches": total_matches,
    }


def _regex_scan_background_job(
    owner_user_id: int,
    project_id: str,
    cpe_id: Optional[str],
    scan_id: str,
    enabled_patterns: List[Dict[str, Any]],
    bucket_minutes: int,
    filter_pre_ntp: bool,
    filter_short_reboots: bool,
) -> None:
    """Run scan in a background thread; updates progress file and writes results."""
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{owner_user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir

    def fail(msg: str) -> None:
        _write_scan_progress(project_dir, scan_id, {
            "status": "error",
            "current": 0,
            "total": len(enabled_patterns),
            "pattern_name": None,
            "error": msg,
        })

    try:
        if not project_dir.exists():
            fail("Project directory not found")
            return

        _write_scan_progress(project_dir, scan_id, {
            "status": "running",
            "current": 0,
            "total": len(enabled_patterns),
            "pattern_name": "Building reboot timeline (large uploads can take several minutes)…",
            "error": None,
        })

        reboots = find_and_extract_reboots(project_dir)
        if filter_short_reboots and len(reboots) > 1:
            reboots = [r for r in reboots if r.get("is_short_reboot", False)]

        total_p = len(enabled_patterns)

        def progress_writer(completed: int, total: int, pattern_name: Optional[str]) -> None:
            _write_scan_progress(project_dir, scan_id, {
                "status": "running",
                "current": completed,
                "total": total,
                "pattern_name": pattern_name,
                "error": None,
            })

        scan_result = _run_ripgrep_scan(
            project_dir=project_dir,
            patterns=enabled_patterns,
            bucket_minutes=bucket_minutes,
            filter_pre_ntp=filter_pre_ntp,
            reboots=reboots,
            scan_id=scan_id,
            progress_writer=progress_writer,
        )

        full_result = {
            "traces": scan_result["traces"],
            "reboots": reboots,
            "total_matches": scan_result["total_matches"],
            "cpe_serial": cpe_id,
        }
        cache_path = _scan_result_path(project_dir, scan_id)
        cache_path.write_text(json.dumps(full_result), encoding="utf-8")

        _write_scan_progress(project_dir, scan_id, {
            "status": "complete",
            "current": total_p,
            "total": total_p,
            "pattern_name": None,
            "error": None,
            "total_matches": scan_result["total_matches"],
            "trace_count": len(scan_result["traces"]),
            "reboots_count": len(reboots),
        })

        logger.info(
            f"[PatternAnalyzer] Scan complete for project {project_id}: "
            f"{scan_result['total_matches']} matches, "
            f"{len(reboots)} reboots, cached as {cache_path.name}"
        )
    except RuntimeError as e:
        logger.warning(f"[PatternAnalyzer] Scan runtime error: {e}")
        fail(str(e))
    except Exception as e:
        logger.exception(f"[PatternAnalyzer] Scan error: {e}")
        fail(f"Scan failed: {str(e)}")


def regex_scan_validate_and_start_async(
    owner_user_id: int,
    project_id: str,
    cpe_id: Optional[str],
    data: Dict[str, Any],
) -> tuple:
    """
    Validate scan payload, spawn background job, return Flask (response, status).

    Cleans prior scan cache files on disk before enqueueing the new job.
    """
    patterns = data.get("patterns", [])
    bucket_minutes = int(data.get("bucket_minutes", 5))
    filter_pre_ntp = bool(data.get("filter_pre_ntp", False))
    filter_short_reboots = bool(data.get("filter_short_reboots", False))

    if bucket_minutes < 1:
        bucket_minutes = 1

    enabled_patterns = [
        p for p in patterns
        if isinstance(p, dict)
        and p.get("enabled", True)
        and p.get("regex", "").strip()
    ]

    if not enabled_patterns:
        return jsonify({"error": "No enabled patterns provided"}), 400

    base_dir = Path(f"{UPLOAD_DIRECTORY}/{owner_user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    if not project_dir.exists():
        return jsonify({"error": "Project directory not found"}), 404

    for p in enabled_patterns:
        try:
            re.compile(p["regex"])
        except re.error as e:
            return jsonify({
                "error": f"Invalid regex for pattern '{p.get('name', '?')}': {e}"
            }), 400

        raw_sf = p.get("scan_filename")
        scan_fn = str(raw_sf).strip() if raw_sf else ""
        if scan_fn and (".." in scan_fn or "/" in scan_fn or "\\" in scan_fn):
            return jsonify({
                "error": f"Pattern '{p.get('name', '?')}': invalid scan_filename (no path separators)",
            }), 400

        paths_check, p_err = _resolve_rg_paths(project_dir, scan_fn or None)
        if p_err:
            return jsonify({"error": f"Pattern '{p.get('name', '?')}': {p_err}"}), 400
        if not paths_check:
            return jsonify({"error": f"Pattern '{p.get('name', '?')}': no scan paths"}), 400

        str_tr = p.get("scan_time_range")
        if str_tr is not None:
            if not isinstance(str_tr, dict):
                return jsonify({
                    "error": f"Pattern '{p.get('name', '?')}': scan_time_range must be an object",
                }), 400
            st_part = str(str_tr.get("start") or "").strip()
            en_part = str(str_tr.get("end") or "").strip()
            if st_part and en_part:
                tw_err = _validate_time_range_window({"start": st_part, "end": en_part})
                if tw_err:
                    return jsonify({"error": f"Pattern '{p.get('name', '?')}': {tw_err}"}), 400
            elif st_part or en_part:
                return jsonify({
                    "error": f"Pattern '{p.get('name', '?')}': scan_time_range requires both start and end",
                }), 400

    _cleanup_old_scan_results(project_dir)

    scan_id = uuid.uuid4().hex[:12]
    patterns_copy = copy.deepcopy(enabled_patterns)

    _write_scan_progress(project_dir, scan_id, {
        "status": "running",
        "current": 0,
        "total": len(enabled_patterns),
        "pattern_name": None,
        "error": None,
    })

    thread = threading.Thread(
        target=_regex_scan_background_job,
        kwargs={
            "owner_user_id": owner_user_id,
            "project_id": project_id,
            "cpe_id": cpe_id,
            "scan_id": scan_id,
            "enabled_patterns": patterns_copy,
            "bucket_minutes": bucket_minutes,
            "filter_pre_ntp": filter_pre_ntp,
            "filter_short_reboots": filter_short_reboots,
        },
        daemon=True,
    )
    thread.start()

    return jsonify({
        "scan_id": scan_id,
        "accepted": True,
        "total_patterns": len(enabled_patterns),
        "rg_timeout_sec": _PATTERN_ANALYZER_RG_TIMEOUT_SEC,
    }), 202


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@regex_analyzer_bp.route("/<project_id>/regex-patterns", methods=["GET"])
@jwt_required()
def get_patterns(project_id):
    """
    Get the user's saved regex patterns grouped by domain.

    Returns:
        { "domains": { "WLAN_Issues": [...], "Core_Router_Issues": [...] } }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    domains = load_project_patterns(user_id, project_id)
    return jsonify({"domains": domains}), 200


@regex_analyzer_bp.route("/<project_id>/regex-patterns", methods=["PUT"])
@jwt_required()
def save_patterns(project_id):
    """
    Save/replace the user's regex patterns (domain-grouped).

    Request body:
        { "domains": { "domain_name": [{
            "name": str, "regex": str, "enabled": bool,
            "maintenance_window": {"start": "HH:MM", "end": "HH:MM"} | null
        }, ...] } }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    domains_raw = data.get("domains", {})

    if not isinstance(domains_raw, dict):
        return jsonify({"error": "domains must be an object"}), 400

    validated_domains: Dict[str, List[Dict[str, Any]]] = {}
    total_saved = 0

    for domain_name, patterns in domains_raw.items():
        domain_name = str(domain_name).strip()
        if not domain_name or not isinstance(patterns, list):
            continue

        validated: List[Dict[str, Any]] = []
        for p in patterns:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "")).strip()
            regex = str(p.get("regex", "")).strip()
            enabled = bool(p.get("enabled", True))

            if not name or not regex:
                continue

            try:
                re.compile(regex)
            except re.error as e:
                return jsonify({
                    "error": f"Invalid regex for pattern '{name}' in domain '{domain_name}': {e}"
                }), 400

            # Optional maintenance window
            raw_mw = p.get("maintenance_window") or None
            mw_err = _validate_maintenance_window(raw_mw)
            if mw_err:
                return jsonify({
                    "error": f"Pattern '{name}' in domain '{domain_name}': {mw_err}"
                }), 400

            # Optional reboot proximity
            raw_rp = p.get("reboot_proximity_minutes")
            if raw_rp is not None and raw_rp != "" and raw_rp is not False:
                rp_err = _validate_reboot_proximity(raw_rp)
                if rp_err:
                    return jsonify({
                        "error": f"Pattern '{name}' in domain '{domain_name}': {rp_err}"
                    }), 400
                raw_rp = int(raw_rp)
            else:
                raw_rp = None

            # Optional frequency threshold
            raw_ft = p.get("min_frequency_threshold")
            if raw_ft is not None and raw_ft != "" and raw_ft is not False:
                try:
                    raw_ft = int(raw_ft)
                    if not (1 <= raw_ft <= 1000):
                        return jsonify({
                            "error": f"Pattern '{name}' in domain '{domain_name}': min_frequency_threshold must be between 1 and 1000"
                        }), 400
                except (ValueError, TypeError):
                    return jsonify({
                        "error": f"Pattern '{name}' in domain '{domain_name}': min_frequency_threshold must be a valid integer"
                    }), 400
            else:
                raw_ft = None

            # Optional per-pattern scan scope (validated at scan time against CPE dir)
            raw_sf = p.get("scan_filename")
            scan_filename_val: Optional[str] = None
            if raw_sf is not None and str(raw_sf).strip():
                sf = str(raw_sf).strip()
                if ".." in sf or "/" in sf or "\\" in sf:
                    return jsonify({
                        "error": f"Pattern '{name}' in domain '{domain_name}': scan_filename must be a basename only",
                    }), 400
                scan_filename_val = sf

            raw_scan_tr = p.get("scan_time_range")
            scan_tr_val: Optional[Dict[str, str]] = None
            if raw_scan_tr is not None:
                if not isinstance(raw_scan_tr, dict):
                    return jsonify({
                        "error": f"Pattern '{name}' in domain '{domain_name}': scan_time_range must be an object",
                    }), 400
                st_tr = str(raw_scan_tr.get("start") or "").strip()
                en_tr = str(raw_scan_tr.get("end") or "").strip()
                if st_tr and en_tr:
                    tw_e = _validate_time_range_window({"start": st_tr, "end": en_tr})
                    if tw_e:
                        return jsonify({
                            "error": f"Pattern '{name}' in domain '{domain_name}': {tw_e}",
                        }), 400
                    scan_tr_val = {"start": st_tr, "end": en_tr}
                elif st_tr or en_tr:
                    return jsonify({
                        "error": f"Pattern '{name}' in domain '{domain_name}': scan_time_range requires both start and end",
                    }), 400

            entry: Dict[str, Any] = {
                "name": name,
                "regex": regex,
                "enabled": enabled,
            }
            if raw_mw:
                entry["maintenance_window"] = {
                    "start": str(raw_mw["start"]).strip(),
                    "end": str(raw_mw["end"]).strip(),
                }
            if raw_rp:
                entry["reboot_proximity_minutes"] = raw_rp
            if raw_ft:
                entry["min_frequency_threshold"] = raw_ft
            if scan_filename_val:
                entry["scan_filename"] = scan_filename_val
            if scan_tr_val:
                entry["scan_time_range"] = scan_tr_val

            validated.append(entry)

        if validated:
            validated_domains[domain_name] = validated
            total_saved += len(validated)

    save_project_patterns(user_id, project_id, validated_domains)
    return jsonify({"domains": validated_domains, "saved": total_saved}), 200


@regex_analyzer_bp.route("/<project_id>/regex-patterns/export", methods=["GET"])
@jwt_required()
def export_patterns(project_id):
    """
    Export user patterns as YAML or JSON.

    Query params:
        format: "yaml" | "json" (default: "json")

    Returns:
        File download with appropriate Content-Type.
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    domains = load_project_patterns(user_id, project_id)
    fmt = request.args.get("format", "json").lower()

    if fmt == "yaml":
        buf = StringIO()
        yaml.dump({"domains": domains}, buf, default_flow_style=False, sort_keys=False)
        return Response(
            buf.getvalue(),
            mimetype="application/x-yaml",
            headers={"Content-Disposition": "attachment; filename=patterns.yaml"},
        )
    else:
        return Response(
            json.dumps({"domains": domains}, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=patterns.json"},
        )


@regex_analyzer_bp.route("/<project_id>/regex-patterns/presets", methods=["GET"])
@jwt_required()
def get_presets(project_id):
    """
    List available domain presets and their patterns.

    Returns:
        { "presets": { "platform": [...], "wireless": [...], ... } }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    presets = _load_domain_presets()
    return jsonify({"presets": presets}), 200


@regex_analyzer_bp.route("/<project_id>/reboots", methods=["GET"])
@jwt_required()
def get_reboots(project_id):
    """
    Get reboot timestamps for a project (lightweight, no scan).

    Returns:
        { "reboots": [{ "timestamp": str, "reason": str, "reboot_type": "soft"|"hard",
            "is_short_reboot": bool, "uptime_before_reboot_sec": int (optional) }, ...] }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    if not project_dir.exists():
        return jsonify({"error": "Project directory not found"}), 404

    try:
        reboots = find_and_extract_reboots(project_dir)
        return jsonify({"reboots": reboots}), 200
    except Exception as e:
        logger.exception(f"[PatternAnalyzer] Reboots error: {e}")
        return jsonify({"error": str(e)}), 500


@regex_analyzer_bp.route("/<project_id>/regex-scan", methods=["POST"])
@jwt_required()
def run_scan(project_id):
    """
    Enqueue ripgrep scan (async). Returns scan_id immediately (HTTP 202).

    Poll ``GET /<project_id>/regex-scan/<scan_id>/progress`` until status is
    ``complete`` or ``error``, then fetch ``.../results``.

    Request body:
        patterns, bucket_minutes, filter_pre_ntp, filter_short_reboots,
        cpe_id (optional).

        Each pattern may include optional scan scope:
        ``scan_filename`` (basename) and ``scan_time_range`` ``{start, end}`` (**UTC** ISO strings).

    Returns (202):
        { "scan_id", "accepted": true, "total_patterns": int }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    cpe_id = data.get("cpe_id") or request.args.get("cpe_id")

    resp, code = regex_scan_validate_and_start_async(user_id, project_id, cpe_id, data)
    return resp, code


@regex_analyzer_bp.route("/<project_id>/regex-scan/<scan_id>/progress", methods=["GET"])
@jwt_required()
def get_scan_progress(project_id, scan_id):
    """Poll scan job progress written under the project (or CPE) directory."""
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    if not re.fullmatch(r"[0-9a-f]{12}", scan_id):
        return jsonify({"error": "Invalid scan_id"}), 400

    cpe_id = request.args.get("cpe_id")
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    prog_path = _scan_progress_path(project_dir, scan_id)

    if not prog_path.exists():
        return jsonify({"error": "Scan progress not found"}), 404

    try:
        payload = json.loads(prog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return jsonify({"error": "Could not read scan progress"}), 500

    return jsonify(payload), 200


@regex_analyzer_bp.route("/<project_id>/regex-scan/<scan_id>/results", methods=["GET"])
@jwt_required()
def get_scan_results(project_id, scan_id):
    """
    Serve cached scan results (Plotly-ready traces + reboots).

    Returns the full JSON written during the scan, streamed directly
    from disk to avoid re-serialization.

    Returns:
        {
            "traces": [{ "name": str, "times": [str], "texts": [str], "total": int }],
            "reboots": [{ "timestamp": str, "reason": str, optional "reboot_type",
                "uptime_before_reboot_sec", "is_short_reboot" }],
            "total_matches": int
        }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    # Validate scan_id format (hex, 12 chars)
    if not re.fullmatch(r"[0-9a-f]{12}", scan_id):
        return jsonify({"error": "Invalid scan_id"}), 400

    cpe_id = request.args.get("cpe_id")
    base_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    project_dir = base_dir / cpe_id if cpe_id else base_dir
    cache_path = _scan_result_path(project_dir, scan_id)

    if not cache_path.exists():
        return jsonify({"error": "Scan results not found or expired"}), 404

    return send_file(
        cache_path,
        mimetype="application/json",
        as_attachment=False,
    )


# ---------------------------------------------------------------------------
# NATCO Pattern Governance: Global / Sync / Submit
# ---------------------------------------------------------------------------

@regex_analyzer_bp.route("/<project_id>/patterns/global", methods=["GET"])
@jwt_required()
def get_global_patterns(project_id):
    """
    Get the global NATCO patterns for this project's assigned NATCO.

    Returns:
        { "domains": {...}, "natco": {id, code, name} | null }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    if not project.natco_id:
        return jsonify({"domains": {}, "natco": None}), 200

    natco = dbm.db.session.get(dbm.Natco, project.natco_id)
    if not natco:
        return jsonify({"domains": {}, "natco": None}), 200

    patterns = (
        dbm.db.session.query(dbm.GlobalPattern)
        .filter_by(natco_id=natco.id)
        .order_by(dbm.GlobalPattern.domain, dbm.GlobalPattern.name)
        .all()
    )

    domains: Dict[str, List[Dict[str, Any]]] = {}
    for p in patterns:
        if p.domain not in domains:
            domains[p.domain] = []
        domains[p.domain].append(global_pattern_row_to_entry(p))

    return jsonify({
        "domains": domains,
        "natco": {"id": natco.id, "code": natco.code, "name": natco.name},
    }), 200


@regex_analyzer_bp.route("/<project_id>/patterns/sync", methods=["POST"])
@jwt_required()
def sync_from_global(project_id):
    """
    Merge latest global NATCO patterns into the user's local patterns.

    Accepts an optional ``{ "domains": {...} }`` body to use as the
    current user patterns instead of loading from the saved YAML.
    This ensures unsaved UI edits are included in the merge without
    passing through the normalising save endpoint.

    Logic:
      - Global patterns replace/update matching entries (by domain + regex)
      - User-only patterns (not in global) are preserved
      - The merged result is saved and returned

    Returns:
        { "domains": {...}, "synced": int }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    if not project.natco_id:
        return jsonify({"error": "Project has no NATCO assigned"}), 400

    # Load global patterns
    global_patterns = (
        dbm.db.session.query(dbm.GlobalPattern)
        .filter_by(natco_id=project.natco_id)
        .order_by(dbm.GlobalPattern.domain, dbm.GlobalPattern.name)
        .all()
    )

    global_by_domain: Dict[str, List[Dict[str, Any]]] = {}
    for gp in global_patterns:
        if gp.domain not in global_by_domain:
            global_by_domain[gp.domain] = []
        global_by_domain[gp.domain].append(global_pattern_row_to_entry(gp))

    # Use caller-supplied patterns or fall back to saved YAML
    body = request.get_json(silent=True) or {}
    if "domains" in body and isinstance(body["domains"], dict):
        user_domains = body["domains"]
    else:
        user_domains = load_project_patterns(user_id, project_id)

    # Merge: global patterns take precedence, project-only patterns preserved
    merged: Dict[str, List[Dict[str, Any]]] = {}
    all_domains = set(list(global_by_domain.keys()) + list(user_domains.keys()))
    synced = 0

    for domain in all_domains:
        global_pats = global_by_domain.get(domain, [])
        user_pats = user_domains.get(domain, [])
        if not isinstance(user_pats, list):
            user_pats = []

        domain_result: List[Dict[str, Any]] = []

        # First add all global patterns (overriding user versions)
        global_regexes = set()
        for gp in global_pats:
            global_regexes.add(gp["regex"])
            entry = dict(gp)
            prev_user = next(
                (up for up in user_pats if isinstance(up, dict) and up.get("regex") == gp["regex"]),
                None,
            )
            if prev_user:
                sf_prev = prev_user.get("scan_filename")
                if sf_prev is not None and str(sf_prev).strip():
                    entry["scan_filename"] = str(sf_prev).strip()
                tr_prev = prev_user.get("scan_time_range")
                if isinstance(tr_prev, dict) and tr_prev.get("start") and tr_prev.get("end"):
                    entry["scan_time_range"] = {
                        "start": str(tr_prev["start"]).strip(),
                        "end": str(tr_prev["end"]).strip(),
                    }
            domain_result.append(entry)
            synced += 1

        # Then add user-only patterns (not in global)
        for up in user_pats:
            if isinstance(up, dict) and up.get("regex") not in global_regexes:
                domain_result.append(up)

        if domain_result:
            merged[domain] = domain_result

    save_project_patterns(user_id, project_id, merged)
    return jsonify({"domains": merged, "synced": synced}), 200


@regex_analyzer_bp.route("/<project_id>/patterns/diff", methods=["GET", "POST"])
@jwt_required()
def diff_patterns(project_id):
    """
    Compare user's local patterns against the NATCO global config.

    Accepts GET (loads saved patterns from YAML) or POST with
    ``{ "domains": {...} }`` to diff the caller-supplied patterns
    directly, avoiding the normalisation round-trip through the
    save endpoint.

    Returns per-domain categorisation:
        {
            "domains": {
                "domain_name": {
                    "new":      [{name, regex, enabled}],
                    "modified": [{name, regex, enabled, global_name, global_enabled}],
                    "unchanged":[{name, regex, enabled}]
                }
            },
            "natco": {id, code, name} | null
        }

    A pattern is "new" if its regex doesn't exist in global.
    A pattern is "modified" if its regex exists but name or enabled differs.
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    if not project.natco_id:
        return jsonify({"domains": {}, "natco": None}), 200

    natco = dbm.db.session.get(dbm.Natco, project.natco_id)
    if not natco:
        return jsonify({"domains": {}, "natco": None}), 200

    # Build global lookup: {domain: {regex: {name, regex, enabled, mw, rp}}}
    global_pats = (
        dbm.db.session.query(dbm.GlobalPattern)
        .filter_by(natco_id=natco.id)
        .all()
    )
    global_by_domain: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for gp in global_pats:
        global_by_domain.setdefault(gp.domain, {})[gp.regex] = global_pattern_row_to_entry(gp)

    # Use caller-supplied patterns (POST) or fall back to saved YAML (GET)
    body = request.get_json(silent=True) or {}
    if request.method == "POST" and "domains" in body and isinstance(body["domains"], dict):
        user_domains = body["domains"]
    else:
        user_domains = load_project_patterns(user_id, project_id)

    result_domains: Dict[str, Dict[str, list]] = {}
    for domain, user_pats in user_domains.items():
        if not isinstance(user_pats, list):
            continue
        gmap = global_by_domain.get(domain, {})
        new_pats = []
        modified_pats = []
        unchanged_pats = []

        for p in user_pats:
            if not isinstance(p, dict):
                continue
            rx = p.get("regex", "")
            name = p.get("name", "")
            enabled = p.get("enabled", True)
            mw = p.get("maintenance_window")
            rp = p.get("reboot_proximity_minutes")
            ft = p.get("min_frequency_threshold")
            sf_u = normalized_pattern_scan_filename(p)

            base: Dict[str, Any] = {"name": name, "regex": rx, "enabled": enabled}
            if mw:
                base["maintenance_window"] = mw
            if rp is not None:
                base["reboot_proximity_minutes"] = rp
            if ft is not None:
                base["min_frequency_threshold"] = ft
            if sf_u:
                base["scan_filename"] = sf_u

            if rx not in gmap:
                new_pats.append(base)
            else:
                gp_entry = gmap[rx]
                g_mw = gp_entry.get("maintenance_window")
                g_rp = gp_entry.get("reboot_proximity_minutes")
                g_ft = gp_entry.get("min_frequency_threshold")
                g_sf = normalized_pattern_scan_filename(gp_entry)
                changed = (
                    gp_entry["name"] != name
                    or gp_entry["enabled"] != enabled
                    or mw != g_mw
                    or rp != g_rp
                    or ft != g_ft
                    or sf_u != g_sf
                )
                if changed:
                    base["global_name"] = gp_entry["name"]
                    base["global_enabled"] = gp_entry["enabled"]
                    if g_mw:
                        base["global_maintenance_window"] = g_mw
                    if g_rp is not None:
                        base["global_reboot_proximity_minutes"] = g_rp
                    if g_ft is not None:
                        base["global_min_frequency_threshold"] = g_ft
                    if g_sf:
                        base["global_scan_filename"] = g_sf
                    modified_pats.append(base)
                else:
                    unchanged_pats.append(base)

        if new_pats or modified_pats or unchanged_pats:
            result_domains[domain] = {
                "new": new_pats,
                "modified": modified_pats,
                "unchanged": unchanged_pats,
            }

    return jsonify({
        "domains": result_domains,
        "natco": {"id": natco.id, "code": natco.code, "name": natco.name},
    }), 200


@regex_analyzer_bp.route("/<project_id>/patterns/submit", methods=["POST"])
@jwt_required()
def submit_patterns(project_id):
    """
    Submit user patterns for admin review (upstream to global).

    Request body:
        {
            "domain": str,
            "patterns": [{ "name": str, "regex": str, "enabled": bool }],
            "comment": str (optional)
        }

    Returns:
        { "id": int, "message": str }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    if not project.natco_id:
        return jsonify({"error": "Project has no NATCO assigned. Cannot submit to global."}), 400

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    patterns = data.get("patterns", [])
    comment = (data.get("comment") or "").strip()

    if not domain:
        return jsonify({"error": "Domain is required"}), 400
    if not patterns or not isinstance(patterns, list):
        return jsonify({"error": "At least one pattern is required"}), 400

    # Validate patterns
    validated = []
    for p in patterns:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        regex_val = str(p.get("regex", "")).strip()
        enabled = bool(p.get("enabled", True))
        change_type = str(p.get("change_type", "new")).strip()
        if not name or not regex_val:
            continue
        try:
            re.compile(regex_val)
        except re.error as e:
            return jsonify({"error": f"Invalid regex '{regex_val}': {e}"}), 400
        entry = {"name": name, "regex": regex_val, "enabled": enabled, "change_type": change_type}
        mw = p.get("maintenance_window")
        if isinstance(mw, dict) and mw.get("start") and mw.get("end"):
            entry["maintenance_window"] = {"start": str(mw["start"]), "end": str(mw["end"])}
        rp = p.get("reboot_proximity_minutes")
        if rp is not None:
            try:
                rp_int = int(rp)
                if 1 <= rp_int <= 60:
                    entry["reboot_proximity_minutes"] = rp_int
            except (TypeError, ValueError):
                pass
        ft = p.get("min_frequency_threshold")
        if ft is not None:
            try:
                ft_int = int(ft)
                if 1 <= ft_int <= 1000:
                    entry["min_frequency_threshold"] = ft_int
            except (TypeError, ValueError):
                pass
        sf = p.get("scan_filename")
        if sf is not None and str(sf).strip():
            entry["scan_filename"] = str(sf).strip()
        validated.append(entry)

    if not validated:
        return jsonify({"error": "No valid patterns to submit"}), 400

    submission = dbm.PatternSubmission(
        user_id=user_id,
        natco_id=project.natco_id,
        domain=domain,
        patterns_json=json.dumps(validated),
        comment=comment,
    )
    dbm.db.session.add(submission)

    try:
        dbm.db.session.commit()
        return jsonify({"id": submission.id, "message": f"Submitted {len(validated)} patterns for review."}), 201
    except Exception as e:
        dbm.db.session.rollback()
        return jsonify({"error": str(e)}), 500


@regex_analyzer_bp.route("/<project_id>/patterns/submissions", methods=["GET"])
@jwt_required()
def get_my_submissions(project_id):
    """
    List the current user's pattern submissions for this project's NATCO.

    Returns:
        [{ id, domain, status, comment, created_at, admin_comment, reviewed_at }]
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    if not project.natco_id:
        return jsonify([]), 200

    subs = (
        dbm.db.session.query(dbm.PatternSubmission)
        .filter_by(user_id=user_id, natco_id=project.natco_id)
        .order_by(dbm.PatternSubmission.created_at.desc())
        .all()
    )

    return jsonify([
        {
            "id": s.id,
            "domain": s.domain,
            "patterns": json.loads(s.patterns_json) if s.patterns_json else [],
            "comment": s.comment or "",
            "status": s.status,
            "admin_comment": s.admin_comment or "",
            "created_at": str(s.created_at) if s.created_at else None,
            "reviewed_at": str(s.reviewed_at) if s.reviewed_at else None,
        }
        for s in subs
    ]), 200


@regex_analyzer_bp.route("/<project_id>/patterns/submissions/clear", methods=["DELETE"])
@jwt_required()
def clear_resolved_submissions(project_id):
    """
    Delete all approved/rejected submissions for the current user & project NATCO.

    Returns:
        { "deleted": int }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    if not project.natco_id:
        return jsonify({"deleted": 0}), 200

    deleted = (
        dbm.db.session.query(dbm.PatternSubmission)
        .filter(
            dbm.PatternSubmission.user_id == user_id,
            dbm.PatternSubmission.natco_id == project.natco_id,
            dbm.PatternSubmission.status.in_(["approved", "rejected"]),
        )
        .delete(synchronize_session="fetch")
    )
    dbm.db.session.commit()

    return jsonify({"deleted": deleted}), 200

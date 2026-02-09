"""
Pattern Analyzer API Routes
=============================

Endpoints for per-user regex pattern management and ripgrep-based
log scanning with time-bucketed occurrence graphs and reboot boundaries.

Patterns are stored per-user as YAML files grouped by domain:
    ``UPLOAD_DIRECTORY/{user_id}/user_patterns.yaml``

Format::

    domains:
      WLAN_Issues:
        - {name: "...", regex: "...", enabled: true}
      Core_Router_Issues:
        - ...
"""

import json
import logging
import re
import shutil
import subprocess
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from flask import Blueprint, jsonify, request, Response, send_file
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY
from logai.info_extractor import find_and_extract_reboots

logger = logging.getLogger(__name__)

regex_analyzer_bp = Blueprint("regex_analyzer", __name__)

# Timestamp regex for RDK log lines (ISO-8601 prefix)
_LOG_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")

# Pattern config directory (domain presets from YAML files)
_RG_PATTERNS_DIR = Path(__file__).resolve().parent.parent.parent / "configs" / "rg_patterns"

# Rule parser config (domain presets from JSON)
_RULE_PARSER_CONFIG = Path(UPLOAD_DIRECTORY) / "rule_parser_config.json"


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
    """Return the path to the user's pattern YAML file."""
    return Path(UPLOAD_DIRECTORY) / str(user_id) / "user_patterns.yaml"


def load_user_patterns(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load user-specific regex patterns from YAML, grouped by domain.

    Returns:
        Dict mapping domain names to lists of pattern dicts.
        Example: {"WLAN_Issues": [{name, regex, enabled}, ...], ...}

    Handles backward-compatible migration from old flat format.
    """
    path = _user_patterns_path(user_id)
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        if not data:
            return {}

        # New domain-grouped format
        if "domains" in data and isinstance(data["domains"], dict):
            return data["domains"]

        # Backward compat: old flat format → migrate to "General" domain
        if "patterns" in data and isinstance(data["patterns"], list):
            logger.info(
                f"[PatternAnalyzer] Migrating flat patterns for user {user_id} "
                f"to domain-grouped format"
            )
            domains = {"General": data["patterns"]}
            save_user_patterns(user_id, domains)
            return domains

        return {}
    except Exception as e:
        logger.warning(f"[PatternAnalyzer] Error loading patterns for user {user_id}: {e}")
        return {}


def save_user_patterns(user_id: int, domains: Dict[str, List[Dict[str, Any]]]) -> None:
    """Save user-specific regex patterns to YAML (domain-grouped)."""
    path = _user_patterns_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump({"domains": domains}, f, default_flow_style=False, sort_keys=False)


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

                for lit in raw.get("literals", []):
                    patterns.append({
                        "name": lit,
                        "regex": re.escape(lit),
                        "enabled": True,
                    })

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


def _scan_result_path(project_dir: Path, scan_id: str) -> Path:
    """Return the path to a scan result cache file."""
    return project_dir / f"{_SCAN_RESULT_PREFIX}{scan_id}.json"


def _cleanup_old_scan_results(project_dir: Path) -> None:
    """Remove old scan result cache files from a project directory."""
    for old_file in project_dir.glob(f"{_SCAN_RESULT_PREFIX}*.json"):
        try:
            old_file.unlink()
        except OSError:
            pass


def _run_ripgrep_scan(
    project_dir: Path,
    patterns: List[Dict[str, Any]],
    bucket_minutes: int = 5,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    filter_pre_ntp: bool = False,
    reboots: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Run ripgrep with combined patterns and return individual match points.

    Each match is returned with its timestamp and a truncated log line for
    hover display.

    Args:
        project_dir: Path to the project directory containing log files.
        patterns: List of enabled patterns [{name, regex}, ...].
        bucket_minutes: (unused, kept for API compat)
        time_start: Optional ISO start time filter.
        time_end: Optional ISO end time filter.
        filter_pre_ntp: When True, exclude log lines whose timestamps are
            from before NTP sync (build-time timestamps).  Uses the earliest
            reboot timestamp minus 24 h as a cutoff.
        reboots: Reboot data (needed when *filter_pre_ntp* is True).

    Returns:
        Dict with:
            - traces: [{name, times, texts}] per pattern
            - total_matches: int
    """
    rg_binary = shutil.which("rg")
    if not rg_binary:
        raise RuntimeError("ripgrep (rg) binary not found")

    if not patterns:
        return {"traces": [], "total_matches": 0}

    # Parse optional time filters
    ts_start = None
    ts_end = None
    if time_start:
        try:
            ts_start = datetime.fromisoformat(time_start)
        except ValueError:
            pass
    if time_end:
        try:
            ts_end = datetime.fromisoformat(time_end)
        except ValueError:
            pass

    # Pre-NTP cutoff: earliest reboot - 24 h
    ntp_cutoff: Optional[datetime] = None
    if filter_pre_ntp and reboots:
        try:
            earliest_ts = min(r["timestamp"] for r in reboots if r.get("timestamp"))
            ntp_cutoff = datetime.fromisoformat(earliest_ts) - timedelta(hours=24)
        except (ValueError, TypeError):
            pass

    traces = []
    total_matches = 0

    for pat in patterns:
        regex = pat["regex"]
        name = pat["name"]

        cmd = [
            rg_binary,
            "--no-heading",
            "--line-number",
            "--no-filename",
            "--max-count", "50000",
            "--max-filesize", "500M",
            "-i",
            "-e", regex,
            str(project_dir),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"[PatternAnalyzer] ripgrep timed out for pattern: {name}")
            continue
        except Exception as e:
            logger.warning(f"[PatternAnalyzer] ripgrep error for pattern {name}: {e}")
            continue

        if result.returncode not in (0, 1):
            logger.warning(
                f"[PatternAnalyzer] rg exit code {result.returncode} "
                f"for pattern '{name}': {result.stderr[:200]}"
            )
            continue

        # Collect individual match points
        times: List[str] = []
        texts: List[str] = []
        match_count = 0

        for line in result.stdout.splitlines():
            ts_match = _LOG_TS_RE.search(line)
            if not ts_match:
                continue

            ts_str = ts_match.group(1)
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue

            if ntp_cutoff and ts < ntp_cutoff:
                continue
            if ts_start and ts < ts_start:
                continue
            if ts_end and ts > ts_end:
                continue

            match_count += 1

            # Cap per-pattern points to keep payload reasonable
            if len(times) < _MAX_POINTS_PER_PATTERN:
                # Strip the line number prefix that rg prepends (e.g. "123:")
                text = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
                if len(text) > _MAX_TEXT_LEN:
                    text = text[:_MAX_TEXT_LEN] + "..."
                times.append(ts_str)
                texts.append(text)

        total_matches += match_count

        if times:
            traces.append({
                "name": name,
                "times": times,
                "texts": texts,
                "total": match_count,
            })

    return {
        "traces": traces,
        "total_matches": total_matches,
    }


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

    domains = load_user_patterns(user_id)
    return jsonify({"domains": domains}), 200


@regex_analyzer_bp.route("/<project_id>/regex-patterns", methods=["PUT"])
@jwt_required()
def save_patterns(project_id):
    """
    Save/replace the user's regex patterns (domain-grouped).

    Request body:
        { "domains": { "domain_name": [{ "name": str, "regex": str, "enabled": bool }, ...] } }
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

            validated.append({
                "name": name,
                "regex": regex,
                "enabled": enabled,
            })

        if validated:
            validated_domains[domain_name] = validated
            total_saved += len(validated)

    save_user_patterns(user_id, validated_domains)
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

    domains = load_user_patterns(user_id)
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
        { "reboots": [{ "timestamp": str, "reason": str }, ...] }
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
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
    Run ripgrep scan, write Plotly-ready results to a cache file,
    and return lightweight metadata.

    Request body:
        {
            "patterns": [{ "name": str, "regex": str, "enabled": bool }, ...],
            "bucket_minutes": int (default 5),
            "time_range": { "start": str, "end": str }  (optional),
            "filter_pre_ntp": bool (default false)
        }

    Returns:
        {
            "scan_id": str,
            "total_matches": int,
            "trace_count": int,
            "reboots_count": int,
            "elapsed_ms": int
        }

    The full result data (traces, reboots) is fetched separately via
    ``GET /<project_id>/regex-scan/<scan_id>/results``.
    """
    user_id = get_user_id()
    _, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    patterns = data.get("patterns", [])
    bucket_minutes = int(data.get("bucket_minutes", 5))
    time_range = data.get("time_range", {})
    filter_pre_ntp = bool(data.get("filter_pre_ntp", False))

    if bucket_minutes < 1:
        bucket_minutes = 1

    # Filter to enabled patterns only
    enabled_patterns = [
        p for p in patterns
        if isinstance(p, dict)
        and p.get("enabled", True)
        and p.get("regex", "").strip()
    ]

    if not enabled_patterns:
        return jsonify({
            "error": "No enabled patterns provided"
        }), 400

    # Validate all regex patterns
    for p in enabled_patterns:
        try:
            re.compile(p["regex"])
        except re.error as e:
            return jsonify({
                "error": f"Invalid regex for pattern '{p.get('name', '?')}': {e}"
            }), 400

    project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    if not project_dir.exists():
        return jsonify({"error": "Project directory not found"}), 404

    try:
        start_time = time.perf_counter()

        # Clean up previous scan results
        _cleanup_old_scan_results(project_dir)

        # Extract reboot boundaries (needed before scan for pre-NTP filter)
        reboots = find_and_extract_reboots(project_dir)

        # Run ripgrep scan
        scan_result = _run_ripgrep_scan(
            project_dir=project_dir,
            patterns=enabled_patterns,
            bucket_minutes=bucket_minutes,
            time_start=time_range.get("start"),
            time_end=time_range.get("end"),
            filter_pre_ntp=filter_pre_ntp,
            reboots=reboots,
        )

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        # Write full results to cache file
        scan_id = uuid.uuid4().hex[:12]
        full_result = {
            "traces": scan_result["traces"],
            "reboots": reboots,
            "total_matches": scan_result["total_matches"],
        }
        cache_path = _scan_result_path(project_dir, scan_id)
        cache_path.write_text(json.dumps(full_result), encoding="utf-8")

        logger.info(
            f"[PatternAnalyzer] Scan complete for project {project_id}: "
            f"{scan_result['total_matches']} matches, "
            f"{len(reboots)} reboots, "
            f"{elapsed_ms}ms, cached as {cache_path.name}"
        )

        # Return lightweight metadata only
        return jsonify({
            "scan_id": scan_id,
            "total_matches": scan_result["total_matches"],
            "trace_count": len(scan_result["traces"]),
            "reboots_count": len(reboots),
            "elapsed_ms": elapsed_ms,
        }), 200

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        logger.exception(f"[PatternAnalyzer] Scan error: {e}")
        return jsonify({"error": f"Scan failed: {str(e)}"}), 500


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
            "reboots": [{ "timestamp": str, "reason": str }],
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

    project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    cache_path = _scan_result_path(project_dir, scan_id)

    if not cache_path.exists():
        return jsonify({"error": "Scan results not found or expired"}), 404

    return send_file(
        cache_path,
        mimetype="application/json",
        as_attachment=False,
    )

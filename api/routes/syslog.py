"""
Syslog API Routes
=================

Endpoints for syslog parsing, event retrieval, and cross-CPE analytics.
Parsed data is cached under ``<project_dir>/<cpe_id>/syslog/`` so subsequent
requests are served instantly without re-parsing.
"""

import csv
import io
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.info_extractor import find_and_extract_reboots
from logai.syslog_parser import (
    load_event_mapping,
    load_syslog_cache,
    parse_syslog_file,
    save_syslog_cache,
)
from logai.timestamp_parser import parse_timestamp
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

syslog_bp = Blueprint("syslog", __name__)


def _verify_project(project_id, user_id):
    """Verify project exists and user has access."""
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _project_dir(user_id, project_id, cpe_id=None) -> Path:
    """Get project directory path."""
    base = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    return base / cpe_id if cpe_id else base


def _find_syslog_file(project_dir: Path) -> Optional[Path]:
    """Find merged syslog.txt in project directory."""
    syslog_path = project_dir / "syslog.txt"
    return syslog_path if syslog_path.exists() else None


def _syslog_event_mapping_path() -> Path:
    return Path(__file__).parent.parent.parent / "configs" / "syslog_event_mapping.yaml"


def _build_and_cache_syslog_response(
    project_dir: Path, cpe_identifier: str
) -> Optional[Dict[str, Any]]:
    """
    Parse syslog.txt for one CPE directory, correlate reboots, persist cache.

    Returns:
        Full parse payload (same shape as ``/syslog/parse``), or None if no syslog.txt.
    """
    syslog_path = _find_syslog_file(project_dir)
    if not syslog_path:
        return None
    event_mapping = load_event_mapping(_syslog_event_mapping_path())
    logger.info("Parsing syslog for dir %s (CPE %s)", project_dir, cpe_identifier)
    parsed_data = parse_syslog_file(syslog_path, event_mapping)
    reboot_correlation = _correlate_with_reboots(parsed_data["events"], project_dir)
    response: Dict[str, Any] = {
        "device_info": {
            "serial": cpe_identifier,
            "cpe_id": cpe_identifier,
        },
        "summary": parsed_data["summary"],
        "events": parsed_data["events"],
        "reboot_correlation": reboot_correlation,
        "cached": False,
    }
    save_syslog_cache(project_dir, response)
    return response


def _load_syslog_payload_for_cross_cpe(
    user_id: str,
    project_id: str,
    cpe_serial: str,
    force: bool,
) -> Tuple[str, Optional[Dict[str, Any]], List[str]]:
    """
    Load or build syslog cache for one CPE for fleet overview.

    Returns:
        (cpe_serial, payload or None, error strings)
    """
    project_dir = _project_dir(
        user_id, project_id, None if cpe_serial == "default" else cpe_serial
    )
    errors: List[str] = []
    try:
        cached: Optional[Dict[str, Any]] = None if force else load_syslog_cache(project_dir)
        if cached is None:
            built = _build_and_cache_syslog_response(project_dir, cpe_serial)
            cached = built
        if not cached:
            if _find_syslog_file(project_dir):
                errors.append(f"CPE {cpe_serial}: syslog.txt found but not parsed")
            return cpe_serial, None, errors
        return cpe_serial, cached, errors
    except Exception as e:
        logger.error(
            "Error processing CPE %s for syslog overview: %s", cpe_serial, e, exc_info=True
        )
        return cpe_serial, None, [f"CPE {cpe_serial}: {str(e)}"]


def _correlate_with_reboots(events: List[Dict], project_dir: Path) -> Dict:
    """Correlate syslog events with reboots from BootTime.log."""
    try:
        # Load reboots (reuse existing extraction from info_extractor)
        reboots_cache = project_dir / ".reboots_cache.json"
        if reboots_cache.exists():
            with open(reboots_cache, 'r', encoding='utf-8') as f:
                reboots_data = json.load(f)
            # Handle different cache formats
            if isinstance(reboots_data, list):
                reboots = reboots_data
            else:
                reboots = reboots_data.get('reboots', [])
        else:
            # Extract reboots if not cached
            reboots = find_and_extract_reboots(str(project_dir))
        
        # Events in the hour before each reboot (inclusive of reboot time); excludes post-reboot lines
        events_near_reboots = []
        reboot_window_before_minutes = 60
        
        for event in events:
            try:
                event_time = datetime.fromisoformat(event['timestamp'])
            except (ValueError, KeyError):
                continue
                
            for reboot in reboots:
                try:
                    reboot_timestamp = reboot.get('timestamp') or reboot.get('time')
                    if not reboot_timestamp:
                        continue
                        
                    reboot_time = parse_timestamp(reboot_timestamp)
                    if not reboot_time:
                        continue

                    if event_time > reboot_time:
                        continue
                    delta_seconds = (reboot_time - event_time).total_seconds()
                    delta_minutes = delta_seconds / 60
                    
                    if delta_minutes <= reboot_window_before_minutes:
                        events_near_reboots.append({
                            "event": event,
                            "reboot": reboot,
                            "delta_minutes": round(delta_minutes, 1),
                            "relation": "before"
                        })
                        
                except Exception as e:
                    logger.debug(f"Error correlating event with reboot: {e}")
                    continue
        
        return {
            "events_near_reboots": events_near_reboots,
            "reboot_timestamps": [r.get('timestamp') or r.get('time') for r in reboots if r.get('timestamp') or r.get('time')],
            "reboot_window_minutes": reboot_window_before_minutes,
            "reboot_window_after_minutes": 0,
        }
        
    except Exception as e:
        logger.error(f"Error correlating with reboots: {e}")
        return {
            "events_near_reboots": [],
            "reboot_timestamps": [],
            "reboot_window_minutes": 60,
            "reboot_window_after_minutes": 0,
        }


@syslog_bp.route("/<project_id>/syslog/parse", methods=["POST"])
@jwt_required()
def parse_syslog(project_id):
    """
    Parse syslog.txt for a CPE and return structured events.
    
    Query params:
        - cpe_id: CPE serial number (optional for single-CPE projects)
        - reparse: bool (default False) - force re-parse ignoring cache
    """
    user_id = get_user_id()
    cpe_id = request.args.get("cpe_id")
    reparse = request.args.get("reparse", "false").lower() == "true"
    
    # Verify project access
    _, error_response = _verify_project(project_id, user_id)
    if error_response:
        return error_response
    
    project_dir = _project_dir(user_id, project_id, cpe_id)
    
    try:
        # Check cache first
        if not reparse:
            cached = load_syslog_cache(project_dir)
            if cached:
                cached['cached'] = True
                return jsonify({"data": cached}), 200
        
        response = _build_and_cache_syslog_response(project_dir, cpe_id or "unknown")
        if not response:
            return jsonify({"error": "syslog.txt not found"}), 404
        return jsonify({"data": response}), 200
        
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Error parsing syslog: {e}")
        return jsonify({"error": f"Failed to parse syslog: {str(e)}"}), 500


@syslog_bp.route("/<project_id>/syslog/cross-cpe-overview", methods=["GET"])
@jwt_required()
def cross_cpe_overview(project_id):
    """
    Aggregate syslog statistics across all CPEs in project.

    Query params:
        force (optional): ``1`` or ``true`` to re-parse syslog for every CPE (same idea as
        telemetry / self-heal cross-CPE overview).

    When ``force`` is false, CPEs without cache are parsed on demand if ``syslog.txt`` exists
    (matches telemetry cross-CPE behavior for existing projects).

    Returns:
        - Event counts by category across all CPEs
        - Top event IDs
        - CPE comparison table
        - Timeline distribution
    """
    user_id = get_user_id()
    force = request.args.get("force", "0") in ("1", "true")

    # Verify project access
    _, error_response = _verify_project(project_id, user_id)
    if error_response:
        return error_response

    try:
        cpes = dbm.list_project_cpes(project_id)
        cpe_serials = [c.serial for c in cpes] if cpes else ["default"]

        aggregated = {
            "total_cpes": len(cpe_serials),
            "cpes_with_syslog": 0,
            "total_events": 0,
            "event_category_totals": defaultdict(int),
            "top_event_ids": defaultdict(int),
            "cpe_comparison": [],
            "parsing_errors": [],
        }

        workers = min(16, max(1, len(cpe_serials)))
        results: List[Tuple[str, Optional[Dict[str, Any]], List[str]]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _load_syslog_payload_for_cross_cpe, user_id, project_id, serial, force
                ): serial
                for serial in cpe_serials
            }
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    serial = futures[fut]
                    logger.warning("Cross-CPE syslog worker failed for %s: %s", serial, exc)
                    results.append(
                        (serial, None, [f"CPE {serial}: {str(exc)}"])
                    )

        for _serial, cached, errs in results:
            aggregated["parsing_errors"].extend(errs)
            if not cached:
                continue

            aggregated["cpes_with_syslog"] += 1
            aggregated["total_events"] += cached["summary"]["parsed_events"]

            for cat, count in cached["summary"]["event_type_counts"].items():
                aggregated["event_category_totals"][cat] += count

            for event in cached["events"]:
                aggregated["top_event_ids"][event["event_id"]] += 1

            cpe_id = cached.get("device_info", {}).get("cpe_id") or _serial
            cpe_data = {
                "cpe_id": cpe_id,
                "total_events": cached["summary"]["parsed_events"],
                "event_counts": cached["summary"]["event_type_counts"],
                "time_range": cached["summary"]["time_range"],
            }

            if "reboot_correlation" in cached:
                cpe_data["events_near_reboots"] = len(
                    cached["reboot_correlation"]["events_near_reboots"]
                )
                cpe_data["total_reboots"] = len(
                    cached["reboot_correlation"]["reboot_timestamps"]
                )

            aggregated["cpe_comparison"].append(cpe_data)
        
        # Sort top event IDs by frequency
        top_events = sorted(
            aggregated["top_event_ids"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:20]  # Top 20 most frequent event IDs
        
        # Sort CPE comparison by total events
        aggregated["cpe_comparison"].sort(
            key=lambda x: x["total_events"],
            reverse=True
        )
        
        response_data = {
            "summary": {
                "total_cpes": aggregated["total_cpes"],
                "cpes_with_syslog": aggregated["cpes_with_syslog"],
                "total_events": aggregated["total_events"],
                "parsing_errors_count": len(aggregated["parsing_errors"])
            },
            "event_category_totals": dict(aggregated["event_category_totals"]),
            "top_event_ids": [{"event_id": event_id, "count": count} for event_id, count in top_events],
            "cpe_comparison": aggregated["cpe_comparison"],
            "parsing_errors": aggregated["parsing_errors"]
        }
        
        return jsonify({"data": response_data}), 200
        
    except Exception as e:
        logger.error(f"Error generating cross-CPE overview: {e}")
        return jsonify({"error": f"Failed to generate overview: {str(e)}"}), 500


@syslog_bp.route("/<project_id>/syslog/export-csv", methods=["GET"])
@jwt_required()
def export_csv(project_id):
    """Export syslog events as CSV."""
    user_id = get_user_id()
    cpe_id = request.args.get("cpe_id")
    
    # Verify project access
    _, error_response = _verify_project(project_id, user_id)
    if error_response:
        return error_response
    
    try:
        project_dir = _project_dir(user_id, project_id, cpe_id)
        cached = load_syslog_cache(project_dir)
        
        if not cached:
            return jsonify({"error": "No syslog data found. Please parse the syslog first."}), 404
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            "Timestamp", "Event ID", "Category", "Module",
            "Thread ID", "Severity", "Description", "Message",
            "MAC Address", "IP Address", "Domain", "Line Number"
        ])
        
        # Write data rows
        for event in cached["events"]:
            metadata = event.get("metadata", {})
            writer.writerow([
                event["timestamp"],
                event["event_id"],
                event["category"],
                event.get("module", ""),
                event.get("thread_id", ""),
                event["severity"],
                event["description"],
                event["message"],
                metadata.get("mac", ""),
                metadata.get("ip", ""),
                metadata.get("domain", ""),
                event.get("line_number", "")
            ])
        
        # Prepare file for download
        output.seek(0)
        filename = f"syslog_{cpe_id or project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"Error exporting syslog CSV: {e}")
        return jsonify({"error": f"Failed to export CSV: {str(e)}"}), 500


@syslog_bp.route("/<project_id>/syslog/event-summary", methods=["GET"])
@jwt_required()
def event_summary(project_id):
    """Get a summary of event types and their descriptions for a CPE."""
    user_id = get_user_id()
    cpe_id = request.args.get("cpe_id")
    
    # Verify project access
    _, error_response = _verify_project(project_id, user_id)
    if error_response:
        return error_response
    
    try:
        project_dir = _project_dir(user_id, project_id, cpe_id)
        cached = load_syslog_cache(project_dir)
        
        if not cached:
            return jsonify({"error": "No syslog data found. Please parse the syslog first."}), 404
        
        # Collect unique event types with their info
        event_summary = {}
        for event in cached["events"]:
            event_id = event["event_id"]
            if event_id not in event_summary:
                event_summary[event_id] = {
                    "event_id": event_id,
                    "category": event["category"],
                    "description": event["description"],
                    "severity": event["severity"],
                    "count": 0,
                    "first_seen": event["timestamp"],
                    "last_seen": event["timestamp"]
                }
            
            event_summary[event_id]["count"] += 1
            if event["timestamp"] < event_summary[event_id]["first_seen"]:
                event_summary[event_id]["first_seen"] = event["timestamp"]
            if event["timestamp"] > event_summary[event_id]["last_seen"]:
                event_summary[event_id]["last_seen"] = event["timestamp"]
        
        # Convert to list and sort by count
        summary_list = sorted(
            event_summary.values(),
            key=lambda x: x["count"],
            reverse=True
        )
        
        return jsonify({"data": summary_list}), 200
        
    except Exception as e:
        logger.error(f"Error generating event summary: {e}")
        return jsonify({"error": f"Failed to generate event summary: {str(e)}"}), 500
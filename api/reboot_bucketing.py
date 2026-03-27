"""
Reboot analytics bucketing module.

Provides utilities to bucket reboot events by:
1. Time-of-day (4 x 6-hour buckets within a 24-hour period)
2. Device uptime before reboot (6 categories from <1day to >20 days)

This module is used by the Telemetry API to analyze fleet-level reboot patterns
and identify trends in when devices reboot and how long they typically run before
rebooting.

Usage:
    from api.reboot_bucketing import bucket_reboot_events, aggregate_buckets

    events = [...]  # List of reboot events from telemetry.all_events
    cpe_info = {"serial": "ABC123", "model": "XB6"}
    
    time_buckets, uptime_buckets = bucket_reboot_events(events, cpe_info)
    aggregated = aggregate_buckets([time_buckets], [uptime_buckets])

Time-of-Day Buckets:
    - 00-06: 12:00 AM to 6:00 AM (midnight to early morning)
    - 06-12: 6:00 AM to 12:00 PM (morning to noon)
    - 12-18: 12:00 PM to 6:00 PM (afternoon)
    - 18-24: 6:00 PM to 12:00 AM (evening to midnight)

Uptime Categories:
    - <1d: Less than 1 day (0 to 86,400 seconds)
    - 1-5d: 1 to 5 days (86,400 to 432,000 seconds)
    - 5-10d: 5 to 10 days (432,000 to 864,000 seconds)
    - 10-15d: 10 to 15 days (864,000 to 1,296,000 seconds)
    - 15-20d: 15 to 20 days (1,296,000 to 1,728,000 seconds)
    - >20d: More than 20 days (> 1,728,000 seconds)
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from logai.timestamp_parser import parse_timestamp as _parse_timestamp_generic


# Time-of-day bucket definitions (hour ranges)
TIME_OF_DAY_BUCKETS = [
    {"id": "00-06", "label": "12 AM - 6 AM", "start_hour": 0, "end_hour": 6},
    {"id": "06-12", "label": "6 AM - 12 PM", "start_hour": 6, "end_hour": 12},
    {"id": "12-18", "label": "12 PM - 6 PM", "start_hour": 12, "end_hour": 18},
    {"id": "18-24", "label": "6 PM - 12 AM", "start_hour": 18, "end_hour": 24},
]

# Uptime bucket definitions (in seconds)
UPTIME_BUCKETS = [
    {"id": "<1d", "label": "< 1 day", "min_seconds": 0, "max_seconds": 86400},
    {"id": "1-5d", "label": "1 - 5 days", "min_seconds": 86400, "max_seconds": 432000},
    {"id": "5-10d", "label": "5 - 10 days", "min_seconds": 432000, "max_seconds": 864000},
    {"id": "10-15d", "label": "10 - 15 days", "min_seconds": 864000, "max_seconds": 1296000},
    {"id": "15-20d", "label": "15 - 20 days", "min_seconds": 1296000, "max_seconds": 1728000},
    {"id": ">20d", "label": "> 20 days", "min_seconds": 1728000, "max_seconds": float("inf")},
]


def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """
    Parse ISO 8601 timestamp string to datetime object.
    
    Uses the centralized timestamp parser with fallback for Z-suffix ISO format.
    
    Args:
        timestamp_str: ISO 8601 formatted timestamp (e.g., "2025-03-15T14:30:00Z")
    
    Returns:
        datetime object or None if parsing fails
    """
    if not timestamp_str:
        return None
    
    # Try generic parser first
    result = _parse_timestamp_generic(timestamp_str)
    if result:
        return result
    
    try:
        # Fallback: Handle ISO 8601 format with 'Z'
        if timestamp_str.endswith("Z"):
            timestamp_str = timestamp_str[:-1] + "+00:00"
        return datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        return None


def get_time_of_day_bucket(hour: int) -> Optional[str]:
    """
    Get time-of-day bucket ID for a given hour (0-23).
    
    Args:
        hour: Hour in 24-hour format (0-23)
    
    Returns:
        Bucket ID (e.g., "00-06") or None if invalid hour
    """
    if not 0 <= hour < 24:
        return None
    
    for bucket in TIME_OF_DAY_BUCKETS:
        if bucket["start_hour"] <= hour < bucket["end_hour"]:
            return bucket["id"]
    
    return None


def get_uptime_bucket(uptime_seconds: int) -> Optional[str]:
    """
    Get uptime bucket ID for a given uptime duration in seconds.
    
    Args:
        uptime_seconds: Uptime duration in seconds
    
    Returns:
        Bucket ID (e.g., "<1d") or None if invalid
    """
    if uptime_seconds < 0:
        return None
    
    for bucket in UPTIME_BUCKETS:
        if bucket["min_seconds"] <= uptime_seconds < bucket["max_seconds"]:
            return bucket["id"]
    
    return None


def extract_reboot_events(reboot_timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract reboot events from a reboot timeline object.
    
    Args:
        reboot_timeline: Telemetry reboot timeline dict with 'all_events' key
    
    Returns:
        List of reboot event dicts with standardized structure
    """
    if not reboot_timeline or "all_events" not in reboot_timeline:
        return []
    
    events = []
    all_events = reboot_timeline.get("all_events", [])
    
    for event in all_events:
        if event.get("source") == "telemetry":
            events.append(event)
    
    return events


def calculate_uptime_seconds(event: Dict[str, Any]) -> Optional[int]:
    """
    Extract uptime duration in seconds from a reboot event.
    
    The event should have 'prev_uptime' field (Device.DeviceInfo.UpTime in seconds).
    
    Args:
        event: Reboot event dict with 'prev_uptime' key
    
    Returns:
        Uptime in seconds or None if not available
    """
    prev_uptime = event.get("prev_uptime")
    
    if prev_uptime is None:
        return None
    
    # prev_uptime may be string or int
    if isinstance(prev_uptime, str):
        try:
            return int(prev_uptime)
        except (ValueError, TypeError):
            return None
    
    if isinstance(prev_uptime, (int, float)):
        return int(prev_uptime)
    
    return None


def bucket_reboot_events(
    events: List[Dict[str, Any]], cpe_info: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    """
    Bucket reboot events by time-of-day and uptime.
    
    Args:
        events: List of reboot event dicts from telemetry
        cpe_info: Optional CPE device info (serial, model, etc.) to include in bucketed data
    
    Returns:
        Tuple of (time_of_day_buckets, uptime_buckets) where each maps bucket ID to list of event data
    """
    time_of_day_buckets: Dict[str, List[Dict[str, Any]]] = {b["id"]: [] for b in TIME_OF_DAY_BUCKETS}
    uptime_buckets: Dict[str, List[Dict[str, Any]]] = {b["id"]: [] for b in UPTIME_BUCKETS}
    
    for event in events:
        timestamp_str = event.get("time")
        timestamp = parse_timestamp(timestamp_str)
        
        if not timestamp:
            continue
        
        hour = timestamp.hour
        time_bucket_id = get_time_of_day_bucket(hour)
        
        if time_bucket_id:
            event_data = {
                "timestamp": timestamp_str,
                "hour": hour,
            }
            if cpe_info:
                event_data.update(cpe_info)
            
            time_of_day_buckets[time_bucket_id].append(event_data)
        
        # Process uptime bucket if available
        uptime_seconds = calculate_uptime_seconds(event)
        if uptime_seconds is not None:
            uptime_bucket_id = get_uptime_bucket(uptime_seconds)
            
            if uptime_bucket_id:
                event_data = {
                    "timestamp": timestamp_str,
                    "uptime_seconds": uptime_seconds,
                }
                if cpe_info:
                    event_data.update(cpe_info)
                
                uptime_buckets[uptime_bucket_id].append(event_data)
    
    return time_of_day_buckets, uptime_buckets


def aggregate_buckets(
    all_time_of_day_buckets: List[Dict[str, List[Dict[str, Any]]]],
    all_uptime_buckets: List[Dict[str, List[Dict[str, Any]]]],
) -> Dict[str, Any]:
    """
    Aggregate bucketed reboot events from multiple CPEs.
    
    Args:
        all_time_of_day_buckets: List of time-of-day bucket dicts from each CPE
        all_uptime_buckets: List of uptime bucket dicts from each CPE
    
    Returns:
        Aggregated reboot analytics dict with counts and device details
    """
    time_of_day_result: Dict[str, Any] = {}
    uptime_result: Dict[str, Any] = {}
    
    # Initialize all buckets with 0 count
    for bucket in TIME_OF_DAY_BUCKETS:
        time_of_day_result[bucket["id"]] = {
            "count": 0,
            "label": bucket["label"],
            "devices": [],
        }
    
    for bucket in UPTIME_BUCKETS:
        uptime_result[bucket["id"]] = {
            "count": 0,
            "label": bucket["label"],
            "devices": [],
        }
    
    # Aggregate time-of-day buckets
    for cpe_buckets in all_time_of_day_buckets:
        for bucket_id, events in cpe_buckets.items():
            time_of_day_result[bucket_id]["count"] += len(events)
            time_of_day_result[bucket_id]["devices"].extend(events)
    
    # Aggregate uptime buckets
    for cpe_buckets in all_uptime_buckets:
        for bucket_id, events in cpe_buckets.items():
            uptime_result[bucket_id]["count"] += len(events)
            uptime_result[bucket_id]["devices"].extend(events)
    
    # Calculate total reboot events for percentage calculation
    total_time_of_day = sum(b["count"] for b in time_of_day_result.values())
    total_uptime = sum(b["count"] for b in uptime_result.values())
    
    # Add percentage to each bucket
    for bucket_id in time_of_day_result:
        count = time_of_day_result[bucket_id]["count"]
        pct = round((count / total_time_of_day * 100), 1) if total_time_of_day > 0 else 0
        time_of_day_result[bucket_id]["percentage"] = pct
    
    for bucket_id in uptime_result:
        count = uptime_result[bucket_id]["count"]
        pct = round((count / total_uptime * 100), 1) if total_uptime > 0 else 0
        uptime_result[bucket_id]["percentage"] = pct
    
    return {
        "time_of_day_buckets": time_of_day_result,
        "uptime_buckets": uptime_result,
        "total_reboot_events": total_time_of_day,
    }


def detect_short_reboots(
    reboot_events: List[Dict[str, Any]],
    telemetry_timestamps: List[str],
    threshold_minutes: int = 30,
) -> List[Dict[str, Any]]:
    """
    Detect short reboots by analyzing time gaps between telemetry data points.
    
    A reboot is considered "short" if the time gap between the last telemetry report
    before the reboot and the first telemetry report after the reboot is less than
    the configured threshold. This indicates the CPE briefly lost power and reconnected
    quickly—not a system issue.
    
    Args:
        reboot_events: List of reboot event dicts, each with at least:
            - "timestamp": ISO 8601 timestamp of the reboot
            - "is_short_reboot": bool (initially False)
        telemetry_timestamps: List of ISO 8601 telemetry report timestamps, sorted
        threshold_minutes: Time gap threshold in minutes (default: 30)
    
    Returns:
        Updated reboot_events list with is_short_reboot flags set based on gap analysis
    """
    if not telemetry_timestamps or not reboot_events:
        return reboot_events
    
    # Parse all telemetry timestamps for comparison
    parsed_timestamps: List[Optional[datetime]] = []
    for ts_str in telemetry_timestamps:
        parsed = parse_timestamp(ts_str)
        if parsed:
            parsed_timestamps.append(parsed)
    
    if not parsed_timestamps:
        return reboot_events
    
    threshold = timedelta(minutes=threshold_minutes)
    
    for reboot in reboot_events:
        # Support both "timestamp" (BootTime events) and "time" (telemetry TR events)
        reboot_timestamp = parse_timestamp(reboot.get("timestamp") or reboot.get("time", ""))
        if not reboot_timestamp:
            continue
        
        # Find the last telemetry report before the reboot
        prev_report_idx = None
        for i, ts in enumerate(parsed_timestamps):
            if ts and ts < reboot_timestamp:
                prev_report_idx = i
            elif ts and ts >= reboot_timestamp:
                break
        
        # Find the first telemetry report after the reboot
        next_report_idx = None
        for i in range(len(parsed_timestamps)):
            if parsed_timestamps[i] and parsed_timestamps[i] > reboot_timestamp:
                next_report_idx = i
                break
        
        # Calculate the gap between prev and next reports
        if prev_report_idx is not None and next_report_idx is not None:
            prev_report_time = parsed_timestamps[prev_report_idx]
            next_report_time = parsed_timestamps[next_report_idx]
            
            if prev_report_time and next_report_time:
                gap = next_report_time - prev_report_time
                
                if gap < threshold:
                    reboot["is_short_reboot"] = True
    
    return reboot_events


"""
Derive SelfHeal fleet / UI insights from raw parse dict (snapshots, cpu_samples, summary).

Tags align with Analytics UI and CPE overview key_metrics (selfheal_* fields).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import polars as pl

from logai.selfheal_parser import process_application_key

CPU_HIGH_PCT = 85.0
CPU_SEVERE_PCT = 92.0
MIN_PID_CHANGE_EVENTS = 2
LEAK_SLOPE_KB_PER_STEP = 5.0
LEAK_DELTA_KB = 256.0
SUNRECLAIM_RATIO_WARN = 55.0
OVERCOMMIT_WARN = 0.85
OVERCOMMIT_SEVERE = 1.0

# Match analytics STA/reboot overlap margins: noise around each reboot instant.
_REBOOT_NOISE_BEFORE = timedelta(seconds=120)
_REBOOT_NOISE_AFTER = timedelta(seconds=600)


def selfheal_insights_empty_schema() -> Dict[str, pl.DataType]:
    return {
        "device_serial": pl.Utf8,
        "processing_date": pl.Utf8,
        "severity": pl.Utf8,
        "tags_json": pl.Utf8,
        "detail_lines_json": pl.Utf8,
        "peak_cpu_pct": pl.Float64,
        "sunreclaim_ratio_peak": pl.Float64,
        "overcommit_ratio_peak": pl.Float64,
    }


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _reboot_noise_intervals(reboot_times: List[datetime]) -> List[Tuple[datetime, datetime]]:
    return [(rb - _REBOOT_NOISE_BEFORE, rb + _REBOOT_NOISE_AFTER) for rb in reboot_times]


def _pair_overlaps_reboot_noise(
    t_prev: Optional[datetime],
    t_curr: Optional[datetime],
    noise_intervals: List[Tuple[datetime, datetime]],
) -> bool:
    """
    True if the SelfHeal snapshot pair [t_prev, t_curr] overlaps expanded reboot noise.

    PID churn across reboots is expected; do not count as application_restarting.
    """
    if t_prev is None or t_curr is None:
        return False
    if t_curr < t_prev:
        t_prev, t_curr = t_curr, t_prev
    for b0, b1 in noise_intervals:
        if t_prev <= b1 and t_curr >= b0:
            return True
    return False


def _pid_map_for_snapshot(snapshot: Dict[str, Any]) -> Dict[str, int]:
    """app_key -> pid (when duplicate keys, keep pid with larger RSS)."""
    best: Dict[str, Tuple[int, int]] = {}
    for proc in snapshot.get("processes") or []:
        if not isinstance(proc, dict):
            continue
        cmd = str(proc.get("command") or "")
        app = process_application_key(cmd)
        if not app:
            continue
        try:
            pid = int(proc.get("pid", -1))
            rss = int(proc.get("rss_kb", 0))
        except (TypeError, ValueError):
            continue
        prev = best.get(app)
        if prev is None or rss > prev[1]:
            best[app] = (pid, rss)
    return {k: v[0] for k, v in best.items()}


def _count_pid_changes_across_snapshots(
    snapshots: List[Dict[str, Any]],
    reboot_events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    """
    Per app_key: PID changes between consecutive snapshots where the app existed.

    Skips pairs whose time range overlaps reboot noise (same margins as STA/reboot hints).
    """
    reboot_times: List[datetime] = []
    if reboot_events:
        for ev in reboot_events:
            ts = _parse_iso_datetime(ev.get("timestamp"))
            if ts is not None:
                reboot_times.append(ts)
    noise = _reboot_noise_intervals(reboot_times)

    changes: Dict[str, int] = {}
    prev_map: Optional[Dict[str, int]] = None
    t_prev: Optional[datetime] = None

    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        t_curr = _parse_iso_datetime(snap.get("timestamp"))
        cur = _pid_map_for_snapshot(snap)
        if prev_map is not None:
            skip_reboot_noise = _pair_overlaps_reboot_noise(t_prev, t_curr, noise)
            if not skip_reboot_noise:
                for app, pid in cur.items():
                    if app in prev_map and prev_map[app] != pid:
                        changes[app] = changes.get(app, 0) + 1
        prev_map = cur
        if t_curr is not None:
            t_prev = t_curr

    return changes


def _meminfo_peaks(
    snapshots: List[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[float]]:
    sun_peak: Optional[float] = None
    oc_peak: Optional[float] = None
    for snap in snapshots:
        mi = snap.get("meminfo")
        if not isinstance(mi, dict):
            continue
        try:
            slab = int(mi.get("slab") or 0)
            su = int(mi.get("sunreclaim") or 0)
            if slab > 0:
                r = 100.0 * su / slab
                sun_peak = r if sun_peak is None else max(sun_peak, r)
        except (TypeError, ValueError):
            pass
        try:
            cas = int(mi.get("committed_as") or 0)
            lim = int(mi.get("commit_limit") or 0)
            if lim > 0:
                r = cas / lim
                oc_peak = r if oc_peak is None else max(oc_peak, r)
        except (TypeError, ValueError):
            pass
    return sun_peak, oc_peak


def build_selfheal_insights_row(
    raw_data: Dict[str, Any],
    *,
    device_serial: str,
    processing_date: str,
    reboot_events: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    One consolidated insight row for ``selfheal_insights.parquet`` + API.

    Returns None if there is no usable SelfHeal capture.
    """
    snapshots = raw_data.get("snapshots") or []
    cpu_samples = raw_data.get("cpu_samples") or []
    summary = raw_data.get("summary") or {}

    if not snapshots and not cpu_samples:
        return None

    tags: List[str] = []
    detail_lines: List[str] = []

    peak_cpu: Optional[float] = None
    if cpu_samples:
        try:
            peak_cpu = max(float(s.get("cpu_usage_pct", 0)) for s in cpu_samples if isinstance(s, dict))
        except ValueError:
            peak_cpu = None
    if peak_cpu is None and isinstance(summary.get("peak_cpu_usage_pct"), (int, float)):
        peak_cpu = float(summary["peak_cpu_usage_pct"])

    if peak_cpu is not None and peak_cpu >= CPU_HIGH_PCT:
        tags.append("high_cpu")
        detail_lines.append(f"{peak_cpu:.0f}% peak CPU")

    restart_counts = _count_pid_changes_across_snapshots(
        [s for s in snapshots if isinstance(s, dict)],
        reboot_events=reboot_events,
    )
    restarting = sorted(
        [(app, n) for app, n in restart_counts.items() if n >= MIN_PID_CHANGE_EVENTS],
        key=lambda x: -x[1],
    )
    if restarting:
        tags.append("application_restarting")
        for app, n in restarting[:5]:
            detail_lines.append(f"{app} process restarting ({n} PID change{'s' if n != 1 else ''})")

    trend_rows = summary.get("top_processes_by_rss_trend") or []
    leaking: List[str] = []
    if isinstance(trend_rows, list):
        for row in trend_rows:
            if not isinstance(row, dict):
                continue
            cmd = str(row.get("command") or "")
            app = cmd
            try:
                slope = float(row.get("rss_trend_slope_kb") or 0)
                delta = float(row.get("rss_delta_kb") or 0)
            except (TypeError, ValueError):
                continue
            if slope >= LEAK_SLOPE_KB_PER_STEP and delta >= LEAK_DELTA_KB:
                leaking.append(app)
    if leaking:
        tags.append("leakage")
        for app in leaking[:5]:
            detail_lines.append(f"{app} process leaking (rising RSS trend)")

    sun_peak, oc_peak = _meminfo_peaks([s for s in snapshots if isinstance(s, dict)])

    alerts = summary.get("alerts") or []
    if isinstance(alerts, list):
        if "KERNEL_LEAK" in alerts and "slab_unreclaim" not in tags:
            tags.append("slab_unreclaim")
        if "OVERCOMMIT_RISK" in alerts and "overcommit_risk" not in tags:
            tags.append("overcommit_risk")

    if sun_peak is not None and sun_peak >= SUNRECLAIM_RATIO_WARN:
        if "slab_unreclaim" not in tags:
            tags.append("slab_unreclaim")
        if not any("SUnreclaim" in d for d in detail_lines):
            detail_lines.append(f"SUnreclaim/Slab peak {sun_peak:.0f}%")

    if oc_peak is not None and oc_peak >= OVERCOMMIT_WARN:
        if "overcommit_risk" not in tags:
            tags.append("overcommit_risk")
        if not any("Overcommit" in d for d in detail_lines):
            detail_lines.append(f"Overcommit ratio peak {oc_peak:.2f}×")

    if not tags:
        return None

    severity = "medium"
    if peak_cpu is not None and peak_cpu >= CPU_SEVERE_PCT:
        severity = "high"
    elif oc_peak is not None and oc_peak >= OVERCOMMIT_SEVERE:
        severity = "high"
    elif restarting and restarting[0][1] >= 5:
        severity = "high"
    elif leaking:
        severity = "high"
    elif sun_peak is not None and sun_peak >= 75:
        severity = "high"

    return {
        "device_serial": device_serial,
        "processing_date": processing_date,
        "severity": severity,
        "tags_json": json.dumps(tags, separators=(",", ":")),
        "detail_lines_json": json.dumps(detail_lines, separators=(",", ":"), ensure_ascii=False),
        "peak_cpu_pct": peak_cpu,
        "sunreclaim_ratio_peak": sun_peak,
        "overcommit_ratio_peak": oc_peak,
    }


def build_selfheal_insights_dataframe(
    raw_data: Dict[str, Any],
    processing_date: str,
    device_serial: str,
    *,
    reboot_events: Optional[List[Dict[str, Any]]] = None,
) -> pl.DataFrame:
    """DataFrame for upsert into ``selfheal_insights.parquet`` (0 rows if no insights)."""
    row = build_selfheal_insights_row(
        raw_data,
        device_serial=device_serial,
        processing_date=processing_date,
        reboot_events=reboot_events,
    )
    if row is None:
        return pl.DataFrame(schema=selfheal_insights_empty_schema())
    return pl.DataFrame([row])


def key_metrics_from_insights_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten for CPE Overview ``key_metrics`` (no large blobs)."""
    try:
        tags = json.loads(row.get("tags_json") or "[]")
    except json.JSONDecodeError:
        tags = []
    if not isinstance(tags, list):
        tags = []
    out: Dict[str, Any] = {
        "selfheal_signal_severity": row.get("severity") or "",
        "selfheal_signal_tags": tags,
        "selfheal_signal_tag_count": len(tags),
    }
    if row.get("peak_cpu_pct") is not None:
        out["selfheal_peak_cpu_pct"] = row["peak_cpu_pct"]
    if row.get("sunreclaim_ratio_peak") is not None:
        out["selfheal_sunreclaim_ratio_peak"] = row["sunreclaim_ratio_peak"]
    if row.get("overcommit_ratio_peak") is not None:
        out["selfheal_overcommit_ratio_peak"] = row["overcommit_ratio_peak"]
    return out

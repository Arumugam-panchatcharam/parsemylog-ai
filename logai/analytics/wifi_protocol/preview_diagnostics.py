"""Pattern Lab preview diagnostics: per-event and per-rule breakdown."""

from __future__ import annotations

from typing import Any, Dict, List, Set

import polars as pl

from .sequence_rules import _normalize_group_by

_MAX_SAMPLES = 3
_MAX_LINE_LEN = 300


def _truncate_line(line: Any) -> str:
    s = str(line or "")
    if len(s) > _MAX_LINE_LEN:
        return s[:_MAX_LINE_LEN] + "…"
    return s


def _sample_rows(frame: pl.DataFrame, limit: int = _MAX_SAMPLES) -> List[Dict[str, Any]]:
    if frame.height == 0:
        return []
    cols = [c for c in ("timestamp", "source_file", "loglines") if c in frame.columns]
    if not cols:
        return []
    samples: List[Dict[str, Any]] = []
    for row in frame.select(cols).head(limit).to_dicts():
        ts = row.get("timestamp")
        samples.append(
            {
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts or ""),
                "source_file": str(row.get("source_file") or ""),
                "logline": _truncate_line(row.get("loglines")),
            }
        )
    return samples


def _events_for_rule(detect: Dict[str, Any]) -> Set[str]:
    dtype = detect.get("type")
    out: Set[str] = set()
    if dtype == "missing_followup":
        if detect.get("trigger"):
            out.add(str(detect["trigger"]))
        if detect.get("expect"):
            out.add(str(detect["expect"]))
    elif dtype == "burst_count" and detect.get("event"):
        out.add(str(detect["event"]))
    elif dtype == "ordered_sequence":
        for step in detect.get("sequence") or []:
            if step:
                out.add(str(step))
    return out


def _candidate_rows(labeled: pl.DataFrame, detect: Dict[str, Any]) -> pl.DataFrame:
    codes = _events_for_rule(detect)
    if not codes:
        return labeled.head(0)
    return labeled.filter(pl.col("event_code").is_in(list(codes)))


def _skip_reason(
    detect: Dict[str, Any],
    candidates: int,
    raw_count: int,
    aggregated_count: int,
) -> str:
    if candidates == 0:
        return "no_labeled_rows_for_rule_events"
    if raw_count > 0 or aggregated_count > 0:
        return "none"
    dtype = detect.get("type")
    if dtype == "missing_followup":
        return "no_missing_followup_matches"
    if dtype == "burst_count":
        return "no_burst_window_matches"
    if dtype == "ordered_sequence":
        return "no_matching_sequence"
    return "no_detector_matches"


def build_event_breakdown(
    df: pl.DataFrame,
    events: Dict[str, Any],
) -> List[Dict[str, Any]]:
    labeled = df.filter(pl.col("event_code").is_not_null())
    breakdown: List[Dict[str, Any]] = []
    for event_code in events.keys():
        sub = labeled.filter(pl.col("event_code") == event_code)
        breakdown.append(
            {
                "event_code": event_code,
                "match_count": int(sub.height),
                "samples": _sample_rows(sub),
            }
        )
    breakdown.sort(key=lambda x: (-int(x["match_count"]), str(x["event_code"])))
    return breakdown


def build_rule_breakdown(
    labeled: pl.DataFrame,
    issues: Dict[str, Any],
    raw_issues: pl.DataFrame,
    sta_issues: pl.DataFrame,
) -> List[Dict[str, Any]]:
    breakdown: List[Dict[str, Any]] = []
    for issue_key, meta in issues.items():
        if not isinstance(meta, dict):
            continue
        detect = meta.get("detect") or {}
        group_by = _normalize_group_by(detect)
        cand = _candidate_rows(labeled, detect)
        raw_n = 0
        agg_n = 0
        if raw_issues.height > 0 and "issue_key" in raw_issues.columns:
            raw_n = int(raw_issues.filter(pl.col("issue_key") == issue_key).height)
        if sta_issues.height > 0 and "issue_key" in sta_issues.columns:
            agg_n = int(sta_issues.filter(pl.col("issue_key") == issue_key).height)
        breakdown.append(
            {
                "issue_key": issue_key,
                "detect_type": str(detect.get("type") or ""),
                "group_by": group_by,
                "candidate_labeled_rows": int(cand.height),
                "issue_rows_raw": raw_n,
                "issue_rows": agg_n,
                "skip_reason": _skip_reason(detect, int(cand.height), raw_n, agg_n),
            }
        )
    return breakdown


def build_preview_diagnostics(
    df: pl.DataFrame,
    events: Dict[str, Any],
    issues: Dict[str, Any],
    labeled: pl.DataFrame,
    raw_issues: pl.DataFrame,
    sta_issues: pl.DataFrame,
) -> Dict[str, Any]:
    return {
        "event_breakdown": build_event_breakdown(df, events),
        "rule_breakdown": build_rule_breakdown(labeled, issues, raw_issues, sta_issues),
    }

"""Issue detectors driven by YAML ``issues`` / ``detect`` blocks (generic Pattern Lab)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import polars as pl

logger = logging.getLogger(__name__)

def _json_safe(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    return obj


def _normalize_group_by(detect: Dict[str, Any]) -> List[str]:
    raw = detect.get("group_by")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _ensure_group_columns(df: pl.DataFrame, group_by: List[str]) -> pl.DataFrame:
    out = df
    for col in group_by:
        if col not in out.columns:
            out = out.with_columns(pl.lit("").alias(col))
    return out


def _correlation_json(row: Dict[str, Any], group_by: List[str]) -> str:
    if not group_by:
        return "{}"
    payload = {col: str(row.get(col) or "") for col in group_by}
    return json.dumps(payload, sort_keys=True)


def _legacy_correlation_slots(
    row: Dict[str, Any], group_by: List[str]
) -> Tuple[str, str, str]:
    """Map group_by values into sta_mac / ifname / wcid when those names are used."""
    sta = str(row.get("sta_mac") or "") if "sta_mac" in group_by else ""
    ifn = str(row.get("ifname") or "") if "ifname" in group_by else ""
    wcid = str(row.get("wcid") or "") if "wcid" in group_by else ""
    if not group_by:
        sta = str(row.get("sta_mac") or "")
        ifn = str(row.get("ifname") or "")
        wcid = str(row.get("wcid") or "")
    return sta, ifn, wcid


def _issue_base(
    device_serial: str,
    processing_date: str,
    issue_key: str,
    category: str,
    severity: str,
    rca_hint: str,
    row: Dict[str, Any],
    group_by: List[str],
    window_start: Optional[datetime],
    window_end: Optional[datetime],
    evidence: Any,
) -> Dict[str, Any]:
    sta_mac, ifname, wcid = _legacy_correlation_slots(row, group_by)
    return {
        "device_serial": device_serial,
        "issue_key": issue_key,
        "category": category,
        "severity": severity,
        "sta_mac": sta_mac,
        "ifname": ifname,
        "wcid": wcid,
        "correlation": _correlation_json(row, group_by),
        "window_start": window_start.isoformat() if window_start else "",
        "window_end": window_end.isoformat() if window_end else "",
        "evidence": json.dumps(_json_safe(evidence)) if evidence is not None else "[]",
        "rca_hint": rca_hint or "",
        "processing_date": processing_date,
    }


def detect_missing_followup(
    df: pl.DataFrame,
    issue_key: str,
    meta: Dict[str, Any],
    device_serial: str,
    processing_date: str,
) -> List[Dict[str, Any]]:
    detect = meta.get("detect") or {}
    trigger = detect.get("trigger")
    expect = detect.get("expect")
    group_by = _normalize_group_by(detect)
    within_sec = float(detect.get("within_sec", 5))
    if not trigger or not expect:
        return []

    tr = df.filter(pl.col("event_code") == trigger)
    ex = df.filter(pl.col("event_code") == expect)
    if tr.height == 0:
        return []

    tr = _ensure_group_columns(tr, group_by)
    ex = _ensure_group_columns(ex, group_by)

    tr = tr.sort((group_by + ["timestamp"]) if group_by else ["timestamp"])
    ex = ex.sort((group_by + ["timestamp"]) if group_by else ["timestamp"])
    ex = ex.rename({"timestamp": "expect_ts"})

    tol = timedelta(seconds=within_sec)
    try:
        join_kwargs: Dict[str, Any] = {
            "left_on": "timestamp",
            "right_on": "expect_ts",
            "strategy": "forward",
            "tolerance": tol,
            "check_sortedness": False,
        }
        if group_by:
            join_kwargs["by"] = group_by
        joined = tr.join_asof(ex, **join_kwargs)
    except Exception as e:
        logger.warning("join_asof failed for %s: %s", issue_key, e)
        return []

    miss = joined.filter(pl.col("expect_ts").is_null())
    out: List[Dict[str, Any]] = []
    for row in miss.to_dicts():
        ws = row.get("timestamp")
        wstart = ws if hasattr(ws, "isoformat") else None
        out.append(
            _issue_base(
                device_serial,
                processing_date,
                issue_key,
                meta.get("category", ""),
                meta.get("severity", "medium"),
                str(meta.get("rca_hint", "")),
                row,
                group_by,
                wstart,
                None,
                [{"event": trigger, "timestamp": wstart.isoformat() if wstart else None}],
            )
        )
    return out


def _burst_windows_for_group(
    timestamps: List[datetime],
    window_sec: float,
    min_occ: int,
) -> List[tuple]:
    """Non-overlapping windows [i:j) where count >= min_occ."""
    if not timestamps:
        return []
    windows: List[tuple] = []
    i = 0
    n = len(timestamps)
    while i < n:
        t0 = timestamps[i]
        j = i
        while j < n and (timestamps[j] - t0).total_seconds() <= window_sec:
            j += 1
        cnt = j - i
        if cnt >= min_occ:
            windows.append((i, j, t0, timestamps[j - 1]))
            i = j
        else:
            i += 1
    return windows


def detect_burst_count(
    df: pl.DataFrame,
    issue_key: str,
    meta: Dict[str, Any],
    device_serial: str,
    processing_date: str,
) -> List[Dict[str, Any]]:
    detect = meta.get("detect") or {}
    event = detect.get("event")
    window_sec = float(detect.get("window_sec", 10))
    min_occ = int(detect.get("min_occurrence", 3))
    group_by = _normalize_group_by(detect)
    if not event:
        return []

    sub = df.filter(pl.col("event_code") == event)
    if sub.height == 0:
        return []

    sub = _ensure_group_columns(sub, group_by)

    out: List[Dict[str, Any]] = []
    parts = sub.partition_by(group_by, maintain_order=True) if group_by else [sub]
    for part in parts:
        if part.height < min_occ:
            continue
        g2 = part.sort("timestamp")
        ts = g2["timestamp"].to_list()
        wins = _burst_windows_for_group(ts, window_sec, min_occ)
        for i, j, t_start, t_end in wins:
            slice_df = g2.slice(i, j - i)
            evidence = [
                {
                    "event": event,
                    "timestamp": slice_df["timestamp"].to_list()[k],
                    "loglines": (
                        slice_df["loglines"].to_list()[k][:200]
                        if "loglines" in slice_df.columns
                        else ""
                    ),
                }
                for k in range(slice_df.height)
            ]
            row0 = slice_df.row(0, named=True)
            out.append(
                _issue_base(
                    device_serial,
                    processing_date,
                    issue_key,
                    meta.get("category", ""),
                    meta.get("severity", "medium"),
                    str(meta.get("rca_hint", "")),
                    row0,
                    group_by,
                    t_start,
                    t_end,
                    evidence,
                )
            )
    return out


def detect_ordered_sequence(
    df: pl.DataFrame,
    issue_key: str,
    meta: Dict[str, Any],
    device_serial: str,
    processing_date: str,
) -> List[Dict[str, Any]]:
    detect = meta.get("detect") or {}
    sequence = list(detect.get("sequence") or [])
    max_gap = float(detect.get("max_gap_sec", 60))
    group_by = _normalize_group_by(detect)
    if len(sequence) < 2:
        return []

    sub = df.filter(pl.col("event_code").is_in(sequence))
    if sub.height == 0:
        return []

    sub = _ensure_group_columns(sub, group_by)

    out: List[Dict[str, Any]] = []
    parts = sub.partition_by(group_by, maintain_order=True) if group_by else [sub]
    for part in parts:
        g2 = part.sort("timestamp")
        evs = g2["event_code"].to_list()
        ts = g2["timestamp"].to_list()
        n = len(evs)
        i = 0
        while i < n:
            if evs[i] != sequence[0]:
                i += 1
                continue
            chain_idx = [i]
            t_prev = ts[i]
            ok = True
            need_pos = 1
            j = i + 1
            while need_pos < len(sequence) and j < n:
                if (ts[j] - t_prev).total_seconds() > max_gap:
                    ok = False
                    break
                if evs[j] == sequence[need_pos]:
                    chain_idx.append(j)
                    t_prev = ts[j]
                    need_pos += 1
                j += 1
            if need_pos < len(sequence):
                ok = False
            if ok and len(chain_idx) == len(sequence):
                evidence = []
                for idx in chain_idx:
                    evidence.append(
                        {
                            "event": evs[idx],
                            "timestamp": (
                                ts[idx].isoformat()
                                if hasattr(ts[idx], "isoformat")
                                else str(ts[idx])
                            ),
                        }
                    )
                row0 = g2.row(chain_idx[0], named=True)
                out.append(
                    _issue_base(
                        device_serial,
                        processing_date,
                        issue_key,
                        meta.get("category", ""),
                        meta.get("severity", "medium"),
                        str(meta.get("rca_hint", "")),
                        row0,
                        group_by,
                        ts[chain_idx[0]],
                        ts[chain_idx[-1]],
                        evidence,
                    )
                )
                i = chain_idx[-1] + 1
            else:
                i += 1
    return out


def run_issue_detectors(
    labeled: pl.DataFrame,
    issues_yaml: Dict[str, Any],
    device_serial: str,
    processing_date: str,
) -> pl.DataFrame:
    rows: List[Dict[str, Any]] = []
    for issue_key, meta in issues_yaml.items():
        if not isinstance(meta, dict):
            continue
        detect = meta.get("detect") or {}
        dtype = detect.get("type")
        try:
            if dtype == "missing_followup":
                rows.extend(
                    detect_missing_followup(
                        labeled, issue_key, meta, device_serial, processing_date
                    )
                )
            elif dtype == "burst_count":
                rows.extend(
                    detect_burst_count(
                        labeled, issue_key, meta, device_serial, processing_date
                    )
                )
            elif dtype == "ordered_sequence":
                rows.extend(
                    detect_ordered_sequence(
                        labeled, issue_key, meta, device_serial, processing_date
                    )
                )
        except Exception as e:
            logger.warning("Detector %s failed: %s", issue_key, e)

    if not rows:
        return pl.DataFrame(
            schema={
                "device_serial": pl.Utf8,
                "issue_key": pl.Utf8,
                "category": pl.Utf8,
                "severity": pl.Utf8,
                "sta_mac": pl.Utf8,
                "ifname": pl.Utf8,
                "wcid": pl.Utf8,
                "correlation": pl.Utf8,
                "window_start": pl.Utf8,
                "window_end": pl.Utf8,
                "evidence": pl.Utf8,
                "rca_hint": pl.Utf8,
                "processing_date": pl.Utf8,
            }
        )
    return pl.DataFrame(rows)

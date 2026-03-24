"""
Drain3 template sequences and reboot-window flows from ``*_rg.parquet`` files.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from logai.graph_analyzer import _load_all_parquet_events, _parse_ts

_MAX_TEMPLATES_PER_WINDOW = 80
_MAX_BIGRAMS_RETURN = 30


def template_sequence_from_dataframe(
    df: pd.DataFrame,
    dedupe_consecutive: bool = True,
) -> List[str]:
    """Ordered template strings (optionally collapse repeats)."""
    if df.empty or "template" not in df.columns:
        return []
    if "_ts" not in df.columns and "timestamp" in df.columns:
        df = df.copy()
        df["_ts"] = df["timestamp"].apply(
            lambda x: _parse_ts(str(x)) if pd.notna(x) else None
        )
    sort_df = df
    if "_ts" in df.columns:
        sort_df = df.sort_values("_ts", na_position="first")
    seq: List[str] = []
    prev: Optional[str] = None
    for _, row in sort_df.iterrows():
        t = str(row.get("template", "")).strip()
        if not t:
            continue
        if dedupe_consecutive and t == prev:
            continue
        seq.append(t)
        prev = t
    return seq


def _window_mask(
    df: pd.DataFrame,
    win_start: datetime,
    win_end: datetime,
) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)
    if "_ts" not in df.columns:
        if "timestamp" in df.columns:
            df = df.copy()
            df["_ts"] = df["timestamp"].apply(
                lambda x: _parse_ts(str(x)) if pd.notna(x) else None
            )
        else:
            return pd.Series(False, index=df.index)
    return df["_ts"].notna() & (df["_ts"] >= win_start) & (df["_ts"] <= win_end)


def template_flow_per_reboot_windows(
    cpe_dir: Path,
    reboots: List[Dict[str, Any]],
    before_min: int = 60,
    after_min: int = 10,
    dedupe_consecutive: bool = True,
    parquet_df: Optional[pd.DataFrame] = None,
) -> List[Dict[str, Any]]:
    """
    For each reboot with parseable timestamp, collect template sequence in
    ``[reboot - before_min, reboot + after_min]``.

    When *parquet_df* is provided (e.g. already loaded for graph analysis),
    skips a second disk read.
    """
    df = parquet_df if parquet_df is not None else _load_all_parquet_events(cpe_dir)
    if df.empty:
        return []

    if "_ts" not in df.columns and "timestamp" in df.columns:
        df = df.copy()
        df["_ts"] = df["timestamp"].apply(
            lambda x: _parse_ts(str(x)) if pd.notna(x) else None
        )

    out: List[Dict[str, Any]] = []
    for rb in reboots:
        ts_raw = rb.get("timestamp") or ""
        rb_ts = _parse_ts(str(ts_raw)) if ts_raw else None
        if not rb_ts:
            out.append({
                "reboot_timestamp": ts_raw,
                "reason": rb.get("reason", ""),
                "templates": [],
                "error": "unparsed_timestamp",
            })
            continue
        win_start = rb_ts - timedelta(minutes=before_min)
        win_end = rb_ts + timedelta(minutes=after_min)
        sub = df.loc[_window_mask(df, win_start, win_end)]
        seq = template_sequence_from_dataframe(sub, dedupe_consecutive=dedupe_consecutive)
        out.append({
            "reboot_timestamp": ts_raw,
            "reason": rb.get("reason", ""),
            "window": {"start": win_start.isoformat(), "end": win_end.isoformat()},
            "templates": seq[:_MAX_TEMPLATES_PER_WINDOW],
            "template_count": len(seq),
        })
    return out


def global_template_bigrams(
    cpe_dir: Path,
    dedupe_consecutive: bool = True,
    parquet_df: Optional[pd.DataFrame] = None,
) -> List[Dict[str, Any]]:
    """Top consecutive template pairs across all logs in *cpe_dir*."""
    df = parquet_df if parquet_df is not None else _load_all_parquet_events(cpe_dir)
    seq = template_sequence_from_dataframe(df, dedupe_consecutive=dedupe_consecutive)
    if len(seq) < 2:
        return []
    ctr: Counter = Counter()
    for i in range(len(seq) - 1):
        ctr[(seq[i], seq[i + 1])] += 1
    rows: List[Dict[str, Any]] = []
    for (a, b), c in ctr.most_common(_MAX_BIGRAMS_RETURN):
        rows.append({"from_template": a, "to_template": b, "count": int(c)})
    return rows


def aggregate_fleet_template_bigrams(
    scan_entries: List[Tuple[str, Path]],
    dedupe_consecutive: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Fleet-wide bigram counts and CPE coverage per bigram.

    Returns:
        summary_rows: sorted by ``cpe_coverage`` then ``total_count``
        stats: ``total_cpes``, useful for prevalence
    """
    total_cpes = len(scan_entries)
    bigram_counts: Counter = Counter()
    bigram_cpes: Dict[Tuple[str, str], set] = defaultdict(set)

    for label, entry_dir in scan_entries:
        df = _load_all_parquet_events(entry_dir)
        seq = template_sequence_from_dataframe(df, dedupe_consecutive=dedupe_consecutive)
        seen_pairs: set = set()
        for i in range(len(seq) - 1):
            pair = (seq[i], seq[i + 1])
            bigram_counts[pair] += 1
            seen_pairs.add(pair)
        for pair in seen_pairs:
            bigram_cpes[pair].add(label)

    rows: List[Dict[str, Any]] = []
    for pair, count in bigram_counts.items():
        n_cpe = len(bigram_cpes[pair])
        prev = (n_cpe / total_cpes) if total_cpes else 0.0
        rows.append({
            "from_template": pair[0],
            "to_template": pair[1],
            "total_count": int(count),
            "cpe_count": n_cpe,
            "cpe_prevalence": round(prev, 4),
        })
    rows.sort(key=lambda r: (-r["cpe_count"], -r["total_count"]))
    stats = {"total_cpes": total_cpes}
    return rows[:_MAX_BIGRAMS_RETURN * 3], stats


def build_template_flow_summary(
    cpe_dir: Path,
    reboots: List[Dict[str, Any]],
    before_min: int = 60,
    after_min: int = 10,
    parquet_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Payload suitable for ``analyze_cpe`` / API consumers."""
    df = parquet_df
    if df is None:
        df = _load_all_parquet_events(cpe_dir)
    per_rb = template_flow_per_reboot_windows(
        cpe_dir, reboots, before_min=before_min, after_min=after_min,
        parquet_df=df,
    )
    bigrams = global_template_bigrams(cpe_dir, parquet_df=df)
    return {
        "reboot_windows": per_rb[:25],
        "global_bigrams": bigrams,
    }

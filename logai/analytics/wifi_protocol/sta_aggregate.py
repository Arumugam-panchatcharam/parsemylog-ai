"""Roll up STA issue rows per (device, STA MAC, issue_key)."""

from __future__ import annotations

import json
from typing import Any, List

import polars as pl


def _flatten_evidence_cells(cells: Any) -> str:
    """Merge JSON evidence arrays from multiple detector hits into one JSON array."""
    merged: List[Any] = []
    if cells is None:
        return "[]"
    for val in cells:
        if val is None or val == "":
            continue
        try:
            parsed = json.loads(val) if isinstance(val, str) else val
            if isinstance(parsed, list):
                merged.extend(parsed)
            else:
                merged.append(parsed)
        except json.JSONDecodeError:
            merged.append({"raw": val})
    return json.dumps(merged)


def aggregate_sta_issues_by_mac(sta_issues: pl.DataFrame) -> pl.DataFrame:
    """
    One row per ``device_serial`` + ``sta_mac`` + ``issue_key`` with counts and merged evidence.

    ``window_start`` / ``window_end`` use min/max over non-empty ISO timestamps.
    """
    if sta_issues.height == 0:
        return sta_issues

    keys = ["device_serial", "sta_mac", "issue_key"]
    for k in keys:
        if k not in sta_issues.columns:
            return sta_issues

    ws = (
        pl.when(pl.col("window_start").is_null() | (pl.col("window_start").cast(pl.Utf8) == ""))
        .then(None)
        .otherwise(pl.col("window_start").str.to_datetime(time_unit="us", strict=False))
        .alias("_ws")
    )
    we = (
        pl.when(pl.col("window_end").is_null() | (pl.col("window_end").cast(pl.Utf8) == ""))
        .then(None)
        .otherwise(pl.col("window_end").str.to_datetime(time_unit="us", strict=False))
        .alias("_we")
    )
    prep = sta_issues.with_columns([ws, we])

    agg = prep.group_by(keys, maintain_order=True).agg(
        [
            pl.len().alias("occurrence_count"),
            pl.col("_ws").min().alias("_ws_min"),
            pl.col("_we").max().alias("_we_max"),
            pl.col("category").first().alias("category"),
            pl.col("severity").first().alias("severity"),
            pl.col("rca_hint").first().alias("rca_hint"),
            pl.col("ifname").first().alias("ifname"),
            pl.col("wcid").first().alias("wcid"),
            pl.col("processing_date").sort(descending=True).first().alias("processing_date"),
            pl.col("evidence").implode().alias("_evidence_parts"),
        ]
    )

    out = agg.with_columns(
        [
            pl.col("_ws_min")
            .dt.strftime("%Y-%m-%dT%H:%M:%S%.6f")
            .fill_null("")
            .alias("window_start"),
            pl.col("_we_max")
            .dt.strftime("%Y-%m-%dT%H:%M:%S%.6f")
            .fill_null("")
            .alias("window_end"),
        ]
    ).drop(["_ws_min", "_we_max"])

    out = out.with_columns(
        pl.col("_evidence_parts")
        .map_elements(_flatten_evidence_cells, return_dtype=pl.Utf8)
        .alias("evidence")
    ).drop("_evidence_parts")

    return out.select(
        [
            "device_serial",
            "issue_key",
            "category",
            "severity",
            "sta_mac",
            "ifname",
            "wcid",
            "window_start",
            "window_end",
            "evidence",
            "rca_hint",
            "processing_date",
            "occurrence_count",
        ]
    )

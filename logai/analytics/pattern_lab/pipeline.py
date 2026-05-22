"""Pattern Lab pipeline: multi-domain RG parquet + raw log fallback."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import polars as pl

from logai.analytics.data_layout import DataLayoutManager
from logai.analytics.wifi_protocol.event_map import with_event_code_column
from logai.analytics.wifi_protocol.extractors import enrich_correlation_columns
from logai.analytics.wifi_protocol.field_extracts import filter_event_codes_by_field_conditions
from logai.analytics.wifi_protocol.pipeline import coerce_timestamp
from logai.analytics.wifi_protocol.sequence_rules import run_issue_detectors
from logai.analytics.wifi_protocol.sta_aggregate import aggregate_sta_issues_by_mac

from .raw_logs import (
    collect_globs_from_events,
    globs_needing_raw_fallback,
    load_raw_lines_for_globs,
)
from .results import build_pattern_lab_result

logger = logging.getLogger(__name__)

_DEFAULT_DOMAINS = [
    "cellular",
    "common",
    "core_router",
    "mesh",
    "platform",
    "telemetry",
    "voice",
    "wireless",
]


def _domains_from_doc(doc: Dict[str, Any], cpe_dir: Path) -> List[str]:
    raw = doc.get("domains")
    if isinstance(raw, list) and raw:
        names = [str(d).strip() for d in raw if str(d).strip()]
        return [d for d in names if (cpe_dir / f"{d}_rg.parquet").is_file()]
    found: List[str] = []
    for d in _DEFAULT_DOMAINS:
        if (cpe_dir / f"{d}_rg.parquet").is_file():
            found.append(d)
    for pq in sorted(cpe_dir.glob("*_rg.parquet")):
        stem = pq.stem.replace("_rg", "")
        if stem and stem not in found:
            found.append(stem)
    return found


def _normalize_log_frame(df: pl.DataFrame, domain: str) -> pl.DataFrame:
    out = df
    if "loglines" not in out.columns:
        out = out.with_columns(pl.lit("").alias("loglines"))
    if "source_file" not in out.columns:
        out = out.with_columns(pl.lit("").alias("source_file"))
    if "template" not in out.columns:
        out = out.with_columns(pl.lit("").alias("template"))
    if "timestamp" not in out.columns:
        out = out.with_columns(pl.lit(None).cast(pl.Datetime("us")).alias("timestamp"))
    return out.with_columns(
        [
            pl.lit(domain).alias("_domain"),
            pl.lit("rg_parquet").alias("data_source"),
        ]
    )


def load_parquet_logs(cpe_dir: Path, domains: List[str]) -> pl.DataFrame:
    frames: List[pl.DataFrame] = []
    for domain in domains:
        pq = cpe_dir / f"{domain}_rg.parquet"
        if not pq.is_file():
            continue
        try:
            df = pl.read_parquet(pq)
            if df.height == 0:
                continue
            frames.append(_normalize_log_frame(df, domain))
        except Exception as e:
            logger.warning("Could not read %s: %s", pq, e)
    if not frames:
        return pl.DataFrame(
            schema={
                "loglines": pl.Utf8,
                "source_file": pl.Utf8,
                "template": pl.Utf8,
                "timestamp": pl.Datetime("us"),
                "_domain": pl.Utf8,
                "data_source": pl.Utf8,
            }
        )
    return pl.concat(frames, how="diagonal_relaxed")


def merge_raw_fallback(
    parquet_df: pl.DataFrame,
    cpe_dir: Path,
    events: Dict[str, Any],
) -> tuple[pl.DataFrame, List[str], int]:
    globs = collect_globs_from_events(events)
    if not globs:
        return parquet_df, [], 0
    need = globs_needing_raw_fallback(parquet_df, globs)
    if not need:
        return parquet_df, [], 0
    raw_df, files_read = load_raw_lines_for_globs(cpe_dir, set(need))
    if raw_df.height == 0:
        return parquet_df, files_read, 0
    if "_domain" not in raw_df.columns:
        raw_df = raw_df.with_columns(pl.lit("raw").alias("_domain"))
    if parquet_df.height == 0:
        return raw_df, files_read, int(raw_df.height)
    return pl.concat([parquet_df, raw_df], how="diagonal_relaxed"), files_read, int(
        raw_df.height
    )


def run_pattern_lab(
    layout: DataLayoutManager,
    cpe_folder_serial: str,
    event_issue_doc: Dict[str, Any],
    device_serial: str,
    processing_date: str,
) -> Dict[str, Any]:
    """
    Label events and run rules on combined RG parquet + raw logs.

    Returns a dict suitable for API ``data`` (summary, event_breakdown, rule_rows).
    """
    cpe_dir = layout.get_cpe_source_dir(cpe_folder_serial)
    events = event_issue_doc.get("events") or {}
    issues = event_issue_doc.get("issues") or {}

    domains = _domains_from_doc(event_issue_doc, cpe_dir)
    parquet_df = load_parquet_logs(cpe_dir, domains)
    parquet_lines = int(parquet_df.height)

    df, raw_files, raw_lines = merge_raw_fallback(parquet_df, cpe_dir, events)

    if df.height == 0:
        return {
            "summary": {
                "device_serial": device_serial,
                "domains_scanned": domains,
                "skipped": True,
                "reason": "no_log_data",
                "total_log_lines": 0,
                "labeled_log_lines": 0,
                "unlabeled_log_lines": 0,
                "parquet_log_lines": 0,
                "raw_log_lines": 0,
                "raw_files_scanned": raw_files,
                "rules_with_matches": 0,
            },
            "event_breakdown": [],
            "rule_rows": [],
        }

    df = coerce_timestamp(df)
    df = with_event_code_column(df, events)
    df = filter_event_codes_by_field_conditions(df, events)
    df = enrich_correlation_columns(df, events)

    labeled = df.filter(pl.col("event_code").is_not_null())
    raw_issues = run_issue_detectors(labeled, issues, device_serial, processing_date)
    if raw_issues.height == 0:
        aggregated = raw_issues
    else:
        aggregated = aggregate_sta_issues_by_mac(raw_issues)

    return build_pattern_lab_result(
        df,
        events,
        issues,
        labeled,
        raw_issues,
        aggregated,
        cpe_serial=device_serial,
        domains_scanned=domains,
        parquet_lines=parquet_lines,
        raw_lines=raw_lines,
        raw_files_scanned=raw_files,
    )

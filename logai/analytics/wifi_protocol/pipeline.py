"""End-to-end WiFi protocol labeling + STA issue detection."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import polars as pl
import yaml

from logai.analytics.data_layout import DataLayoutManager

from .config_paths import wifi_auth_assoc_event_map_path
from .drain3_params import add_parameter_list_column
from .event_map import with_event_code_column
from .extractors import (
    enrich_correlation_columns,
    forward_fill_sta_mac_by_partition,
    scrub_sta_mac_matching_expected_bssid,
)
from .interface_map import build_interface_table, load_interface_map_yaml, model_matches_device
from .sequence_rules import run_issue_detectors
from .sta_aggregate import aggregate_sta_issues_by_mac

logger = logging.getLogger(__name__)

_STA_ISSUES_SCHEMA: Dict[str, pl.DataType] = {
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
    "occurrence_count": pl.Int64,
}


def _is_pattern_lab_mode(
    yaml_path: Path | None,
    event_issue_doc: Optional[Dict[str, Any]],
) -> bool:
    if event_issue_doc is not None:
        return True
    if yaml_path is None:
        return False
    try:
        return yaml_path.resolve() != wifi_auth_assoc_event_map_path().resolve()
    except OSError:
        return True


def empty_sta_issues() -> pl.DataFrame:
    return pl.DataFrame(schema=_STA_ISSUES_SCHEMA)


def _load_event_issue_yaml(path: Path | None = None) -> Dict[str, Any]:
    p = path or wifi_auth_assoc_event_map_path()
    if not p.is_file():
        logger.warning("wifi_auth_assoc_event_map.yaml missing at %s", p)
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _event_issue_from_source(
    yaml_path: Path | None,
    event_issue_doc: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if event_issue_doc is not None:
        return dict(event_issue_doc)
    return _load_event_issue_yaml(yaml_path)


def coerce_timestamp(df: pl.DataFrame) -> pl.DataFrame:
    if df.height == 0 or "timestamp" not in df.columns:
        return df
    dtype = df["timestamp"].dtype
    if dtype == pl.Datetime:
        return df
    if dtype in (pl.Utf8, pl.String):
        return df.with_columns(
            pl.col("timestamp").str.to_datetime(time_unit="us", strict=False)
        )
    try:
        return df.with_columns(pl.col("timestamp").cast(pl.Datetime(time_unit="us")))
    except Exception:
        return df


def run_wifi_sta_issues(
    layout: DataLayoutManager,
    serial: str,
    device_info: Dict[str, Any],
    processing_date: str,
    device_serial: str,
    write_labeled_debug: bool = False,
    yaml_path: Path | None = None,
    event_issue_doc: Optional[Dict[str, Any]] = None,
    include_event_diagnostics: bool = False,
) -> Tuple[pl.DataFrame, Dict[str, Any]]:
    """
    Load ``wireless_rg.parquet`` for CPE ``serial``, label events, extract Drain3
    parameters, run issue detectors, return ``sta_issues`` and summary stats.

    If ``event_issue_doc`` is set, it is used as the YAML root (``events`` / ``issues``)
    instead of reading from ``yaml_path`` or the repository default.
    """
    cpe_dir = layout.get_cpe_source_dir(serial)
    wireless_pq = cpe_dir / "wireless_rg.parquet"
    raw = _event_issue_from_source(yaml_path, event_issue_doc)
    events = raw.get("events") or {}
    issues = raw.get("issues") or {}
    pattern_lab_mode = _is_pattern_lab_mode(yaml_path, event_issue_doc)

    if not wireless_pq.is_file():
        logger.info("No wireless_rg.parquet for CPE %s", serial)
        return empty_sta_issues(), {
            "skipped": True,
            "reason": "no_wireless_parquet",
            "device_serial": device_serial,
        }

    df = pl.read_parquet(wireless_pq)
    if df.height == 0:
        return empty_sta_issues(), {
            "skipped": True,
            "reason": "empty_wireless_parquet",
            "device_serial": device_serial,
        }

    df = coerce_timestamp(df)
    df = with_event_code_column(df, events)
    from .field_extracts import filter_event_codes_by_field_conditions

    df = filter_event_codes_by_field_conditions(df, events)
    df = add_parameter_list_column(df, cpe_dir, domain="wireless")
    df = enrich_correlation_columns(df, events)

    if not pattern_lab_mode:
        iface_yaml = load_interface_map_yaml()
        if model_matches_device(iface_yaml, device_info):
            iface_tbl = build_interface_table(device_info, iface_yaml)
        else:
            iface_tbl = pl.DataFrame(
                schema={"ifname": pl.Utf8, "role": pl.Utf8, "bssid": pl.Utf8}
            )
        if iface_tbl.height > 0 and "ifname" in df.columns:
            df = df.join(
                iface_tbl.select(["ifname", "role", "bssid"]).rename(
                    {"role": "bss_role", "bssid": "expected_bssid"}
                ),
                on="ifname",
                how="left",
            )
        df = scrub_sta_mac_matching_expected_bssid(df)
        df = forward_fill_sta_mac_by_partition(df)

    labeled_for_detect = df.filter(pl.col("event_code").is_not_null())
    raw_issues = run_issue_detectors(
        labeled_for_detect, issues, device_serial, processing_date
    )
    if raw_issues.height == 0:
        sta_issues = empty_sta_issues()
    else:
        sta_issues = aggregate_sta_issues_by_mac(raw_issues)

    labeled_ct = int(labeled_for_detect.height)
    total_rows = int(df.height)
    stats: Dict[str, Any] = {
        "device_serial": device_serial,
        "pattern_lab_mode": pattern_lab_mode,
        "wireless_rows": total_rows,
        "total_log_lines": total_rows,
        "labeled_events": labeled_ct,
        "labeled_log_lines": labeled_ct,
        "unlabeled_log_lines": total_rows - labeled_ct,
        "sta_issues_rows": int(sta_issues.height),
    }

    if include_event_diagnostics:
        from .preview_diagnostics import build_preview_diagnostics

        diag = build_preview_diagnostics(
            df, events, issues, labeled_for_detect, raw_issues, sta_issues
        )
        stats.update(diag)

    if write_labeled_debug and df.height > 0:
        debug_path = layout.consolidated_parquet_path("wifi_labeled_events")
        layout.ensure_directories(layout.get_consolidated_analytics_dir())
        dbg = df.with_columns(
            [
                pl.lit(device_serial).alias("device_serial"),
                pl.lit(processing_date).alias("processing_date"),
            ]
        )
        from logai.analytics.consolidated_io import upsert_replace_device_serial

        upsert_replace_device_serial(debug_path, dbg, device_serial)
        stats["wifi_labeled_events_path"] = str(debug_path)

    return sta_issues, stats

"""
Consolidated analytics Parquet I/O: one file per dataset under issue_analysis/analytics/.

Replaces per-CPE / per-date partitioned folders for better Polars/DuckDB performance.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import polars as pl

from .data_layout import DataLayoutManager

logger = logging.getLogger(__name__)


def upsert_replace_device_serial(path: Path, new_df: pl.DataFrame, serial: str) -> None:
    """
    Replace rows for the given device_serial and append new_df; write atomically via temp file.

    If new_df is empty, only removes rows for serial (other rows unchanged).
    """
    key = "device_serial"
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        if new_df.height == 0:
            return
        if key not in new_df.columns:
            raise ValueError(
                f"Consolidated parquet requires column {key!r}: {path.name}"
            )
        new_df.write_parquet(path)
        return

    existing = pl.read_parquet(path)
    if key in existing.columns:
        kept = existing.filter(pl.col(key) != serial)
        # Drop orphan rows written when device_info had empty serial (bad .get default).
        nonempty = (
            pl.col(key).is_not_null()
            & (pl.col(key).cast(pl.Utf8).str.strip_chars() != "")
        )
        kept = kept.filter(nonempty)
    else:
        logger.warning(
            "Existing %s has no device_serial; replacing file with new data only",
            path.name,
        )
        kept = pl.DataFrame()

    if new_df.height == 0:
        out = kept
    else:
        if key not in new_df.columns:
            raise ValueError(f"New data must include {key!r} for {path.name}")
        if kept.height == 0:
            out = new_df
        elif set(kept.columns) == set(new_df.columns):
            out = pl.concat([kept, new_df], how="vertical")
        else:
            out = pl.concat([kept, new_df], how="diagonal")

    if out.height > 0:
        tmp = path.with_suffix(path.suffix + ".tmp")
        out.write_parquet(tmp)
        tmp.replace(path)
    elif path.exists():
        path.unlink()


def load_legacy_partitioned_parquets(
    layout: DataLayoutManager,
) -> Tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Load and combine legacy issue_analysis/cpes/serial=*/date=*/*.parquet files."""
    all_reboot: List[pl.DataFrame] = []
    all_dh: List[pl.DataFrame] = []
    all_sig: List[pl.DataFrame] = []
    all_et: List[pl.DataFrame] = []

    cpes_dir = layout.get_issue_analysis_dir() / "cpes"
    if not cpes_dir.is_dir():
        return tuple(pl.DataFrame() for _ in range(4))

    for serial_dir in sorted(cpes_dir.glob("serial=*")):
        if not serial_dir.is_dir():
            continue
        serial = serial_dir.name.replace("serial=", "")
        date_dirs = sorted(
            d
            for d in serial_dir.iterdir()
            if d.is_dir() and d.name.startswith("date=")
        )
        if not date_dirs:
            continue
        latest = date_dirs[-1]

        specs = [
            ("reboot_features", all_reboot, "reboot_features.parquet"),
            ("device_health", all_dh, "device_health.parquet"),
            ("signals", all_sig, "signals.parquet"),
            ("error_templates", all_et, "error_templates.parquet"),
        ]
        for kind, bucket, fname in specs:
            fp = latest / fname
            if not fp.is_file():
                continue
            try:
                df = pl.read_parquet(fp)
            except Exception as e:
                logger.warning("Failed to read legacy %s: %s", fp, e)
                continue
            if kind in ("signals", "error_templates") and "device_serial" not in df.columns:
                df = df.with_columns(pl.lit(serial).alias("device_serial"))
            bucket.append(df)

    def _concat(parts: List[pl.DataFrame]) -> pl.DataFrame:
        if not parts:
            return pl.DataFrame()
        if len(parts) == 1:
            return parts[0]
        return pl.concat(parts, how="diagonal")

    return (
        _concat(all_reboot),
        _concat(all_dh),
        _concat(all_sig),
        _concat(all_et),
    )


def ensure_migrated_from_legacy(layout: DataLayoutManager) -> bool:
    """
    If consolidated analytics are missing but legacy partitioned parquets exist,
    merge legacy into issue_analysis/analytics/*.parquet once.

    Returns:
        True if migration wrote consolidated files.
    """
    consolidated_dh = layout.consolidated_parquet_path("device_health")
    if consolidated_dh.is_file():
        return False

    cpes_dir = layout.get_issue_analysis_dir() / "cpes"
    if not cpes_dir.is_dir():
        return False

    rb, dh, sg, et = load_legacy_partitioned_parquets(layout)
    if dh.height == 0 and rb.height == 0 and sg.height == 0 and et.height == 0:
        return False

    analytics_dir = layout.get_consolidated_analytics_dir()
    layout.ensure_directories(analytics_dir)

    written = False
    for name, df in (
        ("reboot_features", rb),
        ("device_health", dh),
        ("signals", sg),
        ("error_templates", et),
    ):
        if df.height > 0:
            p = layout.consolidated_parquet_path(name)
            tmp = p.with_suffix(p.suffix + ".tmp")
            df.write_parquet(tmp)
            tmp.replace(p)
            written = True

    if written:
        logger.info(
            "Migrated legacy partitioned analytics to consolidated files under %s",
            analytics_dir,
        )
    return written

"""
Backfill consolidated analytics Parquet rows for fleet projects.

Runs Polars ETL for CPEs that have *_rg.parquet but no row yet in
issue_analysis/analytics/device_health.parquet (after any legacy migration).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from .consolidated_io import ensure_migrated_from_legacy
from .data_layout import DataLayoutManager
from .fleet_summary import _find_processed_cpes
from .polars_etl import polars_etl_per_cpe


def cpe_has_rg_inputs(layout: DataLayoutManager, serial: str) -> bool:
    """True if the CPE directory has at least one domain *_rg.parquet."""
    return len(layout.get_cpe_parquet_files(serial)) > 0


def backfill_missing_issue_analysis(
    user_id: str,
    project_id: str,
    processing_date: str | None = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Run polars_etl_per_cpe for each project CPE that lacks issue_analysis data
    but has RG parquet inputs.

    When ``force`` is True, run ETL for every CPE with ``*_rg.parquet`` even if
    consolidated analytics already exist (refreshes ``sta_issues`` and siblings).

    Returns:
        Summary dict with per-serial results and aggregate counts.
    """
    if processing_date is None:
        processing_date = datetime.now().strftime("%Y-%m-%d")

    layout = DataLayoutManager(user_id, project_id)
    ensure_migrated_from_legacy(layout)
    with_analytics = set(_find_processed_cpes(layout))
    fleet_serials = layout.list_cpes_with_rg_parquet()
    details: List[Dict[str, Any]] = []

    for serial in fleet_serials:
        if not force and serial in with_analytics:
            details.append(
                {
                    "serial": serial,
                    "status": "skipped",
                    "reason": "issue_analysis_already_present",
                }
            )
            continue
        if not cpe_has_rg_inputs(layout, serial):
            details.append(
                {
                    "serial": serial,
                    "status": "skipped",
                    "reason": "no_rg_parquet",
                }
            )
            continue
        result = polars_etl_per_cpe(user_id, project_id, serial, processing_date)
        details.append(result)
        if result.get("status") == "success":
            with_analytics.add(serial)

    backfilled = sum(1 for d in details if d.get("status") == "success")
    failed = [d for d in details if d.get("status") == "error"]
    skipped = sum(1 for d in details if d.get("status") == "skipped")

    return {
        "processing_date": processing_date,
        "force": force,
        "fleet_cpe_count": len(fleet_serials),
        "details": details,
        "backfilled_count": backfilled,
        "skipped_count": skipped,
        "failed_count": len(failed),
        "failures": [
            {"serial": f.get("serial"), "error": f.get("error")}
            for f in failed
            if f.get("serial") is not None
        ],
    }

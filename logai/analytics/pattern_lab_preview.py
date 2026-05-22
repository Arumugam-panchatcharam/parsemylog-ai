"""On-demand Pattern Lab preview for one CPE (no Parquet writes)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Tuple

from logai.analytics.data_layout import DataLayoutManager
from logai.analytics.pattern_lab.pipeline import run_pattern_lab
from logai.analytics.polars_etl import _cpe_identity_serial, _load_device_info


def preview_pattern_lab(
    user_id: str,
    project_id: str,
    cpe_folder_serial: str,
    event_issue_doc: Dict[str, Any],
    processing_date: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Run Pattern Lab labeling + rules for one CPE.

    Returns:
        (result_payload, stats) where result_payload has summary, event_breakdown, rule_rows.
    """
    if processing_date is None:
        processing_date = datetime.now().strftime("%Y-%m-%d")

    layout = DataLayoutManager(user_id, project_id)
    device_info = _load_device_info(layout, cpe_folder_serial)
    device_serial = _cpe_identity_serial(device_info, cpe_folder_serial)

    result = run_pattern_lab(
        layout,
        cpe_folder_serial,
        event_issue_doc,
        device_serial,
        processing_date,
    )
    stats = dict(result.get("summary") or {})
    stats["event_breakdown"] = result.get("event_breakdown") or []
    stats["rule_breakdown"] = [
        {
            "issue_key": r.get("rule_key"),
            "detect_type": r.get("detect_type"),
            "group_by": r.get("group_by"),
            "candidate_labeled_rows": r.get("candidate_labeled_rows"),
            "issue_rows": r.get("total_matches"),
            "skip_reason": r.get("skip_reason"),
        }
        for r in result.get("rule_rows") or []
    ]
    return result, stats

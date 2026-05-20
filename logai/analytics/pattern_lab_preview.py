"""On-demand pattern lab preview for one CPE (no Parquet writes)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple

from logai.analytics.data_layout import DataLayoutManager
from logai.analytics.polars_etl import _cpe_identity_serial, _load_device_info
from logai.analytics.wifi_protocol.pipeline import run_wifi_sta_issues


def preview_pattern_lab(
    user_id: str,
    project_id: str,
    cpe_folder_serial: str,
    event_issue_doc: Dict[str, Any],
    processing_date: str | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Run issue detection pipeline with an in-memory event/issue document.

    Returns:
        (issue_rows_as_dicts, pipeline_stats) including skip reasons when data is missing.
    """
    if processing_date is None:
        processing_date = datetime.now().strftime("%Y-%m-%d")

    layout = DataLayoutManager(user_id, project_id)
    device_info = _load_device_info(layout, cpe_folder_serial)
    device_serial = _cpe_identity_serial(device_info, cpe_folder_serial)

    sta_issues, stats = run_wifi_sta_issues(
        layout,
        cpe_folder_serial,
        device_info,
        processing_date,
        device_serial,
        write_labeled_debug=False,
        yaml_path=None,
        event_issue_doc=event_issue_doc,
    )

    if sta_issues.height == 0:
        return [], stats

    rows = sta_issues.to_dicts()
    out: List[Dict[str, Any]] = []
    for row in rows:
        clean: Dict[str, Any] = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                clean[k] = v.isoformat()
            else:
                clean[k] = v
        out.append(clean)
    return out, stats

"""Build Pattern Lab API response from pipeline dataframes."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import polars as pl

from logai.analytics.wifi_protocol.preview_diagnostics import (
    build_event_breakdown,
    build_rule_breakdown,
)


def _issue_samples(raw_issues: pl.DataFrame, issue_key: str, limit: int = 3) -> List[Dict[str, Any]]:
    if raw_issues.height == 0 or "issue_key" not in raw_issues.columns:
        return []
    sub = raw_issues.filter(pl.col("issue_key") == issue_key)
    if sub.height == 0:
        return []
    out: List[Dict[str, Any]] = []
    for row in sub.head(limit).to_dicts():
        evidence_raw = row.get("evidence") or "[]"
        try:
            evidence = json.loads(evidence_raw) if isinstance(evidence_raw, str) else evidence_raw
        except json.JSONDecodeError:
            evidence = [{"raw": evidence_raw}]
        if isinstance(evidence, list) and evidence:
            for ev in evidence[:limit]:
                if isinstance(ev, dict):
                    out.append(
                        {
                            "timestamp": str(ev.get("timestamp") or row.get("window_start") or ""),
                            "source_file": "",
                            "logline": str(ev.get("loglines") or ev.get("event") or "")[:300],
                        }
                    )
        if len(out) >= limit:
            break
    return out[:limit]


def build_pattern_lab_result(
    df: pl.DataFrame,
    events: Dict[str, Any],
    issues: Dict[str, Any],
    labeled: pl.DataFrame,
    raw_issues: pl.DataFrame,
    aggregated: pl.DataFrame,
    *,
    cpe_serial: str,
    domains_scanned: List[str],
    parquet_lines: int,
    raw_lines: int,
    raw_files_scanned: List[str],
) -> Dict[str, Any]:
    """Shape returned as API ``data`` payload."""
    diag = {
        "event_breakdown": build_event_breakdown(df, events),
        "rule_breakdown": build_rule_breakdown(labeled, issues, raw_issues, aggregated),
    }

    rule_rows: List[Dict[str, Any]] = []
    for rb in diag["rule_breakdown"]:
        ik = rb["issue_key"]
        agg_n = int(rb.get("issue_rows") or 0)
        raw_n = int(rb.get("issue_rows_raw") or 0)
        total = max(agg_n, raw_n)
        rule_rows.append(
            {
                "rule_key": ik,
                "detect_type": rb.get("detect_type") or "",
                "group_by": rb.get("group_by") or [],
                "total_matches": total,
                "candidate_labeled_rows": rb.get("candidate_labeled_rows") or 0,
                "skip_reason": rb.get("skip_reason") or "",
                "samples": _issue_samples(raw_issues, ik),
                "per_cpe": [{"serial": cpe_serial, "count": total}] if total > 0 else [],
            }
        )

    total = int(df.height)
    labeled_ct = int(labeled.height)

    return {
        "summary": {
            "device_serial": cpe_serial,
            "domains_scanned": domains_scanned,
            "total_log_lines": total,
            "labeled_log_lines": labeled_ct,
            "unlabeled_log_lines": total - labeled_ct,
            "parquet_log_lines": parquet_lines,
            "raw_log_lines": raw_lines,
            "raw_files_scanned": raw_files_scanned,
            "rules_with_matches": sum(1 for r in rule_rows if r["total_matches"] > 0),
        },
        "event_breakdown": diag["event_breakdown"],
        "rule_rows": rule_rows,
    }

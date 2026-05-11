"""
Numeric extraction and threshold comparison for Pattern Analyzer patterns.

Patterns may include ``value_compare`` (project YAML only) to classify each CPE
as matching (1) or not (0) in multi-CPE overview scans, based on aggregated
extracted numeric values per operator semantics.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

VALUE_COMPARE_OPERATORS = frozenset({"gt", "gte", "lt", "lte", "eq", "neq"})
VALUE_COMPARE_KINDS = frozenset({"int", "float"})


def parse_value_compare_config(vc_raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Validate and normalize ``value_compare`` from a pattern dict.

    Returns:
        ``(normalized, None)`` or ``(None, error_message)``.
    """
    if vc_raw is None or vc_raw is False:
        return None, None

    if not isinstance(vc_raw, dict):
        return None, "value_compare must be an object"

    if not bool(vc_raw.get("enabled")):
        return None, None

    op = str(vc_raw.get("operator") or "").strip().lower()
    if op not in VALUE_COMPARE_OPERATORS:
        return None, (
            f"value_compare.operator must be one of "
            f"{', '.join(sorted(VALUE_COMPARE_OPERATORS))}"
        )

    ct_raw = vc_raw.get("compare_to")
    try:
        if isinstance(ct_raw, bool):
            return None, "value_compare.compare_to cannot be boolean"
        if isinstance(ct_raw, int) and not isinstance(ct_raw, bool):
            compare_to = float(ct_raw)
        elif isinstance(ct_raw, float):
            compare_to = float(ct_raw)
        else:
            s = str(ct_raw).strip()
            if "/" in s and op not in ("eq", "neq"):
                compare_to = float(s)
            elif "." in s or "e" in s.lower():
                compare_to = float(s)
            else:
                compare_to = float(int(s))
    except (ValueError, TypeError):
        return None, "value_compare.compare_to must be a number"

    kind = str(vc_raw.get("numeric_kind") or "int").strip().lower()
    if kind not in VALUE_COMPARE_KINDS:
        return None, f"value_compare.numeric_kind must be one of {sorted(VALUE_COMPARE_KINDS)}"

    cap_raw = vc_raw.get("capture_group")
    group = int(cap_raw) if cap_raw is not None else 1
    if group < 1:
        return None, "value_compare.capture_group must be >= 1"

    normalized: Dict[str, Any] = {
        "enabled": True,
        "operator": op,
        "compare_to": compare_to,
        "numeric_kind": kind,
        "capture_group": group,
    }

    return normalized, None


def validate_regex_capture_group_count(regex_str: str, capture_group: int) -> Optional[str]:
    """Return an error message if ``regex_str`` lacks enough capturing groups."""
    try:
        cre = re.compile(regex_str)
    except re.error as e:
        return f"invalid regex: {e}"
    if cre.groups < capture_group:
        return (
            f"regex must define at least {capture_group} capturing group(s) when "
            f"value_compare is enabled (e.g. Waninit_start=(\\\\d+))"
        )
    return None


def extract_numeric_from_match(
    m: re.Match[str],
    capture_group: int,
    numeric_kind: str,
) -> Optional[float]:
    """Extract and parse numeric value from regex match ``m``."""
    try:
        raw_g = m.group(capture_group)
    except IndexError:
        return None

    if raw_g is None:
        return None

    s = str(raw_g).strip()
    if not s:
        return None

    try:
        if numeric_kind == "int":
            v = float(int(s.split(".", 1)[0]))
        else:
            v = float(s)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (ValueError, TypeError):
        return None


def values_satisfy_compare(
    values: List[float],
    operator: str,
    compare_to: float,
    numeric_kind: str,
) -> bool:
    """
    Return True if aggregated / existential semantics pass for ``values``.
    Empty list → False.

    Aggregation:
      - gt, gte: max(values)
      - lt, lte: min(values)
      - eq, neq: any single value satisfies the predicate
    """
    if not values:
        return False

    tol = (
        None
        if numeric_kind != "float"
        else max(1e-9 * max(abs(max(values)), abs(compare_to), 1), 1e-12)
    )

    def _eq(a: float, b: float) -> bool:
        if tol is None:
            return float(a) == float(b)
        return math.isclose(a, b, rel_tol=0, abs_tol=tol)

    if operator == "gt":
        return max(values) > compare_to
    if operator == "gte":
        return max(values) >= compare_to
    if operator == "lt":
        return min(values) < compare_to
    if operator == "lte":
        return min(values) <= compare_to
    if operator == "eq":
        return any(_eq(v, compare_to) for v in values)
    if operator == "neq":
        return any(not _eq(v, compare_to) for v in values)
    return False


def finalize_cpe_counts_for_value_compare_tasks(
    per_pattern_counts: Dict[str, Dict[str, int]],
    all_tasks: List[Dict[str, Any]],
    cpe_serials: List[str],
    gathered: Dict[str, Dict[str, List[float]]],
) -> None:
    """
    For each task carrying ``value_compare_cfg`` (normalized), set counts to 1 or 0 per
    serial from ``gathered``. Other tasks are unchanged.
    """
    for t in all_tasks:
        cfg = t.get("value_compare_cfg")
        if not isinstance(cfg, dict):
            continue
        key = f"{t['domain']}::{t['idx']}"
        row = per_pattern_counts.setdefault(key, {s: 0 for s in cpe_serials})
        by_serial_vals = gathered.get(key, {})

        operator = str(cfg["operator"])
        compare_to = float(cfg["compare_to"])
        nk = str(cfg["numeric_kind"])

        for serial in cpe_serials:
            vals = by_serial_vals.get(serial, [])
            row[serial] = 1 if values_satisfy_compare(vals, operator, compare_to, nk) else 0

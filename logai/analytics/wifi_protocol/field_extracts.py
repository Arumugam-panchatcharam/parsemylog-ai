"""Generic per-event field extraction from log line regex capture groups."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import polars as pl

from .interface_map import normalize_mac

_COMPARE_OPS = frozenset({"lt", "gt", "lte", "gte", "eq"})


def _regex_group(line: str, pattern: str, group: int) -> str:
    if not pattern or not line:
        return ""
    try:
        m = re.search(pattern, line)
    except re.error:
        return ""
    if not m or not m.groups():
        return ""
    gi = max(1, int(group))
    if gi > len(m.groups()):
        return ""
    return str(m.group(gi)).strip()


def _compare(raw: str, typ: str, op: str, target: str) -> bool:
    if op not in _COMPARE_OPS:
        return True
    if typ == "number":
        try:
            a = float(raw)
            b = float(target)
        except ValueError:
            return False
        if op == "eq":
            return a == b
        if op == "lt":
            return a < b
        if op == "lte":
            return a <= b
        if op == "gt":
            return a > b
        if op == "gte":
            return a >= b
        return False
    if op == "eq":
        return raw == target
    return False


def _iter_matcher_regex_refs(spec: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Yield (matcher_ref, logline_regex pattern) from event match conditions."""
    out: List[Tuple[str, str]] = []
    for mi, m in enumerate(spec.get("matchers") or []):
        if not isinstance(m, dict):
            continue
        and_list = m.get("and")
        if isinstance(and_list, list):
            for ai, sub in enumerate(and_list):
                if isinstance(sub, dict) and sub.get("logline_regex"):
                    out.append((f"{mi}-{ai}", str(sub["logline_regex"])))
        elif m.get("logline_regex"):
            out.append((f"{mi}-0", str(m["logline_regex"])))
    return out


def _resolve_rule_regex(rule: Dict[str, Any], spec: Dict[str, Any]) -> str:
    ref = rule.get("matcher_ref")
    if ref:
        for key, pat in _iter_matcher_regex_refs(spec):
            if key == str(ref):
                return pat
    return str(rule.get("logline_regex") or "")


def _rules_for_event(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    raw = spec.get("field_extracts")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("name") and item.get("logline_regex"):
                out.append(item)
    for legacy in ("sta_mac", "wcid", "ifname"):
        block = spec.get(legacy)
        if isinstance(block, dict) and block.get("logline_regex"):
            out.append(
                {
                    "name": legacy,
                    "logline_regex": block.get("logline_regex"),
                    "group": block.get("group", 1),
                    "type": "string",
                }
            )
    return out


def field_extract_rules_pass(line: str, spec: Dict[str, Any]) -> bool:
    """When a rule sets ``condition``, captured value must satisfy it for the line to match."""
    for rule in _rules_for_event(spec):
        cond = rule.get("condition")
        if not cond or cond not in _COMPARE_OPS:
            continue
        rx = _resolve_rule_regex(rule, spec)
        gi = int(rule.get("group") or 1)
        raw = _regex_group(line, rx, gi)
        if not raw:
            return False
        typ = str(rule.get("type") or "string")
        if not _compare(raw, typ, str(cond), str(rule.get("compare") or "")):
            return False
    return True


def extract_field_values(
    event_code: Optional[str],
    line: str,
    events_yaml: Dict[str, Any],
) -> Dict[str, str]:
    if not event_code:
        return {}
    spec = events_yaml.get(event_code) or {}
    values: Dict[str, str] = {}
    for rule in _rules_for_event(spec):
        name = str(rule.get("name") or "").strip()
        if not name:
            continue
        rx = _resolve_rule_regex(rule, spec)
        gi = int(rule.get("group") or 1)
        raw = _regex_group(line, rx, gi)
        if name == "sta_mac" and raw:
            raw = normalize_mac(raw) or raw
        values[name] = raw
    return values


def filter_event_codes_by_field_conditions(
    df: pl.DataFrame,
    events_yaml: Dict[str, Any],
) -> pl.DataFrame:
    """Clear ``event_code`` when conditional ``field_extracts`` rules fail."""
    if df.height == 0 or "event_code" not in df.columns:
        return df
    rows = df.to_dicts()
    codes: List[Optional[str]] = []
    for r in rows:
        ev = r.get("event_code")
        if ev is None or ev == "":
            codes.append(ev)
            continue
        line = str(r.get("loglines") or "")
        spec = events_yaml.get(str(ev)) or {}
        if field_extract_rules_pass(line, spec):
            codes.append(str(ev))
        else:
            codes.append(None)
    return df.with_columns(pl.Series("event_code", codes))


def enrich_field_extract_columns(
    df: pl.DataFrame,
    events_yaml: Dict[str, Any],
) -> pl.DataFrame:
    """Add columns for each ``field_extracts[].name`` (plus legacy sta_mac/wcid/ifname)."""
    if df.height == 0:
        return df

    all_names: List[str] = []
    for _code, spec in events_yaml.items():
        if not isinstance(spec, dict):
            continue
        for rule in _rules_for_event(spec):
            n = str(rule.get("name") or "").strip()
            if n and n not in all_names:
                all_names.append(n)

    if not all_names:
        return df

    rows = df.to_dicts()
    series: Dict[str, List[str]] = {n: [] for n in all_names}
    for r in rows:
        ev = r.get("event_code")
        line = str(r.get("loglines") or "")
        vals = extract_field_values(
            str(ev) if ev is not None else None,
            line,
            events_yaml,
        )
        for n in all_names:
            series[n].append(vals.get(n, ""))

    return df.with_columns([pl.Series(n, series[n]) for n in all_names])

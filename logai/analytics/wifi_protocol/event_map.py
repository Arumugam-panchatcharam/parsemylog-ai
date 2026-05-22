"""Vectorized event labeling from YAML matchers (Polars)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

import polars as pl

logger = logging.getLogger(__name__)


def _glob_to_polars_regex(glob_pat: str) -> str:
    """
    Convert a shell-style glob to regex for Polars ``str.contains`` (Rust regex).

    ``fnmatch.translate`` emits PCRE-only constructs (``(?s:…)``, ``(?>…)``, ``\\Z``)
    that Polars rejects.
    """
    if not glob_pat:
        return "^$"

    parts: List[str] = []
    i = 0
    n = len(glob_pat)
    while i < n:
        c = glob_pat[i]
        if c == "*":
            parts.append(".*")
            i += 1
        elif c == "?":
            parts.append(".")
            i += 1
        elif c == "[":
            j = glob_pat.find("]", i + 1)
            if j < 0:
                parts.append(re.escape(c))
                i += 1
            else:
                parts.append(glob_pat[i : j + 1])
                i = j + 1
        else:
            parts.append(re.escape(c))
            i += 1
    return f"^{''.join(parts)}$"


def load_events_ordered(raw_events: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Preserve YAML insertion order (Python 3.7+ dict)."""
    return list(raw_events.items())


def _matcher_expr(m: Dict[str, Any], has_source_file: bool) -> pl.Expr:
    and_list = m.get("and")
    if isinstance(and_list, list) and and_list:
        sub_exprs = [
            _matcher_expr(x, has_source_file)
            for x in and_list
            if isinstance(x, dict)
        ]
        if not sub_exprs:
            return pl.lit(False)
        out = sub_exprs[0]
        for e in sub_exprs[1:]:
            out = out & e
        return out

    parts: List[pl.Expr] = []
    if "template_contains" in m and m["template_contains"]:
        parts.append(
            pl.col("template").fill_null("").str.contains(str(m["template_contains"]), literal=True)
        )
    if "template_regex" in m and m["template_regex"]:
        pat = str(m["template_regex"])
        try:
            re.compile(pat)
        except re.error as e:
            logger.warning("Invalid template_regex %r: %s", pat, e)
        else:
            parts.append(pl.col("template").fill_null("").str.contains(pat))
    if "logline_contains" in m and m["logline_contains"]:
        parts.append(
            pl.col("loglines").fill_null("").str.contains(str(m["logline_contains"]), literal=True)
        )
    if "logline_regex" in m and m["logline_regex"]:
        pat = str(m["logline_regex"])
        try:
            re.compile(pat)
        except re.error as e:
            logger.warning("Invalid logline_regex %r: %s", pat, e)
        else:
            parts.append(pl.col("loglines").fill_null("").str.contains(pat))
    if "source_file_glob" in m and m["source_file_glob"] and has_source_file:
        glob_pat = str(m["source_file_glob"])
        rx = _glob_to_polars_regex(glob_pat)
        parts.append(pl.col("source_file").fill_null("").str.contains(rx))

    if not parts:
        return pl.lit(False)
    out = parts[0]
    for p in parts[1:]:
        out = out & p
    return out


def _event_level_file_expr(spec: Dict[str, Any], has_source_file: bool) -> pl.Expr:
    glob_pat = spec.get("source_file_glob")
    if not glob_pat or not has_source_file:
        return pl.lit(True)
    rx = _glob_to_polars_regex(str(glob_pat))
    return pl.col("source_file").fill_null("").str.contains(rx)


def _event_match_expr(
    spec: Dict[str, Any], has_source_file: bool
) -> pl.Expr:
    cond = pl.lit(False)
    for m in spec.get("matchers") or []:
        if not isinstance(m, dict):
            continue
        cond = cond | _matcher_expr(m, has_source_file)
    return cond & _event_level_file_expr(spec, has_source_file)


def with_event_code_column(df: pl.DataFrame, events: Dict[str, Any]) -> pl.DataFrame:
    """
    Add ``event_code`` using first matching event definition (dict order).
    Unmatched rows get null event_code.
    """
    if df.height == 0:
        return df.with_columns(pl.lit(None).cast(pl.Utf8).alias("event_code"))

    has_sf = "source_file" in df.columns
    if "template" not in df.columns:
        df = df.with_columns(pl.lit("").alias("template"))
    if "loglines" not in df.columns:
        df = df.with_columns(pl.lit("").alias("loglines"))

    expr: pl.Expr = pl.lit(None).cast(pl.Utf8)
    for eid, spec in reversed(load_events_ordered(events)):
        cond = _event_match_expr(spec, has_sf)
        expr = pl.when(cond).then(pl.lit(eid)).otherwise(expr)

    return df.with_columns(expr.alias("event_code"))

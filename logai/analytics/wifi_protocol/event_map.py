"""Vectorized event labeling from YAML matchers (Polars)."""

from __future__ import annotations

import fnmatch
import logging
import re
from typing import Any, Dict, List, Tuple

import polars as pl

logger = logging.getLogger(__name__)


def load_events_ordered(raw_events: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Preserve YAML insertion order (Python 3.7+ dict)."""
    return list(raw_events.items())


def _matcher_expr(m: Dict[str, Any], has_source_file: bool) -> pl.Expr:
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
        rx = fnmatch.translate(glob_pat)
        parts.append(pl.col("source_file").fill_null("").str.contains(rx))

    if not parts:
        return pl.lit(False)
    out = parts[0]
    for p in parts[1:]:
        out = out & p
    return out


def _event_match_expr(
    spec: Dict[str, Any], has_source_file: bool
) -> pl.Expr:
    cond = pl.lit(False)
    for m in spec.get("matchers") or []:
        if not isinstance(m, dict):
            continue
        cond = cond | _matcher_expr(m, has_source_file)
    return cond


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

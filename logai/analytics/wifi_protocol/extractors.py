"""Derive sta_mac, wcid, ifname from parameter_list + YAML + regex fallbacks."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import polars as pl

from .interface_map import normalize_mac

_MAC_HEX_LEN = 12


def _is_plausible_sta_mac(normalized: str) -> bool:
    """True if value looks like a 48-bit MAC after normalization (12 hex digits)."""
    if not normalized:
        return False
    h = re.sub(r"[^0-9a-fA-F]", "", normalized)
    return len(h) == _MAC_HEX_LEN


def _param_at(params: Optional[List[str]], idx: Optional[int]) -> str:
    if params is None or idx is None:
        return ""
    if idx < 0 or idx >= len(params):
        return ""
    return str(params[idx]).strip()


def _regex_first_group(line: str, pattern: Optional[str]) -> str:
    if not pattern or not line:
        return ""
    try:
        m = re.search(pattern, line)
    except re.error:
        return ""
    if not m:
        return ""
    if m.lastgroup:
        return str(m.group(m.lastgroup)).strip()
    if m.groups():
        return str(m.group(1)).strip()
    return ""


def _field_for_row(
    event_code: Optional[str],
    line: str,
    params: Optional[List[str]],
    events_yaml: Dict[str, Any],
    field: str,
) -> str:
    if not event_code:
        return ""
    spec = events_yaml.get(event_code) or {}
    block = spec.get(field)
    if not isinstance(block, dict):
        block = {}
    idx = block.get("param_index")
    from_param = ""
    if idx is not None and params is not None:
        try:
            pi = int(idx)
        except (TypeError, ValueError):
            pi = None
        else:
            raw = _param_at(params, pi)
            if raw:
                from_param = normalize_mac(raw) if field == "sta_mac" else raw

    rx = block.get("logline_regex")
    from_rx = _regex_first_group(line, str(rx) if rx else None)
    if from_rx:
        from_rx = normalize_mac(from_rx) if field == "sta_mac" else from_rx

    if field == "sta_mac":
        # Prefer Drain3 slot only if it resolves to a real MAC (avoids alg/seq/wcid confusion).
        if from_param and _is_plausible_sta_mac(from_param):
            return from_param
        if from_rx and _is_plausible_sta_mac(from_rx):
            return from_rx
        return ""

    if from_param:
        return from_param
    if from_rx:
        return from_rx
    return ""


def enrich_correlation_columns(
    df: pl.DataFrame,
    events_yaml: Dict[str, Any],
) -> pl.DataFrame:
    """Add sta_mac, wcid, ifname columns."""
    if df.height == 0:
        return df.with_columns(
            [
                pl.lit("").alias("sta_mac"),
                pl.lit("").alias("wcid"),
                pl.lit("").alias("ifname"),
            ]
        )

    has_params = "parameter_list" in df.columns
    rows = df.to_dicts()
    sta: List[str] = []
    wcid: List[str] = []
    ifn: List[str] = []

    for r in rows:
        ev = r.get("event_code")
        line = str(r.get("loglines") or "")
        params = r.get("parameter_list") if has_params else None
        if not isinstance(params, list):
            params = None

        sm = _field_for_row(ev, line, params, events_yaml, "sta_mac")
        wc = _field_for_row(ev, line, params, events_yaml, "wcid")
        iface = _field_for_row(ev, line, params, events_yaml, "ifname")

        sta.append(sm)
        wcid.append(wc)
        ifn.append(iface)

    out = df.with_columns(
        [
            pl.Series("sta_mac", sta),
            pl.Series("wcid", wcid),
            pl.Series("ifname", ifn),
        ]
    )
    return out


def forward_fill_sta_mac_by_partition(out: pl.DataFrame) -> pl.DataFrame:
    """Help EAPOL Send lines that omit MAC: forward-fill within source_file."""
    if out.height == 0:
        return out
    empty_to_null = (
        pl.when(pl.col("sta_mac") == "")
        .then(pl.lit(None).cast(pl.Utf8))
        .otherwise(pl.col("sta_mac"))
    )
    if "source_file" in out.columns:
        return (
            out.sort(["source_file", "timestamp"])
            .with_columns(empty_to_null.alias("_sta_mac_ff"))
            .with_columns(
                pl.col("_sta_mac_ff")
                .forward_fill()
                .over("source_file")
                .fill_null("")
                .alias("sta_mac")
            )
            .drop("_sta_mac_ff")
        )
    return (
        out.sort("timestamp")
        .with_columns(empty_to_null.alias("_sta_mac_ff"))
        .with_columns(
            pl.col("_sta_mac_ff").forward_fill().fill_null("").alias("sta_mac")
        )
        .drop("_sta_mac_ff")
    )

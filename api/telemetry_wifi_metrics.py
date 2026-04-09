"""
WiFi RF metrics for cross-CPE telemetry overview.

Derives channel change events, utilization (crowding), and latest bandwidth/band
from the cached telemetry API response (charts + status_labels).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# Crowding: flag if max utilization across samples is at or above this %, or avg is at/above _UTIL_CROWDED_AVG_PCT.
_UTIL_CROWDED_MAX_PCT = 70.0
_UTIL_CROWDED_AVG_PCT = 50.0

# EU (ETSI-harmonized) 5 GHz DFS channel numbers — default domain (indicative; national rules may differ).
# 5250–5350 MHz: 52–64. 5470–5725 MHz: 100–140 (US often extends DFS styling to 141–144; EU high band stops at 140).
_DFS_CHANNELS_5GHZ_EU = frozenset(range(52, 65)) | frozenset(range(100, 141))

# EU 5 GHz subset with prominent radar / military system overlap in the mid-UNII band (indicative).
# Kept in sync with frontend fleet channel styling. Radar rows are styled separately from other DFS.
_RADAR_CHANNELS_5GHZ_EU = frozenset({116, 120, 124, 128, 132})

_RADIO_CHANNEL_LABEL = re.compile(r"^Radio (\d+) Channel$")
_RADIO_UTIL_LABEL = re.compile(r"^Radio (\d+) Ch Util$")


def _band_hint(band_str: Optional[str]) -> str:
    """Return coarse band key: '5', '6', '2.4', or ''."""
    if not band_str:
        return ""
    s = str(band_str).upper().replace("_", ".")
    if "6G" in s or ("6" in s and "GHZ" in s) or "6.0" in s:
        return "6"
    if "5G" in s or "5GHZ" in s or ("5" in s and "GHZ" in s):
        return "5"
    if "2.4" in s or "24" in s or "2_4" in s:
        return "2.4"
    return ""


def _dfs_related_for_channel(band_hint: str, channel: Optional[float]) -> bool:
    if band_hint != "5" or channel is None:
        return False
    ch = int(round(channel))
    return ch in _DFS_CHANNELS_5GHZ_EU


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _chart_group(charts: Optional[List[Dict[str, Any]]], group_name: str) -> Optional[Dict[str, Any]]:
    for chart in charts or []:
        if chart.get("group") == group_name:
            return chart
    return None


def _radios_from_status(status_labels: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, str]]:
    """instance id -> meta strings from Radio status cards."""
    out: Dict[str, Dict[str, str]] = {}
    for entry in status_labels or []:
        if entry.get("type") != "Radio":
            continue
        inst = str(entry.get("instance") or "")
        meta = entry.get("meta") or {}
        if not isinstance(meta, dict):
            continue
        merged: Dict[str, str] = {}
        for k, val in meta.items():
            merged[str(k)] = "" if val is None else str(val)
        out[inst] = merged
    return out


def _channel_events_for_trace(
    radio: int,
    times: List[Any],
    values: List[Any],
    band_hint: str,
) -> Tuple[List[Dict[str, Any]], Optional[float], Optional[float], int]:
    events: List[Dict[str, Any]] = []
    prev: Optional[float] = None
    first_v: Optional[float] = None
    last_v: Optional[float] = None

    for t, raw in zip(times or [], values or []):
        cur = _num(raw)
        if cur is None:
            continue
        if first_v is None:
            first_v = cur
        if prev is None:
            prev = cur
            last_v = cur
            continue
        last_v = cur
        if cur != prev:
            dfs_rel = (
                _dfs_related_for_channel(band_hint, prev)
                or _dfs_related_for_channel(band_hint, cur)
            )
            events.append({
                "radio": radio,
                "from_channel": prev,
                "to_channel": cur,
                "at_time": str(t) if t is not None else "",
                "dfs_related": dfs_rel,
            })
            prev = cur

    changes = len(events)
    return events, first_v, last_v, changes


def _util_stats(times: List[Any], values: List[Any]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    nums: List[float] = []
    for raw in values or []:
        v = _num(raw)
        if v is not None:
            nums.append(v)
    if not nums:
        return None, None, None, None
    avg = round(sum(nums) / len(nums), 2)
    return nums[0], nums[-1], round(max(nums), 2), avg


def extract_wifi_rf_from_cache(cached: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build wifi_rf payload from a telemetry cache / parse response dict.

    Returns a new dict suitable for merging into cross-CPE CPE entries.
    """
    charts = cached.get("charts")
    status_by_inst = _radios_from_status(cached.get("status_labels"))

    ch_chart = _chart_group(charts, "WiFi Radio Channel")
    util_chart = _chart_group(charts, "WiFi Radio Utilization")

    channel_events: List[Dict[str, Any]] = []
    per_radio: Dict[int, Dict[str, Any]] = {}

    def ensure_radio(r: int) -> Dict[str, Any]:
        if r not in per_radio:
            inst_meta = status_by_inst.get(str(r), {})
            band_raw = inst_meta.get("Band")
            per_radio[r] = {
                "radio": r,
                "band": band_raw or None,
                "bandwidth": inst_meta.get("BW") or None,
                "channel_first": _num(inst_meta.get("Channel")),
                "channel_last": _num(inst_meta.get("Channel")),
                "channel_change_count": 0,
                "util_first": None,
                "util_last": None,
                "util_max": None,
                "util_avg": None,
                "crowded": False,
            }
        return per_radio[r]

    for inst in status_by_inst:
        try:
            rnum = int(inst)
        except ValueError:
            continue
        ensure_radio(rnum)

    if ch_chart:
        for trace in ch_chart.get("traces") or []:
            label = trace.get("label") or ""
            m = _RADIO_CHANNEL_LABEL.match(str(label))
            if not m:
                continue
            radio = int(m.group(1))
            row = ensure_radio(radio)
            band_h = _band_hint(row.get("band"))
            evts, first_v, last_v, n_changes = _channel_events_for_trace(
                radio,
                list(trace.get("times") or []),
                list(trace.get("values") or []),
                band_h,
            )
            for e in evts:
                e_with_band = {**e, "band": row.get("band")}
                channel_events.append(e_with_band)
            if first_v is not None:
                row["channel_first"] = first_v
            if last_v is not None:
                row["channel_last"] = last_v
            row["channel_change_count"] = n_changes

    if util_chart:
        for trace in util_chart.get("traces") or []:
            label = trace.get("label") or ""
            m = _RADIO_UTIL_LABEL.match(str(label))
            if not m:
                continue
            radio = int(m.group(1))
            row = ensure_radio(radio)
            u_first, u_last, u_max, u_avg = _util_stats(
                list(trace.get("times") or []),
                list(trace.get("values") or []),
            )
            row["util_first"] = u_first
            row["util_last"] = u_last
            row["util_max"] = u_max
            row["util_avg"] = u_avg
            crowded = False
            if u_max is not None and u_max >= _UTIL_CROWDED_MAX_PCT:
                crowded = True
            if u_avg is not None and u_avg >= _UTIL_CROWDED_AVG_PCT:
                crowded = True
            row["crowded"] = crowded

    radios_sorted = [per_radio[k] for k in sorted(per_radio.keys())]

    return {
        "wifi_rf": {
            "radios": radios_sorted,
            "channel_events": channel_events,
            "util_crowded_max_pct": _UTIL_CROWDED_MAX_PCT,
            "util_crowded_avg_pct": _UTIL_CROWDED_AVG_PCT,
        }
    }


def aggregate_wifi_fleet_from_cpes(cpe_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fleet-level rollups from per-CPE entries (each may contain wifi_rf)."""
    cpes_with_channel_changes = 0
    cpes_with_dfs_hint = 0
    cpes_wifi_crowded = 0
    transition_counts: Dict[Tuple[float, float], int] = {}
    total_channel_events = 0

    for cpe in cpe_results:
        wf = cpe.get("wifi_rf")
        if not wf:
            continue
        events = wf.get("channel_events") or []
        if events:
            cpes_with_channel_changes += 1
        total_channel_events += len(events)
        if any(e.get("dfs_related") for e in events):
            cpes_with_dfs_hint += 1
        radios = wf.get("radios") or []
        if any(r.get("crowded") for r in radios):
            cpes_wifi_crowded += 1
        for e in events:
            if "from_channel" not in e or "to_channel" not in e:
                continue
            key = (float(e["from_channel"]), float(e["to_channel"]))
            transition_counts[key] = transition_counts.get(key, 0) + 1

    histogram = [
        {"from": a, "to": b, "count": c}
        for (a, b), c in sorted(transition_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "cpes_with_channel_changes": cpes_with_channel_changes,
        "cpes_with_dfs_hint_events": cpes_with_dfs_hint,
        "cpes_wifi_crowded": cpes_wifi_crowded,
        "total_channel_events": total_channel_events,
        "transition_histogram": histogram,
    }


def _dominant_band_for_radio(cpe_results: List[Dict[str, Any]], radio: int) -> Optional[str]:
    votes: Counter = Counter()
    for cpe in cpe_results:
        wf = cpe.get("wifi_rf") or {}
        for row in wf.get("radios") or []:
            try:
                r = int(row["radio"])
            except (KeyError, TypeError, ValueError):
                continue
            if r != radio:
                continue
            b = row.get("band")
            if b is None:
                continue
            s = str(b).strip()
            if s:
                votes[s] += 1
    if not votes:
        return None
    return votes.most_common(1)[0][0]


def build_wifi_fleet_radio_tables(cpe_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Per-radio fleet rollups: channel occupancy + util aggregates, and top channel switches.

    Channel/util stats attribute each CPE radio row to ``channel_last`` (fallback ``channel_first``).
    Utilization is the reported time-series aggregate for that radio (not split per hop).
    """
    transition_by_radio: Dict[int, Counter] = defaultdict(Counter)
    util_by_radio_channel: Dict[int, Dict[int, Dict[str, List[float]]]] = defaultdict(
        lambda: defaultdict(lambda: {"avg": [], "max": []})
    )
    cpe_count_by_radio_channel: Dict[int, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for cpe in cpe_results:
        wf = cpe.get("wifi_rf") or {}
        for e in wf.get("channel_events") or []:
            try:
                radio = int(e["radio"])
            except (KeyError, TypeError, ValueError):
                continue
            if "from_channel" not in e or "to_channel" not in e:
                continue
            frm_t = float(e["from_channel"])
            to_t = float(e["to_channel"])
            transition_by_radio[radio][(frm_t, to_t)] += 1

        for row in wf.get("radios") or []:
            try:
                radio = int(row["radio"])
            except (KeyError, TypeError, ValueError):
                continue
            ch = row.get("channel_last")
            if ch is None:
                ch = row.get("channel_first")
            if ch is None:
                continue
            ch_i = int(round(float(ch)))
            cpe_count_by_radio_channel[radio][ch_i] += 1

            ua = row.get("util_avg")
            if ua is not None:
                try:
                    util_by_radio_channel[radio][ch_i]["avg"].append(float(ua))
                except (TypeError, ValueError):
                    pass
            um = row.get("util_max")
            if um is not None:
                try:
                    util_by_radio_channel[radio][ch_i]["max"].append(float(um))
                except (TypeError, ValueError):
                    pass

    all_radios = set(transition_by_radio.keys()) | set(cpe_count_by_radio_channel.keys())
    wifi_radio_fleet: List[Dict[str, Any]] = []

    for radio in sorted(all_radios):
        trans = transition_by_radio[radio]
        total_ev = sum(trans.values())
        top_trans: List[Dict[str, Any]] = []
        if total_ev > 0:
            for (frm, to), cnt in trans.most_common(10):
                top_trans.append({
                    "from": frm,
                    "to": to,
                    "count": cnt,
                    "share_pct": round(100.0 * cnt / total_ev, 1),
                })

        ch_rows: List[Dict[str, Any]] = []
        for ch in sorted(cpe_count_by_radio_channel[radio].keys()):
            n = cpe_count_by_radio_channel[radio][ch]
            avgs = util_by_radio_channel[radio][ch]["avg"]
            maxs = util_by_radio_channel[radio][ch]["max"]
            mean_u = round(sum(avgs) / len(avgs), 2) if avgs else None
            max_u = round(max(maxs), 2) if maxs else None
            ch_rows.append({
                "channel": ch,
                "cpe_count": n,
                "mean_util_pct": mean_u,
                "max_util_pct": max_u,
            })

        reporting = sum(cpe_count_by_radio_channel[radio].values())
        wifi_radio_fleet.append({
            "radio": radio,
            "band": _dominant_band_for_radio(cpe_results, radio),
            "cpes_reporting": reporting,
            "channels": ch_rows,
            "top_transitions": top_trans,
        })

    return {"wifi_radio_fleet": wifi_radio_fleet}

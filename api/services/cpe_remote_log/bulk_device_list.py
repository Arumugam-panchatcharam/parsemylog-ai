"""Parse admin bulk device-list JSON payloads (pure, no Flask)."""

from __future__ import annotations

import json
import re
from typing import Any, List, Tuple

from api.services.cpe_remote_log.range_datetime import (
    DEFAULT_END_TIME,
    DEFAULT_START_TIME,
    canonical_range_bound,
    split_range_bound,
)

EntryRow = Tuple[int, str, str]

_SERIAL_SPLIT_RE = re.compile(r"[,;\n\r\t]+")


def parse_serial_numbers_text(raw: str) -> Tuple[List[str] | None, str | None]:
    """Parse comma/newline/semicolon-separated serials; preserve order, dedupe."""
    text = str(raw or "").strip()
    if not text:
        return None, "At least one serial number is required"
    seen: set[str] = set()
    out: List[str] = []
    for part in _SERIAL_SPLIT_RE.split(text):
        serial = part.strip()
        if not serial:
            continue
        key = serial.lower()
        if key in seen:
            return None, f"Duplicate serial in list: {serial}"
        seen.add(key)
        out.append(serial)
    if not out:
        return None, "At least one serial number is required"
    return out, None


def build_device_list_from_serials(
    serials: List[str],
    range_start: str,
    range_end: str,
) -> List[dict[str, Any]]:
    """Build device-list JSON array for one shared datetime range."""
    start_canon = canonical_range_bound(range_start, DEFAULT_START_TIME)
    end_canon = canonical_range_bound(range_end, DEFAULT_END_TIME)
    return [
        {
            "serialnumber": serial,
            "ranges": [{"start": start_canon, "end": end_canon}],
        }
        for serial in serials
    ]


def iso_bounds_from_ranges_payload(ranges: Any) -> tuple[str | None, str | None]:
    """
    Earliest ``start`` and latest ``end`` across a list of range dicts (as stored in JSON).

    Values are typically ``YYYY-MM-DDTHH:MM:SS`` after normalization; date-only strings are supported.
    """
    if not isinstance(ranges, list):
        return None, None
    starts: list[str] = []
    ends: list[str] = []
    for r in ranges:
        if not isinstance(r, dict):
            continue
        s = str(r.get("start") or r.get("date_start") or "").strip()
        e = str(r.get("end") or r.get("date_end") or "").strip()
        if s:
            starts.append(s)
        if e:
            ends.append(e)
    if not starts or not ends:
        return None, None
    return min(starts), max(ends)


def _normalize_range_item(obj: dict) -> dict[str, str] | None:
    start_raw = str(obj.get("start") or obj.get("date_start") or "").strip()
    end_raw = str(obj.get("end") or obj.get("date_end") or "").strip()
    if not start_raw or not end_raw:
        return None
    try:
        start_canon = canonical_range_bound(start_raw, DEFAULT_START_TIME)
        end_canon = canonical_range_bound(end_raw, DEFAULT_END_TIME)
    except ValueError:
        return None
    return {"start": start_canon, "end": end_canon}


def _fallback_range(
    default_start: str | None,
    default_end: str | None,
    *,
    default_start_time: str | None = None,
    default_end_time: str | None = None,
) -> List[dict[str, str]]:
    ds = str(default_start or "").strip()
    de = str(default_end or "").strip()
    if len(ds) < 10 or len(de) < 10:
        return []
    start_val = ds[:10]
    end_val = de[:10]
    st = str(default_start_time or DEFAULT_START_TIME).strip() or DEFAULT_START_TIME
    et = str(default_end_time or DEFAULT_END_TIME).strip() or DEFAULT_END_TIME
    if len(st) == 5:
        st = f"{st}:00"
    if len(et) == 5:
        et = f"{et}:00"
    try:
        return [
            {
                "start": canonical_range_bound(f"{start_val}T{st}", DEFAULT_START_TIME),
                "end": canonical_range_bound(f"{end_val}T{et}", DEFAULT_END_TIME),
            }
        ]
    except ValueError:
        return []


def parse_bulk_device_list_json(
    blob: Any,
    default_start: str | None,
    default_end: str | None,
    *,
    default_start_time: str | None = None,
    default_end_time: str | None = None,
) -> Tuple[List[EntryRow] | None, str | None]:
    """
    Return (entries, None) where each entry is (ordinal, serial, ranges_json).

    ranges_json is a JSON array of {"start":"YYYY-MM-DDTHH:MM:SS","end":"..."}.
    """
    if not isinstance(blob, list):
        return None, "Device list JSON must be a non-empty array"
    if len(blob) == 0:
        return None, "Device list is empty"

    out: List[EntryRow] = []
    fallback_range = _fallback_range(
        default_start,
        default_end,
        default_start_time=default_start_time,
        default_end_time=default_end_time,
    )

    seen_serials: dict[str, int] = {}

    for idx, entry in enumerate(blob):
        if not isinstance(entry, dict):
            return None, f"Entry {idx} must be an object"
        serial_raw = (
            entry.get("serialnumber")
            or entry.get("serial")
            or entry.get("SerialNumber")
        )
        serial = str(serial_raw or "").strip()
        if not serial:
            return None, f"Entry {idx}: missing serial number"

        seen_serials[serial] = seen_serials.get(serial, 0) + 1
        if seen_serials[serial] > 1:
            return None, f"Duplicate serial in list: {serial}"

        rng = entry.get("ranges")
        normalized: List[dict[str, str]] = []
        if isinstance(rng, list) and rng:
            for r in rng:
                if isinstance(r, dict):
                    rr = _normalize_range_item(r)
                    if rr:
                        normalized.append(rr)
            if not normalized and fallback_range:
                normalized = list(fallback_range)
            elif not normalized:
                return None, (
                    f"Entry {idx}: ranges missing or invalid; provide default dates/times"
                )
        elif fallback_range:
            normalized = list(fallback_range)
        else:
            return None, f"Entry {idx}: ranges missing and no default range provided"

        out.append((idx, serial, json.dumps(normalized)))

    return out, None

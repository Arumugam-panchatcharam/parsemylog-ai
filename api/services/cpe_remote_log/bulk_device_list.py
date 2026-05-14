"""Parse admin bulk device-list JSON payloads (pure, no Flask)."""

from __future__ import annotations

import json
from typing import Any, List, Tuple

EntryRow = Tuple[int, str, str]


def iso_bounds_from_ranges_payload(ranges: Any) -> tuple[str | None, str | None]:
    """
    Min/max ISO date strings (YYYY-MM-DD) across a list of {start,end} dicts.

    Matches how ``ranges_json`` is stored after ``parse_bulk_device_list_json``.
    """
    if not isinstance(ranges, list):
        return None, None
    dates: list[str] = []
    for r in ranges:
        if not isinstance(r, dict):
            continue
        s = str(r.get("start") or "").strip()[:10]
        e = str(r.get("end") or "").strip()[:10]
        if len(s) == 10:
            dates.append(s)
        if len(e) == 10:
            dates.append(e)
    if not dates:
        return None, None
    return min(dates), max(dates)


def parse_bulk_device_list_json(
    blob: Any,
    default_start: str | None,
    default_end: str | None,
) -> Tuple[List[EntryRow] | None, str | None]:
    """
    Return (entries, None) where each entry is (ordinal, serial, ranges_json).

    ranges_json is a JSON array of {\"start\":\"YYYY-MM-DD\",\"end\":\"YYYY-MM-DD\"}.
    """
    if not isinstance(blob, list):
        return None, "Device list JSON must be a non-empty array"
    if len(blob) == 0:
        return None, "Device list is empty"

    def _normalize_range_item(obj: dict) -> dict[str, str] | None:
        s = str(obj.get("start") or obj.get("date_start") or "").strip()[:10]
        e = str(obj.get("end") or obj.get("date_end") or "").strip()[:10]
        if len(s) != 10 or len(e) != 10:
            return None
        return {"start": s, "end": e}

    out: List[EntryRow] = []

    ds = str(default_start or "").strip()[:10] if default_start else ""
    de = str(default_end or "").strip()[:10] if default_end else ""
    fallback_range: List[dict[str, str]] = []
    if len(ds) == 10 and len(de) == 10:
        fallback_range = [{"start": ds, "end": de}]

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
                return None, f"Entry {idx}: ranges missing or invalid; provide default dates"
        elif fallback_range:
            normalized = list(fallback_range)
        else:
            return None, f"Entry {idx}: ranges missing and no default range provided"

        out.append((idx, serial, json.dumps(normalized)))

    return out, None

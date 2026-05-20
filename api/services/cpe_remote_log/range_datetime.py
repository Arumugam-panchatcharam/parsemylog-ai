"""Parse range start/end with optional time (aligned with download_cpelogs_v1.sh)."""

from __future__ import annotations

import json
import re
from typing import Tuple

DEFAULT_START_TIME = "00:00:00"
DEFAULT_END_TIME = "23:59:00"

_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_TIME_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})")


def split_range_bound(value: str, default_time: str) -> Tuple[str, str]:
    """
    Split a range bound into (YYYY-MM-DD, HH:MM:SS).

    Accepts YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS, YYYY-MM-DD HH:MM:SS, YYYY-MM-DD:HH:MM:SS.
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("range bound is empty")
    date_m = _DATE_PREFIX_RE.match(raw)
    if not date_m:
        raise ValueError(f"expected YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS, got {raw!r}")
    date_part = date_m.group(1)
    rest = raw[len(date_part) :].lstrip()
    if not rest:
        return date_part, default_time
    if rest[0] in "T :":
        rest = rest[1:].lstrip()
    time_m = _TIME_RE.match(rest)
    if time_m:
        return date_part, time_m.group(1)
    return date_part, default_time


def canonical_range_bound(value: str, default_time: str) -> str:
    """Canonical stored form: YYYY-MM-DDTHH:MM:SS."""
    date_part, time_part = split_range_bound(value, default_time)
    return f"{date_part}T{time_part}"


def build_crash_date_filter_json(range_start: str, range_end: str) -> str:
    """
    Crash-portal / logInfo dateFilter payload (milliseconds suffix like the shell script).
    """
    start_d, start_t = split_range_bound(range_start, DEFAULT_START_TIME)
    end_d, end_t = split_range_bound(range_end, DEFAULT_END_TIME)
    return json.dumps(
        {"startDate": f"{start_d}T{start_t}.000", "endDate": f"{end_d}T{end_t}.000"}
    )


def date_only_from_bound(value: str) -> str:
    """First 10 chars when valid; used for batch telemetry fallbacks."""
    date_part, _ = split_range_bound(value, DEFAULT_START_TIME)
    return date_part

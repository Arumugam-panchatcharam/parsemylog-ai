"""
Generic Timestamp Parser
========================

Handles parsing of timestamps in various formats found across RDK logs.
Supports multiple formats including ISO, RFC, Unix timestamps, and device-specific formats.

Timestamp Patterns Supported:
1. Unix epoch: 1234567890.123 (milliseconds/microseconds)
2. ISO format: 2025-11-13T08:06:53, 2026-03-27T00:00 (minute precision), or with Z / offset
3. Dash-separated: 2025-11-13-08-06-53
4. Custom format 1: 200000-12:34:56.789 (device uptime)
5. RFC short: Mon 1 12:34:56 (weekday) or syslog-style Mar 19 22:31:31 (month + day)
6. RFC full: Mon Nov 01 12:34:56 UTC 2025
7. Space-separated: 2025-11-13 08:06:53 or 2025-11-13 08:06:53.041582
8. Compact date + time: 260325-02:58:46.700024 (YYMMDD-HH:MM:SS.microseconds), e.g. RDK/CPE logs
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Regex patterns for detecting timestamp formats
_TIMESTAMP_PATTERNS = {
    # Unix epoch timestamp: 1234567890.123 or 1234567890
    "unix_epoch": re.compile(r"^\d{10,}(?:\.\d+)?$"),
    
    # ISO-like: YYYY-MM-DDTHH:MM[:SS[.fraction]][offset|Z]; seconds optional (HTML datetime-local, APIs)
    "iso_format": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),
    
    # YYYY-MM-DD-HH-MM-SS: 2025-11-13-08-06-53
    "dash_separated": re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}"),
    
    # Device uptime format: 200000-12:34:56.789 or 123456.789
    "device_uptime": re.compile(r"^(?:\d{6}-)?\d{2}:\d{2}:\d{2}\.\d+"),
    
    # Space-separated: 2025-11-13 08:06:53[.fraction]
    "space_separated": re.compile(
        r"^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:\.\d+)?$"
    ),
    
    # Weekday or month + day + time (BSD/syslog): Mon 1 12:34:56 | Mar 19 22:31:31[.fraction]
    "rfc_short": re.compile(
        r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?$"
    ),
    
    # RFC full format: Mon Nov 01 12:34:56 UTC 2025
    "rfc_full": re.compile(r"^[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+UTC\s+\d{4}"),
    
    # YYMMDD-HH:MM:SS[.fraction]: 260325-02:58:46.700024 (must be valid calendar date)
    "compact_yy_mm_dd_time": re.compile(r"^\d{6}-\d{2}:\d{2}:\d{2}(?:\.\d+)?$"),
}


def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """
    Parse a timestamp string in various formats and return a datetime object.
    
    Tries multiple format parsers in order of likelihood. Returns None if parsing fails.
    
    Args:
        timestamp_str: The timestamp string to parse
    
    Returns:
        datetime object if parsing successful, None otherwise
    
    Examples:
        >>> parse_timestamp("2025-11-13 08:06:53")
        datetime.datetime(2025, 11, 13, 8, 6, 53)
        
        >>> parse_timestamp("2025-11-13T08:06:53Z")
        datetime.datetime(2025, 11, 13, 8, 6, 53)
        
        >>> parse_timestamp("1234567890.123")
        datetime.datetime(2009, 2, 13, 23, 31, 30, 123000)
        
        >>> parse_timestamp("invalid")
        None
    """
    if not timestamp_str or not isinstance(timestamp_str, str):
        return None
    
    timestamp_str = timestamp_str.strip().strip('"\'')
    
    # Try each format parser in priority order
    parsers = [
        _parse_iso_format,
        _parse_space_separated,
        _parse_dash_separated,
        _parse_rfc_full,
        _parse_rfc_short,
        _parse_unix_epoch,
        _parse_compact_yy_mm_dd_time,
        _parse_device_uptime,
    ]
    
    for parser in parsers:
        try:
            result = parser(timestamp_str)
            if result:
                logger.debug(f"[TimestampParser] Successfully parsed '{timestamp_str}' → {result}")
                return result
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"[TimestampParser] {parser.__name__} failed for '{timestamp_str}': {e}")
            continue
    
    logger.warning(f"[TimestampParser] Could not parse timestamp '{timestamp_str}' with any format")
    return None


def _parse_iso_format(ts: str) -> Optional[datetime]:
    """Parse ISO-like calendar datetimes (RFC 3339 subset via ``datetime.fromisoformat``).

    Supports optional seconds and sub-second fraction, optional ``Z``, and minute-only
    times such as ``2026-03-27T00:00``.
    """
    if not _TIMESTAMP_PATTERNS["iso_format"].match(ts):
        return None

    ts_clean = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_clean)
    except ValueError:
        return None


def _parse_space_separated(ts: str) -> Optional[datetime]:
    """Parse YYYY-MM-DD HH:MM:SS[.microseconds] format: 2025-11-13 08:06:53"""
    if not _TIMESTAMP_PATTERNS["space_separated"].match(ts):
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def _parse_dash_separated(ts: str) -> Optional[datetime]:
    """Parse YYYY-MM-DD-HH-MM-SS format: 2025-11-13-08-06-53"""
    if not _TIMESTAMP_PATTERNS["dash_separated"].match(ts):
        return None
    
    return datetime.strptime(ts, "%Y-%m-%d-%H-%M-%S")


def _parse_rfc_full(ts: str) -> Optional[datetime]:
    """Parse RFC full format: Mon Nov 01 12:34:56 UTC 2025"""
    if not _TIMESTAMP_PATTERNS["rfc_full"].match(ts):
        return None
    
    # Note: %Z (timezone) only works if the timezone is recognized
    # For UTC, this should work fine
    return datetime.strptime(ts, "%a %b %d %H:%M:%S %Z %Y")


_MONTH_ABBREV = frozenset(
    "jan feb mar apr may jun jul aug sep oct nov dec".split()
)
_WEEKDAY_ABBREV = frozenset(
    "mon tue wed thu fri sat sun".split()
)


def _parse_rfc_short(ts: str) -> Optional[datetime]:
    """Parse weekday+day+time (Mon 1 12:34:56) or syslog month+day+time (Mar 19 22:31:31).

    Year is inferred (current year, or previous if that makes the instant clearly in the future).
    """
    if not _TIMESTAMP_PATTERNS["rfc_short"].match(ts):
        return None
    
    parts = ts.split()
    if len(parts) < 3:
        return None
    
    first = parts[0].lower()
    now = datetime.now()
    
    if first in _MONTH_ABBREV:
        formats = ("%b %d %H:%M:%S.%f", "%b %d %H:%M:%S")
    elif first in _WEEKDAY_ABBREV:
        formats = ("%a %d %H:%M:%S.%f", "%a %d %H:%M:%S")
    else:
        return None
    
    try:
        parsed: Optional[datetime] = None
        for fmt in formats:
            try:
                parsed = datetime.strptime(ts, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
        
        result = parsed.replace(year=now.year)
        if result > now + timedelta(days=1):
            result = result.replace(year=now.year - 1)
        
        return result
    except ValueError:
        return None


def _parse_unix_epoch(ts: str) -> Optional[datetime]:
    """Parse Unix epoch format: 1234567890 or 1234567890.123"""
    if not _TIMESTAMP_PATTERNS["unix_epoch"].match(ts):
        return None
    
    try:
        epoch_float = float(ts)
        # Handle both seconds and milliseconds/microseconds
        # If the number is very large (> year 2100 in seconds), assume it's milliseconds
        if epoch_float > 4102444800:  # Year 2100
            epoch_float = epoch_float / 1000
        
        return datetime.fromtimestamp(epoch_float)
    except (ValueError, OSError):
        return None


def _parse_compact_yy_mm_dd_time(ts: str) -> Optional[datetime]:
    """Parse YYMMDD-HH:MM:SS[.microseconds], e.g. 260325-02:58:46.700024 → 2026-03-25.

    Tried before device-uptime patterns that look similar but are not absolute times.
    """
    if not _TIMESTAMP_PATTERNS["compact_yy_mm_dd_time"].match(ts):
        return None
    
    for fmt in ("%y%m%d-%H:%M:%S.%f", "%y%m%d-%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def _parse_device_uptime(ts: str) -> Optional[datetime]:
    """Parse device uptime format: 200000-12:34:56.789 or 123456.789
    
    This format typically represents device uptime in seconds.milliseconds.
    Since we don't have a reference point, we return None for this format
    as it's not an absolute timestamp.
    """
    if not _TIMESTAMP_PATTERNS["device_uptime"].match(ts):
        return None
    
    # Device uptime is not an absolute timestamp, so we can't convert it meaningfully
    logger.debug(f"[TimestampParser] Skipping device uptime format: {ts}")
    return None


def normalize_to_date_only(dt: datetime) -> datetime:
    """
    Normalize a datetime to date-only (year-month-date), setting time to 00:00:00.
    
    Args:
        dt: datetime object to normalize
    
    Returns:
        datetime with hours, minutes, seconds, and microseconds set to 0
    """
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


if __name__ == "__main__":
    # Test the parser with various timestamp formats
    test_timestamps = [
        "2025-11-13 08:06:53",           # Space-separated
        "2026-03-26 23:03:05.041582",    # Space-separated + microseconds
        "2025-11-13T08:06:53Z",          # ISO format
        "2025-11-13T08:06:53",           # ISO format (no Z)
        "2026-03-27T00:00",              # ISO minute precision (no seconds)
        "2025-11-13-08-06-53",           # Dash-separated
        "2024-11-07 05:37:07",           # Another space-separated
        "Wed Nov 13 08:06:53 UTC 2025",  # RFC full
        "Mon 13 08:06:53",               # RFC short (current year assumed)
        "1234567890.123",                # Unix epoch
        "1234567890",                    # Unix epoch (no decimals)
        "invalid timestamp",             # Invalid
    ]
    
    print("=" * 70)
    print("TIMESTAMP PARSER TEST")
    print("=" * 70)
    
    for ts in test_timestamps:
        result = parse_timestamp(ts)
        if result:
            print(f"✓ '{ts}' → {result}")
        else:
            print(f"✗ '{ts}' → FAILED")
    
    print("\n" + "=" * 70)
    print("DATE NORMALIZATION TEST")
    print("=" * 70)
    
    test_dt = datetime(2025, 11, 13, 8, 6, 53)
    normalized = normalize_to_date_only(test_dt)
    print(f"Original:   {test_dt}")
    print(f"Normalized: {normalized}")

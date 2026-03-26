"""
Log pattern extraction for automatic deduplication rule generation.

This module provides functions to:
1. Strip timestamps from log lines using patterns from drain3.ini
2. Replace variable patterns (numbers, hex values, IPs, etc.) with regex wildcards
3. Generate complete dedup patterns suitable for the log viewer dedup system
"""

import re
from typing import Optional


# Timestamp patterns from drain3.ini MASKING section
TIMESTAMP_PATTERNS = [
    # ISO-8601 with optional fractional seconds and timezone (e.g., 2026-02-27T00:03:21.000 or 2026-02-27T00:03:21+00:00)
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?",
    # Space-separated ISO with optional fractional seconds (e.g., 2026-02-27 00:03:21.000)
    r"\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}(?:\.\d+)?",
    # Dash-separated (e.g., 2026-02-27-00-03-21)
    r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}",
    # RDK-style (e.g., 260227-00:03:21.000000)
    r"\d{6}-\d{2}:\d{2}:\d{2}(?:\.\d+)?",
    # Syslog-style with optional date (e.g., Feb 27 00:03:21 UTC 2026 or Feb Wed 27 00:03:21 UTC 2026)
    r"[A-Z][a-z]{2}\s+(?:[A-Z][a-z]{2}\s+)?\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\s+UTC\s+\d{4})?",
    # Epoch with decimals (e.g., 1234567890.123456) - must be last to avoid false matches
    r"(?<![0-9.])\d{5,}\.\d+(?::)?",
]

# Compiled timestamp patterns for efficiency
_COMPILED_TIMESTAMP_PATTERNS = [re.compile(p) for p in TIMESTAMP_PATTERNS]


def strip_timestamp(line: str) -> str:
    """
    Remove timestamp from the beginning of a log line.

    Supports multiple timestamp formats from drain3.ini. Removes the first
    timestamp match found, plus any trailing whitespace that separates it
    from the actual log message.

    Args:
        line: Raw log line that may contain a timestamp prefix

    Returns:
        Log line with timestamp removed and leading/trailing whitespace trimmed
    """
    for pattern in _COMPILED_TIMESTAMP_PATTERNS:
        match = pattern.search(line)
        if match:
            # Remove the timestamp and any following whitespace
            start, end = match.span()
            # If timestamp is at the start, remove it and trailing whitespace
            if start == 0:
                remaining = line[end:].lstrip()
                if remaining:
                    return remaining
            # If there's content before the timestamp, check if it looks like
            # a prefix (unlikely for valid logs). If timestamp is in middle,
            # keep everything (might be part of the message)
            break

    # If no timestamp found, return original line
    return line


def replace_variables_with_regex(line: str) -> str:
    """
    Replace variable patterns in a log line with appropriate regex wildcards.

    Args:
        line: Log line with variable patterns

    Returns:
        Log line with variables replaced by regex patterns and special chars escaped for regex
    """
    result = line

    # Step 1: Replace variable patterns with temporary placeholders (before escaping)
    # This ensures regex patterns we're creating don't get escaped
    
    # Replace hex values (0x followed by hex digits)
    result = re.sub(r"0x[0-9A-Fa-f]+", "HEXREGEX", result)

    # Replace MAC addresses (xx:xx:xx:xx:xx:xx or xx-xx-xx-xx-xx-xx)
    mac_pattern = r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}"
    result = re.sub(mac_pattern, "MACREGEX", result)

    # Replace IPv4 addresses (XXX.XXX.XXX.XXX)
    ipv4_pattern = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"
    result = re.sub(ipv4_pattern, "IPREGEX", result)

    # Replace IPv6 addresses (multiple hex groups with colons)
    ipv6_pattern = r"\b(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}\b"
    result = re.sub(ipv6_pattern, "IPv6REGEX", result)

    # Replace plain decimal numbers (including thread IDs - use generic number regex)
    result = re.sub(r"\b\d+\b", "NUMREGEX", result)

    # Step 2: Escape special regex characters
    # Brackets MUST be escaped because in literal text like [poll], they need to match literally
    # In regex, [poll] would be a character class, but we want to match the literal "[poll]"
    escape_chars = {
        '\\': r'\\',  # Must be first
        '.': r'\.',
        '*': r'\*',
        '+': r'\+',
        '?': r'\?',
        '^': r'\^',
        '$': r'\$',
        '{': r'\{',
        '}': r'\}',
        '(': r'\(',
        ')': r'\)',
        '[': r'\[',
        ']': r'\]',
        '|': r'\|',
    }

    for char, escaped in escape_chars.items():
        result = result.replace(char, escaped)

    # Step 3: Replace placeholders with actual regex patterns (these won't get escaped)
    result = result.replace("NUMREGEX", r"\d+")
    result = result.replace("IPREGEX", r"\d+\.\d+\.\d+\.\d+")
    result = result.replace("IPv6REGEX", "[0-9A-Fa-f:]+")
    result = result.replace("MACREGEX", "[0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}")
    result = result.replace("HEXREGEX", "0x[0-9A-Fa-f]+")

    return result


def generate_dedup_pattern(line: str) -> str:
    """
    Generate a complete deduplication pattern from a raw log line.

    This function orchestrates:
    1. Timestamp removal
    2. Variable replacement with regex wildcards
    3. Final regex validation

    The resulting pattern is ready to be used as a regex in the dedup system.

    Args:
        line: Raw log line from the log viewer

    Returns:
        Regex pattern suitable for use in log_viewer_dedup_patterns.json

    Raises:
        ValueError: If the resulting pattern is invalid regex
    """
    # Step 1: Remove timestamp
    stripped = strip_timestamp(line)

    # Step 2: Replace variables with regex
    pattern = replace_variables_with_regex(stripped)

    # Step 3: Validate the result is valid regex
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Generated invalid regex pattern: {pattern}") from e

    return pattern


def validate_pattern(pattern: str) -> tuple[bool, Optional[str]]:
    """
    Validate that a regex pattern is valid and compilable.

    Args:
        pattern: Regex pattern string to validate

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    try:
        re.compile(pattern)
        return True, None
    except re.error as e:
        return False, str(e)

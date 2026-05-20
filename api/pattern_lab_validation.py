"""Pattern lab document validation (stdlib only; no PyYAML)."""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

MAX_PATTERN_LAB_BYTES = 512_000
ALLOWED_DETECT_TYPES = frozenset({"missing_followup", "burst_count", "ordered_sequence"})


def _serialized_byte_size(events: Dict[str, Any], issues: Dict[str, Any]) -> int:
    """Conservative size bound for API payloads (JSON UTF-8 length)."""
    return len(
        json.dumps({"events": events, "issues": issues}, default=str, ensure_ascii=False).encode("utf-8")
    )


def _validate_detect_block(issue_key: str, detect: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(detect, dict):
        return False, f"issue {issue_key}: detect must be an object"
    dtype = detect.get("type")
    if dtype not in ALLOWED_DETECT_TYPES:
        return (
            False,
            f"issue {issue_key}: detect.type must be one of {sorted(ALLOWED_DETECT_TYPES)}",
        )
    if dtype == "ordered_sequence":
        seq = detect.get("sequence") or []
        if not isinstance(seq, list) or len(seq) < 2:
            return False, f"issue {issue_key}: ordered_sequence requires sequence list with at least 2 items"
        for i, item in enumerate(seq):
            if not isinstance(item, str) or not item.strip():
                return False, f"issue {issue_key}: sequence[{i}] must be a non-empty string"
    elif dtype == "missing_followup":
        if not detect.get("trigger") or not isinstance(detect.get("trigger"), str):
            return False, f"issue {issue_key}: missing_followup requires string trigger"
        if not detect.get("expect") or not isinstance(detect.get("expect"), str):
            return False, f"issue {issue_key}: missing_followup requires string expect"
    elif dtype == "burst_count":
        if not detect.get("event") or not isinstance(detect.get("event"), str):
            return False, f"issue {issue_key}: burst_count requires string event"
    return True, ""


def _validate_event_codes_in_sequence(
    events: Dict[str, Any], issues: Dict[str, Any]
) -> Tuple[bool, str]:
    if not events:
        return True, ""
    codes = set(events.keys())
    for ik, meta in issues.items():
        if not isinstance(meta, dict):
            continue
        det = meta.get("detect") or {}
        if det.get("type") == "ordered_sequence":
            seq = det.get("sequence") or []
            if isinstance(seq, list):
                for ev in seq:
                    if isinstance(ev, str) and ev and ev not in codes:
                        return (
                            False,
                            f"issue {ik}: sequence references unknown event code {ev!r}",
                        )
        if det.get("type") == "missing_followup":
            for fld in ("trigger", "expect"):
                v = det.get(fld)
                if isinstance(v, str) and v and v not in codes:
                    return (
                        False,
                        f"issue {ik}: {fld} references unknown event code {v!r}",
                    )
        if det.get("type") == "burst_count":
            v = det.get("event")
            if isinstance(v, str) and v and v not in codes:
                return False, f"issue {ik}: event references unknown event code {v!r}"
    return True, ""


def validate_pattern_lab(doc: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(doc, dict):
        return False, "body must be a JSON object"
    extra = set(doc.keys()) - {"events", "issues"}
    if extra:
        return False, f"unsupported keys: {sorted(extra)}"

    events = doc.get("events", {})
    issues = doc.get("issues", {})
    if events is None:
        events = {}
    if issues is None:
        issues = {}
    if not isinstance(events, dict):
        return False, "events must be an object"
    if not isinstance(issues, dict):
        return False, "issues must be an object"

    for code, ev in events.items():
        if not isinstance(code, str) or not code.strip():
            return False, "event keys must be non-empty strings"
        if not isinstance(ev, dict):
            return False, f"event {code} must be an object"

    for issue_key, meta in issues.items():
        if not isinstance(issue_key, str) or not issue_key.strip():
            return False, "issue keys must be non-empty strings"
        if not isinstance(meta, dict):
            return False, f"issue {issue_key} must be an object"
        det = meta.get("detect")
        if det is not None:
            ok, err = _validate_detect_block(issue_key, det)
            if not ok:
                return False, err

    ok, err = _validate_event_codes_in_sequence(events, issues)
    if not ok:
        return False, err

    size = _serialized_byte_size(events, issues)
    if size > MAX_PATTERN_LAB_BYTES:
        return False, f"document exceeds maximum size ({MAX_PATTERN_LAB_BYTES} bytes)"

    return True, ""

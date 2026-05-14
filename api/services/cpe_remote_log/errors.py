"""Exceptions for remote CPE log bundle fetching (avoid circular imports)."""

from __future__ import annotations

import json
from typing import Any


class RemoteLogFetchError(Exception):
    """Raised when the remote bundle pipeline fails in a user-actionable way."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        remediation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.remediation = remediation


def remote_log_failure_to_stored_text(exc: BaseException) -> str:
    """
    Format for persistence (remote_log_fetch_units.last_error).

    Structured JSON when we have an error_code or remediation so the UI can highlight actions
    (e.g. refresh crash_portal_bearer). Plain str for legacy/generic exceptions.
    """
    if isinstance(exc, RemoteLogFetchError) and (exc.error_code or exc.remediation):
        payload: dict[str, Any] = {
            "error_code": exc.error_code or "remote_log_error",
            "message": str(exc),
        }
        if exc.remediation:
            payload["remediation"] = exc.remediation
        return json.dumps(payload, ensure_ascii=False)
    return str(exc)

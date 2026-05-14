"""Thin HTTP facade (no bearer logging)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    content: bytes


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None = None,
    timeout_sec: float,
    label: str = "",
) -> HttpResult:
    try:
        r = requests.request(
            method=method.upper(),
            url=url,
            headers=dict(headers),
            data=body,
            timeout=timeout_sec,
        )
        return HttpResult(status_code=r.status_code, content=r.content or b"")
    except requests.RequestException as exc:
        logger.warning("[RemoteLog%s] HTTP error %s %s", f" {label}" if label else "", url, exc)
        raise

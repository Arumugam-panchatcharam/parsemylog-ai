"""Environment-driven configuration for remote CPE bundle HTTP calls."""

from __future__ import annotations

import dataclasses
import os
from typing import Optional


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _normalize_subpath(raw: str | None, default: str) -> str:
    s = (raw or "").strip().strip("/")
    return s if s else default


def device_registry_api_url(*, cdn_base: str, device_registry_path: str, route: str) -> str:
    """
    Build an absolute device-registry HTTP path under ``cdn_base``.

    ``device_registry_path`` comes from ``CPE_REMOTE_LOG_DEVICE_REGISTRY_PATH``
    ``route`` is the remainder (e.g. ``v1/cpe/deep-link?...``), without a leading slash.
    """
    root = (cdn_base or "").strip().rstrip("/")
    prefix = device_registry_path.strip().strip("/")
    suffix = route.strip().lstrip("/")
    return f"{root}/{prefix}/{suffix}"


@dataclasses.dataclass(frozen=True)
class RemoteLogHttpConfig:
    cdn_base: str
    portal_origin: str
    http_timeout_sec: float

    cms_cookie: Optional[str]
    cms_x_dtpc: Optional[str]
    cms_x_dtreferer: Optional[str]

    #: Path segment(s) between CDN origin and device-registry API routes (env override).
    device_registry_path: str


def load_remote_log_http_config() -> RemoteLogHttpConfig:
    base = (
        os.environ.get("CPE_REMOTE_LOG_CDN_BASE", "").strip()
        or os.environ.get("CPE_REMOTE_LOG_CDN_HOST", "").strip()
    ).rstrip("/")
    portal = os.environ.get("CPE_REMOTE_LOG_PORTAL_ORIGIN", "").strip().rstrip("/")
    dr_raw = (
        os.environ.get("CPE_REMOTE_LOG_DEVICE_REGISTRY_PATH")
    )
    device_registry_path = _normalize_subpath(dr_raw, "")
    return RemoteLogHttpConfig(
        cdn_base=base,
        portal_origin=portal,
        http_timeout_sec=_env_float("CPE_REMOTE_LOG_HTTP_TIMEOUT_SEC", 120.0),
        cms_cookie=(os.environ.get("CPE_REMOTE_LOG_CMS_COOKIE") or "").strip() or None,
        cms_x_dtpc=(os.environ.get("CPE_REMOTE_LOG_CMS_X_DTPC") or "").strip() or None,
        cms_x_dtreferer=(os.environ.get("CPE_REMOTE_LOG_CMS_X_DTREFERER") or "").strip() or None,
        device_registry_path=device_registry_path,
    )


def resolve_crash_natco_key_for_code(natco_code: str) -> str:
    """
    Prefer global key, then per-code suffix: CPE_REMOTE_LOG_CRASH_NATCO_KEY__CZ.
    """
    generic = os.environ.get("CPE_REMOTE_LOG_CRASH_NATCO_KEY", "").strip()
    if generic:
        return generic
    code = (natco_code or "").strip().upper()
    if code:
        per = os.environ.get(f"CPE_REMOTE_LOG_CRASH_NATCO_KEY__{code}", "").strip()
        if per:
            return per
    return ""

"""Resolve CPE identity from device serial via registry HTTP API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.parse import quote

from api.services.cpe_remote_log import error_codes as remote_err_codes
from api.services.cpe_remote_log.config import device_registry_api_url
from api.services.cpe_remote_log.errors import RemoteLogFetchError
from api.services.cpe_remote_log.http_client import http_request
from api.services.cpe_remote_log.http_hints import registry_step_hint

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CpeResolvedIdentity:
    uuid: str
    cpe_numeric_id: str
    mac_lower: str


class DeviceRegistryClient:
    """HTTP client for CDN registry deep-link lookups (generic naming)."""

    def __init__(
        self,
        *,
        cdn_base: str,
        device_registry_path: str,
        tenant_id: str,
        bearer: str,
        portal_origin: str,
        timeout_sec: float,
    ) -> None:
        self._cdn_base = cdn_base.rstrip("/")
        self._device_registry_path = device_registry_path
        self._tenant = tenant_id.strip().lower()
        self._bearer = bearer
        self._portal_origin = (portal_origin or "").rstrip("/")
        self._timeout = timeout_sec

    def _browser_headers(self) -> dict[str, str]:
        origin = self._portal_origin or self._cdn_base
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "authorization": f"Bearer {self._bearer}",
            "origin": origin,
            "referer": f"{origin}/",
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
            ),
            "x-tenant-id": self._tenant,
        }

    def resolve_cpe(self, serial: str) -> CpeResolvedIdentity | None:
        filt = json.dumps({"filter": serial.strip()})
        url = device_registry_api_url(
            cdn_base=self._cdn_base,
            device_registry_path=self._device_registry_path,
            route=f"v1/cpe/deep-link?cpeGenericFilter={quote(filt)}",
        )
        r = http_request(
            "GET",
            url,
            headers=self._browser_headers(),
            timeout_sec=self._timeout,
            label="registry-deep-link",
        )
        if r.status_code != 200:
            msg = registry_step_hint(r.status_code, step="deep_link") or f"Device registry deep-link HTTP {r.status_code}."
            ec: str | None = None
            rem: str | None = None
            if r.status_code == 401:
                ec = remote_err_codes.DEVICE_REGISTRY_UNAUTHORIZED
                rem = remote_err_codes.REMEDIATION_REGISTRY_BEARER
            raise RemoteLogFetchError(msg, error_code=ec, remediation=rem)
        try:
            data = json.loads(r.content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        uid = (data.get("info") or {}).get("uuid") or ""
        if not uid:
            return None

        filt2 = json.dumps({"filter": uid})
        url2 = device_registry_api_url(
            cdn_base=self._cdn_base,
            device_registry_path=self._device_registry_path,
            route=f"v1/cpe?cpeGenericFilter={quote(filt2)}",
        )
        r2 = http_request(
            "GET",
            url2,
            headers=self._browser_headers(),
            timeout_sec=self._timeout,
            label="registry-cpe",
        )
        if r2.status_code != 200:
            msg = registry_step_hint(r2.status_code, step="cpe_detail") or f"Device registry cpe detail HTTP {r2.status_code}."
            ec2: str | None = None
            rem2: str | None = None
            if r2.status_code == 401:
                ec2 = remote_err_codes.DEVICE_REGISTRY_UNAUTHORIZED
                rem2 = remote_err_codes.REMEDIATION_REGISTRY_BEARER
            raise RemoteLogFetchError(msg, error_code=ec2, remediation=rem2)
        try:
            info2 = json.loads(r2.content.decode("utf-8")).get("info") or {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        cpe_id = str(info2.get("cpeId") or "")
        mac = info2.get("macAddress") or (info2.get("deviceInfo") or {}).get("macAddress") or ""
        mac = str(mac).lower()
        if not cpe_id or not mac:
            return None
        return CpeResolvedIdentity(uuid=str(uid), cpe_numeric_id=str(cpe_id), mac_lower=mac)

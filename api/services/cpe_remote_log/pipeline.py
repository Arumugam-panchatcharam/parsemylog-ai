"""High-level orchestration: download all ranges for serial → single `{serial}.zip`."""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from urllib.parse import quote

from api.services.cpe_remote_log import error_codes as remote_err_codes
from api.services.cpe_remote_log.config import (
    RemoteLogHttpConfig,
    device_registry_api_url,
    load_remote_log_http_config,
    resolve_crash_natco_key_for_code,
)
from api.services.cpe_remote_log.crash_logs import clamp_page_size, extract_log_ids_from_json
from api.services.cpe_remote_log.device_registry import DeviceRegistryClient
from api.services.cpe_remote_log.errors import RemoteLogFetchError
from api.services.cpe_remote_log.http_client import http_request
from api.services.cpe_remote_log.http_hints import bundle_post_hint, crash_log_list_hint

logger = logging.getLogger(__name__)


def _raise_crash_listing_http(*, http_code: int, date_span: str, page: int) -> None:
    hint = crash_log_list_hint(http_code, date_span=date_span, page=page)
    msg = hint or f"crash log listing {date_span} page={page}: HTTP {http_code}"
    code: str | None = None
    remediation: str | None = None
    if http_code == 401:
        code = remote_err_codes.CRASH_PORTAL_UNAUTHORIZED
        remediation = remote_err_codes.REMEDIATION_UPDATE_CRASH_BEARER
    elif http_code == 403:
        code = remote_err_codes.CRASH_PORTAL_FORBIDDEN
        remediation = (
            f"{remote_err_codes.REMEDIATION_UPDATE_CRASH_BEARER} "
            f"{remote_err_codes.REMEDIATION_CMS_ENV_WORKER}"
        )
    raise RemoteLogFetchError(msg, error_code=code, remediation=remediation)


def _crash_debug_body_enabled() -> bool:
    v = os.environ.get("CPE_REMOTE_LOG_DEBUG_BODY", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _crash_portal_mac_id_variants(mac_lower: str) -> list[str]:
    """CDN may expect aa:bb:cc:dd:ee:ff or compact aabbccddeeff."""
    raw = (mac_lower or "").strip().lower()
    uniq: list[str] = []
    seen: set[str] = set()
    for cand in (raw, "".join(raw.split(":"))):
        if not cand or cand in seen:
            continue
        seen.add(cand)
        uniq.append(cand)
    return uniq


def _list_log_ids_page(
    *,
    cfg: RemoteLogHttpConfig,
    _tenant_id: str,
    crash_bearer: str,
    natco_key: str,
    mac_lower: str,
    date_start: str,
    date_end: str,
    page: int,
) -> tuple[int, list[str]]:
    payload = json.dumps({"startDate": date_start[:10], "endDate": date_end[:10]})
    enc = quote(payload, safe="")
    page_size = clamp_page_size()
    qs = (
        f"page={page}&size={page_size}&macId={mac_lower}"
        f"&dateFilter={enc}&natcoKey={natco_key}"
    )
    url = f"{cfg.cdn_base}/hgw/crash-portal/api/v2/crash/logs?{qs}"
    referer = f"{cfg.cdn_base}/crash/?{qs}"
    headers = {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {crash_bearer}",
        "content-type": "application/json",
        "referer": referer,
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
        ),
        "x-app-name": "cms",
        "x-natco-key": natco_key,
    }
    if cfg.cms_cookie:
        headers["Cookie"] = cfg.cms_cookie
    if cfg.cms_x_dtpc:
        headers["x-dtpc"] = cfg.cms_x_dtpc
    if cfg.cms_x_dtreferer:
        headers["x-dtreferer"] = cfg.cms_x_dtreferer

    r = http_request(
        "GET",
        url,
        headers={k: str(v) for k, v in headers.items()},
        timeout_sec=cfg.http_timeout_sec,
        label=f"crash-logs-{page}",
    )
    if r.status_code == 204:
        return 204, []
    if r.status_code != 200:
        return r.status_code, []
    if not r.content:
        return 200, []
    try:
        tree = json.loads(r.content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        if _crash_debug_body_enabled():
            snippet = r.content[:1200].decode("utf-8", errors="replace")
            logger.warning("[RemoteFetch] Crash list JSON decode failed page=%s: %s", page, snippet)
        return 200, []
    page_ids = extract_log_ids_from_json(tree)
    if not page_ids and _crash_debug_body_enabled():
        snippet = r.content[:1200].decode("utf-8", errors="replace")
        logger.warning(
            "[RemoteFetch] Crash list parsed 0 file IDs — page=%s len=%s head=%s",
            page,
            len(r.content),
            snippet,
        )
    return 200, page_ids


def _peek_crash_list_mac_variant(
    *,
    cfg: RemoteLogHttpConfig,
    tenant_id: str,
    crash_bearer: str,
    natco_key: str,
    mac_lower: str,
    probe_start: str,
    probe_end: str,
) -> str:
    """Prefer a macId query string that returns IDs on probe page 0."""
    variants = _crash_portal_mac_id_variants(mac_lower)
    fallback = variants[0] if variants else mac_lower

    ps, pe = probe_start[:10], probe_end[:10]
    if len(ps) != 10 or len(pe) != 10:
        return fallback

    for cand in variants:
        code0, probe_ids = _list_log_ids_page(
            cfg=cfg,
            _tenant_id=tenant_id,
            crash_bearer=crash_bearer,
            natco_key=natco_key,
            mac_lower=cand,
            date_start=ps,
            date_end=pe,
            page=0,
        )
        if probe_ids:
            if cand.strip().lower() != (mac_lower or "").strip().lower():
                logger.info("[RemoteFetch] Crash portal prefers alternate macId form for listings.")
            return cand

        if code0 not in (200, 204):
            span = f"{ps}–{pe}"
            _raise_crash_listing_http(http_code=code0, date_span=span, page=0)

    return fallback


def _post_bundle_zip_bytes(
    *,
    cfg: RemoteLogHttpConfig,
    tenant_id: str,
    registry_bearer: str,
    cpe_numeric_id: str,
    log_ids: list[str],
) -> bytes:
    portal = cfg.portal_origin or cfg.cdn_base
    url = device_registry_api_url(
        cdn_base=cfg.cdn_base,
        device_registry_path=cfg.device_registry_path,
        route=f"v2/cpe/{cpe_numeric_id}/logFile",
    )
    body = json.dumps({"cpeLogFileIds": log_ids}).encode("utf-8")
    headers = {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {registry_bearer}",
        "content-type": "application/json",
        "origin": portal,
        "referer": f"{portal}/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
        ),
        "x-tenant-id": tenant_id.strip().lower(),
    }
    r = http_request(
        "POST",
        url,
        headers=headers,
        body=body,
        timeout_sec=cfg.http_timeout_sec,
        label="bundle-post",
    )
    if r.status_code != 200:
        msg = bundle_post_hint(r.status_code)
        base = msg if msg else f"log bundle POST HTTP {r.status_code}"
        reg_code: str | None = None
        reg_fix: str | None = None
        if r.status_code == 401:
            reg_code = remote_err_codes.DEVICE_REGISTRY_UNAUTHORIZED
            reg_fix = remote_err_codes.REMEDIATION_REGISTRY_BEARER
        raise RemoteLogFetchError(base, error_code=reg_code, remediation=reg_fix)
    return r.content


def _extract_bytes_to_dir(data: bytes, dest_dir: Path) -> None:
    bio = io.BytesIO(data)
    try:
        with zipfile.ZipFile(bio, "r") as zf:
            zf.extractall(dest_dir)
        return
    except zipfile.BadZipFile:
        pass
    bio.seek(0)
    with tarfile.open(fileobj=bio, mode="r:*") as tf:
        tf.extractall(dest_dir)


def _zip_tree(src_dir: Path, dest_zip: Path) -> None:
    """Write extracted tree into zip preserving relative paths."""
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    part = dest_zip.with_suffix(dest_zip.suffix + ".part")
    if part.exists():
        part.unlink()
    with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_dir():
                continue
            arc = path.relative_to(src_dir).as_posix()
            zf.write(path, arcname=arc)
    os.replace(part, dest_zip)


def download_serial_bundle_to_zip(
    *,
    serial: str,
    ranges: list[dict[str, str]],
    tenant_id: str,
    natco_code: str,
    device_registry_bearer: str,
    crash_portal_bearer: str,
    staging_dir: Path,
    bundle_filename: str | None = None,
) -> Path:
    """
    Fetch remote bundles for serial across ranges, merge extracted files into a single `{serial}.zip`.

    Raises RemoteLogFetchError on missing config / download failure.
    """
    cfg = load_remote_log_http_config()
    if not cfg.cdn_base:
        raise RemoteLogFetchError("CPE_REMOTE_LOG_CDN_BASE is not configured.")
    natco_key = resolve_crash_natco_key_for_code(natco_code)
    if not natco_key:
        raise RemoteLogFetchError(
            "CPE_REMOTE_LOG_CRASH_NATCO_KEY (or CPE_REMOTE_LOG_CRASH_NATCO_KEY__NATCO) missing."
        )
    """
    if not (cfg.cms_cookie and cfg.cms_x_dtpc and cfg.cms_x_dtreferer):
        logger.warning(
            "[RemoteFetch] Crash-portal CMS headers are incomplete "
            "(set CPE_REMOTE_LOG_CMS_COOKIE, CPE_REMOTE_LOG_CMS_X_DTPC, "
            "CPE_REMOTE_LOG_CMS_X_DTREFERER). Without them the crash log list endpoint often responds "
            "with HTTP 204 or empty payloads even when logs exist."
        )
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    safe_serial_tag = "".join(ch if ch.isalnum() else "_" for ch in serial.strip())[:240] or "device"
    work_root = staging_dir / f"_work_{safe_serial_tag}"
    if work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)
    merge_dir = work_root / "merge"
    merge_dir.mkdir(parents=True, exist_ok=True)

    reg = DeviceRegistryClient(
        cdn_base=cfg.cdn_base,
        device_registry_path=cfg.device_registry_path,
        tenant_id=tenant_id,
        bearer=device_registry_bearer,
        portal_origin=cfg.portal_origin,
        timeout_sec=cfg.http_timeout_sec,
    )

    def _resolve_with_cp_fallback(sel_serial: str) -> object:
        return reg.resolve_cpe(sel_serial)

    resolved = _resolve_with_cp_fallback(serial.strip())
    if resolved is None and serial.strip().upper().startswith("CP"):
        alt = serial.strip()[2:]
        logger.info("[RemoteLog] Retrying registry without CP prefix: %s", alt)
        resolved = reg.resolve_cpe(alt)
    if resolved is None:
        raise RemoteLogFetchError(f"Could not resolve device serial '{serial}'.")

    # Final zip must match batch CPE record serial (original JSON line).
    zip_stem = (bundle_filename or serial.strip()).removesuffix(".zip")
    safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in zip_stem)[:200]
    final_zip = staging_dir / f"{safe_stem}.zip"

    downloaded_chunks = 0
    page_size = clamp_page_size()
    # First GET /crash/logs result per date range (page=0 only); used if nothing downloads.
    listing_first_page: list[tuple[str, str, int, int]] = []

    if not ranges:
        raise RemoteLogFetchError("No date ranges for device.")

    rng0 = ranges[0]
    probe_s = str(rng0.get("start") or "").strip()[:10]
    probe_e = str(rng0.get("end") or "").strip()[:10]
    crash_mac_id = resolved.mac_lower
    if len(probe_s) == 10 and len(probe_e) == 10:
        crash_mac_id = _peek_crash_list_mac_variant(
            cfg=cfg,
            tenant_id=tenant_id,
            crash_bearer=crash_portal_bearer,
            natco_key=natco_key,
            mac_lower=resolved.mac_lower,
            probe_start=probe_s,
            probe_end=probe_e,
        )

    for rng in ranges:
        start_d = str(rng.get("start") or "").strip()[:10]
        end_d = str(rng.get("end") or "").strip()[:10]
        if len(start_d) != 10 or len(end_d) != 10:
            raise RemoteLogFetchError(f"Invalid range {rng!r} — use YYYY-MM-DD.")
        page = 0
        while True:
            code, page_ids = _list_log_ids_page(
                cfg=cfg,
                _tenant_id=tenant_id,
                crash_bearer=crash_portal_bearer,
                natco_key=natco_key,
                mac_lower=crash_mac_id,
                date_start=start_d,
                date_end=end_d,
                page=page,
            )
            if page == 0:
                listing_first_page.append(
                    (start_d, end_d, code, len(page_ids)),
                )
            # 204 No Content: reference script treats page 0 as "no listings for this MAC+range",
            # page > 0 as normal end-of-pagination.
            if code == 204:
                break
            if code != 200:
                span = f"{start_d}…{end_d}"
                _raise_crash_listing_http(http_code=code, date_span=span, page=page)
            if not page_ids:
                break

            bucket = 0
            while bucket < len(page_ids):
                chunk_ids = page_ids[bucket : bucket + page_size]
                bucket += len(chunk_ids)

                raw_z = _post_bundle_zip_bytes(
                    cfg=cfg,
                    tenant_id=tenant_id,
                    registry_bearer=device_registry_bearer,
                    cpe_numeric_id=resolved.cpe_numeric_id,
                    log_ids=list(chunk_ids),
                )
                _extract_bytes_to_dir(raw_z, merge_dir)
                downloaded_chunks += 1

            if len(page_ids) < page_size:
                break
            page += 1

    if downloaded_chunks == 0:
        shutil.rmtree(work_root, ignore_errors=True)
        range_summary = "; ".join(
            f'{str(rng.get("start") or "")[:10]}→{str(rng.get("end") or "")[:10]}' for rng in ranges
        )
        probe_detail = "; ".join(
            f"{a}→{b}: HTTP {c}, ids_on_first_page={n}"
            for a, b, c, n in listing_first_page
        )
        cms_incomplete = not (cfg.cms_cookie and cfg.cms_x_dtpc and cfg.cms_x_dtreferer)
        only_204 = bool(listing_first_page) and all(x[2] == 204 for x in listing_first_page)
        empty_200 = any(x[2] == 200 and x[3] == 0 for x in listing_first_page)

        reasons: list[str] = []
        if only_204:
            reasons.append(
                "The crash log list returned HTTP 204 (no content) on the first page for every range. "
                "The CDN does this when the crash-portal session is not accepted — paste a fresh "
                "crash_portal_bearer (CMS crash UI session token) and copy "
                "CPE_REMOTE_LOG_CMS_COOKIE, CPE_REMOTE_LOG_CMS_X_DTPC, and CPE_REMOTE_LOG_CMS_X_DTREFERER "
                "from DevTools → Network on a request that lists crashes successfully in the browser."
            )
        elif empty_200:
            reasons.append(
                "Listing returned HTTP 200 but 0 file IDs were extracted — upstream JSON may differ, "
                "or filters exclude all files. Set CPE_REMOTE_LOG_DEBUG_BODY=1 on the worker to log "
                "truncated crash listing responses."
            )
        if cms_incomplete:
            reasons.append(
                "All three CMS header env vars are not set; without them the list endpoint often "
                "returns HTTP 204 or empty payload even when logs exist in the UI."
            )

        extra = (" " + " ".join(reasons)) if reasons else ""
        detail_msg = (
            "No crash log file IDs matched for this device/listing filters for "
            f"date window(s): {range_summary}. "
            f"(macId={crash_mac_id}; first-page listing: {probe_detail or 'none'}.)"
            f"{extra} "
            "Also verify: CPE_REMOTE_LOG_CRASH_NATCO_KEY (or per-NATCO suffix), NATCO remote_log_tenant_id, "
            "and UTC date bounds. See worker logs for [RemoteFetch] CMS / crash-portal warnings."
        )
        session_fix = (
            f"{remote_err_codes.REMEDIATION_UPDATE_CRASH_BEARER} "
            f"{remote_err_codes.REMEDIATION_CMS_ENV_WORKER}"
        )
        if cms_incomplete:
            no_match_remediation = (
                f"{session_fix} (CMS env vars are unset; the worker log should show [RemoteFetch] "
                "Crash-portal CMS headers are incomplete.)"
            )
        else:
            no_match_remediation = session_fix
        raise RemoteLogFetchError(
            detail_msg,
            error_code=remote_err_codes.CRASH_LISTING_NO_MATCH,
            remediation=no_match_remediation,
        )

    _zip_tree(merge_dir, final_zip)
    shutil.rmtree(work_root, ignore_errors=True)

    try:
        with zipfile.ZipFile(final_zip, "r") as zf:
            zf.testzip()
    except zipfile.BadZipFile as exc:
        final_zip.unlink(missing_ok=True)
        raise RemoteLogFetchError(f"Corrupt archive after assemble: {exc}") from exc

    return final_zip

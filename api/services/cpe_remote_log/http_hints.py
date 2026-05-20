"""Map CDN HTTP statuses to concise operator hints for remote CPE bundle fetch."""

from __future__ import annotations

# -----------------------------------------------------------------------------
# Device registry (deep-link + cpe by UUID), GET
# -----------------------------------------------------------------------------
def registry_step_hint(status_code: int, *, step: str) -> str | None:
    """
    Return a user-facing suffix for RemoteLogFetchError, or None to use generic.

    ``step``: deep_link | cpe_detail
    """
    if status_code == 200:
        return None
    if status_code == 401:
        return (
            "HTTP 401 — device registry Bearer token rejected. "
            "Use the Device registry token aligned with NATCO tenant (x-tenant-id / project NATCO)."
        )
    if status_code == 403:
        return (
            f"HTTP 403 — device registry {step} forbidden. "
            "x-tenant-id does not match the device registry bearer (set NATCO remote_log_tenant_id in Admin, "
            "not CPE_REMOTE_LOG_CRASH_NATCO_KEY). Wrong project NATCO or expired token also cause this."
        )
    if status_code == 404:
        if step == "deep_link":
            return "HTTP 404 — serial not found in registry deep-link lookup."
        return "HTTP 404 — device UUID lookup returned nothing (registry inconsistency)."
    if status_code == 429:
        return "HTTP 429 — rate limited on registry API; retry later."
    if status_code in (408, 502, 503, 504):
        return f"HTTP {status_code} — registry temporarily unavailable or timeout; retry later."
    if 500 <= status_code < 600:
        return f"HTTP {status_code} — upstream registry failure."
    if 400 <= status_code < 500:
        return f"HTTP {status_code} — registry client error ({step}); check CDN base URL and tenant."
    return f"HTTP {status_code} — unexpected registry response ({step})."


# -----------------------------------------------------------------------------
# Crash portal log id listing, GET /hgw/crash-portal/api/v2/crash/logs
# -----------------------------------------------------------------------------
def crash_log_list_hint(status_code: int, *, date_span: str, page: int) -> str | None:
    if status_code in (200, 204):
        return None
    ctx = f"crash log listing {date_span}, page={page}"
    if status_code == 401:
        return (
            f"{ctx}: HTTP 401 — CMS crash-portal Bearer invalid or expired "
            "(use the same CDN crash UI session token, not only the Device registry token)."
        )
    if status_code == 403:
        return (
            f"{ctx}: HTTP 403 — crash portal forbids listing; wrong NATCO / natcoKey / tenant "
            "or missing CMS Cookie / x-dtpc / x-dtreferer."
        )
    if status_code == 404:
        return (
            f"{ctx}: HTTP 404 — crash listing endpoint or query not found; "
            "check CPE_REMOTE_LOG_CDN_BASE."
        )
    if status_code == 429:
        return f"{ctx}: HTTP 429 — rate limited; retry later."
    if status_code in (408, 502, 503, 504):
        return f"{ctx}: HTTP {status_code} — CDN/crash-portal unreachable; retry later."
    if 500 <= status_code < 600:
        return f"{ctx}: HTTP {status_code} — upstream crash-portal failure."
    if 400 <= status_code < 500:
        return f"{ctx}: HTTP {status_code} — request rejected by crash portal."
    return f"{ctx}: unexpected HTTP {status_code}"


# -----------------------------------------------------------------------------
# Bundle bytes POST /hgw/<device-registry>/v2/cpe/{{id}}/logFile
# -----------------------------------------------------------------------------
def bundle_post_hint(status_code: int) -> str | None:
    if status_code == 200:
        return None
    if status_code == 401:
        return (
            "HTTP 401 — device registry Bearer rejected on log bundle POST "
            "(Device registry token; must match x-tenant-id / NATCO)."
        )
    if status_code == 403:
        return "HTTP 403 — forbidden to download bundles for this CPE or log IDs."
    if status_code == 404:
        return (
            "HTTP 404 — CPE or log IDs not known to bundle endpoint (wrong cpeId vs listing IDs?)."
        )
    if status_code == 413:
        return "HTTP 413 — bundle request too large; reduce page size batching."
    if status_code == 429:
        return "HTTP 429 — rate limited on bundle download."
    if status_code in (408, 502, 503, 504):
        return f"HTTP {status_code} — CDN bundle endpoint unavailable; retry later."
    if 500 <= status_code < 600:
        return f"HTTP {status_code} — upstream failure building log bundle."
    if 400 <= status_code < 500:
        return f"HTTP {status_code} — bundle request rejected (invalid log IDs or payload)."
    return f"log bundle POST HTTP {status_code}"

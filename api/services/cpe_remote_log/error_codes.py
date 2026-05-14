"""Stable error_code values for RemoteLogFetchError and API/UI mapping."""

# Crash portal GET .../crash/logs
CRASH_PORTAL_UNAUTHORIZED = "crash_portal_unauthorized"
CRASH_PORTAL_FORBIDDEN = "crash_portal_forbidden"

# Listing returned no file IDs (HTTP 204, empty JSON, or filters excluding everything)
CRASH_LISTING_NO_MATCH = "crash_listing_no_match"

# Worker env: optional CMS edge headers
CRASH_CMS_HEADERS_RECOMMENDED = "crash_cms_headers_recommended"

# Device registry / bundle POST
DEVICE_REGISTRY_UNAUTHORIZED = "device_registry_unauthorized"

REMEDIATION_UPDATE_CRASH_BEARER = (
    "Paste a fresh crash portal bearer into this form (or retry bulk/restart with a new value): "
    "in the browser, open the CDN crash UI, log in, open DevTools → Network, run a crash log list "
    "that succeeds for this MAC, and copy the Authorization Bearer token from that request."
)

REMEDIATION_CMS_ENV_WORKER = (
    "If listing still returns nothing, copy Cookie, x-dtpc, and x-dtreferer from that same "
    "Network request into server env: CPE_REMOTE_LOG_CMS_COOKIE, CPE_REMOTE_LOG_CMS_X_DTPC, "
    "CPE_REMOTE_LOG_CMS_X_DTREFERER, then restart the API/worker."
)

REMEDIATION_REGISTRY_BEARER = (
    "Update the device registry bearer (Device registry token aligned with this NATCO / x-tenant-id)."
)

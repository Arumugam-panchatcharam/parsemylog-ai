"""
Utility Callbacks
==================

Populates the domain dropdown on the Pattern page with available
rg+Drain3 domain parquet caches. When a project has been indexed,
each domain (wireless, platform, etc.) gets a ``{domain}_rg.parquet``
file in the project directory.
"""

import os
import logging
from pathlib import Path

from dash import Input, Output, callback

from gui.app_instance import dbm
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

# Canonical domain display names (keys must match 'domain:' in rg_patterns YAMLs)
_DOMAIN_LABELS = {
    "wireless": "Wireless (WiFi)",
    "platform": "Platform",
    "core_router": "Core Router",
    "cellular": "Cellular",
    "mesh": "Mesh",
}


@callback(
    Output("file-select", "options"),
    Output("file-select", "value"),
    [
        Input("refresh-filelist-icon", "n_clicks"),
        Input("current-project-store", "data"),
    ],
)
def update_domain_list(n_clicks, project_data):
    """
    Populate the domain dropdown with domains that have indexed parquet caches.

    Scans the project directory for ``*_rg.parquet`` files produced by the
    rg+Drain3 indexer and returns them as dropdown options.
    """
    if not project_data or not project_data.get("project_id"):
        return [], None

    project_id = project_data["project_id"]
    user_id = project_data.get("user_id")
    project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")

    options = []

    if project_dir.exists():
        # Fast check: iterate known domain names instead of glob
        _known = ["wireless", "platform", "core_router", "cellular", "mesh"]
        for domain in _known:
            pq = project_dir / f"{domain}_rg.parquet"
            if pq.exists():
                label = _DOMAIN_LABELS.get(domain, domain.replace("_", " ").title())
                size_mb = round(pq.stat().st_size / (1024 * 1024), 2)
                options.append({
                    "label": f"{label} ({size_mb} MB)",
                    "value": domain,
                })

    logger.debug(f"[DomainList] Found {len(options)} indexed domains for project {project_id}")
    if options:
        return options, options[0]["value"]
    return options, None

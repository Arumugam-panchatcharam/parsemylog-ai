"""
Device Info Extractor
======================

Parses key RDK log files to extract structured device metadata.

Adopted from dt-smart-cpe-agent/src/cpe_rdk_rag/core/info_extractor.py.

Currently supports:
    - version.txt: Firmware versions, build info, SDK version, SW upgrade detection

The extracted info is used by the Telemetry tab to enrich the Device Info card.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# version.txt parser
# ---------------------------------------------------------------------------

# Fields in a single version block (10 lines per block)
_VERSION_FIELDS = [
    "MACHINE_NAME", "imagename", "BRANCH", "VERSION", "SPIN",
    "BUILD-TIME", "WORKFLOW-TYPE", "BUILD-ID", "Generated on", "SDK_VERSION",
]


def parse_version_txt(content: str) -> Dict[str, Any]:
    """
    Parse version.txt which may contain multiple repeated blocks.

    Each block is 10 lines::

        MACHINE_NAME=...
        imagename:...
        BRANCH=...
        VERSION=...
        SPIN=...
        BUILD-TIME="..."
        WORKFLOW-TYPE=...
        BUILD-ID=...
        Generated on ...
        SDK_VERSION=...

    Returns:
        Dict with:
            - machine_name, branch, sdk_version (from latest block)
            - firmware_versions: list of unique {version, build_id, build_time, ...}
            - sw_upgrade_detected: bool (True if more than one unique VERSION found)
            - sw_upgrade_detail: str description (e.g. "004.011.080 -> 004.011.082")
            - total_blocks: total version blocks found (approx log rotations)
    """
    if not content or not content.strip():
        return {}

    lines = [ln.strip() for ln in content.strip().splitlines() if ln.strip()]

    # Parse all lines into key=value blocks
    blocks: List[Dict[str, str]] = []
    current_block: Dict[str, str] = {}

    for line in lines:
        if line.startswith("MACHINE_NAME=") and current_block:
            blocks.append(current_block)
            current_block = {}

        if "=" in line:
            key, _, value = line.partition("=")
            current_block[key.strip()] = value.strip().strip('"')
        elif line.startswith("imagename:"):
            current_block["imagename"] = line.split(":", 1)[1].strip()
        elif line.startswith("Generated on"):
            current_block["Generated on"] = line.replace("Generated on", "").strip()

    if current_block:
        blocks.append(current_block)

    if not blocks:
        return {}

    # Deduplicate by VERSION+BUILD-ID
    seen_versions: OrderedDict[str, Dict[str, str]] = OrderedDict()
    for block in blocks:
        version = block.get("VERSION", "")
        build_id = block.get("BUILD-ID", "")
        key = f"{version}_{build_id}"
        if key not in seen_versions:
            seen_versions[key] = block

    unique_versions = list(seen_versions.values())
    latest = blocks[-1]

    firmware_versions = []
    for v in unique_versions:
        firmware_versions.append({
            "version": v.get("VERSION", ""),
            "build_id": v.get("BUILD-ID", ""),
            "build_time": v.get("BUILD-TIME", ""),
            "image_name": v.get("imagename", ""),
            "spin": v.get("SPIN", ""),
        })

    # SW upgrade detection
    sw_upgrade = len(unique_versions) > 1
    sw_detail = ""
    if sw_upgrade and firmware_versions:
        old_ver = firmware_versions[0]["version"]
        new_ver = firmware_versions[-1]["version"]
        sw_detail = f"{old_ver} → {new_ver}"

    return {
        "machine_name": latest.get("MACHINE_NAME", ""),
        "branch": latest.get("BRANCH", ""),
        "sdk_version": latest.get("SDK_VERSION", ""),
        "firmware_versions": firmware_versions,
        "sw_upgrade_detected": sw_upgrade,
        "sw_upgrade_detail": sw_detail,
        "total_blocks": len(blocks),
    }


def find_and_parse_version_txt(project_dir: Path) -> Dict[str, Any]:
    """
    Locate version.txt in the project's merged_logs directory and parse it.

    Searches in:
        1. {project_dir}/merged_logs/version.txt
        2. {project_dir}/version.txt (fallback)

    Args:
        project_dir: Path to the project directory.

    Returns:
        Parsed version info dict, or empty dict if not found.
    """
    search_paths = [
        project_dir / "merged_logs" / "version.txt",
        project_dir / "version.txt",
    ]

    for path in search_paths:
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                result = parse_version_txt(content)
                if result:
                    logger.info(
                        f"[InfoExtractor] Parsed {path}: "
                        f"SDK={result.get('sdk_version', 'N/A')}, "
                        f"upgrade={result.get('sw_upgrade_detected', False)}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"[InfoExtractor] Error parsing {path}: {e}")

    return {}

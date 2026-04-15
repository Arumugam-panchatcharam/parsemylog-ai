"""BSSID / interface static map from device base MAC + YAML offsets."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import polars as pl
import yaml

from .config_paths import wifi_interface_map_path

logger = logging.getLogger(__name__)


def normalize_mac(mac: Optional[str]) -> str:
    if mac is None:
        return ""
    s = str(mac).strip()
    if not s:
        return ""
    hex_only = re.sub(r"[^0-9a-fA-F]", "", s)
    if len(hex_only) != 12:
        return s.lower()
    return ":".join(hex_only[i : i + 2].lower() for i in range(0, 12, 2))


def bssid_with_offset(base_mac: str, offset: int) -> str:
    hex_only = re.sub(r"[^0-9a-fA-F]", "", base_mac)
    if len(hex_only) != 12:
        return ""
    val = (int(hex_only, 16) + int(offset)) & 0xFFFFFFFFFFFF
    out = f"{val:012x}"
    return ":".join(out[i : i + 2] for i in range(0, 12, 2))


@dataclass(frozen=True)
class InterfaceRow:
    ifname: str
    role: str
    bssid: str


def load_interface_map_yaml(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or wifi_interface_map_path()
    if not p.is_file():
        logger.warning("wifi_interface_map.yaml not found at %s", p)
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_interface_table(
    device_info: Dict[str, Any],
    map_yaml: Optional[Dict[str, Any]] = None,
) -> pl.DataFrame:
    """
    Build a table of ifname, role, bssid for this device using base MAC from device_info.
    """
    data = map_yaml if map_yaml is not None else load_interface_map_yaml()
    if not data:
        return pl.DataFrame(
            schema={
                "ifname": pl.Utf8,
                "role": pl.Utf8,
                "bssid": pl.Utf8,
            }
        )

    field = data.get("base_mac_field", "mac")
    base_raw = device_info.get(field, "")
    base = normalize_mac(str(base_raw)) if base_raw else ""

    rows: List[InterfaceRow] = []
    for entry in data.get("interfaces") or []:
        ifname = str(entry.get("ifname", "")).strip()
        role = str(entry.get("role", "")).strip()
        off = int(entry.get("bssid_offset", 0))
        bssid = bssid_with_offset(base, off) if base else ""
        if ifname:
            rows.append(InterfaceRow(ifname=ifname, role=role, bssid=bssid))

    if not rows:
        return pl.DataFrame(
            schema={
                "ifname": pl.Utf8,
                "role": pl.Utf8,
                "bssid": pl.Utf8,
            }
        )

    return pl.DataFrame(
        {
            "ifname": [r.ifname for r in rows],
            "role": [r.role for r in rows],
            "bssid": [r.bssid for r in rows],
        }
    )


def model_matches_device(map_yaml: Dict[str, Any], device_info: Dict[str, Any]) -> bool:
    models = map_yaml.get("models") or []
    if not models:
        return True
    m = str(device_info.get("model", "")).strip()
    return m in {str(x).strip() for x in models}

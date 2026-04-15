"""Resolve repository paths for wireless YAML configs."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Repository root (parent of ``logai``)."""
    return Path(__file__).resolve().parents[3]


def wireless_configs_dir() -> Path:
    return repo_root() / "configs" / "wireless"


def wifi_interface_map_path() -> Path:
    return wireless_configs_dir() / "wifi_interface_map.yaml"


def wifi_auth_assoc_event_map_path() -> Path:
    return wireless_configs_dir() / "wifi_auth_assoc_event_map.yaml"

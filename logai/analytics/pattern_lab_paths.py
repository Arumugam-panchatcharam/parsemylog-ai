"""Paths for per-user Pattern Lab profile YAML files and per-project active profile."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Union

from logai.utils.constants import UPLOAD_DIRECTORY

PATTERN_LAB_PROFILES_DIRNAME = "pattern_lab_profiles"
PATTERN_LAB_ACTIVE_FILENAME = "pattern_lab_active.json"
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def sanitize_profile_id(raw: str) -> Optional[str]:
    """Normalize user-facing profile name to a safe file id."""
    s = (raw or "").strip().lower().replace(" ", "_")
    s = re.sub(r"[^a-z0-9_-]+", "_", s).strip("_")
    if not s or not PROFILE_ID_PATTERN.match(s):
        return None
    return s


def user_pattern_lab_profiles_dir(user_id: Union[int, str]) -> Path:
    return Path(UPLOAD_DIRECTORY) / str(user_id) / PATTERN_LAB_PROFILES_DIRNAME


def user_profile_yaml_path(user_id: Union[int, str], profile_id: str) -> Path:
    return user_pattern_lab_profiles_dir(user_id) / f"{profile_id}.yaml"


def project_active_profile_path(user_id: Union[int, str], project_id: str) -> Path:
    return Path(UPLOAD_DIRECTORY) / str(user_id) / project_id / PATTERN_LAB_ACTIVE_FILENAME


def read_active_profile_id(user_id: Union[int, str], project_id: str) -> Optional[str]:
    path = project_active_profile_path(user_id, project_id)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            pid = raw.get("profile")
            if isinstance(pid, str) and pid.strip():
                return sanitize_profile_id(pid) or pid.strip()
    except Exception:
        return None
    return None


def write_active_profile_id(user_id: Union[int, str], project_id: str, profile_id: str) -> Path:
    path = project_active_profile_path(user_id, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"profile": profile_id}, f, indent=2)
    return path


def resolved_pattern_lab_yaml_path(user_id: Union[int, str], project_id: str) -> Optional[Path]:
    """YAML file used for Polars ETL: active profile for this project, if set and present."""
    pid = read_active_profile_id(user_id, project_id)
    if not pid:
        return None
    p = user_profile_yaml_path(user_id, pid)
    return p if p.is_file() else None

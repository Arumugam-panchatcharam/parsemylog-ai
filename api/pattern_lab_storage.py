"""Per-user Pattern Lab profiles and per-project active profile selection."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from api.pattern_lab_validation import MAX_PATTERN_LAB_BYTES, validate_pattern_lab
from logai.analytics.pattern_lab_paths import (
    read_active_profile_id,
    sanitize_profile_id,
    user_pattern_lab_profiles_dir,
    user_profile_yaml_path,
    write_active_profile_id,
)
from logai.analytics.wifi_protocol.config_paths import repo_root
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

MAX_YAML_BYTES = MAX_PATTERN_LAB_BYTES

_STARTER_PATH = repo_root() / "configs" / "analytics" / "pattern_lab_starter.yaml"


def _doc_from_raw(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"events": {}, "issues": {}}
    return {
        "events": dict(raw.get("events") or {}),
        "issues": dict(raw.get("issues") or {}),
    }


def load_starter_example() -> Dict[str, Any]:
    """Built-in generic example (not WiFi-specific)."""
    if not _STARTER_PATH.is_file():
        logger.warning("Pattern lab starter missing at %s", _STARTER_PATH)
        return {"events": {}, "issues": {}}
    with open(_STARTER_PATH, encoding="utf-8") as f:
        return _doc_from_raw(yaml.safe_load(f))


def load_profile(user_id: Union[int, str], profile_id: str) -> Optional[Dict[str, Any]]:
    path = user_profile_yaml_path(user_id, profile_id)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return _doc_from_raw(yaml.safe_load(f))
    except Exception as e:
        logger.warning("Failed to read profile %s: %s", path, e)
        return None


def save_profile(
    user_id: Union[int, str],
    profile_id: str,
    doc: Dict[str, Any],
) -> Path:
    pid = sanitize_profile_id(profile_id)
    if not pid:
        raise ValueError("Invalid profile name")
    ok, msg = validate_pattern_lab(doc, strict=False)
    if not ok:
        raise ValueError(msg)
    root = user_pattern_lab_profiles_dir(user_id)
    root.mkdir(parents=True, exist_ok=True)
    path = user_profile_yaml_path(user_id, pid)
    payload = {"events": dict(doc.get("events") or {}), "issues": dict(doc.get("issues") or {})}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return path


def duplicate_profile(
    user_id: Union[int, str],
    target_id: str,
    source_id: Optional[str] = None,
    doc: Optional[Dict[str, Any]] = None,
) -> Path:
    """Copy ``source_id`` or ``doc`` into a new profile ``target_id`` (must not exist)."""
    target = sanitize_profile_id(target_id)
    if not target:
        raise ValueError("Invalid target profile name")
    if user_profile_yaml_path(user_id, target).is_file():
        raise ValueError(f"Profile {target!r} already exists. Choose another name.")

    if doc is not None:
        return save_profile(user_id, target, doc)

    if source_id:
        src = sanitize_profile_id(source_id)
        if not src:
            raise ValueError("Invalid source profile name")
        loaded = load_profile(user_id, src)
        if loaded is None:
            raise ValueError(f"Source profile {src!r} not found")
        return save_profile(user_id, target, loaded)

    raise ValueError("Provide a source profile or document content to duplicate")


def delete_profile(user_id: Union[int, str], profile_id: str) -> bool:
    pid = sanitize_profile_id(profile_id)
    if not pid:
        return False
    path = user_profile_yaml_path(user_id, pid)
    if path.is_file():
        path.unlink()
        return True
    return False


def list_profiles(user_id: Union[int, str]) -> List[Dict[str, Any]]:
    root = user_pattern_lab_profiles_dir(user_id)
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(root.glob("*.yaml")):
        pid = p.stem
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            mtime = None
        out.append({"id": pid, "name": pid.replace("_", " "), "updated_at": mtime})
    return out


def set_active_profile(user_id: Union[int, str], project_id: str, profile_id: str) -> str:
    pid = sanitize_profile_id(profile_id)
    if not pid:
        raise ValueError("Invalid profile name")
    path = user_profile_yaml_path(user_id, pid)
    if not path.is_file():
        raise ValueError(f"Profile {pid!r} does not exist; save it first")
    write_active_profile_id(user_id, project_id, pid)
    return pid


def _migrate_legacy_project_yaml(user_id: Union[int, str], project_id: str) -> None:
    """Import legacy single-file ``pattern_lab.yaml`` in project root into a user profile once."""
    if list_profiles(user_id):
        return
    legacy = Path(UPLOAD_DIRECTORY) / str(user_id) / project_id / "pattern_lab.yaml"
    if not legacy.is_file():
        return
    try:
        with open(legacy, encoding="utf-8") as f:
            doc = _doc_from_raw(yaml.safe_load(f))
        save_profile(user_id, "imported", doc)
        set_active_profile(user_id, project_id, "imported")
        logger.info("Migrated legacy pattern_lab.yaml to profile 'imported' for user %s", user_id)
    except Exception as e:
        logger.warning("Legacy pattern_lab.yaml migration skipped: %s", e)


def get_pattern_lab_state(
    user_id: Union[int, str], project_id: str,
) -> Tuple[Dict[str, Any], str, Optional[str], List[Dict[str, Any]]]:
    """
    Returns (doc, source, active_profile_id, profiles_list).

    source: ``profile`` | ``starter``
    """
    _migrate_legacy_project_yaml(user_id, project_id)
    profiles = list_profiles(user_id)
    active = read_active_profile_id(user_id, project_id)
    if active:
        doc = load_profile(user_id, active)
        if doc is not None:
            return doc, "profile", active, profiles
    return load_starter_example(), "starter", active, profiles


def load_active_or_starter(user_id: Union[int, str], project_id: str) -> Dict[str, Any]:
    doc, _src, _active, _profiles = get_pattern_lab_state(user_id, project_id)
    return doc


def doc_from_request_body(body: Any) -> Tuple[Dict[str, Any] | None, str | None, Optional[str]]:
    if not isinstance(body, dict):
        return None, "JSON body must be an object", None
    profile_raw = body.get("profile")
    profile_id: Optional[str] = None
    if profile_raw is not None:
        if not isinstance(profile_raw, str):
            return None, "profile must be a string", None
        profile_id = sanitize_profile_id(profile_raw)
        if not profile_id:
            return None, "profile name must be 1–64 chars: letters, numbers, underscore, hyphen", None
    doc = {"events": body.get("events") or {}, "issues": body.get("issues") or {}}
    return doc, None, profile_id


def duplicate_from_request_body(body: Any) -> Tuple[str | None, Optional[str], Dict[str, Any] | None, str | None]:
    """
    Parse duplicate request: target profile (required), optional source profile, optional inline doc.

    Returns (target_id, source_id, doc_or_none, error_message).
    """
    if not isinstance(body, dict):
        return None, None, None, "JSON body must be an object"
    target_raw = body.get("target_profile") or body.get("target")
    if not isinstance(target_raw, str):
        return None, None, None, "target_profile is required"
    target_id = sanitize_profile_id(target_raw)
    if not target_id:
        return None, None, None, "target_profile name must be 1–64 chars: letters, numbers, underscore, hyphen"

    source_id: Optional[str] = None
    source_raw = body.get("source_profile") or body.get("source")
    if source_raw is not None:
        if not isinstance(source_raw, str):
            return None, None, None, "source_profile must be a string"
        source_id = sanitize_profile_id(source_raw)
        if not source_id:
            return None, None, None, "source_profile name is invalid"

    has_doc = "events" in body or "issues" in body
    doc: Optional[Dict[str, Any]] = None
    if has_doc:
        doc = {"events": body.get("events") or {}, "issues": body.get("issues") or {}}
        ok, msg = validate_pattern_lab(doc, strict=False)
        if not ok:
            return None, None, None, msg

    if doc is None and not source_id:
        return None, None, None, "Provide source_profile or events/issues in the request body"

    return target_id, source_id, doc, None

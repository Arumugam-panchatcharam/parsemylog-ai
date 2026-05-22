"""
Admin-controlled deployment update orchestration.

Spawns scripts/server-upgrade.sh detached; reads status from DEPLOY_STATUS_FILE.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RUNNING_STATES = frozenset(
    {"previewing", "applying", "rolling_back"}
)


def is_enabled() -> bool:
    return os.environ.get("DEPLOY_UPDATE_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def project_root() -> Path:
    raw = os.environ.get("DEPLOY_PROJECT_ROOT", "").strip()
    if raw:
        return Path(raw)
    # Dev fallback: repo root (api/services -> api -> repo)
    return Path(__file__).resolve().parent.parent.parent


def status_file_path() -> Path:
    raw = os.environ.get("DEPLOY_STATUS_FILE", "").strip()
    if raw:
        return Path(raw)
    return project_root() / "data" / "deploy_update_status.json"


def get_app_version() -> str:
    """Read application version from VERSION file at deploy/project root."""
    candidates = [
        project_root() / "VERSION",
        Path("/deploy/VERSION"),
        Path(__file__).resolve().parent.parent.parent / "VERSION",
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8").strip() or "0.0.0"
            except OSError:
                continue
    return "0.0.0"


def upgrade_script_path() -> Path:
    root = project_root()
    candidates = [
        root / "scripts" / "server-upgrade.sh",
        Path("/deploy/scripts/server-upgrade.sh"),
        Path("/app/scripts/server-upgrade.sh"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def read_status() -> dict[str, Any]:
    path = status_file_path()
    if not path.is_file():
        return _idle_status()
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _idle_status()
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read deployment status: %s", e)
        return _idle_status()


def _idle_status() -> dict[str, Any]:
    return {
        "phase": "idle",
        "state": "idle",
        "step": None,
        "error": None,
        "enabled": is_enabled(),
    }


def is_running() -> bool:
    state = read_status().get("state", "idle")
    return state in RUNNING_STATES


def _tail_log(log_file: str | None, max_lines: int = 40) -> str:
    if not log_file:
        return ""
    path = Path(log_file)
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:])
    except OSError:
        return ""


def public_status(dbm=None) -> dict[str, Any]:
    data = read_status()
    out: dict[str, Any] = {
        "enabled": is_enabled(),
        "version": get_app_version(),
        "phase": data.get("phase", "idle"),
        "state": data.get("state", "idle"),
        "step": data.get("step"),
        "error": data.get("error"),
        "current_sha": data.get("current_sha"),
        "pre_sha": data.get("pre_sha"),
        "post_sha": data.get("post_sha"),
        "upstream_sha": data.get("upstream_sha"),
        "upstream_ref": data.get("upstream_ref"),
        "behind_count": data.get("behind_count"),
        "commits": data.get("commits") or [],
        "diff_stat": data.get("diff_stat") or "",
        "preview_ready": bool(data.get("preview_ready")),
        "updated_at": data.get("updated_at"),
        "log_tail": _tail_log(data.get("log_file")),
        "project_root": str(project_root()),
    }
    if dbm is not None:
        out["last_update_at"] = dbm.get_setting("deployment_last_update_at")
        out["last_update_by"] = dbm.get_setting("deployment_last_update_by")
        out["last_update_status"] = dbm.get_setting("deployment_last_update_status")
    return out


def _compose_project_name() -> str:
    explicit = os.environ.get("COMPOSE_PROJECT_NAME", "").strip()
    if explicit:
        return explicit
    raw_root = os.environ.get("DEPLOY_PROJECT_ROOT", "").strip()
    root = Path(raw_root) if raw_root else project_root()
    if root.name and root.name != "deploy":
        return root.name
    return "parsemylog-ai"


def _logai_data_volume_name() -> str:
    # Docker Compose names volumes: {project}_{volume}
    project = _compose_project_name()
    return os.environ.get("DEPLOY_LOGAI_DATA_VOLUME", f"{project}_logai_data")


def _spawn_phase(phase: str, env_extra: dict[str, str] | None = None) -> None:
    script = upgrade_script_path()
    if not script.is_file():
        raise FileNotFoundError(f"Upgrade script not found: {script}")

    root = project_root()
    status_path = status_file_path()
    app_port = os.environ.get("APP_PORT", "40901").strip() or "40901"
    health_url = os.environ.get(
        "DEPLOY_HEALTH_CHECK_URL",
        f"http://host.docker.internal:{app_port}/api/auth/health",
    )

    log_path = status_path.with_suffix(".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Run in a detached one-off container so the job survives logai-api restart.
    deploy_root = os.environ.get("DEPLOY_PROJECT_ROOT", str(root)).strip() or str(root)
    data_volume = _logai_data_volume_name()
    image = os.environ.get("DEPLOY_RUNNER_IMAGE", "parsemylog-ai:latest")
    container_name = f"logai-upgrade-{phase}-{int(datetime.now(timezone.utc).timestamp())}"

    cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        container_name,
        "--add-host=host.docker.internal:host-gateway",
        "-v",
        f"{deploy_root}:/deploy:rw",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        f"{data_volume}:/app/data",
        "-e",
        "DEPLOY_PROJECT_ROOT=/deploy",
        "-e",
        f"DEPLOY_STATUS_FILE=/app/data/deploy_update_status.json",
        "-e",
        f"APP_PORT={app_port}",
        "-e",
        f"HEALTH_CHECK_URL={health_url}",
        "-e",
        f"COMPOSE_PROJECT_NAME={_compose_project_name()}",
        "-w",
        "/deploy",
        image,
        "sh",
        "/deploy/scripts/server-upgrade.sh",
        phase,
    ]
    if env_extra:
        for key, val in env_extra.items():
            cmd.extend(["-e", f"{key}={val}"])

    logger.info("Starting deployment %s via docker run: %s", phase, container_name)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "docker run failed").strip()
        raise RuntimeError(f"Failed to start upgrade container: {err}")


def start_preview() -> dict[str, Any]:
    if not is_enabled():
        raise DeploymentUpdateError(
            "Deployment updates are disabled on this instance. "
            "Set DEPLOY_UPDATE_ENABLED=1 and configure deploy mounts.",
            status_code=503,
        )
    if is_running():
        raise DeploymentUpdateError(
            "A deployment operation is already in progress.",
            status_code=409,
        )
    _spawn_phase("preview")
    return public_status()


def start_apply(admin_user_id: int, admin_username: str, dbm) -> dict[str, Any]:
    if not is_enabled():
        raise DeploymentUpdateError(
            "Deployment updates are disabled on this instance.",
            status_code=503,
        )
    if is_running():
        raise DeploymentUpdateError(
            "A deployment operation is already in progress.",
            status_code=409,
        )

    st = read_status()
    if st.get("phase") != "preview" or st.get("state") != "completed":
        raise DeploymentUpdateError(
            "Run preview first and wait for it to complete before applying.",
            status_code=400,
        )
    if not st.get("preview_ready"):
        raise DeploymentUpdateError(
            "Preview is not ready. Check for errors and try preview again.",
            status_code=400,
        )

    _spawn_phase(
        "apply",
        env_extra={
            "DEPLOY_ADMIN_USER_ID": str(admin_user_id),
            "DEPLOY_ADMIN_USERNAME": admin_username,
        },
    )

    now = datetime.now(timezone.utc).isoformat()
    dbm.set_setting("deployment_last_update_at", now)
    dbm.set_setting("deployment_last_update_by", admin_username)
    dbm.set_setting("deployment_last_update_status", "applying")

    return public_status(dbm=dbm)


def record_apply_finished(dbm, final_state: str) -> None:
    """Called when polling detects terminal apply state (optional hook)."""
    dbm.set_setting("deployment_last_update_status", final_state)


class DeploymentUpdateError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

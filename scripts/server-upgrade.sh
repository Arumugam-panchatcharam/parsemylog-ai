#!/usr/bin/env bash
# Admin-triggered server upgrade: preview (git fetch) or apply (pull, build, restart).
# Invoked detached from the API; persists status to DEPLOY_STATUS_FILE.
#
# Usage:
#   ./scripts/server-upgrade.sh preview
#   ./scripts/server-upgrade.sh apply
#
# Environment:
#   DEPLOY_PROJECT_ROOT  — git + docker compose working directory (default: repo root)
#   DEPLOY_STATUS_FILE   — JSON status path (default: <root>/data/deploy_update_status.json)
#   APP_PORT             — host port for health check (default: 40901)
#   COMPOSE_CMD          — e.g. "docker compose" (default)
#   GIT_REMOTE           — default: origin

set -euo pipefail

PHASE="${1:-}"
if [[ -z "$PHASE" ]] || [[ "$PHASE" != "preview" && "$PHASE" != "apply" ]]; then
  echo "Usage: $0 preview|apply" >&2
  exit 1
fi

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
DEPLOY_PROJECT_ROOT="${DEPLOY_PROJECT_ROOT:-$ROOT}"
DEPLOY_STATUS_FILE="${DEPLOY_STATUS_FILE:-$DEPLOY_PROJECT_ROOT/data/deploy_update_status.json}"
APP_PORT="${APP_PORT:-40901}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
LOG_FILE="${DEPLOY_STATUS_FILE%.json}.log"

export DEPLOY_STATUS_FILE DEPLOY_PROJECT_ROOT

mkdir -p "$(dirname "$DEPLOY_STATUS_FILE")"
cd "$DEPLOY_PROJECT_ROOT"

status_patch() {
  python3 - "$DEPLOY_STATUS_FILE" <<'PY'
import json, os, sys
from datetime import datetime, timezone

path, patch_json = sys.argv[1], sys.argv[2]
patch = json.loads(patch_json)
data = {}
if os.path.isfile(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
data.update(patch)
data["updated_at"] = datetime.now(timezone.utc).isoformat()
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY
}

append_log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >>"$LOG_FILE"
}

require_clean_tree() {
  if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    status_patch "{\"phase\":\"$PHASE\",\"state\":\"failed\",\"step\":\"check_tree\",\"error\":\"Working tree is not clean. Commit or stash changes before upgrading.\"}"
    append_log "ERROR: dirty working tree"
    exit 1
  fi
  if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    status_patch "{\"phase\":\"$PHASE\",\"state\":\"failed\",\"step\":\"check_tree\",\"error\":\"Working tree is not clean. Commit or stash changes before upgrading.\"}"
    append_log "ERROR: uncommitted files"
    exit 1
  fi
}

upstream_ref() {
  git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "${GIT_REMOTE}/HEAD"
}

health_check() {
  local url="${HEALTH_CHECK_URL:-http://127.0.0.1:${APP_PORT}/api/auth/health}"
  local i=0 max=30
  append_log "Health check: $url"
  while [ "$i" -lt "$max" ]; do
    if curl -sf --max-time 5 "$url" >/dev/null 2>&1; then
      append_log "Health check OK"
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  append_log "Health check FAILED after ${max} attempts"
  return 1
}

run_compose_frontend_build() {
  append_log "Running: $COMPOSE_CMD --profile build up frontend-build"
  # shellcheck disable=SC2086
  $COMPOSE_CMD --profile build up frontend-build
}

run_compose_restart() {
  append_log "Running: $COMPOSE_CMD restart nginx celery-worker logai-api"
  # shellcheck disable=SC2086
  $COMPOSE_CMD restart nginx celery-worker logai-api
}

rollback_to() {
  local pre_sha="$1"
  local err_msg="${2:-Upgrade failed}"
  append_log "ROLLBACK to $pre_sha: $err_msg"
  DEPLOY_ERR="$err_msg" DEPLOY_PRE="$pre_sha" python3 <<'PY'
import json, os
from datetime import datetime, timezone
path = os.environ["DEPLOY_STATUS_FILE"]
err = os.environ["DEPLOY_ERR"]
pre = os.environ["DEPLOY_PRE"]
data = {}
if os.path.isfile(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
data.update({"phase": "apply", "state": "rolling_back", "step": "rollback", "pre_sha": pre, "error": err,
             "updated_at": datetime.now(timezone.utc).isoformat()})
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY

  git reset --hard "$pre_sha" || true
  status_patch "{\"phase\":\"apply\",\"state\":\"rolling_back\",\"step\":\"rebuild_frontend\",\"pre_sha\":\"$pre_sha\"}"

  if ! run_compose_frontend_build 2>>"$LOG_FILE"; then
    append_log "Rollback frontend build failed"
    DEPLOY_ERR="${err_msg} (rollback frontend build also failed)" DEPLOY_PRE="$pre_sha" python3 <<'PY'
import json, os
from datetime import datetime, timezone
path = os.environ["DEPLOY_STATUS_FILE"]
data = {}
if os.path.isfile(path):
    with open(path) as f:
        data = json.load(f)
data.update({"phase": "apply", "state": "failed", "step": "rollback",
             "error": os.environ["DEPLOY_ERR"], "updated_at": datetime.now(timezone.utc).isoformat()})
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY
    exit 1
  fi

  status_patch "{\"phase\":\"apply\",\"state\":\"rolling_back\",\"step\":\"restart\",\"pre_sha\":\"$pre_sha\"}"
  run_compose_restart 2>>"$LOG_FILE" || true

  local cur
  cur="$(git rev-parse HEAD 2>/dev/null || echo "")"
  if health_check; then
    DEPLOY_ERR="$err_msg" DEPLOY_PRE="$pre_sha" DEPLOY_CUR="$cur" python3 <<'PY'
import json, os
from datetime import datetime, timezone
path = os.environ["DEPLOY_STATUS_FILE"]
data = {}
if os.path.isfile(path):
    with open(path) as f:
        data = json.load(f)
data.update({
    "phase": "apply", "state": "rolled_back", "step": "done",
    "pre_sha": os.environ["DEPLOY_PRE"], "current_sha": os.environ["DEPLOY_CUR"],
    "error": os.environ["DEPLOY_ERR"],
    "updated_at": datetime.now(timezone.utc).isoformat(),
})
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY
  else
    status_patch "{\"phase\":\"apply\",\"state\":\"failed\",\"step\":\"rollback\",\"error\":\"${err_msg} (rolled back git but health check still failing)\"}"
  fi
  exit 1
}

do_preview() {
  : >"$LOG_FILE" 2>/dev/null || true
  status_patch "{\"phase\":\"preview\",\"state\":\"previewing\",\"step\":\"fetch\",\"error\":null,\"log_file\":\"$LOG_FILE\"}"
  append_log "Starting preview"

  require_clean_tree

  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    status_patch "{\"phase\":\"preview\",\"state\":\"failed\",\"step\":\"fetch\",\"error\":\"Not a git repository at ${DEPLOY_PROJECT_ROOT}\"}"
    exit 1
  fi

  if ! git fetch "$GIT_REMOTE" 2>>"$LOG_FILE"; then
    status_patch "{\"phase\":\"preview\",\"state\":\"failed\",\"step\":\"fetch\",\"error\":\"git fetch ${GIT_REMOTE} failed\"}"
    exit 1
  fi

  local up head_sha behind up_sha
  up="$(upstream_ref)"
  head_sha="$(git rev-parse HEAD)"
  behind=0
  up_sha=""
  if git rev-parse "$up" >/dev/null 2>&1; then
    up_sha="$(git rev-parse "$up")"
    behind="$(git rev-list --count HEAD.."$up" 2>/dev/null || echo 0)"
  fi

  python3 <<PY
import json, subprocess, os
from datetime import datetime, timezone

deploy_root = "$DEPLOY_PROJECT_ROOT"
up = "$up"
behind = int("$behind")
head_sha = "$head_sha"
up_sha = "$up_sha"
status_path = "$DEPLOY_STATUS_FILE"
log_file = "$LOG_FILE"

commits = []
diff_stat = ""
if behind > 0:
    r = subprocess.run(
        ["git", "log", f"HEAD..{up}", "--pretty=format:%H|%h|%s|%an|%ar"],
        capture_output=True, text=True, cwd=deploy_root,
    )
    for line in (r.stdout or "").strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 4)
        commits.append({
            "full_sha": parts[0],
            "sha": parts[1],
            "subject": parts[2],
            "author": parts[3] if len(parts) > 3 else "",
            "date_relative": parts[4] if len(parts) > 4 else "",
        })
    r2 = subprocess.run(
        ["git", "diff", "--stat", f"HEAD..{up}"],
        capture_output=True, text=True, cwd=deploy_root,
    )
    diff_stat = (r2.stdout or "").strip()

data = {}
if os.path.isfile(status_path):
    try:
        with open(status_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        pass

data.update({
    "phase": "preview",
    "state": "completed",
    "step": "done",
    "error": None,
    "current_sha": head_sha,
    "upstream_sha": up_sha,
    "upstream_ref": up,
    "behind_count": behind,
    "commits": commits,
    "diff_stat": diff_stat,
    "preview_ready": True,
    "log_file": log_file,
    "updated_at": datetime.now(timezone.utc).isoformat(),
})
os.makedirs(os.path.dirname(status_path) or ".", exist_ok=True)
with open(status_path, "w") as f:
    json.dump(data, f, indent=2)
PY

  append_log "Preview done: behind=$behind"
}

do_apply() {
  append_log "Starting apply"
  status_patch "{\"phase\":\"apply\",\"state\":\"applying\",\"step\":\"check_tree\",\"error\":null,\"log_file\":\"$LOG_FILE\"}"

  require_clean_tree

  local pre_sha post_sha
  pre_sha="$(git rev-parse HEAD)"
  status_patch "{\"phase\":\"apply\",\"state\":\"applying\",\"step\":\"pull\",\"pre_sha\":\"$pre_sha\"}"
  append_log "pre_sha=$pre_sha"

  if ! git pull "$GIT_REMOTE" 2>>"$LOG_FILE"; then
    rollback_to "$pre_sha" "git pull failed"
  fi

  post_sha="$(git rev-parse HEAD)"
  status_patch "{\"phase\":\"apply\",\"state\":\"applying\",\"step\":\"pull\",\"pre_sha\":\"$pre_sha\",\"post_sha\":\"$post_sha\"}"
  append_log "post_sha=$post_sha"

  status_patch "{\"phase\":\"apply\",\"state\":\"applying\",\"step\":\"build_frontend\",\"pre_sha\":\"$pre_sha\",\"post_sha\":\"$post_sha\"}"
  if ! run_compose_frontend_build 2>>"$LOG_FILE"; then
    rollback_to "$pre_sha" "Frontend build failed"
  fi

  status_patch "{\"phase\":\"apply\",\"state\":\"applying\",\"step\":\"restart\",\"pre_sha\":\"$pre_sha\",\"post_sha\":\"$post_sha\"}"
  if ! run_compose_restart 2>>"$LOG_FILE"; then
    rollback_to "$pre_sha" "docker compose restart failed"
  fi

  status_patch "{\"phase\":\"apply\",\"state\":\"applying\",\"step\":\"health_check\",\"pre_sha\":\"$pre_sha\",\"post_sha\":\"$post_sha\"}"
  if ! health_check; then
    rollback_to "$pre_sha" "Health check failed after restart"
  fi

  status_patch "{\"phase\":\"apply\",\"state\":\"completed\",\"step\":\"done\",\"pre_sha\":\"$pre_sha\",\"post_sha\":\"$post_sha\",\"current_sha\":\"$post_sha\",\"error\":null}"
  append_log "Apply completed successfully"
}

case "$PHASE" in
  preview) do_preview ;;
  apply) do_apply ;;
esac

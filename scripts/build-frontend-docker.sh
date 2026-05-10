#!/usr/bin/env sh
# Build the React SPA into the same Docker volumes nginx uses, without requiring
# Docker Compose v2 (`docker compose`). Mirrors docker-compose.yml service frontend-build.
#
# Usage (from repo root):
#   ./scripts/build-frontend-docker.sh
#
# Compose prefixes volumes as ${COMPOSE_PROJECT_NAME}_<volume>; default project name
# is the directory name (same as `docker-compose` / `docker compose` without -p).

set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$ROOT")}"
NODE_VOL="${PROJECT}_frontend_node_modules"
DIST_VOL="${PROJECT}_frontend_dist"

echo "Project/volume prefix: ${PROJECT}"
echo "Using volumes: ${NODE_VOL}, ${DIST_VOL}"

docker run --rm \
  --name frontend-build \
  -v "${ROOT}/frontend:/app" \
  -v "${NODE_VOL}:/app/node_modules" \
  -v "${DIST_VOL}:/app/dist" \
  -w /app \
  node:22-alpine \
  sh -c '
    echo "Installing npm dependencies..."
    npm install --prefer-offline
    echo "Building frontend..."
    npx tsc -b && npx vite build
    echo "Frontend build complete."
  '

# Flask REST API server — dependencies only.
# Source code is bind-mounted at runtime via docker-compose.yml,
# so you only need to rebuild this image when requirements.txt changes.
FROM python:3.11-slim

WORKDIR /app

# Install ripgrep (required for rg+Drain3 two-stage pipeline) and tshark (required for PCAP analysis)
# docker.io for deployment updates; compose v2 plugin is not in Debian apt (install manually below)
RUN apt-get update && \
    echo "wireshark-common wireshark-common/install-setuid boolean false" | debconf-set-selections && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        ripgrep tshark git curl ca-certificates docker.io && \
    rm -rf /var/lib/apt/lists/*

# Docker Compose v2 CLI plugin (admin in-app deployment update)
ARG TARGETARCH
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) COMPOSE_ARCH=x86_64 ;; \
        arm64) COMPOSE_ARCH=aarch64 ;; \
        *) COMPOSE_ARCH=x86_64 ;; \
    esac; \
    mkdir -p /usr/local/lib/docker/cli-plugins; \
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-${COMPOSE_ARCH}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose; \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose; \
    docker compose version

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Batch / CPE helpers (compose also bind-mounts ./scripts for live updates)
COPY scripts /app/scripts

VOLUME ["/app/user_uploads", "/app/bge-small-en-v1.5-local"]

EXPOSE 5000

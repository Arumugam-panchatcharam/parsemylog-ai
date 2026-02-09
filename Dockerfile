# Flask REST API server — dependencies only.
# Source code is bind-mounted at runtime via docker-compose.yml,
# so you only need to rebuild this image when requirements.txt changes.
FROM python:3.11-slim

WORKDIR /app

# Install ripgrep (required for rg+Drain3 two-stage pipeline)
RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

VOLUME ["/app/user_uploads", "/app/bge-small-en-v1.5-local"]

EXPOSE 5000

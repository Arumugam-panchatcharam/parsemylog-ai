FROM python:3.11-slim
MAINTAINER p.arumugam@telekom-digital.com

WORKDIR /app

# Install ripgrep (required for rg+Drain3 two-stage pipeline)
RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

VOLUME ["/app"]

EXPOSE 40901

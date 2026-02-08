# Flask REST API server
FROM python:3.11-slim

WORKDIR /app

# Install ripgrep (required for rg+Drain3 two-stage pipeline)
RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api/ ./api/
COPY gui/ ./gui/
COPY logai/ ./logai/
COPY configs/ ./configs/
COPY logai_wsgi.py logai_api_wsgi.py run_api.py run_dev.py ./

VOLUME ["/app/user_uploads", "/app/bge-small-en-v1.5-local"]

EXPOSE 40901

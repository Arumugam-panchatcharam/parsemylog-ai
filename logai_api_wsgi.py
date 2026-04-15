"""
Production WSGI entry point for the REST API (Gunicorn).

Usage (Docker): see docker-compose.yml (GUNICORN_TIMEOUT, typically 1800s).
    gunicorn -w 4 -b 0.0.0.0:5000 --timeout 1800 --graceful-timeout 120 --preload logai_api_wsgi:app

Environment variables (set via .env):
    LOG_LEVEL              - Python log level (default: INFO).
    QDRANT_URL             - Qdrant server URL.
    JWT_SECRET_KEY         - Secret for JWT signing (auto-generated if not set).
    TOKENIZERS_PARALLELISM - HuggingFace tokenizer parallelism (default: false).
"""

import os
import sys
import logging

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)

logging.getLogger("drain3.template_miner").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logging.getLogger(__name__).info(f"API Logging configured: level={LOG_LEVEL}")

from api.app import create_api_app

app = create_api_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("APP_PORT", 40901)))

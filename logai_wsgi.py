"""
Production WSGI entry point for Gunicorn.

Usage (Docker):
    gunicorn -w 8 -b 0.0.0.0:40901 --timeout 360 --preload logai_wsgi:server

Environment variables (set via .env):
    LOG_LEVEL              - Python log level (default: INFO).
    QDRANT_URL             - Qdrant server URL.
    TOKENIZERS_PARALLELISM - HuggingFace tokenizer parallelism (default: false).
"""

import os
import sys
import logging

# Safety net: if TOKENIZERS_PARALLELISM is not set by .env, default to false
# to suppress HuggingFace fork warnings in Gunicorn workers.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Configure root logger BEFORE any application imports so all
# logai/gui modules that use logging.getLogger(__name__) inherit
# the handler and formatter.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,       # Gunicorn captures stdout → docker logs
    force=True,              # Override any prior basicConfig from --preload
)

# Suppress noisy third-party loggers
logging.getLogger("drain3.template_miner").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logging.getLogger(__name__).info(f"Logging configured: level={LOG_LEVEL}")

from gui.application import app
server = app.server

if __name__ == "__main__":
    app.run(debug=True)
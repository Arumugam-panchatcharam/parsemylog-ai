#!/usr/bin/env python3
"""
Local development server runner.

Starts the Flask REST API in debug mode with hot-reload.
Run from the project root:

    python run_dev.py

Prerequisites:
    - Qdrant must be running: docker compose up qdrant -d
    - Python venv activated with requirements installed
    - QDRANT_URL defaults to http://localhost:6333
    - Frontend dev server: cd frontend && npm run dev

Environment variables (optional):
    QDRANT_URL              - Qdrant server URL (default: http://localhost:6333)
    APP_PORT                - API port (default: 40901)
    CPE_OVERVIEW_ENABLED    - Cross-CPE pattern scan (default: 1; set 0 to disable)
"""

import os
import sys
import logging

# Ensure the project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Default to localhost Qdrant for local development
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
# Match docker-compose: cross-CPE overview enabled unless explicitly turned off
os.environ.setdefault("CPE_OVERVIEW_ENABLED", "1")

# Suppress HuggingFace tokenizers fork warning
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Suppress verbose loggers
logging.getLogger("drain3.template_miner").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from api.app import create_api_app

if __name__ == "__main__":
    app = create_api_app()
    port = int(os.environ.get("APP_PORT", 40901))
    print(f"Starting LogAI API dev server on http://localhost:{port}")
    print(f"Qdrant URL: {os.environ.get('QDRANT_URL')}")
    app.run(debug=True, host="0.0.0.0", port=port)

#!/usr/bin/env python3
"""
API development server runner.

Starts the Flask REST API in debug mode.
Run from the project root:

    python run_api.py

Prerequisites:
    - Qdrant must be running: docker compose up qdrant -d
    - Python venv activated with requirements installed
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
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("drain3.template_miner").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from api.app import create_api_app

if __name__ == "__main__":
    app = create_api_app()
    port = int(os.environ.get("API_PORT", 40901))
    print(f"Starting LogAI API server on http://localhost:{port}")
    print(f"Qdrant URL: {os.environ.get('QDRANT_URL')}")
    app.run(debug=True, host="0.0.0.0", port=port)

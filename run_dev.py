#!/usr/bin/env python3
"""
Local development server runner.

Starts the Dash app in debug mode with hot-reload.
Run from the project root:

    python run_dev.py

Prerequisites:
    - Qdrant must be running: docker compose up qdrant -d
    - Python venv activated with requirements installed
    - QDRANT_URL defaults to http://localhost:6333

Environment variables (optional):
    QDRANT_URL   - Qdrant server URL (default: http://localhost:6333)
    APP_PORT     - App port (default: 40901)
"""

import os
import sys
import logging

# Ensure the project root is on sys.path (fixes "No module named 'gui'" error)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Default to localhost Qdrant for local development
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

# Suppress HuggingFace tokenizers fork warning (safe -- we don't rely on
# tokenizer parallelism inside Dash/Gunicorn workers)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Configure logging for all logai/gui modules
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Suppress verbose drain3 state-saving logs (floods the console with
# "Saving state of N clusters..." on every new cluster)
logging.getLogger("drain3.template_miner").setLevel(logging.WARNING)

# Suppress httpx INFO logs (Qdrant HTTP request/response lines)
logging.getLogger("httpx").setLevel(logging.WARNING)

from gui.application import app

if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", 40901))
    print(f"Starting LogAI dev server on http://localhost:{port}")
    print(f"Qdrant URL: {os.environ.get('QDRANT_URL')}")
    app.run(debug=True, host="0.0.0.0", port=port)

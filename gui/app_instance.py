"""
Application Instance Module
============================

Creates and configures the Flask/Dash application, initializes the database,
and loads the BGE embedding model (BAAI/bge-small-en-v1.5) for semantic search.

The embedding model is loaded once at startup and shared across all requests.
Model loading priority:
1. Local cached path (bge-small-en-v1.5-local/)
2. Downloads from HuggingFace if not cached (~114s first time)

Exports:
    dbm: DBManager instance for database operations.
    EMBEDDING_MODEL: SentenceTransformer instance (loaded at startup).
    create_app(): Factory function that returns (app, flask_server).
"""

import os
import logging

# Suppress HuggingFace tokenizers fork warning early, before any import
# that triggers tokenizer initialization.  Safe because we don't rely on
# tokenizer-internal parallelism inside Dash/Gunicorn workers.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Suppress verbose drain3 state-saving logs ("Saving state of N clusters...")
logging.getLogger("drain3.template_miner").setLevel(logging.WARNING)

# Suppress httpx INFO logs (Qdrant HTTP request/response lines)
logging.getLogger("httpx").setLevel(logging.WARNING)

from dash import Dash
import dash_bootstrap_components as dbc
from flask import Flask
import secrets
from pathlib import Path
from gui.user_db_mngr import DBManager
from sentence_transformers import SentenceTransformer

dbm = DBManager()

from logai.utils.constants import (
    BASE_DIR,
    UPLOAD_DIRECTORY,
    SENTENCE_TRANSFORMER_MODE_NAME,
)

EMBEDDING_MODEL = None


def create_app():
    """
    Create and configure the Flask/Dash application.

    This function:
    1. Initializes Flask server with SQLAlchemy.
    2. Sets up the database schema (users, projects, files).
    3. Downloads and caches the BGE embedding model.
    4. Creates the Dash app with Bootstrap styling.

    Returns:
        Tuple of (Dash app, Flask server).
    """
    # Initialize Flask server and Dash app
    flask_server = Flask(__name__, static_folder=UPLOAD_DIRECTORY)
    flask_server.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'logai_users.db')}"
    flask_server.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    SECRET_KEY = secrets.token_hex(16)
    flask_server.secret_key = SECRET_KEY

    # Database setup
    dbm.init_app(flask_server)
    dbm.create_tables(flask_server)

    # Load BGE embedding model (BAAI/bge-small-en-v1.5, 384-dim).
    # If a local cache exists, try loading it first.  If the cache is
    # corrupt (e.g. leftover from a different model), delete it and
    # re-download from HuggingFace.
    import shutil
    model_path = os.path.join(BASE_DIR, SENTENCE_TRANSFORMER_MODE_NAME)
    global EMBEDDING_MODEL

    def _try_load_local(path: str):
        """Attempt to load model from local cache; returns model or None."""
        try:
            return SentenceTransformer(path)
        except Exception as exc:
            print(f"Failed to load model from {path}: {exc}")
            return None

    if os.path.exists(model_path):
        EMBEDDING_MODEL = _try_load_local(model_path)
        if EMBEDDING_MODEL is None:
            # Local cache is corrupted -- remove and re-download
            print(f"Removing corrupted model cache at {model_path}")
            shutil.rmtree(model_path, ignore_errors=True)

    if EMBEDDING_MODEL is None:
        print("Downloading BGE embedding model (BAAI/bge-small-en-v1.5)...")
        EMBEDDING_MODEL = SentenceTransformer('BAAI/bge-small-en-v1.5')
        EMBEDDING_MODEL.save(model_path)

    print(f"Loaded SentenceTransformer model from {model_path}")

    app = Dash(
        __name__,
        use_pages=True,
        suppress_callback_exceptions=True,
        external_stylesheets=[
            dbc.themes.BOOTSTRAP,
            "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"
        ],
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
        title="LogAI",
        server=flask_server,
    )

    return app, flask_server

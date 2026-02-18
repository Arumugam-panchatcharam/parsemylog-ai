"""
Flask REST API Application Factory
====================================

Creates the Flask application with JWT auth, CORS, SQLAlchemy,
and registers all API route blueprints.

The existing gui/user_db_mngr.py DBManager is reused as-is.
The embedding model is lazy-loaded on first AI search request.
"""

import os
import sys
import hashlib
import logging
from datetime import timedelta

# Suppress HuggingFace tokenizers fork warning
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Suppress verbose drain3 / httpx logs
logging.getLogger("drain3.template_miner").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from logai.utils.constants import BASE_DIR, UPLOAD_DIRECTORY

# Reuse the existing DBManager (shared SQLAlchemy instance)
from api.user_db_mngr import DBManager

# Global singletons
dbm = DBManager()
jwt = JWTManager()

# Lazy-loaded embedding model (loaded on first AI search)
_embedding_model = None
_embedding_lock = None


def get_embedding_model():
    """
    Lazy-load the SentenceTransformer embedding model.

    Thread-safe: uses a lock to prevent multiple threads from
    loading the model simultaneously.

    Returns:
        SentenceTransformer model instance.
    """
    global _embedding_model, _embedding_lock
    import threading

    if _embedding_lock is None:
        _embedding_lock = threading.Lock()

    if _embedding_model is not None:
        return _embedding_model

    with _embedding_lock:
        # Double-check after acquiring lock
        if _embedding_model is not None:
            return _embedding_model

        from sentence_transformers import SentenceTransformer
        from logai.utils.constants import SENTENCE_TRANSFORMER_MODE_NAME

        model_path = os.path.join(BASE_DIR, SENTENCE_TRANSFORMER_MODE_NAME)

        if os.path.exists(model_path):
            try:
                _embedding_model = SentenceTransformer(model_path)
                logging.info(f"Loaded embedding model from {model_path}")
                return _embedding_model
            except Exception as exc:
                logging.warning(f"Failed to load model from {model_path}: {exc}")
                import shutil
                shutil.rmtree(model_path, ignore_errors=True)

        logging.info("Downloading BGE embedding model (BAAI/bge-small-en-v1.5)...")
        _embedding_model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        _embedding_model.save(model_path)
        logging.info(f"Saved embedding model to {model_path}")
        return _embedding_model


def create_api_app():
    """
    Create and configure the Flask REST API application.

    Returns:
        Configured Flask app instance.
    """
    app = Flask(__name__, static_folder=UPLOAD_DIRECTORY)

    # Configuration
    db_path = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "logai_users.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # JWT secret: Use env var if set, otherwise derive a stable key from the DB
    # path so the secret survives debug-mode reloader restarts.
    jwt_secret = os.environ.get("JWT_SECRET_KEY")
    if not jwt_secret:
        jwt_secret = hashlib.sha256(f"logai-jwt-{db_path}".encode()).hexdigest()
    app.config["JWT_SECRET_KEY"] = jwt_secret
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(
        seconds=int(os.environ.get("JWT_ACCESS_EXPIRES", 3600))
    )
    app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(
        seconds=int(os.environ.get("JWT_REFRESH_EXPIRES", 86400 * 30))
    )
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB max upload
    app.config["LLM_URL"] = os.environ.get("LLM_URL", "http://localhost:8000/v1")

    app.secret_key = hashlib.sha256(f"logai-flask-{db_path}".encode()).hexdigest()

    # Initialize extensions
    dbm.init_app(app)
    dbm.create_tables(app)
    jwt.init_app(app)

    # CORS: allow React dev server
    CORS(app, resources={
        r"/api/*": {
            "origins": [
                "http://localhost:5173",   # Vite dev server
                "http://localhost:3000",
                "http://localhost:8091",   # Nginx
                os.environ.get("FRONTEND_URL", "http://localhost:5173"),
            ],
            "supports_credentials": True,
        }
    })

    # Register blueprints
    from api.routes.auth import auth_bp
    from api.routes.projects import projects_bp
    from api.routes.files import files_bp
    from api.routes.patterns import patterns_bp
    from api.routes.telemetry import telemetry_bp
    from api.routes.ai_analysis import ai_bp
    from api.routes.embedding import embedding_bp
    from api.routes.admin import admin_bp
    from api.routes.regex_analyzer import regex_analyzer_bp
    from api.routes.cpe_overview import cpe_overview_bp
    from api.routes.natco_admin import natco_admin_bp
    from api.routes.natco import natco_bp
    from api.routes.chat import chat_bp
    from api.routes.pcap import pcap_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(projects_bp, url_prefix="/api/projects")
    app.register_blueprint(files_bp, url_prefix="/api/projects")
    app.register_blueprint(patterns_bp, url_prefix="/api/projects")
    app.register_blueprint(telemetry_bp, url_prefix="/api/projects")
    app.register_blueprint(ai_bp, url_prefix="/api/projects")
    app.register_blueprint(embedding_bp, url_prefix="/api/projects")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(regex_analyzer_bp, url_prefix="/api/projects")
    app.register_blueprint(cpe_overview_bp, url_prefix="/api/projects")
    app.register_blueprint(natco_admin_bp, url_prefix="/api/admin")
    app.register_blueprint(natco_bp, url_prefix="/api/natcos")
    app.register_blueprint(chat_bp, url_prefix="/api/projects")
    app.register_blueprint(pcap_bp, url_prefix="/api/pcap")

    # Health check
    @app.route("/api/health")
    def health():
        return {"status": "ok"}

    return app

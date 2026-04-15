"""
Flask REST API Application Factory
====================================

Creates the Flask application with JWT auth, CORS, SQLAlchemy,
and registers all API route blueprints.

The existing gui/user_db_mngr.py DBManager is reused as-is.
The embedding model is lazy-loaded on first AI search request.
"""

import gzip
import os
import sys
import hashlib
import logging
from datetime import timedelta

from flask import Response, request

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

        # Force CPU device to prevent MPS crashes in forked processes (Celery workers on macOS)
        device = "cpu"
        logging.info(f"Loading embedding model with device={device}")

        if os.path.exists(model_path):
            try:
                _embedding_model = SentenceTransformer(model_path, device=device)
                logging.info(f"Loaded embedding model from {model_path}")
                return _embedding_model
            except Exception as exc:
                logging.warning(f"Failed to load model from {model_path}: {exc}")
                import shutil
                shutil.rmtree(model_path, ignore_errors=True)

        logging.info("Downloading BGE embedding model (BAAI/bge-small-en-v1.5)...")
        _embedding_model = SentenceTransformer("BAAI/bge-small-en-v1.5", device=device)
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

    # Minified JSON for all jsonify() responses (smaller payloads; pairs with gzip below).
    app.json.compact = True
    app.json.ensure_ascii = False

    # Compress JSON when client sends Accept-Encoding: gzip (browsers do by default).
    # Low default threshold so medium syslog/overview responses still compress.
    _gzip_min = int(os.environ.get("GZIP_JSON_MIN_BYTES", "256"))
    _gzip_level = int(os.environ.get("GZIP_COMPRESS_LEVEL", "6"))

    @app.after_request
    def _maybe_gzip_json_response(response: Response) -> Response:
        if getattr(response, "direct_passthrough", False):
            return response
        if not (200 <= response.status_code < 300):
            return response
        content_type = response.content_type or ""
        if "application/json" not in content_type:
            return response
        accept = (request.headers.get("Accept-Encoding") or "").lower()
        if "gzip" not in accept:
            return response
        try:
            data = response.get_data()
        except RuntimeError:
            return response
        if not data or len(data) < _gzip_min:
            return response
        try:
            compressed = gzip.compress(data, compresslevel=_gzip_level)
        except OSError as exc:
            logging.getLogger(__name__).warning("gzip response skipped: %s", exc)
            return response
        if len(compressed) >= len(data):
            return response
        out = Response(compressed, status=response.status_code)
        out.headers["Content-Type"] = response.content_type
        out.headers["Content-Encoding"] = "gzip"
        out.headers["Content-Length"] = str(len(compressed))
        vary = response.headers.get("Vary")
        out.headers["Vary"] = f"{vary}, Accept-Encoding" if vary else "Accept-Encoding"
        for key, value in response.headers:
            lk = key.lower()
            if lk in ("content-type", "content-length", "content-encoding", "vary"):
                continue
            out.headers.add(key, value)
        return out

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
    from api.routes.syslog import syslog_bp
    from api.routes.selfheal import selfheal_bp
    from api.routes.ai_analysis import ai_bp
    from api.routes.embedding import embedding_bp
    from api.routes.admin import admin_bp
    from api.routes.regex_analyzer import regex_analyzer_bp
    from api.routes.cpe_overview import cpe_overview_bp
    from api.routes.natco_admin import natco_admin_bp
    from api.routes.natco import natco_bp
    from api.routes.chat import chat_bp
    from api.routes.pcap import pcap_bp
    from api.routes.telemetry_csv import telemetry_csv_bp
    from api.routes.batch_jobs import batch_jobs_bp
    from api.routes.knowledge_graph import knowledge_graph_bp
    from api.routes.issue_analysis import issue_analysis_bp
    from api.routes.ml_anomaly import ml_anomaly_bp
    from api.routes.ml_feedback import ml_feedback_bp
    from api.routes.utilities import utilities_bp
    from api.routes.version import version_bp
    from api.routes.analytics import analytics_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(projects_bp, url_prefix="/api/projects")
    app.register_blueprint(files_bp, url_prefix="/api/projects")
    app.register_blueprint(patterns_bp, url_prefix="/api/projects")
    app.register_blueprint(telemetry_bp, url_prefix="/api/projects")
    app.register_blueprint(syslog_bp, url_prefix="/api/projects")
    app.register_blueprint(selfheal_bp, url_prefix="/api/projects")
    app.register_blueprint(ai_bp, url_prefix="/api/projects")
    app.register_blueprint(embedding_bp, url_prefix="/api/projects")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(regex_analyzer_bp, url_prefix="/api/projects")
    app.register_blueprint(cpe_overview_bp, url_prefix="/api/projects")
    app.register_blueprint(natco_admin_bp, url_prefix="/api/admin")
    app.register_blueprint(natco_bp, url_prefix="/api/natcos")
    app.register_blueprint(chat_bp, url_prefix="/api/projects")
    app.register_blueprint(pcap_bp, url_prefix="/api/pcap")
    app.register_blueprint(telemetry_csv_bp, url_prefix="/api/telemetry-csv")
    app.register_blueprint(batch_jobs_bp, url_prefix="/api/projects")
    app.register_blueprint(knowledge_graph_bp, url_prefix="/api/knowledge-graphs")
    app.register_blueprint(issue_analysis_bp, url_prefix="/api/projects")
    app.register_blueprint(ml_anomaly_bp, url_prefix="/api/projects")
    app.register_blueprint(ml_feedback_bp, url_prefix="/api/projects")
    app.register_blueprint(utilities_bp, url_prefix="/api/utilities")
    app.register_blueprint(version_bp, url_prefix="/api")
    app.register_blueprint(analytics_bp, url_prefix="/api")
    
    # Create feedback tables
    with app.app_context():
        try:
            from logai.ml.feedback import create_feedback_tables
            create_feedback_tables()
            import logging
            logging.getLogger(__name__).info("[App] Feedback tables created/verified")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[App] Could not create feedback tables: {e}")
    
    # Health check
    @app.route("/api/health")
    def health():
        return {"status": "ok"}

    return app

"""
Version Information Blueprint
==============================

Provides version information about the application.
"""

import os
from flask import Blueprint, jsonify
from datetime import datetime

version_bp = Blueprint("version", __name__)


def get_version():
    """
    Read version from VERSION file at project root.
    
    Returns:
        str: Version string (e.g., "1.0.0")
    """
    version_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "VERSION")
    try:
        with open(version_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "0.0.0"


@version_bp.route("/version", methods=["GET"])
def get_version_info():
    """
    Get version information about the application.
    
    Returns:
        JSON response with version details.
    """
    return jsonify({
        "version": get_version(),
        "name": "ParseMyLog-AI",
        "description": "A modern web application for comprehensive log analysis with semantic search powered by a rg+Drain3 RAG pipeline and Qdrant vector database.",
        "repository": "https://github.com/your-org/parsemylog-ai",
        "license": "MIT",
        "buildDate": datetime.now().strftime("%Y-%m-%d"),
        "techStack": {
            "backend": [
                "Flask 3.1",
                "Gunicorn",
                "Celery 5.4",
                "Flask-JWT-Extended",
                "SQLAlchemy 2.0",
            ],
            "machineLearning": [
                "SentenceTransformers (BGE-small-en-v1.5)",
                "Drain3",
                "scikit-learn",
                "PyTorch 2.8",
            ],
            "dataStores": [
                "Qdrant (vectors)",
                "SQLite/PostgreSQL",
                "Redis 7",
                "PyArrow (Parquet)",
            ],
        },
        "features": [
            "🔍 Semantic Search with BGE embeddings",
            "📊 Telemetry Visualization with interactive charts",
            "🤖 ML Anomaly Detection",
            "🌐 Multi-CPE Support",
            "🔐 Pattern Governance (NATCO)",
            "💬 AI Chat Assistant",
            "📦 Batch Processing",
            "🔎 rg+Drain3 Pipeline",
            "📈 Knowledge Graph",
            "🔧 PCAP Analysis",
        ],
    })

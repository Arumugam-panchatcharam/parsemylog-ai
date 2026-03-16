/**
 * Application version information
 * This file is used to display version info in the About dialog
 */

export const APP_VERSION = "1.0.0";
export const APP_NAME = "ParseMyLog-AI";
export const APP_DESCRIPTION = "A modern web application for comprehensive log analysis with semantic search powered by a rg+Drain3 RAG pipeline and Qdrant vector database.";

export const PROJECT_INFO = {
  version: APP_VERSION,
  name: APP_NAME,
  description: APP_DESCRIPTION,
  repository: "https://github.com/your-org/parsemylog-ai",
  license: "MIT",
  buildDate: new Date().toISOString().split('T')[0],
};

export const TECH_STACK = {
  frontend: [
    "React 19",
    "TypeScript",
    "Vite",
    "Material UI v7",
    "Tailwind CSS v4",
    "Plotly.js",
    "TanStack Query",
    "React Router v7",
  ],
  backend: [
    "Flask 3.1",
    "Gunicorn",
    "Celery 5.4",
    "Flask-JWT-Extended",
    "SQLAlchemy 2.0",
  ],
  machineLearning: [
    "SentenceTransformers (BGE-small-en-v1.5)",
    "Drain3",
    "scikit-learn",
    "PyTorch 2.8",
  ],
  dataStores: [
    "Qdrant (vectors)",
    "SQLite/PostgreSQL",
    "Redis 7",
    "PyArrow (Parquet)",
  ],
};

export const FEATURES = [
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
];

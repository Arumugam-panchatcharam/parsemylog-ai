# ParseMyLog-AI

A modern web application for comprehensive log analysis with semantic search powered by a **rg+Drain3 RAG pipeline** and **Qdrant vector database**. Features a **React 19** frontend with Material UI, a **Flask REST API** backend, multi-CPE support, machine learning anomaly detection, and a NATCO-based pattern governance system.

**[📚 Full Documentation](./docs/)** | **[🚀 Quick Start](./docs/QUICK_START.md)** | **[🏗️ Architecture](./docs/ARCHITECTURE.md)** | **[✨ Features](./docs/FEATURES.md)**

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Tech Stack](#tech-stack)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

ParseMyLog-AI is an enterprise-grade log analysis platform designed for networking equipment, IoT devices, and embedded systems. It combines traditional log parsing (Drain3), semantic search (BGE embeddings + Qdrant), and machine learning anomaly detection to provide actionable insights from complex log data.

**Key Capabilities:**

- 🔍 **Semantic Search:** Find issues by meaning, not just keywords
- 📊 **Telemetry Visualization:** Interactive charts for periodic reports
- 🤖 **ML Anomaly Detection:** Unsupervised detection of unusual patterns
- 🌐 **Multi-CPE Support:** Analyze fleets of devices simultaneously
- 🔐 **Pattern Governance:** Centralized pattern management with NATCO system
- 💬 **AI Chat Assistant:** Query logs with natural language
- 📦 **Batch Processing:** Process hundreds of CPEs asynchronously

---

## Key Features

### 🔍 Core Analysis

- **[File Upload & Extraction](./docs/features/FILE_UPLOAD.md)** -- Drag-and-drop log tarballs with automatic MAC/serial detection and chronological merging
- **[rg+Drain3 Pipeline](./docs/features/DRAIN3_PATTERNS.md)** -- Two-stage indexing: ripgrep pre-filtering (6-10x speedup) + Drain3 template extraction
- **[Semantic Search](./docs/features/SEMANTIC_SEARCH.md)** -- BGE embeddings (384-dim) + Qdrant vector search for finding issues by meaning
- **[Telemetry Dashboard](./docs/features/TELEMETRY.md)** -- YAML-driven TR-181 parsing with interactive Plotly charts and trend analysis
- **[Log Viewer](./docs/features/LOG_VIEWER.md)** -- IDE-style viewer with syntax highlighting, regex search, and quick-pattern filters
- **[Pattern Analysis](./docs/features/DRAIN3_PATTERNS.md)** -- Frequency analysis, parameter extraction, and per-domain filtering

### 🌐 Multi-CPE Support

- **[CPE Auto-Detection](./docs/features/MULTI_CPE.md)** -- Automatic identification via MAC/serial in filenames with isolated processing
- **[CPE Overview Dashboard](./docs/features/CPE_OVERVIEW.md)** -- Cross-device comparison with aggregated metrics and visualizations
- **Per-CPE Isolation** -- Independent Drain3 states, Qdrant collections, and analysis contexts

### 🔐 Pattern Governance (NATCO)

- **[Global Pattern Library](./docs/features/NATCO_GOVERNANCE.md)** -- Admin-managed per-country pattern sets for different deployments
- **[Sync & Override](./docs/features/NATCO_GOVERNANCE.md#sync-workflow)** -- Users pull global patterns and customize locally
- **[Submission Workflow](./docs/features/NATCO_GOVERNANCE.md#submission-workflow)** -- Diff-based change submissions with admin review
- **[Import/Export](./docs/features/PATTERN_IMPORT_EXPORT.md)** -- Multiple format support (JSON, YAML, rule_parser_config.json)

### 🤖 Advanced Analytics

- **[ML Anomaly Detection](./docs/features/ML_ANOMALY.md)** -- Isolation Forest for log patterns, time-series analysis for telemetry
- **[Knowledge Graph](./docs/features/KNOWLEDGE_GRAPH.md)** -- Visual event relationship mapping and root cause analysis
- **[Batch Processing](./docs/features/BATCH_PROCESSING.md)** -- Celery-based async processing for fleet-scale analysis
- **[AI Chat Assistant](./docs/features/AI_CHAT.md)** -- LLM-powered natural language querying of logs
- **[PCAP Analysis](./docs/features/PCAP_ANALYSIS.md)** -- Network packet correlation with log events

### 👥 Multi-User & Admin

- **[JWT Authentication](./docs/ARCHITECTURE.md#security-architecture)** -- Stateless tokens with automatic refresh and per-project isolation
- **[User Management](./docs/features/USER_MANAGEMENT.md)** -- Admin dashboard for user CRUD, project oversight, and access control
- **[NATCO Administration](./docs/features/NATCO_ADMIN.md)** -- Pattern library management and submission review system

📖 **[View All Features →](./docs/FEATURES.md)**

## Architecture

ParseMyLog-AI uses a microservices architecture with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────┐
│                     Client Browser                      │
└──────────────────────┬──────────────────────────────────┘
                       │
                ┌──────▼───────┐
                │ Nginx :40901 │  (Static SPA + /api proxy)
                └──┬────────┬──┘
                   │        │
        ┌──────────▼──┐  ┌──▼─────────────┐
        │  React SPA  │  │ Flask API :5000│ (4 Gunicorn workers)
        │  (Vite)     │  │  + Celery      │
        └─────────────┘  └─┬───────┬──────┘
                           │       │
              ┌────────────┼───────┼────────────┐
              │            │       │            │
        ┌─────▼────┐  ┌────▼───┐  ┌▼──────┐  ┌──▼─────┐
        │ SQLite   │  │ Qdrant │  │ Redis │  │ Files  │
        │ (Users,  │  │ (BGE   │  │ (Msg  │  │ (Logs, │
        │ Projects)│  │ 384d)  │  │ Queue)│  │ Cache) │
        └──────────┘  └────────┘  └───────┘  └────────┘
```

**Key Components:**

- **Frontend:** React 19 + TypeScript + Material UI + Plotly.js
- **Backend:** Flask 3.1 + Gunicorn (4 workers) + Celery
- **Vector DB:** Qdrant with BGE-small-en-v1.5 embeddings (384-dim)
- **Queue:** Redis for async task processing
- **Database:** SQLite (easily replaceable with PostgreSQL)

📖 **[Detailed Architecture Guide →](./docs/ARCHITECTURE.md)**

## Tech Stack


| Layer                | Technologies                                                                                                   |
| -------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Frontend**         | React 19 • TypeScript • Vite • Material UI v7 • Tailwind CSS v4 • Plotly.js • TanStack Query • React Router v7 |
| **Backend**          | Flask 3.1 • Gunicorn • Celery 5.4 • Flask-JWT-Extended • Flask-CORS • SQLAlchemy 2.0                           |
| **Machine Learning** | SentenceTransformers (BGE-small-en-v1.5) • Drain3 • scikit-learn • PyTorch 2.8                                 |
| **Data Stores**      | Qdrant (vectors) • SQLite/PostgreSQL • Redis 7 • PyArrow (Parquet)                                             |
| **Log Processing**   | ripgrep • pandas • PyYAML • python-dateutil                                                                    |
| **Infrastructure**   | Docker Compose • Nginx • Linux/macOS/Windows (WSL2)                                                            |
| **Security**         | JWT (HMAC-SHA256) • bcrypt • CORS • SQLAlchemy ORM                                                             |


📊 **Performance:**

- Handles 1M+ log lines in <5 minutes
- Semantic search: <100ms per query
- Supports 100s of projects, 1000s of CPEs
- Optimized for 1-10 concurrent users (horizontally scalable)

## Quick Start

### 🚀 Production Deployment (5 minutes)

**Prerequisites:** Docker 20.10+ and Docker Compose v2+

```bash
# 1. Clone and configure
git clone https://github.com/your-org/parsemylog-ai.git
cd parsemylog-ai
cp .env_example .env

# 2. Build frontend
docker compose --profile build up frontend-build

# 3. Start all services
docker compose up -d --build

# 4. Open browser
open http://localhost:40901
```

**Default credentials:** `admin` / `admin123` (⚠️ change immediately!)

**Services running:**

- `nginx` → React SPA + API proxy (port 40901)
- `logai-api` → Flask REST API (4 Gunicorn workers)
- `qdrant` → Vector database (port 6333)
- `redis` → Message broker (port 6379)
- `celery-worker` → Async task processor

---

### 💻 Local Development Setup

**Prerequisites:** Python 3.11+, Node.js 18+, ripgrep

```bash
# 1. Set up backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Set up frontend
cd frontend && npm install && cd ..

# 3. Start dependencies
docker compose up qdrant redis -d

# 4. Start dev servers (both frontend + backend)
python run_dev.py
```

**Access:** [http://localhost:5173](http://localhost:5173) (Vite dev server with HMR)

---

📖 **[Full Quick Start Guide →](./docs/QUICK_START.md)** (includes troubleshooting, common tasks, and advanced setup)

## Documentation

### 📚 Core Documentation


| Document                                         | Description                                                 |
| ------------------------------------------------ | ----------------------------------------------------------- |
| **[Architecture Guide](./docs/ARCHITECTURE.md)** | System design, data flow, security model, and scalability   |
| **[Features Overview](./docs/FEATURES.md)**      | Comprehensive feature catalog with links to detailed guides |
| **[Quick Start Guide](./docs/QUICK_START.md)**   | Production deployment and local development setup           |
| **[API Reference](./docs/API_REFERENCE.md)**     | REST API endpoints, authentication, and examples            |
| **[User Guide](./docs/USER_GUIDE.md)**           | End-user documentation for all features                     |


### 🎯 Feature Documentation


| Feature                  | Guide                                                      |
| ------------------------ | ---------------------------------------------------------- |
| File Upload & Extraction | [FILE_UPLOAD.md](./docs/features/FILE_UPLOAD.md)           |
| Log Viewer               | [LOG_VIEWER.md](./docs/features/LOG_VIEWER.md)             |
| Drain3 Pattern Analysis  | [DRAIN3_PATTERNS.md](./docs/features/DRAIN3_PATTERNS.md)   |
| Semantic Search          | [SEMANTIC_SEARCH.md](./docs/features/SEMANTIC_SEARCH.md)   |
| Telemetry Dashboard      | [TELEMETRY.md](./docs/features/TELEMETRY.md)               |
| Pattern Analyzer         | [PATTERN_ANALYZER.md](./docs/features/PATTERN_ANALYZER.md) |
| Multi-CPE Support        | [MULTI_CPE.md](./docs/features/MULTI_CPE.md)               |
| CPE Overview             | [CPE_OVERVIEW.md](./docs/features/CPE_OVERVIEW.md)         |
| NATCO Governance         | [NATCO_GOVERNANCE.md](./docs/features/NATCO_GOVERNANCE.md) |
| ML Anomaly Detection     | [ML_ANOMALY.md](./docs/features/ML_ANOMALY.md)             |
| Knowledge Graph          | [KNOWLEDGE_GRAPH.md](./docs/features/KNOWLEDGE_GRAPH.md)   |
| Batch Processing         | [BATCH_PROCESSING.md](./docs/features/BATCH_PROCESSING.md) |
| AI Chat Assistant        | [AI_CHAT.md](./docs/features/AI_CHAT.md)                   |


### 🔧 Operations


| Document                                                     | Description                                        |
| ------------------------------------------------------------ | -------------------------------------------------- |
| **[Deployment Guide](./docs/DEPLOYMENT.md)**                 | Production deployment, monitoring, and maintenance |
| **[Environment Variables](./docs/ENVIRONMENT_VARIABLES.md)** | Complete configuration reference                   |
| **[Troubleshooting](./docs/TROUBLESHOOTING.md)**             | Common issues and solutions                        |
| **[Performance Tuning](./docs/PERFORMANCE.md)**              | Optimization guidelines and benchmarks             |


---

## Contributing

We welcome contributions! Please see our contribution guidelines:

### Development Workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes with clear commit messages
4. Write/update tests for new functionality
5. Run tests: `pytest api/tests/` and `npm test` (in frontend/)
6. Submit a pull request

### Code Style

**Backend (Python):**

- Follow PEP 8 style guide
- Use `black` for formatting: `black api/ logai/`
- Use `flake8` for linting: `flake8 api/ logai/`
- Add type hints where appropriate

**Frontend (TypeScript):**

- Follow TypeScript best practices
- Use ESLint: `npm run lint`
- Component naming: PascalCase
- File naming: PascalCase for components, camelCase for utilities

### Documentation

- Update relevant documentation for new features
- Add JSDoc/docstrings for public APIs
- Include examples in feature documentation

### Testing

- **Backend:** Unit tests in `api/tests/`, integration tests in `api/tests/integration/`
- **Frontend:** Jest for unit tests, Playwright for E2E
- Aim for >80% code coverage on new code

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

Built with:

- [Drain3](https://github.com/logpai/Drain3) - Log template mining
- [Qdrant](https://qdrant.tech/) - Vector database
- [BGE Embeddings](https://huggingface.co/BAAI/bge-small-en-v1.5) - Semantic embeddings
- [ripgrep](https://github.com/BurntSushi/ripgrep) - Fast text search
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [React](https://react.dev/) - UI library
- [Material UI](https://mui.com/) - Component library
- [Plotly](https://plotly.com/) - Data visualization

Special thanks to the open-source community!
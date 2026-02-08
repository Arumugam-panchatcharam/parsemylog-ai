# ParseMyLog-AI

A modern web application for log analysis with semantic search powered by a **rg+Drain3 RAG pipeline** and **Qdrant vector database**. Features a **React** frontend with Material Design and a **Flask REST API** backend.

## Features

- **File Upload & Extraction** -- Drag-and-drop log tarballs (.tgz/.tar.gz); automatic extraction and chronological merging.
- **rg+Drain3 Pipeline** -- Two-stage log indexing: ripgrep pre-filters error-class lines (6-10x speedup), then Drain3 extracts templates per domain.
- **Semantic Search** -- BGE embeddings (BAAI/bge-small-en-v1.5) stored in Qdrant for cosine similarity search across log patterns.
- **Telemetry Dashboard** -- YAML-driven parsing of T2 periodic reports with key metric trends, interactive Plotly charts, radio/SSID status cards, and device info.
- **Log Viewer** -- IDE-style paginated viewer with syntax highlighting (timestamps, IPs, MACs, modules, keywords), regex search, and quick-pattern buttons.
- **Pattern Analysis** -- Drain3 template extraction with frequency analysis, per-domain file filtering, and on-demand parameter extraction.
- **AI Analysis** -- Semantic search with matching loglines, dynamic parameter extraction, and log context window.
- **Multi-User Support** -- JWT authentication, per-project isolation, thread-safe indexing with per-project locks.

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │          Nginx (port 8091)           │
                    │    React SPA  ←→  /api proxy        │
                    └──────┬─────────────────┬────────────┘
                           │                 │
                  Static files         API requests
                           │                 │
                ┌──────────▼──┐    ┌─────────▼──────────┐
                │  React SPA  │    │  Flask REST API     │
                │  (Vite)     │    │  (Gunicorn)         │
                │  Port: 80   │    │  Port: 40901        │
                └─────────────┘    └─────────┬──────────┘
                                             │
                              ┌──────────────┼──────────────┐
                              │              │              │
                    ┌─────────▼──┐  ┌────────▼───┐  ┌──────▼──────┐
                    │  SQLite    │  │  Qdrant    │  │  File Store │
                    │  (Users/   │  │  (Vectors) │  │  (Uploads)  │
                    │  Projects) │  │  Port 6333 │  │             │
                    └────────────┘  └────────────┘  └─────────────┘
```

### Pipeline

```mermaid
flowchart TD
    Upload["File Upload (.tgz)"] --> Extract["Extract & Merge Logs"]
    Extract --> RgScan["ripgrep Pre-Filter\n(per-domain YAML patterns)"]
    RgScan --> Drain3["Drain3 Template Extraction\n(per-domain state files)"]
    Drain3 --> Parquet["Parquet Cache\n(domain_rg.parquet)"]
    Drain3 --> Embed["BGE Embedding\n(bge-small-en-v1.5)"]
    Embed --> Qdrant["Qdrant Vector Store\n(per-project collections)"]
    Extract --> Telemetry["Telemetry 2.0 Parser\n(YAML-driven)"]
    Telemetry --> Dashboard["Telemetry Dashboard\n(Plotly Charts)"]
    Qdrant --> Search["Semantic Search"]
    Search --> Results["Similar Log Patterns\n+ Context Window"]
    Parquet --> PatternPage["Pattern Analysis\n+ Parameter Extraction"]
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, MUI Icons |
| Charts | Plotly.js (react-plotly.js) |
| State Management | TanStack Query (React Query) |
| Routing | React Router v7 |
| Backend API | Flask + Flask-JWT-Extended |
| Log Parsing | Drain3 (online template mining) |
| Pre-filtering | ripgrep (rg) |
| Embeddings | SentenceTransformers (BAAI/bge-small-en-v1.5, 384-dim) |
| Vector Database | Qdrant |
| Data Processing | pandas, PyArrow (parquet caching) |
| Authentication | JWT (access + refresh tokens) + bcrypt |
| Database | SQLite + SQLAlchemy |
| WSGI Server | Gunicorn |
| Reverse Proxy | Nginx |
| Containerization | Docker Compose |

## Quick Start

### Prerequisites

- **Docker** and **Docker Compose** (v2+)
- **Node.js** 18+ (for local frontend development only)
- OR **Python 3.11+** with **ripgrep** installed (for local backend development)

### Production Deployment (Docker)

```bash
# 1. Clone the repository
git clone <repo-url> && cd parsemylog-ai

# 2. Create environment file
cp .env_example .env
# Edit .env if needed (ports, JWT secret, log level)

# 3. Build and start all services (frontend is built inside Docker automatically)
docker compose up -d --build

# 4. Verify services are running
docker compose ps
```

The application will be available at **http://localhost:8091** (or your configured `NGINX_PORT`).

No local Node.js installation is needed -- the Nginx container builds the React frontend during `docker compose build`.

**Services started:**

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| `logai-api` | logai-api | 40901 | Flask REST API (Gunicorn, 4 workers) |
| `qdrant` | qdrant | 6333 | Qdrant vector database |
| `nginx` | nginx | 8091 | Nginx — builds & serves React SPA + proxies /api |

### Updating the Application

```bash
# Pull latest changes
git pull

# Rebuild and restart services (frontend is rebuilt automatically)
docker compose up -d --build
```

### Stopping Services

```bash
# Stop all services (preserves data volumes)
docker compose down

# Stop and remove data volumes (DESTRUCTIVE — deletes all user data)
docker compose down -v
```

### Local Development

```bash
# 1. Install ripgrep
# macOS: brew install ripgrep
# Ubuntu: apt-get install ripgrep

# 2. Set up Python backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Start Qdrant (required for vector search)
docker compose up qdrant -d

# 4. Start the API backend (with hot-reload)
python run_api.py

# 5. In a separate terminal, start the frontend dev server
cd frontend && npm install && npm run dev
```

The frontend dev server runs at **http://localhost:5173** and proxies `/api` requests to the Flask backend on port 40901.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_PORT` | `40901` | Flask API server port |
| `NGINX_PORT` | `8091` | Nginx reverse proxy port |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant server URL (`http://localhost:6333` for local dev) |
| `QDRANT_PORT` | `6333` | Qdrant host port mapping |
| `LOG_LEVEL` | `INFO` | Python log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `JWT_SECRET_KEY` | auto-generated | JWT signing key (set for persistence across restarts) |
| `JWT_ACCESS_EXPIRES` | `3600` | Access token TTL in seconds (1 hour) |
| `JWT_REFRESH_EXPIRES` | `2592000` | Refresh token TTL in seconds (30 days) |
| `TOKENIZERS_PARALLELISM` | `false` | Suppress HuggingFace tokenizer fork warnings |

A template is provided in `.env_example`:

```bash
cp .env_example .env
```

## Logging

### Production (Docker)

```bash
# View all logs in real-time
docker compose logs -f

# View only API logs
docker compose logs -f logai-api

# View last 100 lines
docker compose logs --tail 100 logai-api
```

To change log level without restarting:

```bash
docker compose run -e LOG_LEVEL=DEBUG logai-api
```

### Log Format

```
HH:MM:SS [module.name] LEVEL: message
```

Example:
```
14:32:10 [logai.indexer] INFO: [RagIndexer] Processing domain=platform
14:32:11 [logai.rg_scanner] INFO: [RgScanner] Domain 'platform' (66 files): 23468 matches in 0.210s
```

## Configuration

### ripgrep Pattern Packs

Domain-specific patterns in `configs/rg_patterns/*.yaml`:

```
configs/rg_patterns/
├── wifi.yaml        # WiFi/wireless log patterns
├── platform.yaml    # System/kernel/boot patterns
├── core_router.yaml # WAN/WebPA/Parodus patterns
├── cellular.yaml    # LTE/5G modem patterns
└── mesh.yaml        # Mesh networking patterns
```

Each YAML file defines:
- **domain**: Domain identifier
- **files**: Glob patterns for log files to scan
- **literals**: Fast literal string matches
- **regex**: Regex patterns

### Telemetry Field Configuration

`configs/telemetry_report_fields.yaml` controls which TR-181 fields are extracted and plotted.

### Drain3 Configuration

`drain3.ini` controls the log template mining behavior:
- **sim_th**: Similarity threshold (default: 0.5)
- **depth**: Parse tree depth (default: 8)
- **max_clusters**: Maximum templates (default: 1024)

## Project Structure

```
parsemylog-ai/
├── frontend/                      # React SPA (Vite + TypeScript)
│   ├── src/
│   │   ├── api/                   # API client (Axios + endpoints)
│   │   ├── hooks/                 # Auth & project context hooks
│   │   ├── lib/                   # Utilities (highlighter, etc.)
│   │   ├── components/layout/     # Sidebar, AppLayout
│   │   └── pages/                 # Page components
│   │       ├── LogViewerPage.tsx  # IDE-style log viewer
│   │       ├── PatternPage.tsx    # Pattern analysis
│   │       ├── TelemetryPage.tsx  # Telemetry dashboard
│   │       ├── AIAnalysisPage.tsx # Semantic search
│   │       ├── DashboardPage.tsx  # Project grid
│   │       └── AdminPage.tsx      # User management
│   ├── package.json
│   └── vite.config.ts
│
├── api/                           # Flask REST API
│   ├── app.py                     # App factory (JWT, CORS, DB)
│   ├── auth.py                    # JWT auth utilities
│   ├── indexer.py                 # Background indexer
│   └── routes/                    # API endpoint blueprints
│       ├── auth.py                # Login, register, refresh
│       ├── projects.py            # CRUD projects
│       ├── files.py               # Upload, content, search, download
│       ├── patterns.py            # Pattern analysis
│       ├── telemetry.py           # Telemetry parsing
│       ├── ai_analysis.py         # Semantic search
│       ├── embedding.py           # Pipeline status
│       └── admin.py               # User management
│
├── logai/                         # Core log analysis library
│   ├── rg_scanner.py              # ripgrep pre-filtering
│   ├── pattern.py                 # Drain3 template extraction
│   ├── indexer.py                 # RAG indexer pipeline
│   ├── embedding.py               # Qdrant + BGE embeddings
│   ├── telemetry_parser.py        # Telemetry 2.0 parser
│   └── utils/constants.py         # App constants
│
├── configs/                       # Configuration files
│   ├── rg_patterns/               # ripgrep domain YAMLs
│   └── telemetry_report_fields.yaml
│
├── nginx/
│   └── default.conf               # Nginx SPA + API proxy config
│
├── docker-compose.yml             # Production services
├── Dockerfile                     # Multi-stage build (Node + Python)
├── drain3.ini                     # Drain3 parser config
├── requirements.txt               # Python dependencies
├── logai_api_wsgi.py              # Production WSGI entry point
├── run_api.py                     # Dev API server
├── .env_example                   # Environment variable template
└── README.md
```

## Data Persistence

Docker Compose uses named volumes for data persistence:

| Volume | Container Path | Description |
|--------|---------------|-------------|
| `user_uploads` | `/app/user_uploads` | Uploaded log files and analysis caches |
| `bge_model` | `/app/bge-small-en-v1.5-local` | BGE embedding model (downloaded on first use) |
| `qdrant_storage` | `/qdrant/storage` | Qdrant vector collections |
| `logai_db` | `/app/data` | SQLite database (users, projects) |

To back up data:

```bash
# Back up the database
docker cp logai-api:/app/data/logai_users.db ./backup_users.db

# Back up uploaded files
docker cp logai-api:/app/user_uploads ./backup_uploads
```

## Multi-User & Multi-Project Safety

- **Per-project locks** -- A `threading.Lock` per project ID prevents concurrent indexing
- **Per-domain Drain3 state** -- Each domain gets its own state file
- **Atomic file writes** -- `os.replace()` for crash-safe writes
- **Per-project Qdrant collections** -- Named `project_{id}` for complete isolation
- **Resume indexing** -- Missing domains are automatically re-indexed
- **JWT authentication** -- Stateless tokens with automatic refresh

## License

See [LICENSE](LICENSE) for details.

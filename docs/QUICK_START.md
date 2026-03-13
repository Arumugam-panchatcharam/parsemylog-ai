# Quick Start Guide for Developers

This guide will help you get ParseMyLog-AI up and running quickly for both production deployment and local development.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Production Deployment (Docker)](#production-deployment-docker)
- [Local Development Setup](#local-development-setup)
- [First-Time Setup](#first-time-setup)
- [Common Development Tasks](#common-development-tasks)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### For Production Deployment

- **Docker** 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- **Docker Compose** v2+ (included with Docker Desktop)
- **Minimum System Requirements:**
  - 4 CPU cores
  - 8GB RAM
  - 50GB disk space (for logs, models, databases)
  - Linux/macOS/Windows (WSL2)

### For Local Development

**Required:**

- **Python 3.11+** ([Download Python](https://www.python.org/downloads/))
- **Node.js 18+** ([Download Node.js](https://nodejs.org/))
- **ripgrep** (for log scanning)
  - macOS: `brew install ripgrep`
  - Ubuntu/Debian: `apt-get install ripgrep`
  - Windows: `choco install ripgrep`
- **Git** (for version control)

**Optional:**

- **Docker** (for running Qdrant, Redis locally)
- **PostgreSQL** (if replacing SQLite)

---

## Production Deployment (Docker)

### 1. Clone the Repository

```bash
# Clone the repo
git clone https://github.com/your-org/parsemylog-ai.git
cd parsemylog-ai

# Check current branch
git branch
```

### 2. Configure Environment

```bash
# Copy the example environment file
cp .env_example .env

# Edit .env with your preferred settings
nano .env  # or vim, code, etc.
```

**Important Environment Variables:**

```bash
# Application
APP_PORT=40901                                  # Nginx exposed port
LOG_LEVEL=INFO                                  # DEBUG, INFO, WARNING, ERROR

# Qdrant Vector Database
QDRANT_URL=http://qdrant:6333
QDRANT_PORT=6333

# Redis (Celery Broker)
REDIS_URL=redis://redis:6379/0
REDIS_PORT=6379

# Database
DB_PATH=/app/data/logai_users.db

# JWT Authentication
JWT_SECRET_KEY=<generate-random-secret>         # IMPORTANT: Set in production
JWT_ACCESS_EXPIRES=3600                         # 1 hour
JWT_REFRESH_EXPIRES=2592000                     # 30 days

# Batch Processing
BATCH_CPE_LOGS_PATH=./batch_cpe_logs           # Host directory for batch jobs

# Optional: LLM Integration
OPENAI_API_KEY=sk-...                          # If using OpenAI for chat
```

**Generate JWT Secret:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. Build the Frontend

The frontend must be built before starting the services.

```bash
# Build React SPA (one-time, or after frontend changes)
docker compose --profile build up frontend-build

# Wait for "Frontend build complete." message
# Container will exit automatically when done
```

**What This Does:**

- Installs npm dependencies in a persistent volume (fast subsequent builds)
- Compiles TypeScript
- Runs Vite build
- Outputs to `frontend_dist` volume (shared with Nginx)

### 4. Start All Services

```bash
# Start all services in background
docker compose up -d --build

# View startup logs
docker compose logs -f
```

**Services Started:**


| Service         | Container     | Port              | Description                          |
| --------------- | ------------- | ----------------- | ------------------------------------ |
| `nginx`         | nginx         | 40901 (host) → 80 | Reverse proxy + static file server   |
| `logai-api`     | logai-api     | 5000 (internal)   | Flask REST API (Gunicorn, 4 workers) |
| `qdrant`        | qdrant        | 6333              | Vector database                      |
| `redis`         | logai-redis   | 6379              | Message broker for Celery            |
| `celery-worker` | celery-worker | N/A               | Async task processor                 |


### 5. Verify Deployment

```bash
# Check service status
docker compose ps

# All services should show "Up" or "Up (healthy)"
# If any service shows "Exit", check logs:
docker compose logs <service-name>

# Test health endpoint
curl http://localhost:40901/api/auth/health
# Expected: {"status": "ok"}
```

### 6. Access the Application

Open your browser and navigate to:

```
http://localhost:40901
```

**Default Admin Credentials:**

- **Username:** `admin`
- **Password:** `admin123`

⚠️ **Security:** Change the admin password immediately after first login!

---

## Local Development Setup

### 1. Clone and Navigate

```bash
git clone https://github.com/your-org/parsemylog-ai.git
cd parsemylog-ai
```

### 2. Set Up Python Backend

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Verify installation
python -c "import flask, qdrant_client, sentence_transformers; print('✅ All imports successful')"
```

### 3. Set Up Frontend

```bash
cd frontend

# Install dependencies
npm install

# Verify installation
npm run lint
```

### 4. Start Required Services (Docker)

Even in local dev, Qdrant and Redis are easiest to run via Docker:

```bash
# From project root
docker compose up qdrant redis -d

# Verify services
docker compose ps qdrant redis
curl http://localhost:6333/health  # Qdrant
docker exec logai-redis redis-cli ping  # Redis
```

**Alternative: Install Qdrant/Redis Locally**

If you prefer not to use Docker:

- **Qdrant:** [Installation Guide](https://qdrant.tech/documentation/quick-start/)
- **Redis:** [Installation Guide](https://redis.io/docs/getting-started/installation/)

Then update `.env`:

```bash
QDRANT_URL=http://localhost:6333
REDIS_URL=redis://localhost:6379/0
```

### 5. Configure Environment for Local Dev

```bash
# From project root
cp .env_example .env
```

Edit `.env`:

```bash
APP_PORT=40901
QDRANT_URL=http://localhost:6333  # Not http://qdrant:6333 (Docker hostname)
REDIS_URL=redis://localhost:6379/0
DB_PATH=./data/logai_users.db     # Local SQLite path
LOG_LEVEL=DEBUG                    # Verbose logging for development
```

Create required directories:

```bash
mkdir -p data user_uploads batch_cpe_logs
```

### 6. Start Development Servers

**Option A: Use run_dev.py (Recommended)**

This starts both backend and frontend in a single terminal:

```bash
# From project root, with venv activated
python run_dev.py
```

**What It Does:**

- Starts Flask API on port 40901 (auto-reload enabled)
- Starts Vite dev server on port 5173 (HMR enabled)
- Frontend proxies `/api` requests to Flask
- Monitors both processes

**Access:**

- **Frontend:** [http://localhost:5173](http://localhost:5173) (use this for development)
- **Backend API:** [http://localhost:40901/api](http://localhost:40901/api) (direct access)

**Option B: Manual Start (Two Terminals)**

Terminal 1 (Backend):

```bash
# From project root, with venv activated
python run_api.py
# Flask API running on http://localhost:40901
```

Terminal 2 (Frontend):

```bash
cd frontend
npm run dev
# Vite dev server on http://localhost:5173
```

### 7. Verify Local Setup

Open browser to [http://localhost:5173](http://localhost:5173) and:

1. Log in with `admin` / `admin123`
2. Create a test project
3. Upload a small log tarball
4. Check terminal logs for indexing progress

---

## First-Time Setup

### 1. Create Admin User (Docker Only)

The admin user is auto-created on first startup. To change the password:

**Via API:**

```bash
# Get access token
TOKEN=$(curl -X POST http://localhost:40901/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | jq -r '.access_token')

# Change password
curl -X PUT http://localhost:40901/api/admin/users/1/password \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"new_password":"YourSecurePassword123!"}'
```

**Via UI:**

1. Log in as admin
2. Navigate to Admin → Users
3. Click on admin user
4. Update password

### 2. Create Your First Project

1. Log in to the application
2. Click **"Create New Project"** on the dashboard
3. Enter project name (e.g., "Test CPE Logs")
4. Optionally assign a NATCO (for pattern governance)
5. Click **Create**

### 3. Upload Sample Logs

**Supported Formats:**

- `.tgz` (gzipped tar archive)
- `.tar.gz` (gzipped tar archive)
- Filenames should contain MAC address or serial number:
  - `logs_mac_AA:BB:CC:DD:EE:FF_2024-03-13.tgz`
  - `cpe_serial_1234567890.tar.gz`

**Upload Steps:**

1. Click on your project
2. Go to **Files** tab
3. Drag and drop a tarball
4. Wait for extraction (progress bar shown)
5. Navigate to **Log Viewer** or **Pattern Analysis**

### 4. Configure Telemetry (Optional)

If your logs include `Telemetry_2.0*.txt` files:

1. Navigate to **Telemetry** page
2. Click **Parse Telemetry**
3. View extracted metrics and charts

### 5. Set Up NATCO (Optional)

For pattern governance:

**As Admin:**

1. Go to **Admin → NATCOs** tab
2. Click **Create NATCO**
3. Enter code (e.g., `EU`), name, description
4. Add global patterns or import from presets
5. Save

**As User:**

1. Edit project settings
2. Assign NATCO
3. Go to **Pattern Analyzer** → **Sync from Global**
4. Patterns are now available for use

---

## Common Development Tasks

### Rebuild Frontend

```bash
# After making frontend changes in Docker deployment
docker compose --profile build up frontend-build --build

# Restart Nginx to serve new build
docker compose restart nginx
```

### Restart Backend (Docker)

```bash
# Restart API after code changes
docker compose restart logai-api

# Restart Celery worker after task code changes
docker compose restart celery-worker
```

### View Logs

```bash
# All services (real-time)
docker compose logs -f

# Specific service
docker compose logs -f logai-api

# Last 100 lines
docker compose logs --tail 100 logai-api

# Search logs
docker compose logs logai-api | grep ERROR
```

### Run Database Migrations

```bash
# If you add new SQLAlchemy models

# In Docker
docker compose exec logai-api python -c "from api.user_db_mngr import init_db; init_db()"

# Local dev
python -c "from api.user_db_mngr import init_db; init_db()"
```

### Reset Database (⚠️ DESTRUCTIVE)

```bash
# Docker
docker compose down -v  # Removes all volumes
docker compose up -d --build

# Local dev
rm data/logai_users.db
python run_api.py  # Will recreate DB with default admin
```

### Clear Qdrant Collections

```bash
# Docker
docker compose exec logai-api python -c "
from qdrant_client import QdrantClient
client = QdrantClient(url='http://qdrant:6333')
collections = client.get_collections().collections
for col in collections:
    client.delete_collection(col.name)
    print(f'Deleted: {col.name}')
"

# Local dev
python -c "
from qdrant_client import QdrantClient
client = QdrantClient(url='http://localhost:6333')
collections = client.get_collections().collections
for col in collections:
    client.delete_collection(col.name)
    print(f'Deleted: {col.name}')
"
```

### Run Backend Tests

```bash
# With venv activated
pytest api/tests/ -v

# With coverage
pytest api/tests/ --cov=api --cov-report=html
open htmlcov/index.html  # View coverage report
```

### Run Frontend Tests

```bash
cd frontend

# Unit tests
npm run test

# E2E tests (requires app running)
npm run test:e2e
```

### Lint and Format Code

```bash
# Backend (with venv activated)
black api/ logai/
flake8 api/ logai/

# Frontend
cd frontend
npm run lint
npm run lint:fix  # Auto-fix issues
```

### Update Dependencies

```bash
# Backend
pip list --outdated
pip install --upgrade <package-name>
pip freeze > requirements.txt

# Frontend
cd frontend
npm outdated
npm update <package-name>
npm install  # Update package-lock.json
```

### Add New API Endpoint

1. Create or edit blueprint in `api/routes/<module>.py`
2. Add route decorator and function
3. Update API client in `frontend/src/api/endpoints.ts`
4. Update frontend page to call new endpoint

**Example:**

```python
# api/routes/example.py
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

example_bp = Blueprint("example", __name__)

@example_bp.route("/<project_id>/example", methods=["GET"])
@jwt_required()
def get_example(project_id):
    user_id = get_jwt_identity()
    # Your logic here
    return jsonify({"data": "example"}), 200
```

```typescript
// frontend/src/api/endpoints.ts
export const exampleApi = {
  getExample: (projectId: string) =>
    api.get(`/api/${projectId}/example`),
};
```

### Add New Frontend Page

1. Create component in `frontend/src/pages/ExamplePage.tsx`
2. Add route in `frontend/src/App.tsx` or routing config
3. Add navigation link in `frontend/src/components/layout/Sidebar.tsx`

**Example:**

```tsx
// frontend/src/pages/ExamplePage.tsx
export const ExamplePage = () => {
  return (
    <div>
      <h1>Example Feature</h1>
      {/* Your content */}
    </div>
  );
};
```

```tsx
// frontend/src/App.tsx
import { ExamplePage } from './pages/ExamplePage';

// In your routes configuration
<Route path="/project/:projectId/example" element={<ExamplePage />} />
```

---

## Troubleshooting

### Issue: "Cannot connect to Docker daemon"

**Solution:**

```bash
# Check if Docker is running
docker info

# Start Docker Desktop (if using macOS/Windows)
# Or start Docker daemon (Linux)
sudo systemctl start docker
```

### Issue: Port 40901 already in use

**Solution:**

```bash
# Find process using the port
lsof -i :40901  # macOS/Linux
netstat -ano | findstr :40901  # Windows

# Kill the process or change APP_PORT in .env
echo "APP_PORT=40902" >> .env
docker compose up -d
```

### Issue: Frontend build fails with "Out of memory"

**Solution:**

```bash
# Increase Node memory limit
docker compose --profile build run --rm \
  -e NODE_OPTIONS="--max-old-space-size=4096" \
  frontend-build
```

### Issue: "ripgrep not found" in local dev

**Solution:**

```bash
# Install ripgrep
# macOS
brew install ripgrep

# Ubuntu/Debian
sudo apt-get install ripgrep

# Windows (with Chocolatey)
choco install ripgrep

# Verify installation
rg --version
```

### Issue: Qdrant connection refused

**Solution:**

```bash
# Check if Qdrant is running
docker compose ps qdrant

# Check logs
docker compose logs qdrant

# Restart Qdrant
docker compose restart qdrant

# Verify connectivity
curl http://localhost:6333/health
```

### Issue: JWT token invalid/expired

**Solution:**

Browser console shows 401 errors:

1. Clear browser cache
2. Log out and log back in
3. Check JWT_SECRET_KEY hasn't changed in `.env`
4. Verify system clock is accurate (JWT uses timestamps)

### Issue: Logs not uploading (file too large)

**Solution:**

Edit `nginx/default.conf`:

```nginx
client_max_body_size 1000M;  # Increase from default
```

Rebuild and restart:

```bash
docker compose up -d --build nginx
```

### Issue: "Cannot find module" in backend

**Solution:**

```bash
# Ensure PYTHONPATH is set
export PYTHONPATH=/path/to/parsemylog-ai:$PYTHONPATH

# Or use absolute imports in code
from api.routes.auth import auth_bp  # Not: from routes.auth
```

### Issue: Frontend API calls return CORS errors

**Solution:**

Check `api/app.py` CORS configuration:

```python
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:5173", "http://localhost:40901"],
        "supports_credentials": True
    }
})
```

For local dev, ensure frontend is on port 5173 or update origins list.

### Issue: Database locked (SQLite)

**Solution:**

SQLite doesn't support concurrent writes well. Options:

1. **Quick Fix:** Restart services to clear locks
  ```bash
   docker compose restart logai-api celery-worker
  ```
2. **Long-term Fix:** Migrate to PostgreSQL
  - Update `DB_PATH` to PostgreSQL connection string
  - Install `psycopg2-binary`
  - Update SQLAlchemy engine configuration

### Getting Help

**Check Logs First:**

```bash
# Backend errors
docker compose logs logai-api | grep ERROR

# Frontend console (browser DevTools)
# Look for network errors, console.error() messages
```

**Enable Debug Logging:**

`.env`:

```bash
LOG_LEVEL=DEBUG
```

Restart services:

```bash
docker compose restart logai-api
```

---

## Next Steps

Now that you have the application running:

1. **Explore Features:** See [Features Overview](./FEATURES.md)
2. **Understand Architecture:** Read [Architecture Guide](./ARCHITECTURE.md)
3. **API Integration:** Check [API Reference](./API_REFERENCE.md)
4. **Production Deployment:** Review [Deployment Guide](./DEPLOYMENT.md)
5. **User Guide:** Share [User Guide](./USER_GUIDE.md) with end-users

Happy coding! 🚀
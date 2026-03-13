# Environment Variables Reference

Complete reference for all environment variables used in ParseMyLog-AI.

## Configuration File

Variables are loaded from `.env` file in the project root.

```bash
# Create from template
cp .env_example .env

# Edit configuration
nano .env
```

---

## Core Application Settings

### APP_PORT

**Description:** Nginx reverse proxy exposed port  
**Type:** Integer  
**Default:** `40901`  
**Required:** No  

```bash
APP_PORT=40901
```

**Usage:**
- URL: `http://localhost:40901`
- Change if port conflicts occur
- Must be available on host system

---

### LOG_LEVEL

**Description:** Python logging verbosity  
**Type:** String  
**Default:** `INFO`  
**Options:** `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`  
**Required:** No  

```bash
LOG_LEVEL=INFO
```

**Usage:**
- `DEBUG`: Verbose output for development
- `INFO`: Standard production logging
- `WARNING`: Only warnings and errors
- `ERROR`: Only errors and critical issues

**Example Output:**
```
14:32:10 [logai.indexer] INFO: Processing domain=platform
14:32:11 [logai.rg_scanner] DEBUG: Pattern matched: kernel panic
```

---

## Database Settings

### DB_PATH

**Description:** SQLite database file path  
**Type:** String (file path)  
**Default:** `/app/data/logai_users.db`  
**Required:** No  

```bash
DB_PATH=/app/data/logai_users.db
```

**Docker:** Uses volume mount `logai_data:/app/data`  
**Local Dev:** Use relative path like `./data/logai_users.db`

**Migration to PostgreSQL:**
```bash
# Example PostgreSQL connection string
DB_PATH=postgresql://user:password@localhost:5432/logai_db
```

---

## Qdrant (Vector Database)

### QDRANT_URL

**Description:** Qdrant server URL  
**Type:** String (URL)  
**Default:** `http://qdrant:6333`  
**Required:** Yes  

```bash
# Docker (use container name)
QDRANT_URL=http://qdrant:6333

# Local dev (use localhost)
QDRANT_URL=http://localhost:6333
```

### QDRANT_PORT

**Description:** Qdrant host port mapping  
**Type:** Integer  
**Default:** `6333`  
**Required:** No  

```bash
QDRANT_PORT=6333
```

**Usage:** Change if port 6333 is already in use on host.

---

## Redis (Message Broker)

### REDIS_URL

**Description:** Redis connection URL for Celery  
**Type:** String (URL)  
**Default:** `redis://redis:6379/0`  
**Required:** Yes (for Celery)  

```bash
# Docker (use container name)
REDIS_URL=redis://redis:6379/0

# Local dev (use localhost)
REDIS_URL=redis://localhost:6379/0

# With password
REDIS_URL=redis://:password@redis:6379/0
```

### REDIS_PORT

**Description:** Redis host port mapping  
**Type:** Integer  
**Default:** `6379`  
**Required:** No  

```bash
REDIS_PORT=6379
```

---

## JWT Authentication

### JWT_SECRET_KEY

**Description:** Secret key for signing JWT tokens  
**Type:** String  
**Default:** Auto-generated (insecure)  
**Required:** **YES for production**  

```bash
# Generate secure key
JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

**⚠️ Security Warning:**
- **MUST** set in production
- Keep secret and secure
- Never commit to version control
- Changing this invalidates all tokens

### JWT_ACCESS_EXPIRES

**Description:** Access token TTL in seconds  
**Type:** Integer  
**Default:** `3600` (1 hour)  
**Required:** No  

```bash
JWT_ACCESS_EXPIRES=3600   # 1 hour
JWT_ACCESS_EXPIRES=7200   # 2 hours
JWT_ACCESS_EXPIRES=1800   # 30 minutes
```

**Considerations:**
- Shorter = more secure, more frequent refreshes
- Longer = less refreshes, less secure
- Recommended: 1-2 hours

### JWT_REFRESH_EXPIRES

**Description:** Refresh token TTL in seconds  
**Type:** Integer  
**Default:** `2592000` (30 days)  
**Required:** No  

```bash
JWT_REFRESH_EXPIRES=2592000   # 30 days
JWT_REFRESH_EXPIRES=604800    # 7 days
JWT_REFRESH_EXPIRES=86400     # 1 day
```

**Considerations:**
- Determines how often users must re-login
- Balance security vs. user experience
- Recommended: 7-30 days

---

## Batch Processing

### BATCH_CPE_LOGS_PATH

**Description:** Host directory for batch CPE log files  
**Type:** String (directory path)  
**Default:** `./batch_cpe_logs`  
**Required:** No  

```bash
BATCH_CPE_LOGS_PATH=./batch_cpe_logs
BATCH_CPE_LOGS_PATH=/mnt/shared/cpe_logs
```

**Usage:**
- Place CPE tarball files here
- Must exist on host system
- Bind-mounted into Docker container

---

## ML/AI Settings

### TOKENIZERS_PARALLELISM

**Description:** HuggingFace tokenizer parallelism  
**Type:** Boolean  
**Default:** `false`  
**Required:** No  

```bash
TOKENIZERS_PARALLELISM=false
```

**Purpose:** Suppress fork warning in multi-process environments

### OPENAI_API_KEY

**Description:** OpenAI API key for LLM features  
**Type:** String  
**Default:** None  
**Required:** Only if using OpenAI chat  

```bash
OPENAI_API_KEY=sk-proj-...
```

**Usage:**
- Required for AI Chat Assistant (OpenAI)
- Configured via Admin → LLM Settings in UI
- Keep secure, never commit

### ANTHROPIC_API_KEY

**Description:** Anthropic API key for Claude  
**Type:** String  
**Default:** None  
**Required:** Only if using Claude  

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Gunicorn (WSGI Server)

### GUNICORN_WORKERS

**Description:** Number of Gunicorn worker processes  
**Type:** Integer  
**Default:** `4`  
**Required:** No  

```bash
GUNICORN_WORKERS=4
```

**Calculation:** `(2 * CPU_CORES) + 1`  
**Example:**
- 2 cores → 5 workers
- 4 cores → 9 workers
- 8 cores → 17 workers

### GUNICORN_TIMEOUT

**Description:** Worker timeout in seconds  
**Type:** Integer  
**Default:** `900` (15 minutes)  
**Required:** No  

```bash
GUNICORN_TIMEOUT=900
```

**Usage:**
- Increase for long-running operations (indexing, large file uploads)
- Decrease for faster error detection
- Recommended: 300-1800 seconds

---

## Development Settings

### FLASK_ENV

**Description:** Flask environment  
**Type:** String  
**Default:** `production`  
**Options:** `development`, `production`  
**Required:** No  

```bash
# Development
FLASK_ENV=development

# Production
FLASK_ENV=production
```

**Development Features:**
- Auto-reload on code changes
- Detailed error pages
- Debug mode enabled

**⚠️ Never use development in production!**

### FLASK_DEBUG

**Description:** Flask debug mode  
**Type:** Boolean  
**Default:** `false`  
**Required:** No  

```bash
FLASK_DEBUG=false  # Production
FLASK_DEBUG=true   # Development only
```

---

## Optional Settings

### CORS_ORIGINS

**Description:** Allowed CORS origins  
**Type:** String (comma-separated URLs)  
**Default:** `*` (allow all)  
**Required:** No  

```bash
# Allow all (development)
CORS_ORIGINS=*

# Specific origins (production)
CORS_ORIGINS=https://myapp.com,https://app.mycompany.com
```

### MAX_UPLOAD_SIZE

**Description:** Maximum file upload size in bytes  
**Type:** Integer  
**Default:** `1073741824` (1 GB)  
**Required:** No  

```bash
MAX_UPLOAD_SIZE=1073741824   # 1 GB
MAX_UPLOAD_SIZE=2147483648   # 2 GB
MAX_UPLOAD_SIZE=536870912    # 512 MB
```

**Note:** Must also configure Nginx `client_max_body_size`

---

## Example Configurations

### Minimal Production

```bash
# .env
APP_PORT=40901
JWT_SECRET_KEY=<generate-secure-key>
QDRANT_URL=http://qdrant:6333
REDIS_URL=redis://redis:6379/0
DB_PATH=/app/data/logai_users.db
LOG_LEVEL=INFO
```

### Development

```bash
# .env
APP_PORT=40901
QDRANT_URL=http://localhost:6333
REDIS_URL=redis://localhost:6379/0
DB_PATH=./data/logai_users.db
LOG_LEVEL=DEBUG
FLASK_ENV=development
FLASK_DEBUG=true
JWT_SECRET_KEY=dev-secret-key-not-for-production
```

### High-Performance Production

```bash
# .env
APP_PORT=40901
JWT_SECRET_KEY=<generate-secure-key>

# Database
DB_PATH=postgresql://logai:password@postgres:5432/logai_db

# Qdrant
QDRANT_URL=http://qdrant-cluster:6333

# Redis
REDIS_URL=redis://redis-cluster:6379/0

# Gunicorn
GUNICORN_WORKERS=17
GUNICORN_TIMEOUT=1800

# Logging
LOG_LEVEL=INFO

# Security
CORS_ORIGINS=https://myapp.com
JWT_ACCESS_EXPIRES=3600
JWT_REFRESH_EXPIRES=604800

# Upload
MAX_UPLOAD_SIZE=2147483648
```

---

## Environment Variable Priority

1. **Exported shell variables** (highest priority)
2. **`.env` file** in project root
3. **Default values** in code (lowest priority)

Example:
```bash
# Shell export overrides .env
export LOG_LEVEL=DEBUG
docker compose up  # Uses DEBUG, not value from .env
```

---

## Validation

### Check Current Configuration

```bash
# View environment in running container
docker compose exec logai-api env | grep -E "(APP_PORT|LOG_LEVEL|QDRANT_URL)"

# Test database connection
docker compose exec logai-api python -c "
from api.user_db_mngr import UserDBManager
db = UserDBManager()
print('✅ Database connection successful')
"

# Test Qdrant connection
curl http://localhost:6333/health
```

### Common Issues

**Issue: JWT tokens invalid after restart**
```bash
# Cause: JWT_SECRET_KEY not set, auto-generates each time
# Solution: Set JWT_SECRET_KEY in .env
JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

**Issue: Can't connect to Qdrant**
```bash
# Docker: Use container name
QDRANT_URL=http://qdrant:6333  # ✅

# Local dev: Use localhost
QDRANT_URL=http://localhost:6333  # ✅

# Wrong:
QDRANT_URL=http://qdrant:6333  # ❌ (in local dev)
```

---

## Security Best Practices

### ⚠️ Never Commit

**Never commit to version control:**
- `JWT_SECRET_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- Database passwords
- Any secrets

### ✅ Use `.gitignore`

```gitignore
.env
.env.local
.env.*.local
```

### ✅ Use Templates

Provide `.env_example` with placeholder values:

```bash
# .env_example
JWT_SECRET_KEY=<generate-with-secrets-token-urlsafe>
OPENAI_API_KEY=sk-proj-<your-api-key>
DB_PATH=/app/data/logai_users.db
```

### ✅ Rotate Secrets

- Change `JWT_SECRET_KEY` periodically (invalidates all sessions)
- Rotate API keys quarterly
- Use different secrets per environment (dev, staging, prod)

---

## Related Documentation

- [Quick Start Guide](./QUICK_START.md) - Setup instructions
- [Architecture](./ARCHITECTURE.md) - System design
- [Deployment Guide](./DEPLOYMENT.md) - Production deployment
- [API Reference](./API_REFERENCE.md) - API endpoints

---

**Last Updated:** March 13, 2024

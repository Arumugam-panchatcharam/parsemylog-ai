# Deployment Guide

Production deployment guide for ParseMyLog-AI with best practices, security hardening, and monitoring setup.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Production Deployment](#production-deployment)
- [Security Hardening](#security-hardening)
- [Performance Tuning](#performance-tuning)
- [Monitoring & Logging](#monitoring--logging)
- [Backup & Recovery](#backup--recovery)
- [Scaling Strategies](#scaling-strategies)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

**Minimum:**
- 4 CPU cores
- 8 GB RAM
- 50 GB disk space
- Ubuntu 20.04+ / Debian 11+ / RHEL 8+

**Recommended:**
- 8 CPU cores
- 16 GB RAM
- 200 GB SSD
- Ubuntu 22.04 LTS

### Software Requirements

- Docker 20.10+
- Docker Compose v2+
- Git
- (Optional) PostgreSQL 13+ if replacing SQLite

### Network Requirements

- Open ports: 40901 (or your APP_PORT), 6333 (Qdrant), 6379 (Redis)
- Internet access for:
  - Docker Hub (image pulls)
  - HuggingFace (model downloads)
  - IEEE (OUI database updates)

---

## Production Deployment

### 1. Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify installation
docker --version
docker compose version
```

### 2. Clone Repository

```bash
# Clone to production directory
cd /opt
sudo git clone https://github.com/your-org/parsemylog-ai.git
cd parsemylog-ai

# Set ownership
sudo chown -R $USER:$USER /opt/parsemylog-ai
```

### 3. Configure Environment

```bash
# Copy template
cp .env_example .env

# Generate secure JWT secret
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Edit configuration
nano .env
```

**Production `.env`:**
```bash
# Application
APP_PORT=40901
LOG_LEVEL=INFO

# Security
JWT_SECRET_KEY=<paste-generated-secret>
JWT_ACCESS_EXPIRES=3600
JWT_REFRESH_EXPIRES=604800

# Database (consider PostgreSQL for production)
DB_PATH=/app/data/logai_users.db

# Qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_PORT=6333

# Redis
REDIS_URL=redis://redis:6379/0
REDIS_PORT=6379

# Gunicorn
GUNICORN_WORKERS=8
GUNICORN_TIMEOUT=900

# CORS (restrict to your domain)
CORS_ORIGINS=https://yourapp.com,https://www.yourapp.com

# Upload limits
MAX_UPLOAD_SIZE=2147483648
```

### 4. Build Frontend

```bash
# Build React SPA
docker compose --profile build up frontend-build

# Wait for completion
# Expected: "Frontend build complete."
```

### 5. Start Services

```bash
# Start all services
docker compose up -d --build

# Verify all containers running
docker compose ps

# Check logs for errors
docker compose logs -f
```

### 6. Initial Setup

```bash
# Access the application
curl http://localhost:40901/api/auth/health
# Expected: {"status": "ok"}

# Login with default admin
# Username: admin
# Password: admin123

# ⚠️ IMPORTANT: Change admin password immediately!
```

### 7. SSL/TLS Setup (Recommended)

#### Option A: Nginx Reverse Proxy (Recommended)

```bash
# Install Nginx on host
sudo apt install nginx certbot python3-certbot-nginx -y

# Create Nginx config
sudo nano /etc/nginx/sites-available/parsemylog-ai
```

**Nginx Configuration:**
```nginx
server {
    listen 80;
    server_name yourapp.com www.yourapp.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourapp.com www.yourapp.com;

    # SSL certificates (certbot will add these)
    ssl_certificate /etc/letsencrypt/live/yourapp.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourapp.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Proxy to Docker
    location / {
        proxy_pass http://localhost:40901;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (if needed)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts for large uploads
        proxy_read_timeout 900s;
        proxy_send_timeout 900s;
    }

    # Max upload size
    client_max_body_size 2G;
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/parsemylog-ai /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Get SSL certificate
sudo certbot --nginx -d yourapp.com -d www.yourapp.com

# Restart Nginx
sudo systemctl restart nginx
```

#### Option B: Traefik (Alternative)

See [Traefik Documentation](https://doc.traefik.io/traefik/)

---

## Security Hardening

### 1. Change Default Credentials

```bash
# Login as admin
# Navigate to Admin → Users
# Change admin password to strong password (16+ chars)

# Or via API:
TOKEN=$(curl -X POST http://localhost:40901/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | jq -r '.access_token')

curl -X PUT http://localhost:40901/api/admin/users/1/password \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"new_password":"YourSecurePassword123!"}'
```

### 2. Firewall Configuration

```bash
# UFW (Ubuntu/Debian)
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (redirect to HTTPS)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# Verify
sudo ufw status
```

### 3. Secure Docker

```bash
# Create non-root user for Docker
sudo useradd -m -s /bin/bash dockeruser
sudo usermod -aG docker dockeruser

# Run containers as non-root
# Add to docker-compose.yml:
# services:
#   logai-api:
#     user: "1000:1000"  # UID:GID of dockeruser
```

### 4. Environment Variable Security

```bash
# Restrict .env permissions
chmod 600 .env

# Never commit .env
echo ".env" >> .gitignore

# Use secrets management (production)
# - Docker Secrets
# - HashiCorp Vault
# - AWS Secrets Manager
```

### 5. Database Security

**If using PostgreSQL:**

```bash
# Create dedicated database user
CREATE USER logai_user WITH PASSWORD 'strong-password';
CREATE DATABASE logai_db OWNER logai_user;
GRANT ALL PRIVILEGES ON DATABASE logai_db TO logai_user;

# Update .env
DB_PATH=postgresql://logai_user:strong-password@postgres:5432/logai_db

# Restrict PostgreSQL network access
# Edit postgresql.conf:
listen_addresses = 'localhost'
```

### 6. Regular Updates

```bash
# Update Docker images
docker compose pull
docker compose up -d --build

# Update system packages
sudo apt update && sudo apt upgrade -y

# Auto-updates (Ubuntu)
sudo apt install unattended-upgrades -y
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## Performance Tuning

### 1. Gunicorn Workers

```bash
# Calculate optimal workers
CPU_CORES=$(nproc)
WORKERS=$((2 * CPU_CORES + 1))

# Update .env
GUNICORN_WORKERS=$WORKERS
```

### 2. Celery Concurrency

```yaml
# docker-compose.yml
celery-worker:
  command: [
    "celery", "-A", "services.celery_worker.celery_app",
    "worker", "--concurrency=4",  # Increase for batch processing
    "--loglevel=info"
  ]
```

### 3. Qdrant Optimization

```bash
# Increase Qdrant memory limit
# docker-compose.yml
qdrant:
  deploy:
    resources:
      limits:
        memory: 4G
```

### 4. Redis Tuning

```yaml
# docker-compose.yml
redis:
  command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru
```

### 5. Nginx Caching

```nginx
# Add to nginx config
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:10m max_size=1g;

location /api/ {
    proxy_cache my_cache;
    proxy_cache_valid 200 5m;
    proxy_cache_bypass $http_cache_control;
}
```

---

## Monitoring & Logging

### 1. Log Aggregation

```bash
# View all logs
docker compose logs -f

# Export logs to file
docker compose logs > logs_$(date +%Y%m%d).txt

# Send logs to external system (Elasticsearch, Splunk, etc.)
# Configure Docker logging driver in docker-compose.yml:
services:
  logai-api:
    logging:
      driver: "syslog"
      options:
        syslog-address: "tcp://192.168.1.100:514"
```

### 2. Health Checks

```bash
# API health
curl http://localhost:40901/api/auth/health

# Qdrant health
curl http://localhost:6333/health

# Redis health
docker exec logai-redis redis-cli ping
```

**Monitoring Script:**
```bash
#!/bin/bash
# healthcheck.sh

check_service() {
    if curl -sf "$1" > /dev/null; then
        echo "✅ $2 is healthy"
    else
        echo "❌ $2 is down"
        # Send alert (email, Slack, PagerDuty)
    fi
}

check_service "http://localhost:40901/api/auth/health" "API"
check_service "http://localhost:6333/health" "Qdrant"

# Add to crontab
# */5 * * * * /opt/parsemylog-ai/healthcheck.sh
```

### 3. Metrics Collection

**Prometheus + Grafana (Optional):**

```yaml
# docker-compose.yml
services:
  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
```

### 4. Disk Usage Monitoring

```bash
# Check volume sizes
docker system df -v

# Monitor user uploads
du -sh /var/lib/docker/volumes/parsemylog-ai_user_uploads/_data

# Alert if >80% full
USAGE=$(df /var/lib/docker | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $USAGE -gt 80 ]; then
    echo "⚠️ Disk usage at ${USAGE}%"
    # Send alert
fi
```

---

## Backup & Recovery

### 1. Database Backup

```bash
# SQLite backup
docker cp logai-api:/app/data/logai_users.db \
  ./backups/logai_users_$(date +%Y%m%d).db

# PostgreSQL backup
docker exec postgres pg_dump -U logai_user logai_db > \
  ./backups/logai_db_$(date +%Y%m%d).sql
```

### 2. User Uploads Backup

```bash
# Backup user uploads volume
docker run --rm -v parsemylog-ai_user_uploads:/source \
  -v $(pwd)/backups:/backup \
  ubuntu tar czf /backup/user_uploads_$(date +%Y%m%d).tar.gz -C /source .
```

### 3. Qdrant Backup

```bash
# Backup Qdrant collections
docker run --rm -v parsemylog-ai_qdrant_storage:/source \
  -v $(pwd)/backups:/backup \
  ubuntu tar czf /backup/qdrant_$(date +%Y%m%d).tar.gz -C /source .
```

### 4. Automated Backups

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/opt/backups/parsemylog-ai"
DATE=$(date +%Y%m%d)

mkdir -p $BACKUP_DIR

# Database
docker cp logai-api:/app/data/logai_users.db \
  $BACKUP_DIR/db_$DATE.db

# User uploads
docker run --rm -v parsemylog-ai_user_uploads:/source \
  -v $BACKUP_DIR:/backup \
  ubuntu tar czf /backup/uploads_$DATE.tar.gz -C /source .

# Keep only last 7 days
find $BACKUP_DIR -type f -mtime +7 -delete

# Upload to S3 (optional)
aws s3 sync $BACKUP_DIR s3://my-backup-bucket/parsemylog-ai/
```

**Schedule:**
```bash
# Daily at 2 AM
0 2 * * * /opt/parsemylog-ai/backup.sh
```

### 5. Disaster Recovery

```bash
# Stop services
docker compose down

# Restore database
docker cp ./backups/logai_users_20240313.db logai-api:/app/data/logai_users.db

# Restore uploads
docker run --rm -v parsemylog-ai_user_uploads:/target \
  -v $(pwd)/backups:/backup \
  ubuntu tar xzf /backup/user_uploads_20240313.tar.gz -C /target

# Restart services
docker compose up -d
```

---

## Scaling Strategies

### Horizontal Scaling

**1. Replace SQLite with PostgreSQL**

```bash
# docker-compose.yml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: logai_db
      POSTGRES_USER: logai_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data

# Update .env
DB_PATH=postgresql://logai_user:password@postgres:5432/logai_db
```

**2. Deploy Multiple API Instances**

```yaml
# docker-compose.yml
services:
  logai-api-1:
    <<: *api-common
    container_name: logai-api-1

  logai-api-2:
    <<: *api-common
    container_name: logai-api-2

  nginx:
    # Add load balancing
    depends_on:
      - logai-api-1
      - logai-api-2
```

**3. Qdrant Cluster**

See [Qdrant Distributed Deployment](https://qdrant.tech/documentation/guides/distributed_deployment/)

### Vertical Scaling

```yaml
# docker-compose.yml
services:
  logai-api:
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
        reservations:
          cpus: '2'
          memory: 4G
```

---

## Troubleshooting

### Service Won't Start

```bash
# Check logs
docker compose logs logai-api

# Common issues:
# 1. Port conflict
sudo lsof -i :40901

# 2. Permissions
sudo chown -R $USER:$USER /opt/parsemylog-ai

# 3. Disk space
df -h
```

### High Memory Usage

```bash
# Check memory
docker stats

# Restart memory-hungry service
docker compose restart logai-api

# Increase limits in docker-compose.yml
```

### Slow Performance

```bash
# Check CPU
top

# Check disk I/O
iotop

# Increase workers
# Update GUNICORN_WORKERS in .env
docker compose up -d --force-recreate
```

---

## Production Checklist

- [ ] Changed default admin password
- [ ] Set secure `JWT_SECRET_KEY`
- [ ] Configured firewall (ports 80, 443 only)
- [ ] Enabled SSL/TLS
- [ ] Configured CORS restrictions
- [ ] Set up automated backups
- [ ] Configured monitoring/alerts
- [ ] Tested disaster recovery
- [ ] Documented runbooks
- [ ] Set up log aggregation
- [ ] Configured auto-updates
- [ ] Restricted `.env` permissions
- [ ] Tested failover scenarios

---

## Related Documentation

- [Quick Start Guide](./QUICK_START.md) - Initial setup
- [Architecture](./ARCHITECTURE.md) - System design
- [Environment Variables](./ENVIRONMENT_VARIABLES.md) - Configuration
- [API Reference](./API_REFERENCE.md) - API endpoints

---

**Last Updated:** March 13, 2024

#!/bin/bash
# Quick start script for batch CPE processing setup

set -e

echo "🚀 Setting up Batch CPE Processing..."
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Step 1: Create batch logs directory
echo -e "${BLUE}📁 Creating batch_cpe_logs directory...${NC}"
mkdir -p batch_cpe_logs
chmod 755 batch_cpe_logs
echo -e "${GREEN}✓ Created: $PROJECT_ROOT/batch_cpe_logs${NC}"
echo ""

# Step 2: Check .env file
echo -e "${BLUE}⚙️  Checking .env configuration...${NC}"
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠  .env file not found, creating from template...${NC}"
    cat > .env << EOF
# Database
DB_PATH=/app/data/logai_users.db

# Services
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333
LLM_URL=http://llm:8000/v1

# Ports
APP_PORT=40901
REDIS_PORT=6379
QDRANT_PORT=6333
LLM_PORT=8000

# Batch processing
BATCH_CPE_LOGS_PATH=$PROJECT_ROOT/batch_cpe_logs
EOF
    echo -e "${GREEN}✓ Created .env file${NC}"
else
    # Check if BATCH_CPE_LOGS_PATH exists
    if grep -q "BATCH_CPE_LOGS_PATH" .env; then
        echo -e "${GREEN}✓ BATCH_CPE_LOGS_PATH already configured${NC}"
    else
        echo -e "${YELLOW}⚠  Adding BATCH_CPE_LOGS_PATH to .env...${NC}"
        echo "" >> .env
        echo "# Batch processing" >> .env
        echo "BATCH_CPE_LOGS_PATH=$PROJECT_ROOT/batch_cpe_logs" >> .env
        echo -e "${GREEN}✓ Added BATCH_CPE_LOGS_PATH${NC}"
    fi
fi
echo ""

# Step 3: Build frontend
echo -e "${BLUE}🔨 Building frontend...${NC}"
cd frontend
npm install --silent
npm run build
cd ..
echo -e "${GREEN}✓ Frontend built successfully${NC}"
echo ""

# Step 4: Docker compose
echo -e "${BLUE}🐳 Starting Docker services...${NC}"
docker-compose down 2>/dev/null || true
docker-compose up -d

echo ""
echo -e "${GREEN}✅ Setup complete!${NC}"
echo ""
echo "📋 Next steps:"
echo "   1. Wait for services to start (30-60 seconds)"
echo "   2. Check status: docker-compose ps"
echo "   3. Place CPE zip files in: $PROJECT_ROOT/batch_cpe_logs"
echo "   4. Open http://localhost:40901"
echo "   5. Create batch job with path: /app/batch_cpe_logs"
echo ""
echo "📊 Monitor logs:"
echo "   • API:     docker-compose logs -f logai-api"
echo "   • Celery:  docker-compose logs -f celery-worker"
echo "   • All:     docker-compose logs -f"
echo ""
echo "🔍 Verify mount:"
echo "   docker exec logai-api ls -la /app/batch_cpe_logs"
echo ""

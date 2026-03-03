# Testing Batch Jobs Locally

## Prerequisites

1. **Redis** - for Celery message broker
2. **Qdrant** - for vector storage (can run in Docker)
3. **Python environment** with all dependencies installed

## Setup Steps

### 1. Start Redis

```bash
docker run -d --name logai-redis -p 6379:6379 redis:7-alpine redis-server --appendonly yes
```

Verify:
```bash
docker exec logai-redis redis-cli ping
# Should return: PONG
```

### 2. Start Qdrant (if not already running)

```bash
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:latest
```

### 3. Set Environment Variables

**CRITICAL:** Both Flask API and Celery worker MUST use the same database path.

```bash
export DB_PATH=/Users/parumugam/Documents/Repos/parsemylog-ai/logai_users.db
export REDIS_URL=redis://localhost:6379/0
export QDRANT_URL=http://localhost:6333
```

### 4. Start Flask API

In terminal 1:
```bash
cd /Users/parumugam/Documents/Repos/parsemylog-ai
export DB_PATH=/Users/parumugam/Documents/Repos/parsemylog-ai/logai_users.db
export REDIS_URL=redis://localhost:6379/0
export QDRANT_URL=http://localhost:6333
python run_api.py
```

### 5. Start Celery Worker

In terminal 2:

**Option A: Using solo pool (RECOMMENDED for macOS - avoids MPS crash)**
```bash
cd /Users/parumugam/Documents/Repos/parsemylog-ai
export DB_PATH=/Users/parumugam/Documents/Repos/parsemylog-ai/logai_users.db
export REDIS_URL=redis://localhost:6379/0
export QDRANT_URL=http://localhost:6333
celery -A services.celery_worker.celery_app worker --loglevel=info --pool=solo
```

**Option B: Using prefork pool (may crash on macOS due to MPS)**
```bash
cd /Users/parumugam/Documents/Repos/parsemylog-ai
export DB_PATH=/Users/parumugam/Documents/Repos/parsemylog-ai/logai_users.db
export REDIS_URL=redis://localhost:6379/0
export QDRANT_URL=http://localhost:6333
celery -A services.celery_worker.celery_app worker --loglevel=info --concurrency=1 --prefork-multiplier=1
```

**Note**: The `--pool=solo` option uses threading instead of process forking, which prevents the Metal Performance Shaders (MPS) crash on macOS. This is the recommended approach for local development on macOS.

### 6. Start Frontend (if needed)

In terminal 3:
```bash
cd /Users/parumugam/Documents/Repos/parsemylog-ai/frontend
npm run dev
```

## Creating a Batch Job

### Via Frontend UI

1. Navigate to the Batch Jobs page
2. Enter the absolute path to CPE zip files: `/Users/parumugam/Documents/Repos/parsemylog-ai/test-batch-job`
3. Click "Create Batch Job"

### Via curl

```bash
curl -X POST http://localhost:5000/api/projects/<PROJECT_ID>/batch-jobs/create \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
  -d '{
    "cpe_folder_path": "/Users/parumugam/Documents/Repos/parsemylog-ai/test-batch-job",
    "job_type": "cpe_processing"
  }'
```

## Monitoring

- **Celery Worker Terminal**: Real-time task execution logs
- **Flask API Terminal**: API request logs
- **Frontend UI**: Batch job status and progress
- **Redis**: `docker exec logai-redis redis-cli llen celery` (queue length)

## Troubleshooting

### Issue: "FOREIGN KEY constraint failed"

**Cause**: Flask API and Celery worker are using different database files.

**Solution**: Ensure `DB_PATH` is set to the SAME absolute path in both terminals before starting Flask API and Celery worker.

### Issue: "Worker exited prematurely: signal 6 (SIGABRT)" with MPS error

**Cause**: PyTorch tries to use Apple's Metal Performance Shaders in forked Celery worker processes, which causes crashes on macOS.

**Solution**: Use `--pool=solo` when starting Celery worker:
```bash
celery -A services.celery_worker.celery_app worker --loglevel=info --pool=solo
```

This uses threading instead of process forking, which prevents the MPS crash.

### Issue: "unable to open database file"

**Cause**: Database path doesn't exist or is incorrect.

**Solution**:  
1. Check that the database file exists: `ls -la /Users/parumugam/Documents/Repos/parsemylog-ai/logai_users.db`
2. Ensure `DB_PATH` is exported before starting services
3. Use absolute paths, not Docker paths like `/app/data/logai_users.db`

### Issue: Celery worker receives tasks but batch job doesn't exist

**Cause**: Flask API created the batch job in a different database than the Celery worker is reading from.

**Solution**: Restart BOTH Flask API and Celery worker with the same `DB_PATH` environment variable set.

### Issue: CPE records stuck in "processing" state after worker crash

**Cause**: When the Celery worker crashes (e.g., due to MPS error), tasks that were in progress are left in "processing" state indefinitely.

**Solution**:  
1. Use `--pool=solo` to prevent worker crashes
2. If crashes occur, manually update stuck records in the database:
```sql
UPDATE cpe_process_records SET status='failed', error_message='Worker crashed' WHERE status='processing';
```
3. The batch job task has retry logic, but worker crashes bypass this. Future improvement: implement task timeout and cleanup mechanisms.

## Summary

The key requirements for local batch job testing:

1. **Same DB_PATH** for both Flask API and Celery worker
2. **Redis running** on port 6379
3. **Qdrant running** on port 6333
4. **Use absolute paths** when specifying CPE folder location
5. **Celery worker** must be running to process tasks

Test data is available in `/Users/parumugam/Documents/Repos/parsemylog-ai/test-batch-job/` (14 CPE zip files).

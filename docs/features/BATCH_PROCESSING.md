# BATCH_PROCESSING.md
# Batch CPE Processing

## Overview

Batch Processing enables asynchronous analysis of 100+ CPE log archives using Celery workers without blocking the UI.

## Key Capabilities

- **Async Processing** - Non-blocking job submission
- **Progress Tracking** - Real-time status updates
- **Bulk Operations** - Extract, index, analyze in one job
- **Result Aggregation** - Fleet-level summary reports
- **Error Handling** - Retry failed CPEs, skip corrupted files

## How It Works

```
User → Place files in batch_cpe_logs/ → Create job → Celery worker processes → Results
```

### Directory Structure

```
batch_cpe_logs/
├── logs_mac_AABBCCDDEEFF.tgz
├── logs_mac_CCDDEE112233.tgz
├── logs_serial_1234567890.tar.gz
└── ...
```

## Usage

### Create Batch Job

```
┌──────────────────────────────────────────────────────┐
│ Create Batch Job                                     │
│ Project: [Fleet Analysis Q1 2024 ▼]                  │
│ File Pattern: [*.tgz──]  (or *.tar.gz, specific)     │
│ Operations:                                          │
│   ☑ Extract logs                                     │
│   ☑ Run Drain3 indexing                              │
│   ☑ Generate telemetry reports                       │
│ Notify Email: [user@example.com──────]               │
│ [Create Job]                                         │
└──────────────────────────────────────────────────────┘

Job created! ID: batch_job_123
Found 156 files matching pattern.
Estimated time: 2-3 hours
```

### Monitor Progress

```
┌──────────────────────────────────────────────────────┐
│ Batch Job #123 - Fleet Analysis Q1 2024             │
│ Status: Running  Progress: 45%                      │
│ [████████████████░░░░░░░░░░░░░░░░] 70/156 CPEs      │
│                                                      │
│ Started: 2024-03-13 14:30                            │
│ Elapsed: 45 minutes                                  │
│ ETA: 55 minutes                                      │
│                                                      │
│ Processed: 70                                        │
│ Failed: 2                                            │
│ Remaining: 84                                        │
│                                                      │
│ [View Logs] [Cancel Job]                            │
└──────────────────────────────────────────────────────┘
```

### View Results

```
Batch Job #123 - Complete

Summary:
- Total CPEs: 156
- Successfully Processed: 154 (98.7%)
- Failed: 2 (1.3%)
- Duration: 2h 15m

Top Issues (across fleet):
1. WiFi Connection Failed: 3,456 occurrences (98 CPEs)
2. DHCP Timeout: 1,234 occurrences (67 CPEs)
3. Kernel Warning: 890 occurrences (134 CPEs)

[📥 Download Full Report] [View CPE Overview]
```

## API Reference

```http
POST /api/batch-jobs
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "project_id": 42,
  "file_pattern": "*.tgz",
  "operations": ["extract", "index", "analyze"],
  "notify_email": "user@example.com"
}

Response:
{
  "job_id": "batch_job_123",
  "total_files": 156,
  "status": "queued"
}
```

```http
GET /api/batch-jobs/<job_id>
Authorization: Bearer <access_token>

Response:
{
  "job_id": "batch_job_123",
  "status": "running",
  "progress": 45,
  "processed": 70,
  "failed": 2,
  "remaining": 84,
  "estimated_completion": "2024-03-13T16:45:00Z",
  "results": {...}
}
```

## Best Practices

- **File Preparation:** Name files with MAC/serial for CPE detection
- **Disk Space:** Ensure sufficient space (extracted size ~10x compressed)
- **Monitoring:** Check progress regularly, especially for large batches
- **Error Handling:** Review failed CPEs, re-upload if necessary

## Related Features

- [File Upload](./FILE_UPLOAD.md)
- [Multi-CPE Support](./MULTI_CPE.md)
- [CPE Overview](./CPE_OVERVIEW.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

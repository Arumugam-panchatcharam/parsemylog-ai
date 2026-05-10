# API Reference

Complete REST API documentation for ParseMyLog-AI.

## Base URL

```
Production: http://localhost:40901/api
Development: http://localhost:5173/api (proxied to :40901)
```

## Authentication

All API endpoints (except `/auth/login`, `/auth/register`, `/auth/health`) require JWT authentication.

### Headers

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

### Token Lifecycle

- **Access Token:** Expires in 1 hour
- **Refresh Token:** Expires in 30 days

---

## Authentication Endpoints

### Login

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "admin123"
}

Response: 200 OK
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user": {
    "id": 1,
    "username": "admin",
    "is_admin": true
  }
}

Errors:
401 - Invalid credentials
```

### Register

```http
POST /api/auth/register
Content-Type: application/json

{
  "username": "new_user",
  "password": "SecurePassword123!"
}

Response: 201 Created
{
  "message": "User created successfully",
  "user_id": 2
}

Errors:
400 - Username already exists
400 - Password too weak
```

### Refresh Token

```http
POST /api/auth/refresh
Authorization: Bearer <refresh_token>

Response: 200 OK
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}

Errors:
401 - Invalid or expired refresh token
```

### Health Check

```http
GET /api/auth/health

Response: 200 OK
{
  "status": "ok"
}
```

---

## Project Endpoints

### List Projects

```http
GET /api/projects
Authorization: Bearer <access_token>

Response: 200 OK
{
  "projects": [
    {
      "id": 1,
      "name": "Fleet Analysis Q1 2024",
      "natco_id": 1,
      "created_at": "2024-01-15T10:30:00Z",
      "file_count": 3,
      "cpe_count": 3
    }
  ]
}
```

### Create Project

```http
POST /api/projects
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "New Project",
  "natco_id": 1  // optional
}

Response: 201 Created
{
  "message": "Project created successfully",
  "project_id": 2
}

Errors:
400 - Missing project name
```

### Get Project

```http
GET /api/projects/<project_id>
Authorization: Bearer <access_token>

Response: 200 OK
{
  "id": 1,
  "name": "Fleet Analysis Q1 2024",
  "natco_id": 1,
  "natco_code": "EU",
  "created_at": "2024-01-15T10:30:00Z",
  "files": [...],
  "cpes": [...]
}

Errors:
404 - Project not found
403 - Access denied (not your project)
```

### Update Project

```http
PUT /api/projects/<project_id>
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "name": "Updated Name",
  "natco_id": 2
}

Response: 200 OK
{
  "message": "Project updated successfully"
}
```

### Delete Project

```http
DELETE /api/projects/<project_id>
Authorization: Bearer <access_token>

Response: 200 OK
{
  "message": "Project deleted successfully"
}

Errors:
404 - Project not found
403 - Access denied
```

---

## File Upload Endpoints

### Upload File

```http
POST /api/<project_id>/files/upload
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

Body:
  file: <binary_data>

Response: 200 OK
{
  "message": "File uploaded successfully",
  "file_id": 123,
  "filename": "logs_mac_AABBCCDDEEFF.tgz",
  "size": 52428800,
  "cpe_identifier": "AABBCCDDEEFF"
}

Errors:
400 - Invalid file format
413 - File too large (>1GB default)
500 - Extraction failed
```

### Get Log Content

```http
GET /api/<project_id>/files/content?cpe_id=<cpe_id>&page=1&page_size=1000
Authorization: Bearer <access_token>

Query Parameters:
  - cpe_id: CPE identifier (required)
  - page: Page number (default: 1)
  - page_size: Lines per page (default: 1000, max: 10000)
  - search: Regex pattern (optional)
  - case_sensitive: true/false (default: false)

Response: 200 OK
{
  "lines": ["2024-03-13 14:32:10 [wifi] INFO: Starting...", ...],
  "total_lines": 1234567,
  "page": 1,
  "page_size": 1000,
  "total_pages": 1235
}

Errors:
404 - CPE not found
404 - Log file not found
```

### Search Logs

```http
POST /api/<project_id>/files/search
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "cpe_id": "AABBCCDDEEFF",
  "pattern": "ERROR.*timeout",
  "case_sensitive": false,
  "regex": true,
  "max_results": 1000
}

Response: 200 OK
{
  "matches": [
    {
      "line_number": 342,
      "content": "2024-03-13 14:32:12 [wifi] ERROR: Connection timeout",
      "timestamp": "2024-03-13T14:32:12Z"
    }
  ],
  "total_matches": 234,
  "search_time_ms": 123
}
```

### Download Logs

```http
GET /api/<project_id>/files/download?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response: 200 OK
Content-Type: text/plain
Content-Disposition: attachment; filename="merged_logs_AABBCCDDEEFF.txt"

<full log contents>
```

---

## Pattern Analysis Endpoints

### Get Drain3 Templates

```http
GET /api/<project_id>/patterns?cpe_id=<cpe_id>&domain=wifi&min_freq=10
Authorization: Bearer <access_token>

Query Parameters:
  - cpe_id: CPE identifier (required)
  - domain: Filter by domain (optional)
  - min_freq: Minimum frequency (default: 1)
  - search: Search pattern (optional)

Response: 200 OK
{
  "templates": [
    {
      "cluster_id": "abc123",
      "template": "[wifi] ERROR: Failed to connect to SSID <*> (code: <*>)",
      "domain": "wifi",
      "frequency": 324,
      "sample_logs": ["...", "...", "..."]
    }
  ],
  "total": 543,
  "domains": {
    "wifi": 123,
    "platform": 234
  }
}
```

### Extract Parameters

```http
POST /api/<project_id>/patterns/extract-parameters
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "cpe_id": "AABBCCDDEEFF",
  "cluster_id": "abc123"
}

Response: 200 OK
{
  "template": "[wifi] ERROR: Failed to connect to SSID <*> (code: <*>)",
  "parameters": [
    {
      "position": 1,
      "values": {"MyNetwork": 234, "GuestWiFi": 67}
    }
  ]
}
```

### Re-Index Patterns

```http
POST /api/<project_id>/patterns/reindex?cpe_id=<cpe_id>&domain=wifi
Authorization: Bearer <access_token>

Response: 202 Accepted
{
  "message": "Re-indexing started",
  "task_id": "xyz789"
}
```

---

## Semantic Search Endpoints

### Search

```http
POST /api/<project_id>/ai-analysis/search?cpe_id=<cpe_id>
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "query": "WiFi connection failures",
  "top_k": 10,
  "domain": null,
  "min_score": 0.0,
  "include_context": false
}

Response: 200 OK
{
  "results": [
    {
      "template": "[wifi] ERROR: Failed to connect to SSID <*>",
      "score": 0.92,
      "domain": "wifi",
      "frequency": 324,
      "sample_logs": [...]
    }
  ],
  "query_time_ms": 45
}
```

### Get Indexing Status

```http
GET /api/<project_id>/embedding/status?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response: 200 OK
{
  "indexed": true,
  "total_templates": 1543,
  "indexed_at": "2024-03-13T14:35:22Z",
  "collection_name": "project_42_cpe_AABBCCDDEEFF"
}
```

---

## Telemetry Endpoints

### Parse Telemetry

```http
POST /api/<project_id>/telemetry/parse?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response: 202 Accepted
{
  "message": "Telemetry parsing started",
  "task_id": "tel_xyz789"
}
```

### Get Telemetry Data

```http
GET /api/<project_id>/telemetry/data?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response: 200 OK
{
  "device_info": {
    "model": "RDK-B Gateway v2",
    "firmware": "24.02.1.5"
  },
  "time_series": [...],
  "reboot_events": [...]
}
```

---

## Pattern Analyzer Endpoints

### Get Regex Patterns

```http
GET /api/<project_id>/regex-patterns
Authorization: Bearer <access_token>

Response: 200 OK
{
  "patterns": {
    "wifi": [
      {"name": "WiFi Connection Failed", "regex": "...", "enabled": true}
    ]
  }
}
```

### Save Regex Patterns

```http
PUT /api/<project_id>/regex-patterns
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "patterns": {
    "wifi": [...]
  }
}

Response: 200 OK
{
  "message": "Patterns saved successfully"
}
```

### Trigger Regex Scan (async)

Starts a background ripgrep job. Poll progress until `complete`, then fetch results.

```http
POST /api/projects/<project_id>/regex-scan?cpe_id=<optional_cpe_serial>
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "patterns": [
    {
      "name": "Example",
      "regex": "error",
      "enabled": true,
      "scan_filename": "WiFi.log",
      "scan_time_range": {"start": "2025-05-06T00:00:00", "end": "2025-05-08T23:59:59"}
    }
  ],
  "bucket_minutes": 60,
  "filter_pre_ntp": true,
  "filter_short_reboots": true,
  "cpe_id": "AABBCCDDEEFF"
}

Response: 202 Accepted
{
  "scan_id": "scan_abc123",
  "accepted": true,
  "total_patterns": 12
}
```

Optional **per-pattern** fields on each object in `patterns`:

| Field | Meaning |
|-------|---------|
| `scan_filename` | Basename only; **for that pattern**, ripgrep searches only uploaded files under the project/CPE directory whose final path segment matches (case-insensitive). Omit to use all files for that pattern. Returns **400** if set and no file matches. |
| `scan_time_range` | `{ "start", "end" }` naive local ISO strings; filters that pattern’s matches **after** ripgrep. Omit entirely or supply **both** start and end. **400** if only one side is set, or if `start` > `end`. |

Top-level JSON fields:

| Field | Meaning |
|-------|---------|
| `cpe_id` | May also be passed as query `cpe_id` (same value). |

### Regex Scan Progress

```http
GET /api/projects/<project_id>/regex-scan/<scan_id>/progress?cpe_id=<optional>
Authorization: Bearer <access_token>

Response: 200 OK
{
  "status": "running",
  "current": 3,
  "total": 12,
  "pattern_name": "WiFi Timeout",
  "error": null
}
```

Status is `running`, `complete`, or `error`. Results are not ready until progress reports `complete`.

### Get Scan Results

```http
GET /api/projects/<project_id>/regex-scan/<scan_id>/results?cpe_id=<optional>
Authorization: Bearer <access_token>

Response: 200 OK
{
  "traces": [{"name": "...", "times": [], "texts": [], "total": 0}],
  "reboots": [],
  "total_matches": 479,
  "cpe_serial": "AABBCCDDEEFF"
}
```

Returns **404** until the worker has written the result file for `scan_id`.

---

## CPE Endpoints

### List CPEs

```http
GET /api/<project_id>/cpes
Authorization: Bearer <access_token>

Response: 200 OK
{
  "cpes": [
    {
      "cpe_id": "AABBCCDDEEFF",
      "source_file": "logs_mac_AA:BB:CC:DD:EE:FF.tgz",
      "detected_at": "2024-03-13T14:32:10Z"
    }
  ]
}
```

### Get CPE Overview

```http
GET /api/<project_id>/cpe-overview
Authorization: Bearer <access_token>

Response: 200 OK
{
  "cpes": [...],
  "fleet_stats": {...},
  "common_patterns": [...]
}
```

---

## NATCO Endpoints

### Get Global Patterns

```http
GET /api/<project_id>/patterns/global
Authorization: Bearer <access_token>

Response: 200 OK
{
  "natco": {"id": 1, "code": "EU"},
  "patterns": {...}
}
```

### Sync from Global

```http
POST /api/<project_id>/patterns/sync
Authorization: Bearer <access_token>

Response: 200 OK
{
  "synced": true,
  "added": 3,
  "updated": 2
}
```

### Submit Patterns

```http
POST /api/<project_id>/patterns/submit
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "patterns": [...],
  "message": "Updated patterns"
}

Response: 201 Created
{
  "submission_id": 42,
  "status": "pending"
}
```

---

## Admin Endpoints

### List Users

```http
GET /api/admin/users
Authorization: Bearer <access_token>  (Admin only)

Response: 200 OK
{
  "users": [...]
}
```

### Create User

```http
POST /api/auth/register
Authorization: Bearer <access_token>  (Admin only)
Content-Type: application/json

{
  "username": "new_user",
  "password": "SecurePassword123!"
}
```

### Delete User

```http
DELETE /api/admin/users/<user_id>
Authorization: Bearer <access_token>  (Admin only)

Response: 200 OK
{
  "message": "User deleted successfully"
}
```

### List NATCOs

```http
GET /api/admin/natcos
Authorization: Bearer <access_token>  (Admin only)

Response: 200 OK
{
  "natcos": [
    {"id": 1, "code": "EU", "name": "Europe"}
  ]
}
```

### Pattern Analyzer preview (admin)

Same scan semantics as the user `POST /api/projects/<project_id>/regex-scan`, but resolves disk paths using the **project owner** from the database so admins can preview patterns against another user’s uploads.

```http
GET /api/admin/projects/<project_id>/cpes
GET /api/admin/projects/<project_id>/files?cpe_id=<optional>
Authorization: Bearer <access_token>  (Admin only)

POST /api/admin/projects/<project_id>/regex-scan?cpe_id=<optional>
GET /api/admin/projects/<project_id>/regex-scan/<scan_id>/progress?cpe_id=<optional>
GET /api/admin/projects/<project_id>/regex-scan/<scan_id>/results?cpe_id=<optional>
```

Request and response bodies match the user-facing regex-scan endpoints.

### Review Pattern Submissions

```http
GET /api/admin/pattern-submissions?status=pending
Authorization: Bearer <access_token>  (Admin only)

Response: 200 OK
{
  "submissions": [...]
}
```

---

## Error Codes

| Code | Meaning |
|------|---------|
| 200 | OK - Request successful |
| 201 | Created - Resource created |
| 202 | Accepted - Async task started |
| 400 | Bad Request - Invalid parameters |
| 401 | Unauthorized - Invalid/missing token |
| 403 | Forbidden - Access denied |
| 404 | Not Found - Resource doesn't exist |
| 413 | Payload Too Large - File too big |
| 500 | Internal Server Error |

## Error Response Format

```json
{
  "error": "Error message",
  "details": "Additional context (optional)"
}
```

---

## Rate Limiting

Currently no rate limiting implemented. Consider adding for production:
- 100 requests/minute per user
- 10 file uploads/hour per user

## Pagination

List endpoints support pagination:

```http
GET /api/endpoint?page=1&page_size=50

Response:
{
  "items": [...],
  "page": 1,
  "page_size": 50,
  "total_items": 234,
  "total_pages": 5
}
```

## Related Documentation

- [Architecture](./ARCHITECTURE.md) - System design
- [Features](./FEATURES.md) - Feature catalog
- [Quick Start](./QUICK_START.md) - Setup guide
- [Environment Variables](./ENVIRONMENT_VARIABLES.md) - Configuration

---

**Last Updated:** March 13, 2024  
**API Version:** 1.0.0

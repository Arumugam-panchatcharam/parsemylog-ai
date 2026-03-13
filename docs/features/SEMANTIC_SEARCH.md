# Semantic Search (AI Analysis)

## Overview

The Semantic Search module enables natural language querying of log patterns using vector embeddings and similarity search. Instead of exact keyword matching, it finds logs by **meaning**, making it easier to discover related issues and patterns.

## How It Works

### Pipeline Architecture

```
User Query                BGE Model              Qdrant
"WiFi disconnects"  →  [0.23, -0.45, ...]  →  Cosine Search  →  Results
                         (384-dim vector)        Top-K matches
```

### Components

1. **BGE Embeddings (BAAI/bge-small-en-v1.5)**
   - 384-dimensional dense vectors
   - Trained on 1B+ sentence pairs
   - Optimized for semantic similarity

2. **Qdrant Vector Database**
   - Per-project+CPE collections
   - HNSW index for fast approximate search
   - Cosine similarity metric

3. **Template Storage**
   - Drain3-extracted log templates
   - Associated metadata (domain, frequency, sample logs)
   - Indexed during log upload/processing

## Usage

### Basic Search

**UI:**
```
┌──────────────────────────────────────────────────┐
│ Search Query                                     │
│ ┌──────────────────────────────────────────────┐ │
│ │ WiFi connection failures                     │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ Results: 10  Domain: All  [Search]              │
└──────────────────────────────────────────────────┘
```

**API:**
```http
POST /api/<project_id>/ai-analysis/search?cpe_id=<cpe_id>
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "query": "WiFi connection failures",
  "top_k": 10,
  "domain": null  // or "wifi", "platform", etc.
}
```

**Response:**
```json
{
  "results": [
    {
      "template": "[wifi] ERROR: Failed to connect to SSID <*> (code: <*>)",
      "score": 0.92,
      "domain": "wifi",
      "frequency": 324,
      "sample_logs": [
        "2024-03-13 14:32:10 [wifi] ERROR: Failed to connect to SSID MyNetwork (code: 12)",
        "2024-03-13 14:35:22 [wifi] ERROR: Failed to connect to SSID GuestWiFi (code: 12)"
      ]
    },
    {
      "template": "[wifi] WARNING: Connection timeout for <*>",
      "score": 0.87,
      "domain": "wifi",
      "frequency": 156,
      "sample_logs": [...]
    }
  ],
  "query_time_ms": 45
}
```

### Advanced Search

**With Domain Filter:**
```json
{
  "query": "memory allocation failures",
  "top_k": 15,
  "domain": "platform"  // Only search platform domain
}
```

**With Context Window:**
```json
{
  "query": "reboot causes",
  "top_k": 10,
  "include_context": true,  // Include ±5 lines around matches
  "context_lines": 5
}
```

## Search Examples

### Example 1: Finding WiFi Issues

**Query:** `"WiFi keeps disconnecting"`

**Results:**
```
1. [wifi] ERROR: Failed to connect to SSID <*> (code: <*>)  [Score: 0.92]
   Frequency: 324 occurrences
   Sample: 2024-03-13 14:32:10 [wifi] ERROR: Failed to connect to SSID MyNetwork (code: 12)

2. [wifi] WARNING: Connection timeout for <*>  [Score: 0.87]
   Frequency: 156 occurrences
   Sample: 2024-03-13 14:35:22 [wifi] WARNING: Connection timeout for 192.168.1.1

3. [wifi] INFO: Disconnected from SSID <*> reason=<*>  [Score: 0.85]
   Frequency: 892 occurrences
   Sample: 2024-03-13 14:40:15 [wifi] INFO: Disconnected from SSID MyNetwork reason=4
```

### Example 2: Finding Boot Failures

**Query:** `"system won't boot"`

**Results:**
```
1. [platform] FATAL: Kernel panic - not syncing: <*>  [Score: 0.94]
2. [platform] ERROR: Failed to mount root filesystem  [Score: 0.89]
3. [platform] ERROR: initramfs: unable to find <*>  [Score: 0.86]
```

### Example 3: Network Issues

**Query:** `"internet not working"`

**Results:**
```
1. [core_router] ERROR: WAN interface down  [Score: 0.91]
2. [core_router] WARNING: DHCP client timeout on <*>  [Score: 0.88]
3. [platform] ERROR: DNS resolution failed for <*>  [Score: 0.84]
```

## Indexing Process

### When Are Logs Indexed?

**Automatic Indexing:**
- After file upload completes
- During Drain3 template extraction
- Per domain (wifi, platform, cellular, etc.)

**Manual Re-Indexing:**
- From Pattern Analysis page
- Click "Re-index" button
- Useful after Drain3 config changes

### Indexing Pipeline

```
1. Upload Complete
   ↓
2. ripgrep Pre-Filter (per domain)
   ↓
3. Drain3 Extract Templates
   ↓
4. Generate BGE Embeddings (batch of 100)
   ↓
5. Upsert to Qdrant Collection
   ↓
6. Ready for Search
```

**Performance:**
- ~50ms per template embedding
- ~100 templates/second
- 1000 templates indexed in ~10 seconds

### Collection Naming

Format: `project_{project_id}_cpe_{cpe_id}`

Example: `project_42_cpe_AABBCCDDEEFF`

**Isolation Benefits:**
- Per-CPE search results
- Easy deletion (drop collection)
- No cross-contamination

## Understanding Similarity Scores

### Score Ranges

| Score | Interpretation |
|-------|----------------|
| 0.9 - 1.0 | Extremely similar (likely same issue) |
| 0.8 - 0.9 | Highly similar (related issue) |
| 0.7 - 0.8 | Moderately similar (may be related) |
| 0.6 - 0.7 | Somewhat similar (check manually) |
| < 0.6 | Not very similar (likely unrelated) |

### Factors Affecting Scores

**High Scores:**
- Exact keyword matches in query and template
- Similar semantic meaning (e.g., "disconnect" ≈ "connection lost")
- Related technical terms (e.g., "WiFi" ≈ "wireless" ≈ "WLAN")

**Lower Scores:**
- Different domains (WiFi query, platform result)
- Ambiguous queries ("errors")
- Generic templates ("[<*>] <*>")

## Query Tips

### ✅ Good Queries

**Specific and descriptive:**
```
"WiFi connection failures with timeout"
"kernel panic out of memory"
"DHCP lease renewal failed"
"cellular modem not responding"
```

**Action-oriented:**
```
"system reboot causes"
"interface going down"
"authentication failures"
```

### ❌ Poor Queries

**Too generic:**
```
"errors"           # Too broad
"logs"             # Meaningless
"problems"         # Ambiguous
```

**Single keywords:**
```
"WiFi"             # Use Grep instead
"ERROR"            # Use Log Viewer filters
"IP"               # Too vague
```

**Questions (rephrase as statements):**
```
❌ "Why did the system reboot?"
✅ "system reboot causes"

❌ "What's wrong with WiFi?"
✅ "WiFi connection issues"
```

## Advanced Features

### Context Window

**Enable Context:**
```json
{
  "query": "reboot",
  "include_context": true,
  "context_lines": 5
}
```

**Result with Context:**
```
Template: [platform] INFO: Reboot triggered by <*>
Sample with context:

  [Line 1234] 2024-03-13 14:30:05 [wifi] WARNING: Signal strength degrading
  [Line 1235] 2024-03-13 14:30:10 [platform] ERROR: Watchdog timeout
  [Line 1236] 2024-03-13 14:30:12 [platform] ERROR: Failed to recover
  [Line 1237] 2024-03-13 14:30:15 [platform] INFO: Reboot triggered by watchdog  ← MATCH
  [Line 1238] 2024-03-13 14:30:16 [platform] INFO: Shutting down services
  [Line 1239] 2024-03-13 14:30:18 [platform] INFO: Unmounting filesystems
  [Line 1240] 2024-03-13 14:30:20 [platform] INFO: System halt
```

### Parameter Extraction

**On-Demand Extraction:**
```json
{
  "query": "connection failed",
  "extract_parameters": true
}
```

**Result:**
```json
{
  "template": "[wifi] ERROR: Failed to connect to SSID <*> (code: <*>)",
  "parameters": {
    "SSID": ["MyNetwork", "GuestWiFi", "Office5G"],
    "code": ["12", "15", "20"]
  },
  "parameter_distribution": {
    "code": {
      "12": 234,  // Most common
      "15": 67,
      "20": 23
    }
  }
}
```

## Troubleshooting

### Issue: No Results Found

**Possible Causes:**
1. Logs not indexed yet (check indexing status)
2. Query too specific or uses uncommon terms
3. Domain filter too restrictive
4. CPE has no matching templates

**Solutions:**
1. Check indexing status: `GET /api/<project_id>/embedding/status`
2. Broaden query ("WiFi disconnect" → "WiFi connection")
3. Remove domain filter
4. Try different CPE

### Issue: Irrelevant Results

**Possible Causes:**
1. Query too generic
2. Low similarity threshold
3. Templates are very generic

**Solutions:**
1. Use more specific terms
2. Increase `min_score` parameter:
   ```json
   {"query": "...", "min_score": 0.8}
   ```
3. Filter by domain

### Issue: Slow Search

**Expected Performance:**
- <100ms for 1,000 templates
- <500ms for 10,000 templates
- <2s for 100,000 templates

**If Slower:**
1. Check Qdrant health: `curl http://localhost:6333/health`
2. Restart Qdrant: `docker compose restart qdrant`
3. Check Qdrant logs: `docker compose logs qdrant`

## API Reference

### Search

```http
POST /api/<project_id>/ai-analysis/search
Authorization: Bearer <access_token>
Content-Type: application/json

Body:
{
  "query": "string (required)",
  "cpe_id": "string (optional, defaults to selected CPE)",
  "top_k": 10,
  "domain": "wifi|platform|cellular|mesh|core_router|null",
  "min_score": 0.0,
  "include_context": false,
  "context_lines": 5,
  "extract_parameters": false
}

Response:
{
  "results": [
    {
      "template": "string",
      "score": float,
      "domain": "string",
      "frequency": int,
      "sample_logs": ["string"],
      "context": {
        "before": ["string"],
        "after": ["string"]
      },
      "parameters": {
        "param_name": ["value1", "value2"]
      }
    }
  ],
  "query_time_ms": int,
  "total_templates": int
}
```

### Get Indexing Status

```http
GET /api/<project_id>/embedding/status?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response:
{
  "indexed": true,
  "total_templates": 1543,
  "indexed_at": "2024-03-13T14:35:22Z",
  "collection_name": "project_42_cpe_AABBCCDDEEFF",
  "domains": {
    "wifi": 423,
    "platform": 687,
    "cellular": 289,
    "mesh": 144
  }
}
```

### Trigger Re-Indexing

```http
POST /api/<project_id>/embedding/reindex?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response:
{
  "message": "Re-indexing started",
  "task_id": "abc123"
}
```

## Performance Optimization

### For Large Projects

**Use Domain Filters:**
```json
{"query": "...", "domain": "wifi"}
```
Searches 500 templates instead of 5000.

**Reduce Top-K:**
```json
{"query": "...", "top_k": 5}
```
Faster retrieval, less data transfer.

**Disable Context:**
```json
{"include_context": false}
```
Saves file I/O for context extraction.

### For Many CPEs

**Batch Searches:**
```python
for cpe_id in cpe_ids:
    search(query, cpe_id=cpe_id)  # Parallel requests
```

**Use CPE Overview:**
Aggregate search results across CPEs in one API call.

## Related Features

- [Drain3 Pattern Analysis](./DRAIN3_PATTERNS.md) - Template extraction
- [Pattern Analyzer](./PATTERN_ANALYZER.md) - Regex-based search
- [Log Viewer](./LOG_VIEWER.md) - Browse raw logs
- [CPE Overview](./CPE_OVERVIEW.md) - Cross-CPE search

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)

# Drain3 Pattern Analysis

## Overview

Drain3 is an online log parsing algorithm that automatically extracts templates from unstructured log messages by replacing variable parts with wildcards. This feature provides frequency analysis, parameter extraction, and per-domain template visualization.

## Key Capabilities

- **Automatic Template Extraction** from raw log lines
- **Per-Domain Processing** (wifi, platform, cellular, mesh, core_router)
- **Frequency Analysis** to identify common patterns
- **Parameter Extraction** to analyze variable values
- **State Persistence** for incremental updates
- **Export** templates to CSV/JSON
- **Filtering** by domain, frequency threshold, or pattern

## How It Works

### Drain3 Algorithm

**Concept:**
Drain3 groups similar log messages into clusters by building a parse tree based on log structure.

**Example:**

```
Input Logs:
1. [wifi] ERROR: Failed to connect to SSID MyNetwork (code: 12)
2. [wifi] ERROR: Failed to connect to SSID GuestWiFi (code: 12)
3. [wifi] ERROR: Failed to connect to SSID Office5G (code: 15)

Drain3 Output:
Template: [wifi] ERROR: Failed to connect to SSID <*> (code: <*>)
Frequency: 3
Parameters:
  - SSID: ["MyNetwork", "GuestWiFi", "Office5G"]
  - code: ["12", "12", "15"]
```

### Architecture

```
Upload → ripgrep Pre-Filter → Drain3 Extract → Templates
                  ↓                              ↓
            domain_rg.parquet        drain3_state_{domain}.bin
```

**Pipeline:**

1. **ripgrep Pre-Filter:**
  - Scan logs with domain-specific YAML patterns
  - Filter only error/warning lines (6-10x speedup)
  - Cache to `domain_rg.parquet`
2. **Drain3 Processing:**
  - Load domain-specific state file (if exists)
  - Feed filtered lines to Drain3
  - Extract templates with wildcards
  - Save updated state
3. **Template Storage:**
  - Persist state to `drain3_state_{domain}.bin`
  - Cache templates for quick retrieval
  - Store frequency counts

### Configuration

**File:** `drain3.ini`

```ini
[DRAIN]
sim_th = 0.5          # Similarity threshold (0.0-1.0)
depth = 8             # Parse tree depth
max_clusters = 1024   # Maximum number of templates
max_children = 100    # Max children per tree node

[MASKING]
# Regex patterns for variable identification
masking = [
    {"regex_pattern": "\\d+\\.\\d+\\.\\d+\\.\\d+", "mask_with": "<IP>"},
    {"regex_pattern": "([0-9A-F]{2}:){5}[0-9A-F]{2}", "mask_with": "<MAC>"},
    {"regex_pattern": "\\d{4}-\\d{2}-\\d{2}", "mask_with": "<DATE>"},
    {"regex_pattern": "\\d+", "mask_with": "<NUM>"}
]
```

**Key Parameters:**

- **sim_th (0.0-1.0):** Lower = more granular templates
  - 0.3: Very strict, many templates
  - 0.5: Balanced (recommended)
  - 0.7: Lenient, fewer templates
- **depth (4-10):** Tree depth affects grouping
  - 4: Fast, less accurate
  - 8: Balanced (recommended)
  - 10: Slow, more accurate
- **max_clusters:** Limit number of templates
  - 512: Small projects
  - 1024: Medium projects (recommended)
  - 2048: Large projects

## Usage

### View Templates

**UI Navigation:**

1. Go to project
2. Select CPE
3. Click "Pattern Analysis" in sidebar
4. Templates load automatically

**Template List:**

```
┌──────────────────────────────────────────────────────────────┐
│ Pattern Analysis - CPE: AABBCCDDEEFF                         │
│ Domain: [All ▼]  Min Frequency: [10─────]                    │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ 1. [wifi] ERROR: Failed to connect to SSID <*> (code: <*>)   │
│    Frequency: 324 | Domain: wifi                             │
│    [📊 Parameters] [📋 Sample Logs] [📍 Show in Viewer]      │
│                                                              │
│ 2. [platform] Kernel panic - not syncing: <*>                │
│    Frequency: 12 | Domain: platform                          │
│    [📊 Parameters] [📋 Sample Logs] [📍 Show in Viewer]      │
│                                                              │
│ 3. [dhcp] DHCP timeout for interface <*>                     │
│    Frequency: 89 | Domain: core_router                       │
│    [📊 Parameters] [📋 Sample Logs] [📍 Show in Viewer]      │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Extract Parameters

Click "📊 Parameters" to expand:

```
Template: [wifi] ERROR: Failed to connect to SSID <*> (code: <*>)

Parameters:
  Parameter 1 (SSID):
    - MyNetwork: 234 occurrences
    - GuestWiFi: 67 occurrences
    - Office5G: 23 occurrences
  
  Parameter 2 (code):
    - 12: 289 occurrences
    - 15: 24 occurrences
    - 20: 11 occurrences

[📥 Export Parameters to CSV]
```

### View Sample Logs

Click "📋 Sample Logs":

```
Sample logs matching this template:

2024-03-13 14:32:10 [wifi] ERROR: Failed to connect to SSID MyNetwork (code: 12)
2024-03-13 14:35:22 [wifi] ERROR: Failed to connect to SSID GuestWiFi (code: 12)
2024-03-13 14:38:45 [wifi] ERROR: Failed to connect to SSID Office5G (code: 15)
... (showing 3 of 324 matches)

[📖 Show All in Log Viewer]
```

### Filter Templates

**By Domain:**

```
Domain: [wifi ▼]
```

Shows only templates from wifi domain.

**By Frequency:**

```
Min Frequency: [50─────]
```

Shows only templates appearing ≥50 times.

**By Pattern:**

```
Search: [timeout────] [🔍]
```

Filter templates containing "timeout".

### Export Templates

**CSV Export:**

```csv
Domain,Template,Frequency,Parameters
wifi,"[wifi] ERROR: Failed to connect to SSID <*> (code: <*>)",324,"SSID:MyNetwork,GuestWiFi,Office5G;code:12,15,20"
platform,"Kernel panic - not syncing: <*>",12,"reason:Out of memory,Watchdog timeout"
```

**JSON Export:**

```json
{
  "templates": [
    {
      "domain": "wifi",
      "template": "[wifi] ERROR: Failed to connect to SSID <*> (code: <*>)",
      "frequency": 324,
      "parameters": {
        "param_1": ["MyNetwork", "GuestWiFi", "Office5G"],
        "param_2": ["12", "15", "20"]
      },
      "sample_logs": [...]
    }
  ]
}
```

## API Reference

### Get Templates

```http
GET /api/<project_id>/patterns?cpe_id=<cpe_id>&domain=wifi&min_freq=10
Authorization: Bearer <access_token>

Query Parameters:
  - cpe_id: CPE identifier (required)
  - domain: Filter by domain (optional)
  - min_freq: Minimum frequency (default: 1)
  - search: Search pattern (optional)

Response:
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
    "platform": 234,
    "cellular": 186
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

Response:
{
  "template": "[wifi] ERROR: Failed to connect to SSID <*> (code: <*>)",
  "parameters": [
    {
      "position": 1,
      "values": {
        "MyNetwork": 234,
        "GuestWiFi": 67,
        "Office5G": 23
      }
    },
    {
      "position": 2,
      "values": {
        "12": 289,
        "15": 24,
        "20": 11
      }
    }
  ]
}
```

### Re-Index Patterns

```http
POST /api/<project_id>/patterns/reindex?cpe_id=<cpe_id>&domain=wifi
Authorization: Bearer <access_token>

Response:
{
  "message": "Re-indexing started",
  "task_id": "xyz789",
  "estimated_time_seconds": 120
}
```

### Export Templates

```http
GET /api/<project_id>/patterns/export?cpe_id=<cpe_id>&format=csv
Authorization: Bearer <access_token>

Response:
Content-Type: text/csv
Content-Disposition: attachment; filename="templates_AABBCCDDEEFF.csv"

<CSV content>
```

## Performance Considerations

### Indexing Speed

**Factors:**

- Log volume: 1M lines = ~2-5 minutes
- Domain count: 5 domains = ~10-25 minutes total
- CPU: More cores = faster (parallel domain processing)

**Optimization:**

- Use ripgrep pre-filtering (6-10x speedup)
- Increase `max_clusters` for large projects
- Process domains in parallel

### State File Size


| Log Lines | Templates | State File Size |
| --------- | --------- | --------------- |
| 100K      | 50        | 100 KB          |
| 1M        | 500       | 1 MB            |
| 10M       | 1000      | 10 MB           |


**Storage Requirements:**

- Per-domain state files
- State files grow logarithmically with log volume
- Typical project: 5 domains × 2 MB = 10 MB total

## Troubleshooting

### Issue: Too many templates

**Cause:** `sim_th` too low or logs very diverse

**Solution:**
Increase similarity threshold in `drain3.ini`:

```ini
sim_th = 0.7  # More lenient grouping
```

Then re-index.

### Issue: Templates too generic

**Cause:** `sim_th` too high

**Solution:**
Decrease similarity threshold:

```ini
sim_th = 0.3  # Stricter grouping
```

### Issue: Indexing stuck

**Possible Causes:**

1. Very large file
2. Complex log patterns
3. Insufficient memory

**Debug:**

```bash
# Check process
docker compose logs logai-api | grep "Drain3"

# Check memory
docker stats logai-api
```

**Solution:**
Increase timeout and memory:

```yaml
# docker-compose.yml
services:
  logai-api:
    deploy:
      resources:
        limits:
          memory: 4G
```

### Issue: Parameters not extracted

**Cause:** No variable parts in template

**Example:**

```
Template: [wifi] INFO: Startup complete
```

No wildcards = no parameters.

**Verify:** Check if template has `<*>` wildcards.

## Best Practices

### Tuning Drain3

**Start with defaults:**

```ini
sim_th = 0.5
depth = 8
max_clusters = 1024
```

**Adjust based on results:**


| Issue                      | Adjustment                      |
| -------------------------- | ------------------------------- |
| Too many similar templates | Increase `sim_th` to 0.6-0.7    |
| Missing important patterns | Decrease `sim_th` to 0.3-0.4    |
| Slow indexing              | Decrease `depth` to 6           |
| Hitting cluster limit      | Increase `max_clusters` to 2048 |


### Domain Organization

**Separate domains by:**

- Log source (wifi, platform, cellular)
- Subsystem (dhcp, dns, firewall)
- Severity (errors only, warnings+errors)

**Example ripgrep patterns:**

```yaml
# wifi.yaml
domain: wifi
files: ["WiFilog.txt", "wireless*.log"]
regex: ["ERROR|WARNING|FATAL"]

# platform.yaml
domain: platform
files: ["Consolelog.txt", "kernel*.log"]
regex: ["kernel panic|segfault|OOM"]
```

### Parameter Analysis

**Useful for:**

- Identifying most common error codes
- Finding problematic SSIDs/interfaces
- Analyzing IP address patterns
- Detecting anomalies in parameters

**Export and analyze:**

```bash
# Export to CSV
curl -o templates.csv "http://localhost:40901/api/42/patterns/export?cpe_id=AABBCCDDEEFF&format=csv"

# Analyze with pandas
import pandas as pd
df = pd.read_csv('templates.csv')
print(df.groupby('Domain')['Frequency'].sum())
```

## Related Features

- [Semantic Search](./SEMANTIC_SEARCH.md) - Vector-based search of templates
- [Pattern Analyzer](./PATTERN_ANALYZER.md) - Regex-based scanning
- [Log Viewer](./LOG_VIEWER.md) - View raw logs
- [File Upload](./FILE_UPLOAD.md) - Triggers indexing

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)
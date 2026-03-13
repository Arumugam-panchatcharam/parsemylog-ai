# Multi-CPE Support

## Overview

ParseMyLog-AI provides comprehensive multi-CPE (Customer Premises Equipment) support, allowing you to analyze logs from multiple devices simultaneously with complete isolation between them. Each CPE is automatically detected, processed independently, and can be compared across a fleet.

## Key Capabilities

- **Automatic CPE Detection** from filenames (MAC addresses or serial numbers)
- **Isolated Processing** with per-CPE directories, caches, and vector collections
- **CPE Selector** on all analysis pages for context switching
- **CPE Overview Dashboard** for cross-device comparison
- **Fleet-Level Analytics** with aggregated metrics
- **Batch Processing** for large-scale CPE analysis

## CPE Detection

### Automatic Identification

CPE identifiers are extracted from uploaded tarball filenames using pattern matching:

**Supported Patterns:**

| Pattern | Example Filename | Extracted CPE ID |
|---------|-----------------|------------------|
| MAC with colons | `logs_mac_AA:BB:CC:DD:EE:FF.tgz` | `AABBCCDDEEFF` |
| MAC with hyphens | `logs_mac_AA-BB-CC-DD-EE-FF.tgz` | `AABBCCDDEEFF` |
| MAC no separator | `logs_mac_AABBCCDDEEFF.tgz` | `AABBCCDDEEFF` |
| Serial number | `cpe_serial_1234567890.tgz` | `1234567890` |
| Serial only | `1234567890_logs.tgz` | `1234567890` |

**Normalization:**
- MAC addresses: uppercase, no separators (e.g., `AABBCCDDEEFF`)
- Serial numbers: as-is from filename

### Database Schema

**ProjectCPE Table:**
```sql
CREATE TABLE project_cpes (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    cpe_identifier VARCHAR(255) NOT NULL,
    source_file VARCHAR(512) NOT NULL,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSON,  -- Device info, firmware version, etc.
    FOREIGN KEY (project_id) REFERENCES projects(id),
    UNIQUE(project_id, cpe_identifier)
);
```

**Example Records:**
```json
[
  {
    "id": 1,
    "project_id": 42,
    "cpe_identifier": "AABBCCDDEEFF",
    "source_file": "logs_mac_AA:BB:CC:DD:EE:FF_2024-03-13.tgz",
    "detected_at": "2024-03-13T14:32:10Z",
    "metadata": {
      "model": "RDK-B Gateway",
      "firmware": "24.02.1.5"
    }
  }
]
```

## Isolated Processing

### Directory Structure

Each CPE gets its own isolated directory tree:

```
user_uploads/
└── user_{user_id}/
    └── project_{project_id}/
        ├── SERIAL_OR_MAC_AABBCCDDEEFF/
        │   ├── files/                    # Extracted log files
        │   │   ├── ArmConsolelog.txt
        │   │   ├── Consolelog.txt
        │   │   └── WiFilog.txt
        │   ├── merged_logs.txt           # Chronologically merged
        │   ├── domain_rg.parquet         # Pre-filtered logs
        │   ├── drain3_state_wifi.bin     # Per-domain Drain3 states
        │   ├── drain3_state_platform.bin
        │   ├── reboot_events.json        # Detected reboots
        │   └── telemetry_parsed.json     # Parsed telemetry
        │
        └── SERIAL_OR_MAC_1234567890/
            ├── files/
            ├── merged_logs.txt
            └── ...
```

**Benefits:**
- No cross-contamination between CPEs
- Independent cache invalidation
- Easy per-CPE cleanup
- Parallel processing

### Qdrant Collections

**Collection Naming:** `project_{project_id}_cpe_{cpe_id}`

**Examples:**
- `project_42_cpe_AABBCCDDEEFF`
- `project_42_cpe_1234567890`

**Isolation Benefits:**
- Semantic search scoped to single CPE
- Independent embedding indices
- Easy CPE deletion (drop collection)
- Per-CPE vector statistics

### Drain3 State Files

**Per-Domain States:** `drain3_state_{domain}.bin`

**Example:**
```
SERIAL_OR_MAC_AABBCCDDEEFF/
├── drain3_state_wifi.bin        # WiFi log templates
├── drain3_state_platform.bin    # Platform log templates
├── drain3_state_cellular.bin    # Cellular log templates
└── ...
```

**Why Per-Domain:**
- Domain-specific log structures
- Independent template mining
- Faster convergence
- Better accuracy

**State Persistence:**
- Saved after each indexing run
- Loaded on subsequent runs
- Enables incremental updates
- Crash-safe (atomic writes)

## CPE Selector

### User Interface

All analysis pages include a CPE selector in the top bar:

```
┌──────────────────────────────────────────────────────┐
│  Project: Fleet Analysis         CPE: [AABBCCDDEEFF▼]│
│  ┌──────────────────────────────────────────────┐    │
│  │  Select CPE:                                  │    │
│  │  ○ AABBCCDDEEFF (MAC: AA:BB:CC:DD:EE:FF)     │    │
│  │  ○ 1234567890  (Serial: 1234567890)          │    │
│  │  ○ FFEEDDCCBBAA (MAC: FF:EE:DD:CC:BB:AA)     │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### Context Switching

**Implementation:**
```tsx
// React context for CPE selection
const CpeContext = createContext<{
  selectedCpe: string | null;
  setSelectedCpe: (cpeId: string) => void;
  availableCpes: ProjectCPE[];
}>();

// Usage in pages
const { selectedCpe } = useCpe();

// API calls automatically use selected CPE
const { data } = useQuery({
  queryKey: ['patterns', projectId, selectedCpe],
  queryFn: () => patternsApi.getPatterns(projectId, selectedCpe)
});
```

**URL Persistence:**
```
/project/42/patterns?cpe=AABBCCDDEEFF
```

### Pages with CPE Support

| Page | CPE Selector | Description |
|------|--------------|-------------|
| **Log Viewer** | ✅ | View logs for selected CPE |
| **Pattern Analysis** | ✅ | Drain3 templates for selected CPE |
| **Telemetry Dashboard** | ✅ | Telemetry metrics for selected CPE |
| **Semantic Search** | ✅ | Search logs of selected CPE |
| **Pattern Analyzer** | ✅ | Regex scan for selected CPE |
| **Knowledge Graph** | ✅ | Event graph for selected CPE |
| **CPE Overview** | ❌ | Compares ALL CPEs |
| **Batch Jobs** | ❌ | Processes multiple CPEs |

## CPE Metadata

### Extraction

Metadata is automatically extracted from logs during processing:

**Sources:**
1. `device_info.txt` file (if present)
2. Telemetry reports (Device.DeviceInfo.* parameters)
3. Log headers (model, firmware in first lines)

**Example Extraction:**
```python
# From Telemetry_2.0 report
metadata = {
    "model": "Device.DeviceInfo.ModelName",
    "firmware": "Device.DeviceInfo.SoftwareVersion",
    "serial": "Device.DeviceInfo.SerialNumber",
    "manufacturer": "Device.DeviceInfo.Manufacturer",
    "uptime": "Device.DeviceInfo.UpTime",
    "mac": "Device.DeviceInfo.MACAddress"
}
```

### Display

**CPE Card:**
```
┌─────────────────────────────────────────────┐
│  CPE: AABBCCDDEEFF                          │
│  ─────────────────────────────────────────  │
│  MAC:          AA:BB:CC:DD:EE:FF            │
│  Model:        RDK-B Gateway v2             │
│  Firmware:     24.02.1.5                    │
│  Manufacturer: TechVendor Inc.              │
│  Uptime:       142h 35m                     │
│  Logs:         1.2M lines                   │
│  Last Reboot:  2024-03-13 14:32:10          │
└─────────────────────────────────────────────┘
```

## Cross-CPE Comparison

### CPE Overview Dashboard

**Purpose:** Compare metrics and patterns across all CPEs in a project

**Key Features:**

1. **Device Comparison Table:**
   ```
   │ CPE ID       │ Model      │ Firmware  │ Uptime  │ Reboots │
   │──────────────│────────────│───────────│─────────│─────────│
   │ AABBCCDDEEFF │ Gateway v2 │ 24.02.1.5 │ 142h    │ 3       │
   │ 1234567890   │ Gateway v2 │ 24.02.1.4 │ 87h     │ 7       │
   │ FFEEDDCCBBAA │ Gateway v3 │ 24.03.0.2 │ 234h    │ 1       │
   ```

2. **Reboot Count Comparison:**
   - Bar chart showing reboot counts per CPE
   - Identify problematic devices
   - Trend over time

3. **Error Distribution:**
   - Pie chart: error patterns by domain per CPE
   - Identify common issues across fleet
   - Highlight CPE-specific anomalies

4. **Telemetry Comparison:**
   - Multi-line charts (one line per CPE)
   - Compare signal strength, throughput, CPU usage
   - Spot outlier devices

**API Endpoint:**
```http
GET /api/<project_id>/cpe-overview
Authorization: Bearer <access_token>

Response:
{
  "cpes": [
    {
      "cpe_id": "AABBCCDDEEFF",
      "metadata": {...},
      "stats": {
        "total_lines": 1234567,
        "reboot_count": 3,
        "error_count": 4523,
        "domains": {
          "wifi": 1892,
          "platform": 1456,
          "cellular": 1175
        }
      }
    }
  ],
  "aggregated": {
    "total_reboots": 11,
    "avg_uptime_hours": 154.3,
    "common_patterns": [...]
  }
}
```

### Fleet-Level Patterns

**Identify Common Issues:**
```python
# Find patterns appearing in >50% of CPEs
common_patterns = []
for pattern in all_patterns:
    cpe_count = count_cpes_with_pattern(pattern)
    if cpe_count / total_cpes > 0.5:
        common_patterns.append(pattern)
```

**Highlight Outliers:**
```python
# CPEs with significantly more errors than average
avg_errors = mean([cpe.error_count for cpe in cpes])
std_errors = stdev([cpe.error_count for cpe in cpes])

outliers = [
    cpe for cpe in cpes
    if cpe.error_count > avg_errors + 2 * std_errors
]
```

## Batch Processing

### Use Case

Process logs from 100+ CPEs without blocking the UI

**Workflow:**

1. Place CPE tarballs in `batch_cpe_logs/` directory
2. Create batch job via API or UI
3. Celery worker processes each CPE sequentially
4. Results aggregated and stored in database
5. Download summary report

**API:**
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
  "job_id": "abc123",
  "total_files": 156,
  "status": "queued"
}
```

**Progress Tracking:**
```http
GET /api/batch-jobs/abc123

Response:
{
  "job_id": "abc123",
  "status": "running",
  "progress": 45,  // %
  "processed": 70,
  "failed": 2,
  "remaining": 84,
  "estimated_completion": "2024-03-13T16:45:00Z"
}
```

See [Batch Processing](./BATCH_PROCESSING.md) for full documentation.

## Performance Considerations

### Scalability

**Current Performance:**
- 100 CPEs: <5 minutes indexing (parallel)
- 1000 CPEs: <30 minutes indexing (batch mode)

**Bottlenecks:**
- Embedding generation (CPU-bound)
- Disk I/O for large log files
- SQLite write concurrency (use PostgreSQL for >100 CPEs)

**Optimization:**
- Use batch processing for large fleets
- Enable GPU for embedding generation (10x speedup)
- Increase Celery worker concurrency

### Storage Requirements

**Per CPE:**
- Logs: 10-500 MB (compressed)
- Extracted: 50-2000 MB
- Caches: 5-50 MB (parquet)
- Drain3 states: 1-10 MB
- Qdrant vectors: 2-20 MB

**Example:**
- 100 CPEs × 100 MB average = 10 GB
- 1000 CPEs × 100 MB average = 100 GB

**Recommendations:**
- Archive old CPE data after analysis
- Use external storage (S3) for >1000 CPEs
- Enable log rotation

## API Reference

### List CPEs

```http
GET /api/<project_id>/cpes
Authorization: Bearer <access_token>

Response:
{
  "cpes": [
    {
      "cpe_id": "AABBCCDDEEFF",
      "source_file": "logs_mac_AA:BB:CC:DD:EE:FF.tgz",
      "detected_at": "2024-03-13T14:32:10Z",
      "metadata": {...}
    }
  ]
}
```

### Get CPE Details

```http
GET /api/<project_id>/cpes/<cpe_id>
Authorization: Bearer <access_token>

Response:
{
  "cpe_id": "AABBCCDDEEFF",
  "metadata": {
    "model": "Gateway v2",
    "firmware": "24.02.1.5",
    ...
  },
  "stats": {
    "total_lines": 1234567,
    "indexed_templates": 543,
    "reboot_count": 3
  }
}
```

### Delete CPE

```http
DELETE /api/<project_id>/cpes/<cpe_id>
Authorization: Bearer <access_token>

Response:
{
  "message": "CPE deleted successfully",
  "freed_space_mb": 234
}
```

## Best Practices

### Naming Conventions

**Use Descriptive Filenames:**
```
✅ logs_mac_AA:BB:CC:DD:EE:FF_site_A_2024-03-13.tgz
✅ cpe_serial_1234567890_customer_XYZ.tar.gz
❌ mylogs.tgz
❌ device1.tgz
```

### Fleet Management

**Group by Deployment:**
- Create separate projects for different sites/regions
- Use consistent naming (site codes in filenames)
- Tag CPEs with metadata (location, customer, firmware)

**Regular Cleanup:**
- Archive CPEs not analyzed in 30+ days
- Delete test CPEs after debugging
- Monitor disk usage alerts

### Comparison Analysis

**Compare Similar CPEs:**
- Same model and firmware version
- Same deployment region
- Similar network configuration

**Identify Patterns:**
- Common errors across all CPEs → likely firmware bug
- Errors in single CPE → hardware or local issue
- Errors in subset → regional or config issue

## Troubleshooting

### Issue: CPE not detected

**Check:**
1. Filename contains MAC or serial
2. Pattern is recognized (see [Supported Patterns](#automatic-identification))
3. No filename corruption

**Solution:**
Rename file to match pattern:
```bash
mv ambiguous_logs.tgz logs_mac_AABBCCDDEEFF.tgz
```

### Issue: Wrong CPE selected

**Cause:** CPE context not persisted across page navigation

**Solution:**
1. Check URL includes `?cpe=AABBCCDDEEFF`
2. Clear browser cache
3. Re-select CPE from dropdown

### Issue: Missing CPE in selector

**Possible Causes:**
1. Upload not completed
2. Extraction failed
3. CPE ID conflict (duplicate)

**Debug:**
```http
GET /api/<project_id>/cpes
# Check if CPE exists in response
```

## Related Features

- [File Upload & Extraction](./FILE_UPLOAD.md) - CPE detection during upload
- [CPE Overview](./CPE_OVERVIEW.md) - Cross-CPE comparison dashboard
- [Batch Processing](./BATCH_PROCESSING.md) - Process multiple CPEs
- [Semantic Search](./SEMANTIC_SEARCH.md) - Per-CPE search

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)

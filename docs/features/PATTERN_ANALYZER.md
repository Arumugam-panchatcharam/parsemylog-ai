# Pattern Analyzer (ripgrep)

## Overview

The Pattern Analyzer provides high-speed regex pattern management and scanning using ripgrep. It features time-series visualization with reboot markers, reboot window filtering, and NATCO pattern governance integration.

## Key Capabilities

- **Regex Pattern Management** - Create, edit, organize by domain
- **ripgrep Scanning** - Ultra-fast regex matching (10-100x faster than Python)
- **Time-Series Visualization** - Pattern occurrences over time with Plotly
- **Reboot Window Filtering** - Select start/end boundaries, zoom with slider
- **Optional file scope per pattern** — Restrict ripgrep to an uploaded **basename** for each pattern (case-insensitive). Clear errors when that pattern’s basename matches no file.
- **Optional time window per pattern** — `scan_time_range` with naive local start/end filters that pattern’s matches after ripgrep (chart reboot window is separate).
- **Async scan + progress** - `POST …/regex-scan` returns **202** with `scan_id`; poll `GET …/regex-scan/<scan_id>/progress` until `complete`, then load results.
- **NATCO Integration** - Sync patterns from global library
- **Pattern Submission** - Submit local changes for admin review
- **Import/Export** - Multiple format support (JSON, YAML, rule_parser_config)
- **Per-CPE Support** - Scan individual or all CPEs (workspace router context)

## How It Works

### Pattern Storage

**User Patterns:** `user_uploads/user_{id}/project_{id}/user_patterns.yaml`

```yaml
wifi:
  - name: WiFi Connection Failed
    regex: 'Failed to connect to SSID'
    enabled: true
  - name: WiFi Timeout
    regex: 'WiFi.*timeout'
    enabled: true

platform:
  - name: Kernel Panic
    regex: 'kernel panic|Kernel panic'
    enabled: true
  - name: Out of Memory
    regex: 'Out of memory|OOM killer'
    enabled: true
```

### Scanning Pipeline

```
User Patterns → ripgrep → Match Results → Time Series → Charts + Reboot Windows
```

**Step 1: Pattern Compilation**

```python
patterns = load_user_patterns(project_id)
enabled_patterns = [p for p in patterns if p['enabled']]
```

**Step 2: ripgrep Execution**

```bash
rg --json \
   --only-matching \
   --line-number \
   --with-filename \
   -e 'pattern1' -e 'pattern2' \
   merged_logs.txt
```

**Step 3: Result Parsing**

```python
matches = []
for line in rg_output:
    match = json.loads(line)
    if match['type'] == 'match':
        matches.append({
            'line_number': match['line_number'],
            'timestamp': extract_timestamp(match['lines']['text']),
            'pattern_name': identify_pattern(match['match']['text']),
            'text': match['lines']['text']
        })
```

**Step 4: Time Series Aggregation**

```python
# Group by hour
time_series = {}
for match in matches:
    hour = match['timestamp'].replace(minute=0, second=0)
    if hour not in time_series:
        time_series[hour] = {}
    
    pattern_name = match['pattern_name']
    time_series[hour][pattern_name] = time_series[hour].get(pattern_name, 0) + 1
```

## Usage

### Manage Patterns

**Add New Pattern:**

```
┌──────────────────────────────────────────────────────┐
│ Add Pattern                                          │
│ Domain: [wifi ▼]                                     │
│ Name: [WiFi Connection Failed───────────────]        │
│ Regex: [Failed to connect to SSID──────────]         │
│ ☑ Enabled                                            │
│ [Test Pattern] [Save]                                │
└──────────────────────────────────────────────────────┘
```

**Pattern List:**

```
┌──────────────────────────────────────────────────────────┐
│ Pattern Library                                          │
│ Domain: [All ▼] [+ Add Pattern] [📥 Import] [📤 Export]  │
├──────────────────────────────────────────────────────────┤
│ WiFi (3 patterns)                                        │
│   ☑ WiFi Connection Failed                               │
│       Regex: Failed to connect to SSID                   │
│       [✏️ Edit] [🗑️ Delete] [📊 Scan]                    │
│   ☑ WiFi Timeout                                         │
│       Regex: WiFi.*timeout                               │
│       [✏️ Edit] [🗑️ Delete] [📊 Scan]                    │
│   ☐ WiFi Disconnect (disabled)                           │
│       Regex: Disconnected from SSID                      │
│       [✏️ Edit] [🗑️ Delete]                              │
│                                                          │
│ Platform (5 patterns)                                    │
│   ☑ Kernel Panic                                         │
│   ☑ Out of Memory                                        │
│   ...                                                    │
└──────────────────────────────────────────────────────────┘
```

### Scan Logs

Open **Filters** on a pattern row to set **Scan log file** (same file list as Log Viewer; empty = all files for that pattern) and optional **Limit matches to time (local)** (`datetime-local` start/end). Use naive local values (avoid `Date.toISOString()`). For inclusive calendar days, end at `23:59:59` on the last day. Incomplete time fields are omitted on **Save** until both start and end are set.

The **reboot range** and slider still define the **chart** window only.

**Run Scan** starts an async job; the progress bar advances per enabled pattern while ripgrep runs.

**Trigger Scan:**

```
┌──────────────────────────────────────────────────────┐
│ Scan Settings                                        │
│ CPE: [AABBCCDDEEFF ▼]                                │
│ Domains: ☑ wifi  ☑ platform  ☑ cellular              │
│ Time Range: [Last 24 hours ▼]                        │
│ [🔍 Start Scan]                                      │
└──────────────────────────────────────────────────────┘

Scanning... 
✓ WiFi: 234 matches
✓ Platform: 156 matches
✓ Cellular: 89 matches

Scan complete in 2.3s
```

**Scan Results:**

```
┌──────────────────────────────────────────────────────────┐
│ Scan Results - Total: 479 matches                        │
├──────────────────────────────────────────────────────────┤
│                                                          │
│ Pattern: WiFi Connection Failed (234 matches)            │
│ [View Time Series] [View Matches] [Export CSV]           │
│                                                          │
│ Pattern: Kernel Panic (12 matches)                       │
│ [View Time Series] [View Matches] [Export CSV]           │
│                                                          │
│ Pattern: Out of Memory (8 matches)                       │
│ [View Time Series] [View Matches] [Export CSV]           │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Time-Series Visualization

**Chart Display:**

```
Pattern Occurrences Over Time

[Interactive Plotly Chart showing:
 - X-axis: Time (hourly buckets)
 - Y-axis: Match count
 - Multiple lines (one per pattern)
 - Red dashed vertical lines (reboots)
]

Reboot Window Filter:
Start Reboot: [Reboot 1 (14:30) ▼]
End Reboot:   [Reboot 3 (18:45) ▼]

Time Range Slider:
[────●═══════════●────] 14:30 - 18:45
```

**Features:**

- **Zoom:** Click and drag on chart
- **Pan:** Hold shift and drag
- **Legend:** Click to toggle patterns
- **Hover:** See exact counts
- **Reboot Markers:** Red dashed lines

### Reboot Window Filtering

**Use Case:** Focus analysis on specific reboot cycles

**Steps:**

1. Select start reboot from dropdown
2. Select end reboot from dropdown
3. Use slider to fine-tune time range
4. Chart updates automatically

**Example:**

```
Start: Reboot 2 (2024-03-13 16:20)
End:   Reboot 3 (2024-03-13 18:45)

Showing matches between these reboots only.

WiFi Connection Failed: 89 matches (vs 234 total)
Kernel Panic: 3 matches (vs 12 total)
```

### NATCO Integration

**Sync from Global:**

```
┌──────────────────────────────────────────────────────┐
│ NATCO: EU (Europe)                                   │
│ Last Synced: 2 days ago                              │
│                                                      │
│ [🔄 Sync from Global]                                │
│                                                      │
│ Pulls latest patterns from global EU library.        │
│ Your local edits will be preserved.                  │
└──────────────────────────────────────────────────────┘
```

**Submit to Global:**

```
┌──────────────────────────────────────────────────────┐
│ Submit Changes to Global                             │
│                                                      │
│ Changes detected:                                    │
│ ✨ NEW: WiFi 6E Connection Failed                    │
│ ✏️ MODIFIED: WiFi Connection Failed (regex updated)  │
│                                                      │
│ Select patterns to submit:                           │
│ ☑ WiFi 6E Connection Failed                          │
│ ☑ WiFi Connection Failed                             │
│                                                      │
│ [📤 Submit for Review]                               │
└──────────────────────────────────────────────────────┘
```

## API Reference

### Get Patterns

```http
GET /api/<project_id>/regex-patterns
Authorization: Bearer <access_token>

Response:
{
  "patterns": {
    "wifi": [
      {
        "name": "WiFi Connection Failed",
        "regex": "Failed to connect to SSID",
        "enabled": true
      }
    ],
    "platform": [...]
  },
  "natco_id": 1,
  "last_synced": "2024-03-11T10:30:00Z"
}
```

### Save Patterns

```http
PUT /api/<project_id>/regex-patterns
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "patterns": {
    "wifi": [
      {
        "name": "WiFi Connection Failed",
        "regex": "Failed to connect to SSID",
        "enabled": true
      }
    ]
  }
}
```

### Trigger Scan

```http
POST /api/<project_id>/regex-scan
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "cpe_id": "AABBCCDDEEFF",
  "domains": ["wifi", "platform"],
  "time_range": {
    "start": "2024-03-13T14:00:00Z",
    "end": "2024-03-13T20:00:00Z"
  }
}

Response:
{
  "scan_id": "scan_abc123",
  "status": "running",
  "estimated_time_seconds": 5
}
```

### Get Scan Results

```http
GET /api/<project_id>/regex-scan/<scan_id>/results
Authorization: Bearer <access_token>

Response:
{
  "scan_id": "scan_abc123",
  "status": "completed",
  "results": [
    {
      "pattern_name": "WiFi Connection Failed",
      "domain": "wifi",
      "match_count": 234,
      "time_series": [
        {
          "timestamp": "2024-03-13T14:00:00Z",
          "count": 12
        },
        ...
      ],
      "sample_matches": [
        {
          "line_number": 12345,
          "timestamp": "2024-03-13T14:32:10Z",
          "text": "2024-03-13 14:32:10 [wifi] ERROR: Failed to connect to SSID MyNetwork"
        }
      ]
    }
  ],
  "reboot_events": [...]
}
```

### Sync from Global

```http
POST /api/<project_id>/patterns/sync
Authorization: Bearer <access_token>

Response:
{
  "message": "Synced successfully",
  "added": 3,
  "updated": 2,
  "unchanged": 15
}
```

### Submit to Global

```http
POST /api/<project_id>/patterns/submit
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "patterns": [
    {
      "domain": "wifi",
      "name": "WiFi 6E Connection Failed",
      "regex": "Failed to connect.*6GHz",
      "change_type": "new"
    }
  ]
}

Response:
{
  "submission_id": 42,
  "status": "pending",
  "patterns_submitted": 1
}
```

## Performance Considerations

### ripgrep Speed

**Benchmarks:**


| File Size | Lines | Patterns | Time  |
| --------- | ----- | -------- | ----- |
| 10 MB     | 100K  | 10       | <0.5s |
| 100 MB    | 1M    | 10       | <2s   |
| 1 GB      | 10M   | 10       | <15s  |
| 10 GB     | 100M  | 10       | <120s |


**Optimization:**

- Combine related patterns with OR: `(pattern1|pattern2)`
- Use literals for prefix matching: `--fixed-strings`
- Limit context lines: `-C 0` (no context)

### Pattern Complexity

**Fast Patterns:**

```regex
✅ literal_string
✅ ^prefix_match
✅ suffix_match$
✅ (option1|option2|option3)
```

**Slow Patterns:**

```regex
❌ .*wildcard.*wildcard.*
❌ (a+)+b  # Catastrophic backtracking
❌ (?i)case_insensitive  # Slower than default
```

## Troubleshooting

### Issue: Pattern not matching

**Debug:**

1. Test pattern in isolation:
  ```bash
   rg 'your_pattern' merged_logs.txt | head
  ```
2. Check for escaping issues:
  - Special chars: `.` `*` `+` `?` `[` `]` `(` `)` `{` `}` `|` `\`
  - Escape: `\.` `\*` etc.
3. Verify case sensitivity

### Issue: Scan timeout

**Cause:** Very large file or complex patterns

**Solution:**

```yaml
# docker-compose.yml
command: ["gunicorn", "--timeout", "300", ...]
```

### Issue: Time series gaps

**Cause:** No matches in certain time periods

**Expected Behavior:** Gaps in data are normal if pattern didn't occur.

## Best Practices

### Pattern Design

**Good Patterns:**

```yaml
wifi:
  - name: Connection Failed (Specific)
    regex: 'Failed to connect to SSID'
  
  - name: Authentication Error (Specific)
    regex: 'Authentication (failed|timeout)'
  
  - name: Signal Issues (Broad)
    regex: '(weak signal|low RSSI|high noise)'
```

**Avoid:**

```yaml
bad:
  - name: Any Error (Too Broad)
    regex: 'ERROR'
  
  - name: Complex Pattern (Hard to Maintain)
    regex: '^.*\[(wifi|wireless|wlan)\].*ERROR.*connect.*\d+$'
```

### Organization

**Group by:**

- Log source (wifi, platform, cellular)
- Severity (errors, warnings)
- Feature (connection, authentication, roaming)

**Example:**

```yaml
wifi_connection:
  - Connection timeout
  - DHCP failure
  - Authentication error

wifi_performance:
  - Weak signal
  - High retries
  - Channel congestion
```

## Related Features

- [NATCO Governance](./NATCO_GOVERNANCE.md) - Pattern submission workflow
- [Pattern Import/Export](./PATTERN_IMPORT_EXPORT.md) - Bulk operations
- [Drain3 Patterns](./DRAIN3_PATTERNS.md) - Template-based analysis
- [Log Viewer](./LOG_VIEWER.md) - View matched lines

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)
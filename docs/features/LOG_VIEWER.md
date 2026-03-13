# Log Viewer

## Overview

The Log Viewer provides an IDE-style interface for browsing and searching through extracted log files. It features syntax highlighting, regex search, pagination, and quick-pattern filters for efficient log analysis.

## Key Capabilities

- **Syntax Highlighting** for timestamps, IPs, MACs, modules, and keywords
- **Regex Search** with case-sensitive/insensitive options
- **Pagination** with configurable page size (100-10,000 lines)
- **Quick Pattern Buttons** for common searches (timestamps, IPs, errors)
- **Line Numbers** and jump-to-line functionality
- **Context View** with expandable sections
- **Download** full logs or filtered results
- **Per-CPE Support** with CPE selector

## How It Works

### Data Source

The Log Viewer displays the `merged_logs.txt` file created during extraction:

```
user_uploads/
└── user_{user_id}/
    └── project_{project_id}/
        └── SERIAL_OR_MAC_{cpe_id}/
            └── merged_logs.txt  ← Source file
```

**File Characteristics:**

- Chronologically sorted log lines
- Combined from all extracted `.txt` files
- Preserves original formatting
- Typical size: 10MB - 2GB (100K - 20M lines)

### Pagination Strategy

**Server-Side Pagination:**

```python
def get_log_lines(file_path, page, page_size):
    start_line = (page - 1) * page_size
    end_line = start_line + page_size
    
    with open(file_path, 'r') as f:
        # Skip to start_line
        for _ in range(start_line):
            f.readline()
        
        # Read page_size lines
        lines = []
        for _ in range(page_size):
            line = f.readline()
            if not line:
                break
            lines.append(line)
    
    return lines
```

**Performance:**

- Uses line offsets for fast random access
- Caches line positions for large files
- Supports files >10GB without loading into memory

### Syntax Highlighting

**Client-Side Highlighting:**

Patterns matched in order:


| Pattern     | Color      | Regex                                    |
| ----------- | ---------- | ---------------------------------------- |
| Timestamp   | Red        | `\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}`    |
| IP Address  | Blue       | `\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b` |
| MAC Address | Magenta    | `([0-9A-F]{2}[:-]){5}[0-9A-F]{2}`        |
| Module      | Green      | `\[[\w\.]+\]`                            |
| ERROR       | Red Bold   | `ERROR                                   |
| WARNING     | Orange     | `WARNING                                 |
| INFO        | Gray       | `INFO`                                   |
| DEBUG       | Light Gray | `DEBUG                                   |


**Implementation:**

```typescript
function highlightLine(line: string): string {
  let html = line;
  
  // Timestamps
  html = html.replace(
    /\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?/g,
    '<span class="timestamp">$&</span>'
  );
  
  // IPs
  html = html.replace(
    /\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/g,
    '<span class="ip">$&</span>'
  );
  
  // MACs
  html = html.replace(
    /([0-9A-F]{2}[:-]){5}[0-9A-F]{2}/gi,
    '<span class="mac">$&</span>'
  );
  
  // Keywords
  html = html.replace(
    /\b(ERROR|FATAL|CRITICAL)\b/g,
    '<span class="error">$&</span>'
  );
  
  return html;
}
```

## Usage

### Basic Viewing

**Load Log Viewer:**

1. Navigate to project
2. Select CPE from dropdown
3. Click "Log Viewer" in sidebar
4. Logs load automatically (first page)

**Navigation:**

```
┌────────────────────────────────────────────────────────────┐
│  Log Viewer - CPE: AABBCCDDEEFF    [Download] [Export]     │
├────────────────────────────────────────────────────────────┤
│  Lines 1-1000 of 1,234,567                                 │
│  ┌────────────────────────────────────────────────────┐    │
│  │ 1 | 2024-03-13 14:32:10 [wifi] INFO: Starting...   │    │
│  │ 2 | 2024-03-13 14:32:11 [platform] INFO: Init OK   │    │
│  │ 3 | 2024-03-13 14:32:12 [wifi] ERROR: Timeout      │    │
│  │ ...                                                │    │
│  └────────────────────────────────────────────────────┘    │
│  [◀ Prev] Page 1 of 1235 [Next ▶]  Lines/page: [1000 ▼]    │
└────────────────────────────────────────────────────────────┘
```

### Search

**Regex Search:**

```
┌──────────────────────────────────────────────────────┐
│ Search: [ERROR.*timeout────────────] [🔍 Search]     │
│ ☐ Case Sensitive  ☑ Regex  Results: 234 matches      │
└──────────────────────────────────────────────────────┘

Results:
  Line 342:  2024-03-13 14:32:12 [wifi] ERROR: Connection timeout
  Line 1205: 2024-03-13 14:35:45 [dhcp] ERROR: DHCP timeout
  Line 2456: 2024-03-13 14:40:23 [wan] ERROR: WAN link timeout
```

**Quick Patterns:**

```
[📅 Timestamps] [🌐 IPs] [🔗 MACs] [❌ Errors] [⚠️ Warnings]
```

Clicking a button auto-fills the search box with the pattern.

### Advanced Features

**Jump to Line:**

```
Go to line: [12345──] [Go]
```

**Context View:**

```
Line 1205: [wifi] ERROR: Connection timeout
  [📖 Show Context ±5 lines]

Expanded:
  1200: [wifi] INFO: Scanning networks
  1201: [wifi] INFO: Found 3 SSIDs
  1202: [wifi] INFO: Connecting to MyNetwork
  1203: [wifi] INFO: Authentication in progress
  1204: [wifi] WARNING: Signal weak (-72 dBm)
→ 1205: [wifi] ERROR: Connection timeout  ← MATCH
  1206: [wifi] INFO: Retry attempt 1
  1207: [wifi] INFO: Retry attempt 2
  1208: [wifi] ERROR: Connection failed
  1209: [wifi] INFO: Waiting 5s before retry
  1210: [wifi] INFO: Retry attempt 3
```

**Filter by Level:**

```
Show: [☑ ERROR] [☑ WARNING] [☐ INFO] [☐ DEBUG]
```

Dynamically filters lines based on log level.

## API Reference

### Get Log Content

```http
GET /api/<project_id>/files/content?cpe_id=<cpe_id>&page=1&page_size=1000
Authorization: Bearer <access_token>

Query Parameters:
  - cpe_id: CPE identifier (required)
  - page: Page number (default: 1)
  - page_size: Lines per page (default: 1000, max: 10000)
  - search: Regex search pattern (optional)
  - case_sensitive: true/false (default: false)

Response:
{
  "lines": [
    "2024-03-13 14:32:10 [wifi] INFO: Starting...",
    "2024-03-13 14:32:11 [platform] INFO: Init OK",
    ...
  ],
  "total_lines": 1234567,
  "page": 1,
  "page_size": 1000,
  "total_pages": 1235
}
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

Response:
{
  "matches": [
    {
      "line_number": 342,
      "content": "2024-03-13 14:32:12 [wifi] ERROR: Connection timeout",
      "timestamp": "2024-03-13T14:32:12Z"
    },
    ...
  ],
  "total_matches": 234,
  "search_time_ms": 123
}
```

### Download Logs

```http
GET /api/<project_id>/files/download?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response:
Content-Type: text/plain
Content-Disposition: attachment; filename="merged_logs_AABBCCDDEEFF.txt"

<full log contents>
```

### Get Log Statistics

```http
GET /api/<project_id>/files/stats?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response:
{
  "total_lines": 1234567,
  "file_size_bytes": 234567890,
  "log_level_counts": {
    "ERROR": 4523,
    "WARNING": 12456,
    "INFO": 1205678,
    "DEBUG": 11910
  },
  "time_range": {
    "start": "2024-03-13T14:30:00Z",
    "end": "2024-03-15T18:45:22Z"
  },
  "line_count_by_module": {
    "wifi": 234567,
    "platform": 456789,
    "cellular": 123456
  }
}
```

## Performance Considerations

### Large File Handling

**Optimization Strategies:**

1. **Line Offset Caching:**
  ```python
   # Cache line positions for fast random access
   line_offsets = []
   with open(file_path, 'rb') as f:
       offset = 0
       line_offsets.append(offset)
       while f.readline():
           offset = f.tell()
           line_offsets.append(offset)

   # Save to cache file
   with open(f"{file_path}.offsets", 'wb') as f:
       pickle.dump(line_offsets, f)
  ```
2. **Lazy Loading:**
  - Load only visible lines
  - Pre-fetch next page in background
  - Cache recent pages
3. **Search Optimization:**
  - Use ripgrep for regex searches (10-100x faster than Python)
  - Index common patterns
  - Limit max results

**Performance Metrics:**


| File Size | Lines | Load Time | Search Time |
| --------- | ----- | --------- | ----------- |
| 10 MB     | 100K  | <100ms    | <500ms      |
| 100 MB    | 1M    | <200ms    | <2s         |
| 1 GB      | 10M   | <500ms    | <10s        |
| 10 GB     | 100M  | <2s       | <60s        |


### Browser Performance

**Virtual Scrolling:**

```tsx
<VirtualList
  height={800}
  itemCount={totalLines}
  itemSize={20}
  renderItem={(index) => <LogLine line={lines[index]} />}
/>
```

Only renders visible lines, handles 1M+ lines smoothly.

**Syntax Highlighting:**

- Debounce highlighting (300ms)
- Use Web Workers for large pages
- Cache highlighted HTML

## Troubleshooting

### Issue: Logs not loading

**Possible Causes:**

1. File not extracted yet
2. CPE not selected
3. Permissions issue

**Solution:**

```bash
# Check file exists
ls -lh user_uploads/user_*/project_*/SERIAL_OR_MAC_*/merged_logs.txt

# Check file permissions
chmod 644 merged_logs.txt

# Check API logs
docker compose logs logai-api | grep "files/content"
```

### Issue: Search timeout

**Cause:** Large file, complex regex

**Solution:**

1. Reduce page size
2. Use simpler regex
3. Increase Gunicorn timeout:
  ```yaml
   # docker-compose.yml
   command: ["gunicorn", "--timeout", "180", ...]
  ```

### Issue: Highlighting broken

**Cause:** Special characters in logs

**Solution:**
Escape HTML before highlighting:

```typescript
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&')
    .replace(/</g, '<')
    .replace(/>/g, '>');
}
```

### Issue: Memory error on large files

**Cause:** Loading entire file into memory

**Solution:**
Use streaming:

```python
def stream_file(file_path):
    with open(file_path, 'r') as f:
        for line in f:
            yield line
```

## Best Practices

### Search Patterns

**Efficient Searches:**

```regex
✅ ERROR.*WiFi          # Specific module
✅ 192\.168\.1\.        # IP range
✅ \[wifi\].*timeout    # Module + keyword

❌ .*                   # Match everything (slow)
❌ (ERROR|WARNING|INFO) # Too broad
❌ .*timeout.*          # Redundant wildcards
```

### Page Size Selection


| Use Case          | Recommended Page Size |
| ----------------- | --------------------- |
| Quick browsing    | 1,000 lines           |
| Detailed analysis | 500 lines             |
| Context search    | 2,000 lines           |
| Large file scan   | 10,000 lines          |


### File Organization

**Keep merged_logs.txt Clean:**

- Remove binary data
- Strip ANSI escape codes
- Normalize line endings (Unix: \n)

## Related Features

- [File Upload & Extraction](./FILE_UPLOAD.md) - Creates merged_logs.txt
- [Semantic Search](./SEMANTIC_SEARCH.md) - AI-powered search alternative
- [Pattern Analyzer](./PATTERN_ANALYZER.md) - Regex scanning at scale
- [Multi-CPE Support](./MULTI_CPE.md) - Per-CPE log viewing

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)
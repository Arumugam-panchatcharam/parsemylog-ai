# File Upload & Extraction

## Overview

The File Upload & Extraction module handles log tarball uploads with automatic CPE detection, extraction, and chronological merging. It's the entry point for all log analysis workflows in ParseMyLog-AI.

## Key Capabilities

- Drag-and-drop interface for `.tgz` and `.tar.gz` files
- Automatic MAC address and serial number detection from filenames
- Per-CPE folder organization with isolated processing
- Chronological log merging across multiple files
- Progress tracking during extraction
- Duplicate upload prevention
- Multi-file concurrent uploads

## Supported File Formats

### Tarball Archives
- `.tgz` (gzipped tar)
- `.tar.gz` (gzipped tar)
- Nested archives (auto-recursive extraction)

### CPE Identifier Patterns

The system automatically detects CPE identifiers from filenames using these patterns:

```regex
*mac_<MAC_ADDRESS>*           # Example: logs_mac_AA:BB:CC:DD:EE:FF_2024-03-13.tgz
*serial_<SERIAL_NUMBER>*      # Example: cpe_serial_1234567890.tar.gz
*<SERIAL_NUMBER>*             # Example: 1234567890_logbundle.tgz
```

**MAC Address Formats:**
- Colon-separated: `AA:BB:CC:DD:EE:FF`
- Hyphen-separated: `AA-BB-CC-DD-EE-FF`
- No separator: `AABBCCDDEEFF`

## Upload Process

### 1. File Selection

**Via Drag-and-Drop:**
```
┌─────────────────────────────────────┐
│  Drop log tarballs here             │
│  or click to browse                 │
│                                     │
│  📁 Supports .tgz, .tar.gz          │
└─────────────────────────────────────┘
```

**Via File Browser:**
- Click the upload area
- Select one or multiple tarball files
- System validates file extensions

### 2. Upload & Storage

**Upload API:**
```http
POST /api/<project_id>/files/upload
Content-Type: multipart/form-data

file: <tarball_binary_data>
```

**Response:**
```json
{
  "message": "File uploaded successfully",
  "file_id": 123,
  "filename": "logs_mac_AA:BB:CC:DD:EE:FF_2024-03-13.tgz",
  "size": 52428800,
  "cpe_identifier": "AABBCCDDEEFF"
}
```

**Storage Path:**
```
user_uploads/
└── user_{user_id}/
    └── project_{project_id}/
        └── uploads/
            └── logs_mac_AA:BB:CC:DD:EE:FF_2024-03-13.tgz
```

### 3. CPE Detection

**Algorithm:**

1. Extract filename from uploaded file
2. Apply regex patterns to detect MAC/serial
3. Normalize MAC address (remove separators, uppercase)
4. Check for existing CPE record in database
5. Create new `ProjectCPE` entry if not found

**Example:**

```python
# Input filename
filename = "logs_mac_AA:BB:CC:DD:EE:FF_2024-03-13.tgz"

# Detected CPE identifier
cpe_id = "AABBCCDDEEFF"

# Database entry
ProjectCPE(
    project_id=1,
    cpe_identifier="AABBCCDDEEFF",
    source_file="logs_mac_AA:BB:CC:DD:EE:FF_2024-03-13.tgz",
    detected_at="2024-03-13T14:32:10Z"
)
```

### 4. Extraction

**Directory Structure:**
```
user_uploads/
└── user_{user_id}/
    └── project_{project_id}/
        └── SERIAL_OR_MAC_{cpe_id}/
            ├── files/                  # Extracted log files
            │   ├── ArmConsolelog.txt
            │   ├── Consolelog.txt
            │   ├── PAMlog.txt
            │   ├── WiFilog.txt
            │   └── ...
            └── merged_logs.txt         # Chronologically merged
```

**Extraction Steps:**

1. Create CPE-specific directory: `SERIAL_OR_MAC_{cpe_id}/`
2. Extract tarball contents to `files/` subdirectory
3. Recursively extract nested archives
4. Scan for log files (`.txt`, `.log`, no extension)
5. Skip binary files and non-log formats

### 5. Chronological Merging

**Purpose:** Combine logs from multiple files into a single timeline

**Algorithm:**

1. Scan all `.txt` files in `files/` directory
2. Parse timestamps using multiple patterns:
   - `YYYY-MM-DD HH:MM:SS`
   - `MMM DD HH:MM:SS` (syslog format)
   - `YYYYMMDD-HH:MM:SS.microseconds`
   - Unix timestamps
3. Sort all log lines by timestamp
4. Write to `merged_logs.txt`

**Example:**

```
# Input files
files/WiFilog.txt:
  2024-03-13 14:32:10 [wifi] ERROR: Connection failed
  2024-03-13 14:32:15 [wifi] INFO: Retry attempt 1

files/Consolelog.txt:
  2024-03-13 14:32:12 [system] WARNING: High CPU usage
  2024-03-13 14:32:20 [system] INFO: CPU normalized

# Output merged_logs.txt
2024-03-13 14:32:10 [wifi] ERROR: Connection failed
2024-03-13 14:32:12 [system] WARNING: High CPU usage
2024-03-13 14:32:15 [wifi] INFO: Retry attempt 1
2024-03-13 14:32:20 [system] INFO: CPU normalized
```

**Handling Missing Timestamps:**
- Lines without timestamps are placed immediately after their preceding timestamped line
- Preserves relative ordering within each source file

### 6. Progress Tracking

**WebSocket Updates (if implemented):**
```json
{
  "stage": "extracting",
  "progress": 45,
  "message": "Extracting files... (312/692)"
}
```

**Polling Updates:**
```http
GET /api/<project_id>/files/<file_id>/status

Response:
{
  "status": "processing",
  "stage": "merging",
  "progress": 75
}
```

## User Interface

### Upload Component

```tsx
<FileUploader
  projectId={projectId}
  onUploadComplete={(fileId) => {
    // Navigate to log viewer or pattern analysis
  }}
  onError={(error) => {
    // Show error notification
  }}
  maxFileSize={1024 * 1024 * 1024}  // 1GB
  acceptedFormats={['.tgz', '.tar.gz']}
/>
```

### Progress Indicators

**Upload Progress:**
```
Uploading: logs_mac_AABBCCDDEEFF.tgz
████████████░░░░░░░░ 62% (324 MB / 520 MB)
```

**Extraction Progress:**
```
Extracting files...
██████████████████░░ 90% (624 / 692 files)
```

**Merging Progress:**
```
Merging logs chronologically...
████████████████████ 100% (1.2M lines sorted)
```

## Error Handling

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid file format` | Non-tarball file uploaded | Use `.tgz` or `.tar.gz` |
| `File too large` | Exceeds max size (default 1GB) | Increase `client_max_body_size` in Nginx |
| `CPE detection failed` | No MAC/serial in filename | Rename file to include identifier |
| `Extraction failed` | Corrupted archive | Re-upload file |
| `Duplicate file` | Same filename already uploaded | Delete existing or rename new file |
| `Insufficient disk space` | Storage volume full | Free up space or increase volume size |

### Retry Mechanism

**Automatic Retries:**
- Upload failures: 3 retries with exponential backoff
- Extraction failures: 1 retry, then mark as failed

**Manual Retries:**
- Failed uploads can be retried from the Files page
- Click "Retry Upload" button next to failed file

## API Reference

### Upload File

```http
POST /api/<project_id>/files/upload
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

Body:
  file: <binary_data>
```

### Get Upload Status

```http
GET /api/<project_id>/files/<file_id>/status
Authorization: Bearer <access_token>

Response:
{
  "file_id": 123,
  "filename": "logs.tgz",
  "status": "completed",  // or "uploading", "processing", "failed"
  "cpe_identifier": "AABBCCDDEEFF",
  "size": 52428800,
  "uploaded_at": "2024-03-13T14:32:10Z",
  "processed_at": "2024-03-13T14:35:22Z"
}
```

### List Uploaded Files

```http
GET /api/<project_id>/files
Authorization: Bearer <access_token>

Response:
{
  "files": [
    {
      "file_id": 123,
      "filename": "logs_mac_AABBCCDDEEFF.tgz",
      "cpe_identifier": "AABBCCDDEEFF",
      "size": 52428800,
      "uploaded_at": "2024-03-13T14:32:10Z",
      "status": "completed"
    }
  ]
}
```

### Delete File

```http
DELETE /api/<project_id>/files/<file_id>
Authorization: Bearer <access_token>

Response:
{
  "message": "File deleted successfully"
}
```

## Best Practices

### Filename Conventions

**Good:**
```
logs_mac_AA:BB:CC:DD:EE:FF_2024-03-13.tgz
cpe_serial_1234567890_logbundle.tar.gz
AABBCCDDEEFF_debug_logs.tgz
```

**Avoid:**
```
mylogs.tgz                     # No CPE identifier
device1_logs.tgz               # Ambiguous identifier
logs-AABBCCDDEEFF.zip          # Wrong format (.zip not supported)
```

### Archive Structure

**Recommended:**
```
tarball.tgz
├── ArmConsolelog.txt
├── Consolelog.txt
├── PAMlog.txt
├── WiFilog.txt
└── Telemetry_2.0_report.txt
```

**Also Supported:**
```
tarball.tgz
└── logs/
    ├── system/
    │   └── console.log
    └── network/
        └── wifi.log
```

### File Size Optimization

**Before Upload:**
- Remove unnecessary files (core dumps, binaries)
- Compress logs if not already compressed
- Split very large archives (>1GB) into multiple tarballs

**Example Optimization:**
```bash
# Remove non-log files
tar -czf optimized_logs.tgz --exclude='*.bin' --exclude='core.*' logs/

# Split large archive
tar -czf - logs/ | split -b 500M - logs_part_
```

## Troubleshooting

### Issue: CPE not detected

**Check:**
1. Filename contains MAC address or serial number
2. MAC format is recognized (AA:BB:CC:DD:EE:FF or variants)
3. No special characters corrupting the identifier

**Solution:**
Rename file to include clear identifier:
```bash
mv mylogs.tgz logs_mac_AABBCCDDEEFF.tgz
```

### Issue: Extraction timeout

**Cause:** Archive is very large (>1GB) or deeply nested

**Solution:**
1. Increase Gunicorn timeout in `docker-compose.yml`:
   ```yaml
   command: ["gunicorn", "--timeout", "1800", ...]
   ```
2. Restart services:
   ```bash
   docker compose up -d --build
   ```

### Issue: Merged logs missing timestamps

**Cause:** Some log files don't use standard timestamp formats

**Solution:**
Add custom timestamp patterns in `logai/utils/timestamp_parser.py`

## Related Features

- [Log Viewer](./LOG_VIEWER.md) - View extracted and merged logs
- [Multi-CPE Support](./MULTI_CPE.md) - How CPE isolation works
- [Pattern Analysis](./DRAIN3_PATTERNS.md) - Analyze uploaded logs

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)

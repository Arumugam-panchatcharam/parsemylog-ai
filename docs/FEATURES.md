# Features Overview

ParseMyLog-AI provides comprehensive log analysis capabilities through multiple specialized modules. This document provides an overview of all features with links to detailed documentation.

## Table of Contents

- [Core Analysis Features](#core-analysis-features)
- [Multi-CPE Support](#multi-cpe-support)
- [Pattern Management](#pattern-management)
- [Advanced Analytics](#advanced-analytics)
- [Administration](#administration)
- [Utilities](#utilities)

---

## Core Analysis Features

### 1. File Upload & Extraction

**Description:** Drag-and-drop log tarball upload with automatic extraction and CPE detection.

**Key Capabilities:**
- Support for `.tgz` and `.tar.gz` formats
- Automatic MAC address and serial number detection from filenames
- Per-CPE folder organization (`SERIAL_OR_MAC_xxx/`)
- Chronological log merging across multiple files
- Progress tracking during extraction
- Duplicate upload prevention

**Supported File Patterns:**
```
*mac_<MAC_ADDRESS>*.tgz
*serial_<SERIAL_NUMBER>*.tgz
*<SERIAL_NUMBER>*.zip
```

**Detailed Guide:** [File Upload & Extraction](./features/FILE_UPLOAD.md)

---

### 2. Log Viewer

**Description:** IDE-style paginated log viewer with syntax highlighting and search capabilities.

**Key Capabilities:**
- **Syntax Highlighting:**
  - Timestamps (red)
  - IP addresses (blue)
  - MAC addresses (magenta)
  - Module names (green)
  - Keywords (WARN, ERROR, FATAL, DHCP, WAN, etc.)
  
- **Search Features:**
  - Regex pattern search
  - Case-sensitive/insensitive toggle
  - Quick pattern buttons (timestamps, IPs, MACs, errors)
  - Jump to line number
  
- **Navigation:**
  - Pagination (configurable page size)
  - Keyboard shortcuts (j/k for line navigation)
  - Bookmark support
  - Line number display

- **Export:**
  - Download full merged logs
  - Export filtered results

**Detailed Guide:** [Log Viewer](./features/LOG_VIEWER.md)

---

### 3. rg+Drain3 Pattern Analysis

**Description:** Two-stage log indexing pipeline for template extraction and frequency analysis.

**How It Works:**

1. **Stage 1: ripgrep Pre-filtering**
   - Scans logs with domain-specific YAML patterns
   - Filters error-class lines (6-10x speedup)
   - Caches results in Parquet format
   
2. **Stage 2: Drain3 Template Extraction**
   - Extracts log templates from filtered lines
   - Groups similar logs by structure
   - Preserves per-domain state files

**Key Capabilities:**
- Per-domain template analysis (wifi, platform, cellular, mesh, core_router)
- Frequency distribution analysis
- Parameter extraction on-demand
- Filter by domain and frequency threshold
- Export templates to CSV/JSON

**Example Template:**
```
Original Log:
2024-03-13 14:32:10 [wifi] ERROR: Failed to connect to SSID MyNetwork (code: 12)

Extracted Template:
[wifi] ERROR: Failed to connect to SSID <*> (code: <*>)

Parameters:
- SSID: MyNetwork
- code: 12
```

**Detailed Guide:** [Drain3 Pattern Analysis](./features/DRAIN3_PATTERNS.md)

---

### 4. Semantic Search (AI Analysis)

**Description:** Vector-based semantic search across log patterns using BGE embeddings and Qdrant.

**How It Works:**

1. Log templates are embedded using BAAI/bge-small-en-v1.5 (384-dim)
2. Embeddings stored in Qdrant per-project+CPE collections
3. User queries are encoded and compared via cosine similarity
4. Top-K matching templates returned with context

**Key Capabilities:**
- Natural language queries (e.g., "WiFi connection failures")
- Cosine similarity ranking
- Configurable result count (default: 10)
- Sample log display with matched templates
- Domain filtering
- Context window extraction (±5 lines)

**Example Usage:**
```
Query: "kernel panics related to memory"

Results:
1. [platform] Kernel panic - not syncing: Out of memory [Score: 0.92]
2. [platform] BUG: unable to handle kernel paging request [Score: 0.87]
3. [platform] Memory cgroup out of memory [Score: 0.84]
```

**Detailed Guide:** [Semantic Search](./features/SEMANTIC_SEARCH.md)

---

### 5. Telemetry Dashboard

**Description:** YAML-driven parsing of Telemetry 2.0 periodic reports with interactive visualizations.

**Key Capabilities:**

- **Metric Extraction:**
  - TR-181 parameter parsing (Device.WiFi.Radio.*, Device.IP.Interface.*, etc.)
  - Time-series data aggregation
  - Automatic unit detection (dBm, Mbps, %, etc.)
  
- **Visualizations:**
  - Line charts for trends (Plotly.js)
  - Status cards (radio stats, SSID info)
  - Device information panel
  - Reboot boundary markers
  
- **Supported Metrics:**
  - WiFi signal strength (RSSI, SNR, Noise)
  - Channel utilization
  - Network throughput (RX/TX bytes)
  - CPU & memory usage
  - Interface statistics
  - Client counts
  
- **YAML Configuration:**
  - `configs/telemetry_report_fields.yaml` defines extractable fields
  - Custom field definitions supported

**Detailed Guide:** [Telemetry Dashboard](./features/TELEMETRY.md)

---

### 6. Pattern Analyzer (ripgrep)

**Description:** High-speed regex pattern management and scanning with time-series visualization.

**Key Capabilities:**

- **Pattern Management:**
  - Create, edit, delete regex patterns
  - Organize by domain (wifi, platform, cellular, etc.)
  - Enable/disable individual patterns
  - Import/export pattern libraries (JSON/YAML)
  
- **Scanning:**
  - ripgrep-powered high-speed scanning
  - Per-CPE support
  - Parallel domain processing
  - Progress tracking
  
- **Visualization:**
  - Time-series plots with reboot markers
  - Reboot window filtering (select start/end boundaries)
  - Zoom slider for time range selection
  - Frequency heatmaps
  
- **NATCO Integration:**
  - Sync patterns from global NATCO library
  - Submit local changes for admin review
  - Diff view (NEW/MODIFIED patterns)

**Detailed Guide:** [Pattern Analyzer](./features/PATTERN_ANALYZER.md)

---

## Multi-CPE Support

### 7. CPE Detection & Isolation

**Description:** Automatic detection and isolated processing of multiple CPE devices per project.

**How It Works:**

1. MAC addresses or serial numbers extracted from tarball filenames
2. Per-CPE subfolders created: `SERIAL_OR_MAC_xxx/`
3. Independent indexing, caching, and analysis per CPE
4. CPE selector on all analysis pages

**Key Capabilities:**
- Automatic CPE identifier detection
- Per-CPE Drain3 state files
- Per-CPE Qdrant collections (`project_{id}_cpe_{cpe_id}`)
- Per-CPE telemetry dashboards
- CPE metadata tracking (detected timestamps, source files)

**Detailed Guide:** [Multi-CPE Support](./features/MULTI_CPE.md)

---

### 8. CPE Overview Dashboard

**Description:** Cross-CPE comparison dashboard with aggregated metrics and visualizations.

**Key Capabilities:**

- **Device Comparison:**
  - Side-by-side device info (model, firmware, uptime)
  - Reboot count comparison
  - Error pattern distribution by domain
  
- **Metric Aggregation:**
  - Average signal strength across CPEs
  - Network throughput trends
  - Error frequency heatmaps
  
- **Visualizations:**
  - Multi-line Plotly charts (one line per CPE)
  - Bar charts for reboot counts
  - Pie charts for error distribution
  
- **Filtering:**
  - Select specific CPEs for comparison
  - Domain-level filtering
  - Time range selection

**Detailed Guide:** [CPE Overview](./features/CPE_OVERVIEW.md)

---

## Pattern Management

### 9. NATCO (Pattern Governance) System

**Description:** Global pattern configuration system for managing deployment-specific log patterns.

**Architecture:**

```
Admin → Create NATCO → Define Global Patterns
                            ↓
            User Projects ← Assign NATCO
                            ↓
            Sync from Global → Local Edits
                            ↓
            Submit to Global → Admin Review
                            ↓
            Approve/Reject → Merge to Global
```

**Key Capabilities:**

**For Admins:**
- Create/edit/delete NATCOs (e.g., EU, DE, PL, US)
- Define global patterns per NATCO
- Review user submissions (NEW/MODIFIED)
- Approve (auto-merge) or reject with comments
- Import patterns from presets or JSON/YAML
- View submission history per user

**For Users:**
- Assign NATCO to projects
- Sync latest global patterns
- Edit patterns locally (full override)
- Submit changes for global inclusion
- Compare local vs. global (diff view)
- Track submission status

**Pattern Submission Workflow:**
1. User syncs from global NATCO patterns
2. User edits locally (add/modify/disable patterns)
3. User clicks "Submit to Global"
4. System computes diff (only NEW/MODIFIED)
5. User selects which changes to submit
6. Admin reviews in Pattern Review tab
7. Admin approves → patterns merged into global
8. Other users sync to receive updates

**Detailed Guide:** [NATCO Pattern Governance](./features/NATCO_GOVERNANCE.md)

---

### 10. Pattern Import/Export

**Description:** Bulk pattern operations for sharing and backup.

**Supported Formats:**

1. **Domain-Grouped JSON:**
```json
{
  "wifi": [
    {"name": "Connection Failed", "regex": "Failed to connect", "enabled": true}
  ]
}
```

2. **Flat Array JSON:**
```json
[
  {"domain": "wifi", "name": "Connection Failed", "regex": "Failed to connect"}
]
```

3. **YAML:**
```yaml
wifi:
  - name: Connection Failed
    regex: Failed to connect
    enabled: true
```

4. **rule_parser_config.json:**
```json
{
  "groups": [
    {
      "group": "wifi",
      "patterns": [
        {"pattern": "Failed to connect", "description": "Connection Failed"}
      ]
    }
  ]
}
```

**Detailed Guide:** [Pattern Import/Export](./features/PATTERN_IMPORT_EXPORT.md)

---

## Advanced Analytics

### 11. Machine Learning Anomaly Detection

**Description:** Unsupervised anomaly detection for log patterns and telemetry metrics.

**Key Capabilities:**

**Log Anomaly Detection:**
- Isolation Forest algorithm
- Detects unusual log patterns based on frequency and co-occurrence
- Anomaly score ranking
- Temporal anomaly tracking

**Telemetry Anomaly Detection:**
- Time-series anomaly detection (ARIMA, Prophet)
- Multivariate analysis (correlation-based)
- Threshold-based alerts
- Seasonal decomposition

**Fleet-Level Anomaly Detection:**
- Cross-CPE comparison
- Identify outlier devices
- Aggregate anomaly scoring

**User Feedback Loop:**
- Label anomalies as true positive / false positive
- Retrain models with feedback data
- Validate model accuracy with ground truth

**Detailed Guide:** [ML Anomaly Detection](./features/ML_ANOMALY.md)

---

### 12. Knowledge Graph

**Description:** Visual representation of log event relationships and causal chains.

**Key Capabilities:**

- **Graph Construction:**
  - Nodes: Log events, entities (IPs, SSIDs, interfaces)
  - Edges: Temporal relationships, causality
  - Automatic graph generation from logs
  
- **Visualization:**
  - Interactive D3.js or XYFlow graph
  - Zoom, pan, node filtering
  - Highlight critical paths
  
- **Analysis:**
  - Find root cause events
  - Identify event cascades
  - Cluster related events
  
- **Export:**
  - GraphML, JSON formats
  - Integration with external graph tools

**Detailed Guide:** [Knowledge Graph](./features/KNOWLEDGE_GRAPH.md)

---

### 13. Batch CPE Processing

**Description:** Asynchronous processing of multiple CPE log archives via Celery workers.

**How It Works:**

1. User places CPE zip files in `batch_cpe_logs/` directory
2. User creates batch job via UI (specify file pattern, analysis options)
3. Job queued to Redis, processed by Celery worker
4. Worker extracts logs, indexes, runs analysis for each CPE
5. Results aggregated and stored in database
6. User polls for status and downloads results

**Key Capabilities:**

- **Async Processing:**
  - Non-blocking job submission
  - Real-time progress tracking
  - Job status: pending, running, completed, failed
  
- **Bulk Operations:**
  - Process 100+ CPEs in one job
  - Parallel domain indexing
  - Aggregated result reports
  
- **Result Management:**
  - Per-CPE analysis summaries
  - Error aggregation across fleet
  - CSV/JSON export

**Detailed Guide:** [Batch CPE Processing](./features/BATCH_PROCESSING.md)

---

### 14. PCAP Analysis

**Description:** Network packet capture analysis with protocol decoding.

**Key Capabilities:**

- **Upload & Parsing:**
  - Upload .pcap/.pcapng files
  - Automatic protocol detection (TCP, UDP, ICMP, DNS, HTTP)
  - Packet metadata extraction
  
- **Analysis:**
  - Connection flow reconstruction
  - Protocol statistics
  - Packet timing analysis
  - Filter by IP, port, protocol
  
- **Integration:**
  - Correlate PCAP events with log timestamps
  - Identify network issues from logs
  - Cross-reference MAC addresses

**Detailed Guide:** [PCAP Analysis](./features/PCAP_ANALYSIS.md)

---

### 15. Issue Analysis

**Description:** Focused investigation of specific issues with multi-source correlation.

**Key Capabilities:**

- **Issue Definition:**
  - Define issue type (e.g., "WiFi Disconnects")
  - Specify relevant log patterns, telemetry metrics
  - Set time range for investigation
  
- **Data Collection:**
  - Gather matching logs across CPEs
  - Extract related telemetry snapshots
  - Fetch PCAP data if available
  
- **Correlation:**
  - Temporal alignment of logs, telemetry, PCAP
  - Identify common precursors
  - Rank CPEs by issue severity
  
- **Reporting:**
  - Generate issue summary reports
  - Timeline visualization
  - Export findings to PDF

**Detailed Guide:** [Issue Analysis](./features/ISSUE_ANALYSIS.md)

---

### 16. AI Chat Assistant

**Description:** Interactive chat interface for querying logs and analysis results using LLMs.

**Key Capabilities:**

- **Natural Language Queries:**
  - "Show me all WiFi disconnects in the last hour"
  - "What caused the reboot at 14:32:10?"
  - "Compare CPU usage across all CPEs"
  
- **Context-Aware Responses:**
  - Access to project logs, telemetry, patterns
  - Multi-turn conversations with history
  - File content retrieval on-demand
  
- **LLM Integration:**
  - Configurable LLM backends (OpenAI, Anthropic, local models)
  - Adjustable temperature, max tokens
  - System prompts for log analysis domain
  
- **Conversation Management:**
  - Save/load conversation history
  - Multiple conversations per project
  - Export chat to text/JSON

**Detailed Guide:** [AI Chat Assistant](./features/AI_CHAT.md)

---

## Administration

### 17. User Management

**Description:** Admin dashboard for managing user accounts and access.

**Key Capabilities:**

- **User CRUD:**
  - Create users with username/password
  - Assign admin privileges
  - Reset user passwords
  - Delete users (with project cleanup)
  
- **User Monitoring:**
  - View all users and their projects
  - Track user activity (last login, upload count)
  - Disk usage per user
  
- **Project Management:**
  - View projects per user
  - Transfer project ownership
  - Delete projects (admin only)

**Detailed Guide:** [User Management](./features/USER_MANAGEMENT.md)

---

### 18. NATCO Administration

**Description:** Admin interface for managing NATCOs and global patterns.

**Key Capabilities:**

- **NATCO CRUD:**
  - Create NATCOs with code (e.g., "EU"), name, description
  - Edit NATCO metadata
  - Delete NATCOs (if no projects assigned)
  
- **Global Pattern Editor:**
  - Add/edit/delete patterns per NATCO
  - Organize by domain
  - Bulk import from presets or files
  - Enable/disable patterns
  
- **Pattern Submission Review:**
  - View pending submissions from users
  - See NEW/MODIFIED labels
  - Approve (auto-merge) or reject
  - Add comments for rejected submissions
  
- **Submission History:**
  - Per-user submission tracking
  - Filter by status (pending, approved, rejected)
  - Clear resolved submissions

**Detailed Guide:** [NATCO Administration](./features/NATCO_ADMIN.md)

---

### 19. LLM Settings

**Description:** Configure external LLM providers for AI features.

**Key Capabilities:**

- **Provider Configuration:**
  - OpenAI (API key, model selection)
  - Anthropic (API key, model selection)
  - Azure OpenAI (endpoint, deployment)
  - Local models (API endpoint)
  
- **Model Parameters:**
  - Temperature (creativity)
  - Max tokens (response length)
  - System prompts
  
- **Testing:**
  - Test connection with configured settings
  - View usage statistics
  - Monitor API costs

**Detailed Guide:** [LLM Settings](./features/LLM_SETTINGS.md)

---

## Utilities

### 20. MAC Address Lookup (OUI Database)

**Description:** Resolve MAC addresses to vendor names using IEEE OUI database.

**Key Capabilities:**

- **OUI Database:**
  - Download latest IEEE OUI database
  - Cache locally (auto-update weekly)
  - 30K+ vendor entries
  
- **Lookup:**
  - Single MAC lookup
  - Bulk lookup from CSV
  - Integration with log viewer (hover tooltips)
  
- **Database Management:**
  - Manual database update
  - View database status (entry count, last update)
  - Export vendor list

**Detailed Guide:** [MAC Address Lookup](./features/MAC_LOOKUP.md)

---

### 21. Telemetry CSV Export

**Description:** Export telemetry data to CSV for external analysis.

**Key Capabilities:**

- **Export Options:**
  - All metrics or selected fields
  - Time range filtering
  - Per-CPE or aggregated
  
- **CSV Format:**
  - Timestamp, CPE_ID, Metric_Name, Value
  - Compatible with Excel, Pandas, R
  
- **Scheduling:**
  - Periodic exports (daily, weekly)
  - Email delivery (optional)

**Detailed Guide:** [Telemetry CSV Export](./features/TELEMETRY_CSV.md)

---

## Feature Matrix

| Feature | Status | Auth Required | Admin Only | Per-CPE |
|---------|--------|---------------|------------|---------|
| File Upload | ✅ | Yes | No | Yes |
| Log Viewer | ✅ | Yes | No | Yes |
| Drain3 Patterns | ✅ | Yes | No | Yes |
| Semantic Search | ✅ | Yes | No | Yes |
| Telemetry Dashboard | ✅ | Yes | No | Yes |
| Pattern Analyzer | ✅ | Yes | No | Yes |
| CPE Overview | ✅ | Yes | No | N/A |
| NATCO Governance | ✅ | Yes | Mixed | No |
| ML Anomaly | ✅ | Yes | No | Yes |
| Knowledge Graph | ✅ | Yes | No | Yes |
| Batch Processing | ✅ | Yes | No | N/A |
| PCAP Analysis | ✅ | Yes | No | No |
| Issue Analysis | ✅ | Yes | No | Yes |
| AI Chat | ✅ | Yes | No | Yes |
| User Management | ✅ | Yes | Yes | No |
| NATCO Admin | ✅ | Yes | Yes | No |
| LLM Settings | ✅ | Yes | Yes | No |
| MAC Lookup | ✅ | Yes | No | No |
| Telemetry CSV | ✅ | Yes | No | Yes |

---

## Coming Soon

- **Automated Report Generation:** Scheduled PDF reports with analysis summaries
- **Webhook Integrations:** Trigger external systems on events (e.g., Slack alerts)
- **Multi-Tenancy:** Organization-level isolation with RBAC
- **Grafana Integration:** Real-time metric streaming to Grafana dashboards
- **Log Forwarding:** Forward logs to external SIEM (Splunk, ELK)

---

## Related Documentation

- [Architecture](./ARCHITECTURE.md)
- [Quick Start Guide](./QUICK_START.md)
- [API Reference](./API_REFERENCE.md)
- [Deployment Guide](./DEPLOYMENT.md)

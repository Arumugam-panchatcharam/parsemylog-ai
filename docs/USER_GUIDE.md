# ParseMyLog-AI -- User Guide

This guide walks through every feature of the ParseMyLog-AI web application, from logging in to interpreting telemetry charts.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Project Management](#2-project-management)
3. [Uploading Log Files](#3-uploading-log-files)
4. [Log Viewer Tab](#4-log-viewer-tab)
5. [Pattern Analysis Tab](#5-pattern-analysis-tab)
6. [Embedding / Indexing Tab](#6-embedding--indexing-tab)
7. [Telemetry Tab](#7-telemetry-tab)
8. [AI Analysis Tab](#8-ai-analysis-tab)
9. [Admin Features](#9-admin-features)
10. [Tips & Troubleshooting](#10-tips--troubleshooting)

---

## 1. Getting Started

### Logging In

1. Navigate to the application URL (default: `http://localhost:40901`).
2. Enter your **username** and **password**.
3. Click **Login**.

First-time users should contact the administrator to create an account.

### Dashboard Overview

After login, you'll see the main dashboard with:
- **Sidebar** (left): Navigation tabs and project selector.
- **Main area** (center): Active tab content.
- **Project selector** (top): Dropdown to choose or create projects.

---

## 2. Project Management

### Creating a New Project

1. Click the **"+ New Project"** button in the sidebar.
2. Enter a **project name** (e.g., "CPE-Debug-2025-01-29").
3. Click **Create**.

Each project is an isolated workspace with its own uploaded files, parsed data, and vector embeddings.

### Switching Projects

Use the project dropdown at the top of the sidebar to switch between existing projects.

---

## 3. Uploading Log Files

### Supported Formats

- `.tgz` / `.tar.gz` -- RDK log tarballs (recommended)
- `.txt` / `.log` -- Individual log files
- `.zip` -- ZIP archives

### Upload Process

1. Go to the **Log Viewer** tab.
2. **Drag and drop** files onto the upload area, or **click** to browse.
3. A **progress bar** appears showing the processing stages:
   - **10%** -- File received and saved.
   - **50%** -- Extracting and merging logs.
   - **100%** -- Processing complete.
4. The upload card disappears and your files appear in the file list.

### What Happens During Upload

1. **Tarball Extraction**: `.tgz` files are extracted, preserving the directory structure.
2. **Log Merging**: Logs of the same type are merged chronologically using timestamps.
3. **Telemetry Parsing**: If a `telemetry2_0.txt` file is found, it's detected for later parsing.
4. **Archive Creation**: A ZIP file of merged logs is created for easy download.

---

## 4. Log Viewer Tab

The Log Viewer lets you browse, search, and navigate through uploaded log files.

### Viewing Files

1. Each file is listed with its **name**, **size**, and action buttons.
2. Click the **eye icon** to view a file's contents.
3. Use **pagination** (bottom) to navigate through large files (1000 lines per page).

### Searching

- **Search bar**: Enter any text or regex pattern, then click **Search**.
- **Quick-pattern buttons**:
  - **ERROR** -- Finds ERROR, FATAL, CRITICAL, FAIL keywords.
  - **WARN** -- Finds WARNING, WARN, ALERT keywords.
  - **IP** -- Finds IPv4 addresses.
  - **TIME** -- Finds HH:MM:SS timestamps.
- **Results panel**: Shows matches with line numbers. Double-click a result to jump to that line in the viewer.

### Notes

- Use the **Notes** area below the file list to add project notes.
- Click **Save** to persist notes for later.

---

## 5. Pattern Analysis Tab

The Pattern Analysis tab shows Drain3 log templates extracted from parsed files.

### Understanding Templates

Drain3 identifies recurring patterns in logs and replaces variable parts with `<*>` placeholders:

| Log Line | Template |
|----------|----------|
| `WiFi client AA:BB connected to AP1` | `WiFi client <*> connected to <*>` |
| `WiFi client CC:DD connected to AP2` | `WiFi client <*> connected to <*>` |

### Using Pattern Analysis

1. Select a file from the dropdown.
2. The template table shows:
   - **Template**: The extracted pattern.
   - **Frequency**: How many times it occurs.
3. Click a template row to see:
   - **Parameter List**: Values that fill each `<*>` placeholder.
   - **Log Lines**: Original log lines matching this template.

---

## 6. Embedding / Indexing Tab

This tab manages the indexing pipeline that powers semantic search.

### Pipeline States

Each file progresses through these states:

| State | Icon | Description |
|-------|------|-------------|
| **Queued** | Clock | File is waiting to be parsed |
| **Parsed** | Gear | Drain3 templates extracted (parquet cache created) |
| **Indexed** | Check | Templates embedded and stored in Qdrant |
| **Error** | Warning | Processing failed (see error message) |

### How It Works

1. After upload, files are automatically **queued** for parsing.
2. The **rg+Drain3 pipeline** processes files:
   - ripgrep pre-filters error-class lines (fast).
   - Drain3 extracts templates from filtered lines.
   - Templates are embedded with BGE and stored in Qdrant.
3. The status refreshes automatically every few seconds.

### Template Download

Click **Download Templates** to export all templates as an Excel file.

---

## 7. Telemetry Tab

The Telemetry 2.0 tab provides device health analysis from periodic telemetry reports.

### Running Telemetry Analysis

1. Switch to the **Telemetry** tab.
2. Click the **Run** button.
3. The system finds and parses `telemetry2_0.txt` from your uploaded logs.

### Understanding the Results

#### Device Info Card

Shows device identity:
- MAC address, serial number, firmware version
- Hardware model and manufacturer

#### Report Status Card

Shows parsing statistics:
- Total reports found vs. successfully parsed
- Time range (first and last report timestamps)
- Per-profile counts (Advanced_dynamic, Basic_dynamic)
- Average interval between reports (expected: 900 seconds)

#### Field Group Tables

Expandable accordion sections organized by domain:
- **WiFi Radio** -- Radio enable, status, channel, TX power, noise floor.
- **WiFi SSID** -- SSID names, status, traffic counters, error counters.
- **System Resources** -- Memory free, CPU usage, uptime, process count.
- **DSL / WAN** -- Downstream/upstream rates, Ethernet link, PPP status.
- **Device Info** -- Reboot reason, connected device count, NTP status.

Each table shows:
- **Field**: Human-readable name.
- **Latest Value**: Most recent value with unit.
- **Type**: numeric, status, text, or bool.
- **Changes**: How many times the value changed across reports.
- **Data Points**: Number of samples available.

#### Time-Series Charts

Interactive Plotly charts for fields marked as `plot: true` in the YAML config:
- **Hover** over data points to see exact values.
- **Click and drag** to zoom into a time range.
- **Double-click** to reset zoom.
- Charts auto-group by domain (WiFi Radio, System Resources, etc.).

---

## 8. AI Analysis Tab

The AI Analysis tab enables semantic search across all indexed log templates.

### Performing a Search

1. Enter a **natural language query** in the search box:
   - Example: "WiFi disconnection issues"
   - Example: "memory leak or OOM"
   - Example: "DSL synchronization failure"
2. Click **Search**.

### Understanding Results

The search returns templates ranked by **semantic similarity** (0.0 to 1.0):

| Column | Description |
|--------|-------------|
| **Filename** | Source log file |
| **Template** | Matching Drain3 template |
| **Frequency** | How often this pattern occurs |
| **Similarity** | Cosine similarity score (higher = more relevant) |

### Drilling Down

1. Click a result row to see:
   - **Parameter List**: Variable values for each `<*>` placeholder.
   - **Log Lines**: Original lines matching this template with timestamps.

2. Select a log line to view **contextual log lines** around it:
   - Use the **time slider** to expand/contract the context window.
   - Toggle **highlight mode** to emphasize matching lines.

---

## 9. Admin Features

### User Management (Admin only)

Administrators can:
- **Create users**: Add new accounts with username/password.
- **Delete users**: Remove accounts and their data.
- **View statistics**: See per-user project counts and storage usage.

### System Health

- **Qdrant Status**: Check vector database connectivity and collection stats.
- **Storage Usage**: Monitor uploaded file storage.

---

## 10. Tips & Troubleshooting

### Performance Tips

- **Upload one tarball at a time** for best progress tracking.
- **Use the AI search** for pattern discovery rather than manual regex search.
- **Check the Embedding tab** to ensure files are indexed before searching.

### Common Issues

| Issue | Solution |
|-------|----------|
| "No similar templates found" | Check that files are indexed (Embedding tab shows "indexed" state) |
| "No telemetry2_0 file found" | Upload a tarball that contains `telemetry2_0.txt` |
| Slow search results | Wait for indexing to complete; check Qdrant container is running |
| Upload progress stuck | Refresh the page; check server logs for errors |
| No templates extracted | The log file may not match any rg pattern; check configs/rg_patterns/ |

### Getting Help

- Check the **README.md** for installation and configuration details.
- Review the **configs/** directory for customizing patterns and telemetry fields.
- Contact the administrator for account or system issues.

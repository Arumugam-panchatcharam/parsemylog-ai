# ParseMyLog-AI -- User Guide

This guide walks through every feature of the ParseMyLog-AI web application, from logging in to managing NATCO pattern governance.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Project Management](#2-project-management)
3. [Uploading Log Files](#3-uploading-log-files)
4. [CPE (Device) Management](#4-cpe-device-management)
5. [Log Viewer](#5-log-viewer)
6. [Pattern Analysis (Drain3)](#6-pattern-analysis-drain3)
7. [Pattern Analyzer (Regex + ripgrep)](#7-pattern-analyzer-regex--ripgrep)
8. [Embedding / Indexing](#8-embedding--indexing)
9. [Telemetry Dashboard](#9-telemetry-dashboard)
10. [AI Analysis (Semantic Search)](#10-ai-analysis-semantic-search)
11. [CPE Overview](#11-cpe-overview)
12. [Pattern Governance (NATCO)](#12-pattern-governance-natco)
13. [Admin Features](#13-admin-features)
14. [Tips & Troubleshooting](#14-tips--troubleshooting)

---

## 1. Getting Started

### Logging In

1. Navigate to the application URL (default: `http://localhost:40901`).
2. Enter your **username** and **password**.
3. Click **Login**.

First-time users should contact the administrator to create an account. On a fresh installation, a default admin account is created automatically: **username** `admin`, **password** `admin123`. Change this immediately after first login.

### Navigation

After login, you'll see:
- **Sidebar** (left): Collapsible navigation with your username, current project, and page links.
- **Dashboard** (center): Project grid for creating and opening projects.

The sidebar shows the following pages when a project is open:
- **Log Viewer** -- Browse and search log files
- **Pattern** -- Drain3 template analysis
- **Pattern Analyzer** -- Regex pattern management + ripgrep scanning
- **Telemetry** -- Device telemetry dashboard
- **AI Analysis** -- Semantic search across indexed templates
- **CPE Overview** -- Cross-device comparison dashboard

Admin users also see an **Admin** link for user/NATCO management.

---

## 2. Project Management

### Creating a New Project

1. Click the **"+ New Project"** button on the Dashboard.
2. Enter a **project name** (e.g., "CPE-Debug-2025-01-29").
3. Optionally add a **description**.
4. Optionally select a **NATCO** (country/deployment configuration) from the dropdown. This determines which global pattern set is available for the project. You can also assign or change the NATCO later from the Pattern Analyzer page.
5. Click **Create**.

Each project is an isolated workspace with its own uploaded files, CPEs, parsed data, patterns, and vector embeddings.

### Opening a Project

Click **Open** on any project card to enter the workspace. The sidebar will show the project name and all available tabs.

### Deleting a Project

Click the **trash icon** on a project card and confirm deletion. This removes all associated data.

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

1. **CPE Detection**: The system extracts the MAC address or serial number from the tarball filename to identify the CPE (device).
2. **Tarball Extraction**: `.tgz` files are extracted, preserving the directory structure.
3. **Log Merging**: Logs of the same type are merged chronologically using timestamps.
4. **Per-CPE Storage**: Files are organized under `user_uploads/{user}/{project}/{cpe_id}/`.
5. **Telemetry Detection**: If a `telemetry2_0.txt` file is found, it's flagged for later parsing.
6. **Archive Creation**: A ZIP file of merged logs is created for easy download.

### Multiple Uploads

You can upload multiple tarballs for different CPEs. Each tarball is processed independently and associated with the detected CPE. If two tarballs share the same CPE identifier, their logs are merged together.

---

## 4. CPE (Device) Management

### CPE Selector

When a project has multiple CPEs, a **CPE selector dropdown** appears at the top of every page (Log Viewer, Pattern, Telemetry, AI Analysis, etc.). Select a CPE to view data specific to that device.

### How CPEs Are Identified

CPEs are identified automatically from uploaded tarball filenames:
- MAC addresses (e.g., `AA:BB:CC:DD:EE:FF`)
- Serial numbers (e.g., `CP2505GDDR1`)
- Date extracted from `.tgz` filenames for context

If the system cannot identify a CPE, it assigns a generic identifier.

---

## 5. Log Viewer

The Log Viewer lets you browse, search, and navigate through uploaded log files for the selected CPE.

### Viewing Files

1. Each file is listed with its **name**, **size**, and action buttons.
2. Click the **eye icon** to view a file's contents.
3. Use **pagination** (bottom) to navigate through large files (1000 lines per page).

### Syntax Highlighting

The viewer automatically highlights:
- **Timestamps** -- Date/time strings
- **IP addresses** -- IPv4 and IPv6
- **MAC addresses** -- Hardware addresses
- **Module names** -- Log source identifiers
- **Keywords** -- ERROR, WARN, DEBUG, etc. with color coding

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

## 6. Pattern Analysis (Drain3)

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

## 7. Pattern Analyzer (Regex + ripgrep)

The Pattern Analyzer provides user-defined regex pattern management with high-speed ripgrep scanning across log files.

### NATCO Assignment

If no NATCO was assigned during project creation, the Pattern Analyzer header shows a **NATCO selector dropdown**. Select a NATCO and click **Assign** to link the project to a country/deployment configuration. If a NATCO is already assigned, the header shows a blue badge (e.g., `NATCO: DE - Germany`) with a **change** link.

### Pattern Configuration

Patterns are organized by **domain** (e.g., wireless, platform, core_router).

**Managing Domains:**
- Click **Add Domain** to create a new domain.
- Collapse/expand domains using the chevron icon.
- Delete a domain using the trash icon.

**Managing Patterns:**
- Each pattern has a **name**, **regex**, and **enabled** checkbox.
- Click **+ Add Pattern** within a domain to add a new row.
- Edit pattern names and regex inline.
- Delete individual patterns with the trash icon.

**Import/Export:**
- **Import Preset**: Load patterns from pre-configured YAML files in `configs/rg_patterns/`.
- **Import JSON**: Import patterns from a JSON or YAML file. Supports domain-grouped, flat array, and `rule_parser_config.json` formats.
- **Export**: Download your patterns as JSON or YAML for sharing or backup.
- **Save**: Always click **Save** to persist pattern changes.

### Running a Scan

1. **Select a CPE** (if multiple exist).
2. **Configure scan settings**:
   - Select which domains/patterns to include.
   - Set the bucket size for time aggregation (1 min, 5 min, 15 min, 1 hour, 1 day).
3. Click the **Run Scan** button.
4. Results show a **time-series chart** with pattern occurrences plotted over time.

### Reboot Window Filtering

If reboots are detected in the logs:
- **Reboot boundaries** are shown as vertical red lines on the chart.
- Use the **Start Reboot** and **End Reboot** dropdowns to select a time window.
- Use the **slider** to skip a percentage from the start, focusing on the period before a crash.

### NATCO Governance Buttons

When a NATCO is assigned (see [Pattern Governance](#12-pattern-governance-natco)):
- **Sync from Global** -- Pull the latest global NATCO patterns into your local configuration (merged, not overwritten).
- **Submit to Global** -- Opens a diff-based dialog to submit your changes for admin review.

---

## 8. Embedding / Indexing

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

## 9. Telemetry Dashboard

The Telemetry 2.0 tab provides device health analysis from periodic telemetry reports for the selected CPE.

### Running Telemetry Analysis

1. Switch to the **Telemetry** tab.
2. Select a **CPE** (if multiple exist).
3. Click the **Run** button.
4. The system finds and parses `telemetry2_0.txt` from the selected CPE's uploaded logs.

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

## 10. AI Analysis (Semantic Search)

The AI Analysis tab enables semantic search across all indexed log templates for the selected CPE.

### Performing a Search

1. Select a **CPE** (if multiple exist).
2. Enter a **natural language query** in the search box:
   - Example: "WiFi disconnection issues"
   - Example: "memory leak or OOM"
   - Example: "DSL synchronization failure"
3. Click **Search**.

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

### Requirements

Semantic search requires files to be indexed first. Check the **Embedding** tab to verify files show "indexed" status. If you see a "Collection doesn't exist" message, run the indexing pipeline first.

---

## 11. CPE Overview

The CPE Overview page provides a cross-device comparison dashboard for all CPEs within a project.

### Accessing CPE Overview

Click **CPE Overview** in the sidebar. This page is available when a project has one or more CPEs.

### What It Shows

#### Device Information Table

A comparison table listing each CPE with:
- Serial number and MAC address
- Date range of logs
- Firmware version and hardware model
- Log file count and total size

#### Reboot Comparison

- Bar chart showing **total reboots per CPE**.
- Table with reboot reasons and counts.
- Color-coded bars for easy comparison across devices.

#### Pattern Distribution (by Domain)

For each domain (e.g., wireless, platform):
- Bar chart showing **total log lines** and **unique patterns** per CPE.
- Quick visual comparison of which devices have more activity in each domain.

#### Telemetry Metrics Comparison

Side-by-side comparison of key metrics:
- Memory usage, CPU, uptime
- WiFi client counts, channel utilization
- Connected device counts

### Use Cases

- Compare device behavior across multiple CPEs in the same deployment.
- Identify which devices have the most reboots or errors.
- Spot anomalies by comparing pattern distributions.

---

## 12. Pattern Governance (NATCO)

The NATCO system enables centralized pattern management across countries/deployments with user contributions and admin review.

### Concepts

| Term | Description |
|------|-------------|
| **NATCO** | A country or deployment configuration (e.g., DE - Germany, PL - Poland, EU - European Union) |
| **Global Patterns** | The master pattern set for a NATCO, managed by admins |
| **Local Patterns** | Your project-specific copy of patterns, which you can freely edit |
| **Submission** | A request to merge your local changes into the global set |

### Workflow for Users

#### 1. Assign a NATCO to Your Project

- **During creation**: Select a NATCO from the dropdown in the "Create New Project" modal.
- **After creation**: Go to the **Pattern Analyzer** page. If no NATCO is assigned, a dropdown appears in the header. Select a NATCO and click **Assign**.
- **Change NATCO**: Click the **change** link next to the NATCO badge in the Pattern Analyzer header.

#### 2. Sync Global Patterns

Click **Sync from Global** in the Pattern Analyzer toolbar. This merges the latest global NATCO patterns into your local configuration. Existing local patterns are preserved; new global patterns are added.

#### 3. Edit Patterns Locally

After syncing, you can freely:
- Add new patterns and domains
- Modify pattern names, regex, or enabled state
- Remove patterns you don't need

These changes only affect your project until you submit them.

#### 4. Submit Changes for Review

1. Click **Submit to Global** in the Pattern Analyzer toolbar.
2. The system computes a **diff** against the global configuration:
   - **NEW** patterns (green badge): Regex patterns that don't exist in global.
   - **MODIFIED** patterns (blue badge): Patterns where the name or enabled state differs from global.
   - Unchanged patterns are not shown.
3. All changes are **pre-selected**. Uncheck any patterns you don't want to submit.
4. Add an optional **comment** describing your changes.
5. Click **Submit N Pattern(s) for Review**.

If there are no differences, a "No changes detected" message appears.

#### 5. Track Your Submissions

The **My Submissions** section (below pattern configuration) shows your submission history:
- **Status badges**: pending (yellow), approved (green), rejected (red).
- **Domain**, pattern count, and date.
- **Admin comments** (if any) shown in italics.

This section is **collapsed by default** -- click the header to expand.

**Clear resolved**: Click the **Clear resolved** button to remove all approved/rejected submissions from your history. Pending submissions are preserved.

### Workflow for Admins

See [Admin Features > NATCO Management](#natco-management) and [Admin Features > Pattern Review](#pattern-review) below.

---

## 13. Admin Features

Admin features are accessed via the **Admin** link in the sidebar (visible only to admin users). The admin page has three tabs: **Users**, **NATCO Management**, and **Pattern Review**.

### User Management

Administrators can:
- **View all users**: See usernames, admin status, and creation dates.
- **Delete users**: Remove accounts and their data.
- **Reset passwords**: Set a new password for any user.
- **View projects**: See per-user project counts.

### NATCO Management

Manage country/deployment configurations and their global pattern sets.

#### Managing NATCOs

- **Create NATCO**: Click **+ Create NATCO**, enter a code (e.g., `DE`), name (e.g., `Germany`), and optional description.
- **Edit NATCO**: Click the edit icon to update code, name, or description.
- **Delete NATCO**: Click the delete icon. This also removes all associated global patterns.
- **Pattern count**: The table shows how many global patterns are defined for each NATCO.

#### Editing Global Patterns

Click **Edit Patterns** on a NATCO to open the **Pattern Editor Modal**:

- **Domains**: Patterns are organized by domain. Add/remove domains as needed.
- **Patterns**: Each pattern has a name, regex, and enabled checkbox. Add/edit/remove patterns within each domain.
- **Import Presets**: Click to seed patterns from the YAML files in `configs/rg_patterns/`. Useful for initial setup.
- **Import JSON/YAML**: Click to import patterns from a file. Supports three formats:
  1. **Domain-grouped**: `{ "domains": { "wireless": [{ name, regex, enabled }], ... } }` -- the standard export format.
  2. **Flat array**: `[{ name, regex }, ...]` -- imported into an "Imported" domain.
  3. **rule_parser_config.json**: `{ "Domain": [{ Title, CPELogs: [{ Regex: [{ pattern, description }] }] }] }`.
- **Save All**: Click to persist all changes to the database.

### Pattern Review

Review and act on pattern submissions from users.

#### Viewing Submissions

- **Filter by status**: Use the dropdown to show pending, approved, rejected, or all submissions.
- **Submission details**: Each card shows the submitter's username, domain, NATCO code, pattern count, date, and optional comment.
- Click a submission to **expand** it and see the submitted patterns.

#### Reviewing Patterns

Each submitted pattern shows:
- **NEW** badge (green): A new pattern not in the current global set.
- **MODIFIED** badge (blue): An existing pattern with changes to name or enabled state.
- Pattern name, regex, and enabled status.

#### Taking Action

- **Approve & Merge**: Approves the submission and automatically merges the patterns into the global NATCO configuration. New patterns are added; modified patterns update existing entries.
- **Reject**: Rejects the submission with an optional comment explaining why.
- Add an optional **admin comment** before approving or rejecting.

---

## 14. Tips & Troubleshooting

### Performance Tips

- **Upload one tarball at a time** for best progress tracking.
- **Use the AI search** for pattern discovery rather than manual regex search.
- **Check the Embedding tab** to ensure files are indexed before using semantic search.
- **Use reboot window filtering** in Pattern Analyzer to focus on specific crash windows.
- **Sync from Global regularly** to stay up to date with the latest NATCO patterns.

### Common Issues

| Issue | Solution |
|-------|----------|
| "No similar templates found" | Check that files are indexed (Embedding tab shows "indexed" state) |
| "Collection doesn't exist" in AI Analysis | Run the indexing pipeline first from the Embedding tab |
| "No telemetry2_0 file found" | Upload a tarball that contains `telemetry2_0.txt` |
| Slow search results | Wait for indexing to complete; check Qdrant container is running |
| Upload progress stuck | Refresh the page; check server logs for errors |
| No templates extracted | The log file may not match any rg pattern; check `configs/rg_patterns/` |
| CPE not detected | Ensure the tarball filename contains a MAC address or serial number |
| NATCO selector not showing | Admin must create NATCOs first via the Admin page |
| "No changes detected" in Submit | Your local patterns match the global configuration exactly |
| Pattern scan shows no results | Check that the selected CPE has log files and patterns are enabled |

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Double-click search result | Jump to that line in Log Viewer |
| Click + drag on chart | Zoom into time range |
| Double-click chart | Reset zoom |

### Getting Help

- Check the **README.md** for installation and configuration details.
- Review the **configs/** directory for customizing patterns and telemetry fields.
- Contact the administrator for account or system issues.

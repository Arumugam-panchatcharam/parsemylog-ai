# Knowledge Graph — User Guide

The Knowledge Graph feature lets you define **what to look for** in CPE logs and **how events relate to each other** — without writing code. You build a visual graph of events, issues, and root causes, then run it against your log data to get automated analysis reports.

---

## Table of Contents

1. [Core Concepts](#1-core-concepts)
2. [Creating a Knowledge Graph](#2-creating-a-knowledge-graph)
3. [Node Types](#3-node-types)
4. [Edge Types (Relationships)](#4-edge-types-relationships)
5. [Building a Graph Step by Step](#5-building-a-graph-step-by-step)
6. [Configuring an Event Node](#6-configuring-an-event-node)
7. [Configuring Edge Conditions](#7-configuring-edge-conditions)
8. [Subgraphs (Graph Composition)](#8-subgraphs-graph-composition)
9. [Managing Graphs per NATCO](#9-managing-graphs-per-natco)
10. [Import, Export & Templates](#10-import-export--templates)
11. [Running Issue Analysis](#11-running-issue-analysis)
12. [Reading the Analysis Results](#12-reading-the-analysis-results)
13. [Tips & Best Practices](#13-tips--best-practices)

---

## 1. Core Concepts

A Knowledge Graph is a directed graph where:

- **Nodes** represent things you want to detect or conclude (log patterns, problems, root causes).
- **Edges** represent causal or correlational relationships between nodes, with optional conditions that control when the relationship "fires."

When you run analysis, the system:

1. Scans CPE parquet log files for patterns defined in EVENT nodes.
2. Checks if edge conditions are met (e.g., "WiFi disconnects happened ≥ 10 times").
3. Activates ISSUE and ROOT_CAUSE nodes when enough evidence flows through the graph.
4. Produces a per-CPE report with ranked root causes, causal chains, and telemetry charts.

---

## 2. Creating a Knowledge Graph

1. Navigate to **Knowledge Graph** in the main sidebar.
2. In the left panel, click **New Graph**.
3. Fill in:
   - **Name** — A descriptive name (e.g., "Reboot Root-Cause Analysis").
   - **Description** — Optional context about what this graph analyzes.
   - **NATCO** — Optionally assign to a specific NATCO (or leave as "Global" for all).
4. Click **Create**.

The graph canvas opens, ready for you to add nodes and edges.

### Quick Start from a Template

Instead of building from scratch, click one of the **template buttons** in the sidebar (e.g., "Reboot Root-Cause Analysis"). This imports a pre-built graph with EVENT, ISSUE, and ROOT_CAUSE nodes already configured. You can then customize it.

---

## 3. Node Types

| Type | Color | Purpose | Detects Patterns? |
|------|-------|---------|-------------------|
| **Event** | Blue | A log pattern to search for | Yes — regex/keywords |
| **Condition** | Yellow | A derived threshold or intermediate state | Planned (manual today) |
| **Issue** | Orange | The observable problem (symptom) | No — activated by edges |
| **Root Cause** | Red | The underlying reason (diagnosis) | No — activated by edges |
| **Subgraph** | Purple | Reference to another knowledge graph | Yes — recursive evaluation |

### How they work together

```
EVENT ──(COULD_CAUSE)──> ISSUE
EVENT ──(INDICATES)────> ROOT_CAUSE
EVENT ──(LEADS_TO)─────> EVENT
```

- **EVENT** nodes are the only ones that scan log files. They produce evidence (counts, sample lines, timestamps).
- **ISSUE** and **ROOT_CAUSE** nodes are conclusions. They activate when enough evidence arrives through edges.
- The difference between ISSUE and ROOT_CAUSE:
  - **ISSUE** = "What is happening?" → the symptom (e.g., "Frequent Reboots").
  - **ROOT_CAUSE** = "Why is it happening?" → the diagnosis (e.g., "WiFi Cascade Failure").

Multiple EVENTs can point to the same ISSUE, while specific EVENTs point to specific ROOT_CAUSEs.

---

## 4. Edge Types (Relationships)

Click and drag from one node's bottom handle to another node's top handle to create an edge. Then click the edge to configure it.

| Relationship | Typical Usage |
|---|---|
| **COULD_CAUSE** | An event may cause an issue (e.g., WiFi storms → Frequent Reboots) |
| **LEADS_TO** | One event leads to another (e.g., Memory Crisis → Kernel Crash) |
| **INDICATES** | An event indicates a root cause (e.g., WiFi Driver Errors → WiFi Cascade Failure) |
| **CORRELATES_WITH** | Events appear together but causality is uncertain |

### Edge Conditions

Each edge has optional conditions that control when it fires:

| Condition | Description | Example |
|---|---|---|
| **Min Count** | Source event must have at least this many occurrences | `10` = fire only if ≥ 10 matches |
| **Time Window (min)** | Context for windowed analysis (reboot windows) | `60` = within 60 minutes |
| **Confidence** | Weight assigned to this relationship (0.0 – 1.0) | `0.7` = moderately confident |

If the source event's evidence count is ≥ Min Count, the edge fires and activates the target node.

---

## 5. Building a Graph Step by Step

Here's a walkthrough for creating a simple "WiFi causing reboots" analysis:

### Step 1: Add Event Nodes

Click **+ Event** in the toolbar. Create these events:

| Name | Keywords | Source Domains |
|---|---|---|
| `wifi_disconnect_storm` | `\bdisassoc`, `\bdeauth`, `disconnected\s+event` | `wireless` |
| `kernel_crash` | `kernel panic`, `Oops`, `BUG:` | `platform` |

### Step 2: Add an Issue Node

Click **+ Issue**. Name it `frequent_reboots` with label "Frequent Reboots."

### Step 3: Add a Root Cause Node

Click **+ Root Cause**. Name it `wifi_cascade` with label "WiFi Cascade Failure."

### Step 4: Connect with Edges

- Drag from `wifi_disconnect_storm` → `frequent_reboots`. Set:
  - Relationship: **COULD_CAUSE**
  - Min Count: `10`
  - Confidence: `0.7`
- Drag from `kernel_crash` → `frequent_reboots`. Set:
  - Relationship: **COULD_CAUSE**
  - Min Count: `1`
  - Confidence: `0.95`
- Drag from `wifi_disconnect_storm` → `wifi_cascade`. Set:
  - Relationship: **INDICATES**
  - Min Count: `10`
  - Confidence: `0.8`

### Step 5: Auto-Layout

Click **Layout** in the toolbar to arrange nodes in columns by type.

---

## 6. Configuring an Event Node

Click any EVENT node to open the property editor on the right.

### Keywords / Regex (one per line)

These are the patterns the system searches for in log data. Each line is compiled as a case-insensitive regex.

```
\bdisassoc
\bdeauth
disconnected\s+event
```

**Tips:**
- Use `\b` for word boundaries to avoid partial matches.
- Use `\s+` for flexible whitespace matching.
- Each keyword is OR'd — a line matches if **any** pattern hits.

### Source Domains (comma-separated)

Limit which parquet log files to search. These correspond to the `_domain` column in parquet data.

```
wireless, platform
```

Leave empty to search all domains.

### Exclusions (one per line)

Regex patterns that **reject** a log line before it can match any keyword. Exclusions are checked first.

```
scheduled_maintenance
test_disconnect
admin_initiated
```

**How it works:**
1. For each log line, check exclusions first.
2. If **any** exclusion matches → skip the line entirely.
3. If no exclusion matches → check keywords.
4. If **any** keyword matches → count as evidence.

**Use case:** You want to detect WiFi disconnections but exclude expected/planned ones.

---

## 7. Configuring Edge Conditions

Click any edge (the line between nodes) to open the edge editor.

### Min Count

The source node must have accumulated **at least this many** evidence hits for the edge to fire.

- Set to `1` for critical events (kernel panics — even one is significant).
- Set to `10+` for noisy events (WiFi disconnects — only a storm is meaningful).

### Time Window (minutes)

Used during per-reboot windowed analysis. The system looks at events within ±N minutes of each reboot to determine what likely caused it.

### Confidence (0.0 – 1.0)

How strongly this relationship implies the target. Used to rank root causes:

- `0.95` — Near certain (kernel panic → reboot).
- `0.7` — Likely (WiFi storm → reboot).
- `0.4` — Possible but weak (BTM steering → reboot).

---

## 8. Subgraphs (Graph Composition)

Subgraphs let you **reuse one graph inside another**. For example, a "WiFi Health" graph can be a component of a "Reboot Analysis" graph.

### Creating a Subgraph Reference

1. Click **+ Subgraph** in the toolbar.
2. In the property editor, select the **Referenced Graph** from the dropdown.
3. Choose an **Activation Mode**:
   - **Any issue activates** — The subgraph fires if any of its internal ISSUE/ROOT_CAUSE nodes activate.
   - **All issues must activate** — The subgraph only fires if every internal issue activates.

### How it works

When analysis runs:
1. The system recursively evaluates the referenced graph against the same log data.
2. If the subgraph activates (based on the chosen mode), its evidence is propagated back to the parent graph as if the SUBGRAPH node were an EVENT with that evidence count.
3. Edges from the SUBGRAPH node to ISSUE/ROOT_CAUSE nodes then fire normally.

Cycle detection prevents infinite loops if graphs reference each other.

---

## 9. Managing Graphs per NATCO

Log patterns often differ between NATCOs (e.g., DE vs EU-HR). You can assign a graph to a specific NATCO:

### In the Knowledge Graph Editor

- Use the **NATCO dropdown** at the top of the sidebar to filter the graph list.
- When creating a new graph, select a NATCO or leave it as "Global."

### In Issue Analysis

When running analysis on a project:
- The graph dropdown shows **NATCO-specific graphs** (matching the project's NATCO) **plus all Global graphs**.
- Global graphs are marked with "(Global)" in the dropdown.

---

## 10. Import, Export & Templates

### Export a Graph

1. Select a graph in the sidebar.
2. Click **Export** (download icon) in the toolbar.
3. A JSON file is downloaded containing all nodes, edges, and metadata.

### Import a Graph

1. Click **Import JSON** in the sidebar.
2. Select a `.json` file in the knowledge graph export format.
3. A new graph is created with all the imported nodes and edges.

### Templates

Pre-built templates appear in the sidebar. Click a template to create a new graph from it. The included template **"Reboot Root-Cause Analysis"** comes with:

- 9 EVENT nodes (WiFi storms, WAN disconnections, memory issues, kernel crashes, etc.)
- 1 ISSUE node (Frequent Reboots)
- 2 ROOT_CAUSE nodes (WiFi Cascade Failure, Memory Cascade Failure)
- 17 edges with calibrated conditions and confidence scores

---

## 11. Running Issue Analysis

1. Navigate to your project workspace → **Issue Analysis** in the sidebar.
2. Select a **Batch Job** (for multi-CPE projects) or it auto-detects single-CPE mode.
3. Select a **Knowledge Graph** from the dropdown.
4. Click **Run Analysis**.
5. The page auto-refreshes every 5 seconds while analysis runs, or click **Refresh** manually.

Analysis is processed asynchronously via Celery. For large batch jobs (many CPEs), it may take a few minutes.

---

## 12. Reading the Analysis Results

### Fleet Overview (Multi-CPE)

The top section shows aggregate statistics:

| Metric | Description |
|---|---|
| Total CPEs | Number of CPE devices analyzed |
| Total Reboots | Sum of reboots across all CPEs |
| CPEs with Reboots | How many CPEs had at least one reboot |
| Avg Reboots/CPE | Average reboots per affected CPE |

Plus:
- **Problem Areas** — WiFi, WAN, and Memory health summaries.
- **Trigger Distribution** — Pie chart showing what likely caused reboots across the fleet.
- **Root Cause Distribution** — Pie chart of identified root causes.
- **Hardware/Firmware Breakdown** — Tags showing device model and firmware distribution.

### Per-CPE Detail

Click any CPE serial number to expand its individual report:

- **Root Cause Ranking** — Ordered list with confidence scores and evidence counts. A score bar shows the relative strength of each root cause.
- **Causal Chains** — The paths through the graph that activated (e.g., `WiFi Disconnect Storm → Frequent Reboots`).
- **Aggregate Issues** — Color-coded tags showing event counts by severity.
- **Reboot Events** — Expandable cards for each reboot showing:
  - Timestamp and reason.
  - Likely trigger and description.
  - Window events (what happened ±N minutes around the reboot).
  - Sample log lines from each event category.
- **Telemetry Charts** — CPU, Memory, Temperature, and Connected Devices over time, with vertical markers at each reboot.

---

## 13. Tips & Best Practices

### Graph Design

- **Start with the template** and customize rather than building from scratch.
- **One ISSUE per graph** keeps analysis focused and results readable.
- Use **multiple ROOT_CAUSE nodes** to distinguish between different failure modes.
- Use **LEADS_TO edges** between events to model cascading failures (e.g., memory crisis → kernel crash).

### Event Patterns

- **Be specific with regex** — use word boundaries (`\b`) and anchoring to avoid false positives.
- **Use exclusions** to filter out expected/planned events that would add noise.
- **Limit source domains** to only the relevant parquet files for faster analysis and fewer false matches.

### Edge Conditions

- **Set appropriate min counts** — Critical events (kernel panic) need count ≥ 1. Noisy events (WiFi disconnects) need count ≥ 10+.
- **Calibrate confidence** — Higher confidence = more weight in root cause ranking. Use 0.9+ for near-certain causality, 0.5–0.7 for probable, below 0.5 for weak correlations.

### NATCO Management

- Create **Global graphs** for patterns common across all NATCOs.
- Create **NATCO-specific graphs** when log formats or failure patterns differ (e.g., different firmware, different hardware).
- In Issue Analysis, both global and NATCO-specific graphs are available.

### Subgraphs

- Use subgraphs to **modularize** complex analysis. E.g., "WiFi Health Check" as a subgraph inside "Reboot Analysis."
- Choose **"Any issue activates"** for broad detection, **"All issues must activate"** for strict conditions.
- Avoid creating circular references (the system detects and prevents cycles).

# Knowledge Graph

## Overview

Knowledge Graph visualizes log event relationships and causal chains using graph algorithms and interactive D3.js/XYFlow rendering.

## Key Capabilities

- **Automatic Graph Construction** from log events
- **Node Types:** Events, Entities (IPs, SSIDs, interfaces)
- **Edge Types:** Temporal, Causal, Co-occurrence
- **Interactive Visualization** with zoom, pan, filtering
- **Path Analysis** - Find root causes, identify cascades
- **Export** - GraphML, JSON formats

## Usage

### Generate Graph

```
┌──────────────────────────────────────────────────────┐
│ Knowledge Graph                                      │
│ CPE: [AABBCCDDEEFF ▼]                                │
│ Time Range: [Last 24 hours ▼]                       │
│ Include: ☑ Errors  ☑ Warnings  ☐ Info               │
│ [Generate Graph]                                     │
└──────────────────────────────────────────────────────┘

Generating graph...
✓ Extracted 234 events
✓ Identified 45 entities
✓ Computed 189 relationships
✓ Graph ready
```

### Explore Graph

```
[Interactive Graph Visualization]

Nodes:
○ Red circles: Error events
○ Yellow circles: Warning events
○ Blue squares: Network entities (IPs, SSIDs)
○ Green diamonds: System components

Edges:
→ Solid arrows: Temporal (A happened before B)
⇢ Dashed arrows: Causal (A likely caused B)
― Dotted lines: Co-occurrence

Controls:
[🔍 Zoom In] [🔎 Zoom Out] [🎯 Center] [📤 Export]
```

### Find Root Cause

```
Select Event: WiFi Connection Failed (18:45:22)

Root Cause Analysis:
1. Signal strength dropped to -75 dBm (18:44:10)
   ↓
2. High noise floor detected (18:44:30)
   ↓
3. Channel congestion warning (18:44:50)
   ↓
4. Connection timeout (18:45:15)
   ↓
5. WiFi Connection Failed (18:45:22)

Recommendation: Investigate channel interference sources
```

## API Reference

```http
POST /api/<project_id>/knowledge-graph/generate
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "cpe_id": "AABBCCDDEEFF",
  "time_range": {
    "start": "2024-03-13T00:00:00Z",
    "end": "2024-03-14T00:00:00Z"
  },
  "include_levels": ["error", "warning"]
}

Response:
{
  "graph_id": "kg_123",
  "nodes": 234,
  "edges": 189,
  "graph_data": {
    "nodes": [...],
    "edges": [...]
  }
}
```

## Related Features

- [Log Viewer](./LOG_VIEWER.md)
- [Drain3 Patterns](./DRAIN3_PATTERNS.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

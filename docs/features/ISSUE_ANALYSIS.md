# Issue Analysis

## Overview

Issue Analysis provides focused investigation of specific problems with multi-source data correlation.

## Key Capabilities

- **Issue Definition** - Specify issue type and time range
- **Data Collection** - Gather logs, telemetry, PCAP
- **Correlation** - Temporal alignment across data sources
- **Root Cause Analysis** - Identify common precursors
- **Reporting** - Generate PDF summaries

## Usage

### Define Issue

```
┌──────────────────────────────────────────────────────┐
│ New Issue Investigation                              │
│ Title: [WiFi Disconnects During Peak Hours──────]    │
│ Type: [Connectivity ▼]                               │
│ Affected CPEs: ☑ AABBCCDDEEFF  ☑ CCDDEE112233       │
│ Time Range: [2024-03-13 17:00] to [20:00]           │
│ [Start Investigation]                                │
└──────────────────────────────────────────────────────┘
```

### Collect Data

```
Collecting data for issue investigation...

✓ Logs: 2,345 relevant lines found
✓ Telemetry: 180 metric snapshots
✓ PCAP: 45,678 packets in time range
✓ Patterns: 12 matching error patterns

[View Timeline] [Generate Report]
```

### Timeline View

```
Timeline: WiFi Disconnects (17:00 - 20:00)

17:30 ┤ Signal strength drops to -72 dBm
17:32 ┤ High noise floor detected (-88 dBm)
17:35 ┤ [PCAP] Increased packet loss (12%)
17:38 ┤ [LOG] WiFi disconnect (reason=4)
17:40 ┤ [LOG] Reconnection attempt
17:42 ┤ [PCAP] DHCP timeout
17:45 ┤ [LOG] Connection restored

Pattern repeats every ~30 minutes
```

## API Reference

```http
POST /api/<project_id>/issues
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "title": "WiFi Disconnects",
  "type": "connectivity",
  "cpe_ids": ["AABBCCDDEEFF"],
  "time_range": {
    "start": "2024-03-13T17:00:00Z",
    "end": "2024-03-13T20:00:00Z"
  }
}
```

## Related Features

- [Log Viewer](./LOG_VIEWER.md)
- [Telemetry Dashboard](./TELEMETRY.md)
- [PCAP Analysis](./PCAP_ANALYSIS.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

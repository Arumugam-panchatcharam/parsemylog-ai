# Telemetry CSV Export

## Overview

Telemetry CSV Export enables exporting parsed telemetry data to CSV format for external analysis in Excel, Pandas, R, etc.

## Key Capabilities

- **Selective Export** - Choose specific metrics or all fields
- **Time Range Filtering** - Export specific date ranges
- **Per-CPE or Aggregated** - Single CPE or fleet-wide
- **Scheduled Exports** - Automated periodic exports
- **Email Delivery** - Optional email with CSV attachment

## Usage

### Export Configuration

```
┌──────────────────────────────────────────────────────┐
│ Export Telemetry to CSV                              │
│ CPE: [AABBCCDDEEFF ▼] (or "All CPEs")                │
│ Time Range: [Last 7 days ▼]                          │
│ Custom: [2024-03-06] to [2024-03-13]                 │
│                                                      │
│ Fields:                                              │
│ ☑ Timestamp                                          │
│ ☑ Device Info (Model, Firmware, Uptime)              │
│ ☑ WiFi Metrics (RSSI, Channel, Noise)                │
│ ☑ Network Stats (Bytes Sent/Received)                │
│ ☑ System Metrics (CPU, Memory)                       │
│ ☐ All Available Fields                               │
│                                                      │
│ [📥 Download CSV] [📧 Email CSV]                     │
└──────────────────────────────────────────────────────┘
```

### CSV Format

```csv
Timestamp,CPE_ID,Model,Firmware,Uptime_Hours,RSSI_2.4GHz,Channel_2.4GHz,NoiseFloor,BytesSent,BytesReceived,CPU_Usage,Memory_Usage
2024-03-13 14:00:00,AABBCCDDEEFF,Gateway v2,24.02.1.5,142.5,-45,6,-92,123456789,987654321,12,45
2024-03-13 14:05:00,AABBCCDDEEFF,Gateway v2,24.02.1.5,142.6,-47,6,-92,123567890,987765432,13,46
```

### Scheduled Export

```
┌──────────────────────────────────────────────────────┐
│ Schedule Telemetry Export                            │
│ Frequency: [Daily ▼] at [02:00 ▼]                    │
│ Email: [user@example.com────────────]                │
│ Include: Last [7] days of data                       │
│ CPEs: ☑ All                                          │
│ [Save Schedule]                                      │
└──────────────────────────────────────────────────────┘

✅ Scheduled export created!
Next run: 2024-03-14 02:00
```

## API Reference

```http
GET /api/<project_id>/telemetry/export?cpe_id=AABBCCDDEEFF&format=csv&start=2024-03-06&end=2024-03-13
Authorization: Bearer <access_token>

Response:
Content-Type: text/csv
Content-Disposition: attachment; filename="telemetry_AABBCCDDEEFF_2024-03-06_to_2024-03-13.csv"

<CSV content>
```

## Use Cases

**Excel Analysis:**

- Pivot tables for aggregations
- Charts and graphs
- Statistical functions

**Pandas/Python:**

```python
import pandas as pd
df = pd.read_csv('telemetry.csv', parse_dates=['Timestamp'])
print(df.groupby('CPE_ID')['RSSI_2.4GHz'].mean())
```

**R Analysis:**

```r
library(tidyverse)
df <- read_csv('telemetry.csv')
df %>% group_by(CPE_ID) %>% summarize(avg_rssi = mean(RSSI_2.4GHz))
```

## Related Features

- [Telemetry Dashboard](./TELEMETRY.md)
- [CPE Overview](./CPE_OVERVIEW.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)
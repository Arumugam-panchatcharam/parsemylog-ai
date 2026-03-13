# CPE Overview Dashboard

## Overview

The CPE Overview Dashboard provides cross-device comparison and fleet-level analytics. It aggregates metrics from multiple CPEs to identify common issues, outlier devices, and deployment-wide trends.

## Key Capabilities

- **Device Comparison Table** - Side-by-side CPE metadata
- **Reboot Count Analysis** - Identify problematic devices
- **Error Distribution Charts** - Pattern frequency by domain
- **Telemetry Comparison** - Multi-line charts (one per CPE)
- **Fleet Statistics** - Aggregated metrics and trends
- **Outlier Detection** - Identify abnormal devices
- **Export** - CSV reports for all CPEs

## How It Works

### Data Aggregation

```
Per-CPE Data → Aggregate → Normalize → Visualize
```

**Sources:**

- Device metadata (model, firmware, uptime)
- Reboot counts from reboot_events.json
- Error patterns from Drain3 templates
- Telemetry metrics from parsed reports

**Aggregation:**

```python
cpe_data = []
for cpe in project_cpes:
    cpe_data.append({
        'cpe_id': cpe.cpe_identifier,
        'metadata': get_device_info(cpe),
        'reboot_count': count_reboots(cpe),
        'error_patterns': get_drain3_templates(cpe),
        'telemetry': get_telemetry_summary(cpe)
    })

# Compute fleet statistics
fleet_stats = {
    'total_cpes': len(cpe_data),
    'avg_uptime': mean([c['metadata']['uptime'] for c in cpe_data]),
    'total_reboots': sum([c['reboot_count'] for c in cpe_data]),
    'common_errors': find_common_patterns(cpe_data)
}
```

## Usage

### Device Comparison

**Navigation:**

1. Go to project
2. Click "CPE Overview" in sidebar
3. Dashboard loads automatically

**Comparison Table:**

```
┌──────────────────────────────────────────────────────────────────────────┐
│ CPE Comparison (3 devices)                                               │
├────────┬──────────┬──────────┬──────────┬─────────┬──────────────────────┤
│ CPE ID │ Model    │ Firmware │ Uptime   │ Reboots │ Top Error            │
├────────┼──────────┼──────────┼──────────┼─────────┼──────────────────────┤
│ AABB   │ Gateway  │ 24.02.1  │ 142h 35m │ 3       │ WiFi timeout (234)   │
│ CCDD   │ Gateway  │ 24.02.1  │ 87h 12m  │ 7 🔴    │ DHCP failed (156)    │
│ EEFF   │ Gateway  │ 24.03.0  │ 234h 18m │ 1       │ Kernel warn (45)     │
└────────┴──────────┴──────────┴──────────┴─────────┴──────────────────────┘

🔴 = Outlier (significantly more than average)
```

**Sorting:**
Click column header to sort:

- Most reboots first
- Lowest uptime first
- By firmware version

### Reboot Analysis

**Reboot Count Chart:**

```
Reboot Count by CPE

[Bar Chart showing:
 - X-axis: CPE IDs
 - Y-axis: Reboot count
 - Red bars for outliers (>2σ from mean)
]

Statistics:
- Total Reboots: 11
- Average: 3.7 per CPE
- Median: 3
- Outliers: CCDD (7 reboots - high)
```

**Reboot Timeline:**

```
Reboot Events Timeline

[Scatter plot showing:
 - X-axis: Time
 - Y-axis: CPE ID
 - Markers: Reboot events
 - Colors: By reboot reason (if known)
]

Patterns:
- Cluster of reboots at 18:45 (possible power issue)
- CCDD frequent reboots (investigate)
```

### Error Distribution

**By Domain:**

```
Error Patterns by Domain

[Stacked Bar Chart:
 - X-axis: CPE IDs
 - Y-axis: Error count
 - Segments: Domain (wifi, platform, cellular, etc.)
]

Insights:
- All CPEs show WiFi errors (common issue)
- CCDD has abnormally high platform errors
- EEFF firmware 24.03.0 shows fewer errors overall
```

**Common Patterns:**

```
Top 10 Patterns Across Fleet

1. WiFi Connection Failed
   CPEs affected: 3/3 (100%)
   Total occurrences: 479
   Avg per CPE: 160

2. DHCP Timeout
   CPEs affected: 2/3 (67%)
   Total occurrences: 234
   Avg per CPE: 117

3. Kernel Warning
   CPEs affected: 3/3 (100%)
   Total occurrences: 156
   Avg per CPE: 52
```

### Telemetry Comparison

**Multi-CPE Charts:**

```
Signal Strength Comparison (Last 24h)

[Line Chart with 3 lines:
 - Blue: AABB (steady -45 to -52 dBm)
 - Red: CCDD (fluctuating -38 to -68 dBm) 🔴
 - Green: EEFF (steady -42 to -48 dBm)
]

Analysis:
- CCDD shows high signal variance (unstable connection)
- AABB and EEFF stable signals
```

**CPU Usage Comparison:**

```
CPU Usage (%)

[Line Chart:
 - AABB: 10-15% (normal)
 - CCDD: 45-98% (abnormally high) 🔴
 - EEFF: 8-12% (normal)
]

Alert:
- CCDD CPU usage consistently high
- May explain frequent reboots
- Investigate runaway processes
```

### Fleet Statistics

**Overview Cards:**

```
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ Total Devices       │  │ Avg Uptime          │  │ Total Reboots       │
│ 3                   │  │ 154.5 hours         │  │ 11                  │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘

┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ Firmware Versions   │  │ Total Errors        │  │ Outlier Devices     │
│ 24.02.1: 2          │  │ 1,234               │  │ 1 (CCDD)            │
│ 24.03.0: 1          │  │                     │  │                     │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

## API Reference

### Get CPE Overview

```http
GET /api/<project_id>/cpe-overview
Authorization: Bearer <access_token>

Response:
{
  "cpes": [
    {
      "cpe_id": "AABBCCDDEEFF",
      "metadata": {
        "model": "RDK-B Gateway v2",
        "firmware": "24.02.1.5",
        "uptime_seconds": 512345,
        "mac": "AA:BB:CC:DD:EE:FF"
      },
      "stats": {
        "total_lines": 1234567,
        "reboot_count": 3,
        "error_count": 4523,
        "error_by_domain": {
          "wifi": 1892,
          "platform": 1456,
          "cellular": 1175
        }
      },
      "telemetry_summary": {
        "avg_signal_strength": -47.2,
        "avg_cpu_usage": 12.5,
        "avg_memory_usage": 45.3
      }
    },
    ...
  ],
  "fleet_stats": {
    "total_cpes": 3,
    "avg_uptime_hours": 154.5,
    "total_reboots": 11,
    "total_errors": 1234,
    "outliers": ["CCDD"]
  },
  "common_patterns": [
    {
      "template": "[wifi] ERROR: Failed to connect to SSID <*>",
      "cpes_affected": 3,
      "total_occurrences": 479,
      "avg_per_cpe": 160
    }
  ]
}
```

### Pattern Scan (All CPEs)

```http
POST /api/<project_id>/cpe-overview/pattern-scan
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "patterns": [
    {
      "name": "WiFi Connection Failed",
      "regex": "Failed to connect to SSID"
    }
  ]
}

Response:
{
  "scan_id": "fleet_scan_123",
  "status": "running",
  "cpes_to_scan": 3,
  "estimated_time_seconds": 15
}
```

### Export Fleet Report

```http
GET /api/<project_id>/cpe-overview/export?format=csv
Authorization: Bearer <access_token>

Response:
Content-Type: text/csv
Content-Disposition: attachment; filename="fleet_report_project_42.csv"

CPE_ID,Model,Firmware,Uptime_Hours,Reboots,WiFi_Errors,Platform_Errors,Cellular_Errors
AABBCCDDEEFF,Gateway v2,24.02.1.5,142.6,3,1892,1456,1175
...
```

## Analysis Techniques

### Outlier Detection

**Statistical Method:**

```python
# Z-score method
mean_reboots = statistics.mean(reboot_counts)
std_reboots = statistics.stdev(reboot_counts)

outliers = []
for cpe, count in zip(cpes, reboot_counts):
    z_score = (count - mean_reboots) / std_reboots
    if abs(z_score) > 2:  # >2 standard deviations
        outliers.append((cpe, count, z_score))
```

**Criteria:**

- Reboot count: >2σ from mean
- Error rate: >2σ from mean
- Signal strength: <-70 dBm consistently
- CPU usage: >80% sustained

### Common Issue Identification

**Pattern Prevalence:**

```python
# Pattern appears in >50% of CPEs = common issue
common_threshold = 0.5
common_patterns = []

for pattern in all_patterns:
    cpes_with_pattern = count_cpes_with_pattern(pattern)
    prevalence = cpes_with_pattern / total_cpes
    
    if prevalence >= common_threshold:
        common_patterns.append({
            'pattern': pattern,
            'prevalence': prevalence,
            'likely_cause': 'firmware bug' if prevalence > 0.8 else 'config issue'
        })
```

### Correlation Analysis

**Identify Relationships:**

```python
# Correlate firmware version with error rate
from scipy.stats import pearsonr

firmware_versions = [cpe['firmware'] for cpe in cpes]
error_rates = [cpe['error_count'] / cpe['total_lines'] for cpe in cpes]

# Check if newer firmware reduces errors
correlation, p_value = pearsonr(firmware_versions_numeric, error_rates)
```

## Troubleshooting

### Issue: Not all CPEs shown

**Cause:** Extraction or indexing incomplete

**Solution:**

```http
# Check project CPEs
GET /api/<project_id>/cpes

# Verify each CPE has data
GET /api/<project_id>/files/content?cpe_id=<cpe_id>&page=1&page_size=10
```

### Issue: Charts empty

**Possible Causes:**

1. Telemetry not parsed
2. No common time range
3. Data format mismatch

**Debug:**

```bash
# Check telemetry data
curl "http://localhost:40901/api/42/telemetry/data?cpe_id=AABBCCDDEEFF"

# Check reboot events
cat SERIAL_OR_MAC_*/reboot_events.json
```

## Best Practices

### Fleet Size Recommendations


| CPEs   | Visualization               | Notes             |
| ------ | --------------------------- | ----------------- |
| 2-5    | Side-by-side comparison     | Detailed analysis |
| 6-20   | Grouped charts              | Medium fleet      |
| 21-100 | Aggregated stats + outliers | Large fleet       |
| 100+   | Statistical summary only    | Use batch jobs    |


### Comparison Strategies

**Cohort Analysis:**

- Group by firmware version
- Group by deployment site
- Group by device model
- Group by time period

**Example:**

```
Firmware 24.02.1 vs 24.03.0

Metrics:
- Avg reboots: 5.2 vs 1.8 (improvement!)
- WiFi errors: 234 vs 89 (improvement!)
- CPU usage: 15% vs 12% (improvement!)

Conclusion: Upgrade recommended
```

## Related Features

- [Multi-CPE Support](./MULTI_CPE.md) - Per-CPE isolation
- [Telemetry Dashboard](./TELEMETRY.md) - Per-CPE telemetry
- [Batch Processing](./BATCH_PROCESSING.md) - Fleet-scale analysis
- [Pattern Analyzer](./PATTERN_ANALYZER.md) - Cross-CPE scanning

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)
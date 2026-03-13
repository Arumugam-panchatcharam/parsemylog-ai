# Telemetry Dashboard

## Overview

The Telemetry Dashboard provides interactive visualization of TR-181 parameters extracted from Telemetry 2.0 periodic reports. It features time-series charts, status cards, device information panels, and trend analysis with reboot boundary markers.

## Key Capabilities

- **YAML-Driven Parsing** of TR-181 parameters
- **Interactive Plotly Charts** for metric trends
- **Status Cards** for radio stats, SSID info, interface status
- **Device Information Panel** with model, firmware, uptime
- **Reboot Boundary Markers** on timelines
- **Cross-CPE Comparison** on CPE Overview page
- **Export** to CSV for external analysis
- **Custom Field Configuration** via YAML

## How It Works

### Data Source

**Telemetry Files:**

```
SERIAL_OR_MAC_AABBCCDDEEFF/
└── files/
    ├── Telemetry_2.0_report_001.txt
    ├── Telemetry_2.0_report_002.txt
    └── Telemetry_2.0_report_003.txt
```

**File Format Example:**

```
============================================
Telemetry Report - 2024-03-13 14:32:10
============================================

Device.DeviceInfo.ModelName = RDK-B Gateway v2
Device.DeviceInfo.SoftwareVersion = 24.02.1.5
Device.DeviceInfo.UpTime = 512345

Device.WiFi.Radio.1.Enable = true
Device.WiFi.Radio.1.Channel = 6
Device.WiFi.Radio.1.Stats.X_COMCAST-COM_NoiseFloor = -92

Device.WiFi.SSID.1.SSID = MyNetwork
Device.WiFi.SSID.1.Enable = true
Device.WiFi.SSID.1.Status = Up

Device.IP.Interface.1.Stats.BytesSent = 1234567890
Device.IP.Interface.1.Stats.BytesReceived = 9876543210
```

### Parsing Pipeline

```
Telemetry Files → YAML Field Definitions → Extract Values → Time Series → Charts
```

**Step 1: Define Fields (YAML)**

`configs/telemetry_report_fields.yaml`:

```yaml
device_info:
  - field: Device.DeviceInfo.ModelName
    label: Model
    type: string
  - field: Device.DeviceInfo.SoftwareVersion
    label: Firmware
    type: string
  - field: Device.DeviceInfo.UpTime
    label: Uptime
    type: integer
    unit: seconds

wifi_radio:
  - field: Device.WiFi.Radio.1.Stats.X_COMCAST-COM_NoiseFloor
    label: Noise Floor
    type: integer
    unit: dBm
    chart: line
  - field: Device.WiFi.Radio.1.Channel
    label: Channel
    type: integer
    chart: scatter

network_stats:
  - field: Device.IP.Interface.1.Stats.BytesSent
    label: Bytes Sent
    type: integer
    unit: bytes
    chart: line
    derivative: true  # Plot rate of change (Bps)
```

**Step 2: Parse Reports**

```python
def parse_telemetry(file_path, field_definitions):
    data = {}
    with open(file_path) as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Check if field is in definitions
                if key in field_definitions:
                    field_def = field_definitions[key]
                    typed_value = convert_type(value, field_def['type'])
                    data[key] = typed_value
    
    return data
```

**Step 3: Build Time Series**

```python
time_series = []
for report_file in sorted(telemetry_files):
    timestamp = extract_timestamp(report_file)
    values = parse_telemetry(report_file, field_definitions)
    
    time_series.append({
        'timestamp': timestamp,
        'values': values
    })
```

**Step 4: Generate Charts**

```python
# Plotly line chart
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=[t['timestamp'] for t in time_series],
    y=[t['values']['Device.WiFi.Radio.1.Stats.X_COMCAST-COM_NoiseFloor'] for t in time_series],
    mode='lines+markers',
    name='Noise Floor'
))

# Add reboot markers
for reboot in reboot_events:
    fig.add_vline(x=reboot['timestamp'], line_dash="dash", line_color="red")
```

## Usage

### View Telemetry

**Navigation:**

1. Go to project
2. Select CPE
3. Click "Telemetry" in sidebar
4. Click "Parse Telemetry" button (first time)

**Dashboard Layout:**

```
┌────────────────────────────────────────────────────────────┐
│ Telemetry Dashboard - CPE: AABBCCDDEEFF                    │
│ [🔄 Refresh] [📥 Export CSV] Last Updated: 2 min ago       │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ Device Information                                         │
│ ┌──────────────────────────────────────────────────────┐   │
│ │ Model: RDK-B Gateway v2    Firmware: 24.02.1.5       │   │
│ │ MAC: AA:BB:CC:DD:EE:FF     Uptime: 142h 35m          │   │
│ │ Manufacturer: TechVendor   Serial: 1234567890        │   │
│ └──────────────────────────────────────────────────────┘   │
│                                                            │
│ WiFi Radio Status                                          │
│ ┌─────────────┬─────────────┬─────────────┐                │
│ │ Radio 1     │ Radio 2     │ Radio 3     │                │
│ │ 2.4 GHz     │ 5 GHz       │ 6 GHz       │                │
│ │ Channel: 6  │ Channel: 36 │ Channel: 5  │                │
│ │ RSSI: -45dBm│ RSSI: -52dBm│ RSSI: -48dBm│                │
│ │ Noise: -92  │ Noise: -95  │ Noise: -93  │                │
│ │ ✅ Enabled  │ ✅ Enabled  │ ❌ Disabled │                │
│ └─────────────┴─────────────┴─────────────┘                │
│                                                            │
│ Signal Strength Trend (Last 24h)                           │
│ [Interactive Plotly Chart]                                 │
│                                                            │
│ Network Throughput                                         │
│ [Interactive Plotly Chart]                                 │
│                                                            │
│ CPU & Memory Usage                                         │
│ [Interactive Plotly Chart]                                 │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Interactive Charts

**Features:**

- **Zoom:** Click and drag to zoom into time range
- **Pan:** Hold shift and drag to pan
- **Hover:** Tooltips show exact values
- **Legend:** Click to toggle traces
- **Download:** Save as PNG image

**Chart Types:**

1. **Line Charts:**
  - Signal strength (RSSI, SNR, Noise Floor)
  - Network throughput (TX/RX rate)
  - CPU/Memory usage
2. **Scatter Plots:**
  - Channel changes over time
  - Discrete state changes
3. **Bar Charts:**
  - Client counts per SSID
  - Error counts per interface

### Reboot Analysis

**Reboot Markers:**
Red dashed lines on charts indicate system reboots.

**Reboot Context:**
Click reboot marker to see:

- Reboot timestamp
- Uptime before reboot
- Metrics before/after reboot
- Potential cause (if detected)

**Example:**

```
Reboot: 2024-03-13 18:45:22
Previous Uptime: 87h 23m
Reason: Watchdog timeout (detected from logs)

Metrics before reboot:
- CPU Usage: 98% (abnormally high)
- Memory: 95% used
- WiFi Errors: 234 in last hour

Metrics after reboot:
- CPU Usage: 12%
- Memory: 45% used
- WiFi Errors: 0
```

### Export Data

**CSV Export:**

```csv
Timestamp,Model,Firmware,Channel_2.4GHz,RSSI_2.4GHz,NoiseFloor_2.4GHz,BytesSent,BytesReceived
2024-03-13 14:30:00,RDK-B Gateway v2,24.02.1.5,6,-45,-92,1234567890,9876543210
2024-03-13 14:35:00,RDK-B Gateway v2,24.02.1.5,6,-47,-92,1235678901,9877654321
...
```

Use exported data in Excel, Pandas, R, etc.

## API Reference

### Parse Telemetry

```http
POST /api/<project_id>/telemetry/parse?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response:
{
  "message": "Telemetry parsing started",
  "task_id": "tel_xyz789",
  "estimated_time_seconds": 30
}
```

### Get Telemetry Data

```http
GET /api/<project_id>/telemetry/data?cpe_id=<cpe_id>
Authorization: Bearer <access_token>

Response:
{
  "device_info": {
    "model": "RDK-B Gateway v2",
    "firmware": "24.02.1.5",
    "uptime_seconds": 512345,
    "mac": "AA:BB:CC:DD:EE:FF"
  },
  "time_series": [
    {
      "timestamp": "2024-03-13T14:30:00Z",
      "metrics": {
        "wifi_radio_1_noise_floor": -92,
        "wifi_radio_1_channel": 6,
        "bytes_sent": 1234567890,
        "bytes_received": 9876543210
      }
    },
    ...
  ],
  "reboot_events": [
    {
      "timestamp": "2024-03-13T18:45:22Z",
      "previous_uptime_seconds": 314558
    }
  ]
}
```

### Get Available Fields

```http
GET /api/<project_id>/telemetry/available-fields
Authorization: Bearer <access_token>

Response:
{
  "fields": [
    {
      "field": "Device.WiFi.Radio.1.Stats.X_COMCAST-COM_NoiseFloor",
      "label": "Noise Floor (2.4GHz)",
      "type": "integer",
      "unit": "dBm",
      "category": "wifi_radio"
    },
    ...
  ],
  "categories": ["device_info", "wifi_radio", "network_stats", "system_stats"]
}
```

### Export CSV

```http
GET /api/<project_id>/telemetry/export?cpe_id=<cpe_id>&format=csv
Authorization: Bearer <access_token>

Response:
Content-Type: text/csv
Content-Disposition: attachment; filename="telemetry_AABBCCDDEEFF.csv"

<CSV content>
```

## Configuration

### Add Custom Fields

Edit `configs/telemetry_report_fields.yaml`:

```yaml
# Add new metric
custom_metrics:
  - field: Device.X_CUSTOM.MyMetric
    label: My Custom Metric
    type: float
    unit: percentage
    chart: line
    threshold_warning: 80
    threshold_critical: 95
```

**Field Properties:**


| Property             | Type    | Description                                   |
| -------------------- | ------- | --------------------------------------------- |
| `field`              | string  | TR-181 parameter path (required)              |
| `label`              | string  | Display name (required)                       |
| `type`               | enum    | `string`, `integer`, `float`, `boolean`       |
| `unit`               | string  | Display unit (dBm, Mbps, %, etc.)             |
| `chart`              | enum    | `line`, `scatter`, `bar`, `none`              |
| `derivative`         | boolean | Plot rate of change (for cumulative counters) |
| `threshold_warning`  | number  | Yellow alert threshold                        |
| `threshold_critical` | number  | Red alert threshold                           |


### Reload Configuration

```bash
# Restart API to reload YAML
docker compose restart logai-api

# Or in local dev
pkill -HUP -f run_api.py
```

## Troubleshooting

### Issue: No telemetry data

**Possible Causes:**

1. No Telemetry_2.0 files in logs
2. Parsing not triggered
3. Field names don't match

**Solution:**

```bash
# Check for telemetry files
ls SERIAL_OR_MAC_*/files/Telemetry*

# Trigger parsing
curl -X POST "http://localhost:40901/api/42/telemetry/parse?cpe_id=AABBCCDDEEFF" \
  -H "Authorization: Bearer $TOKEN"

# Check logs
docker compose logs logai-api | grep telemetry
```

### Issue: Fields not showing

**Cause:** Field name mismatch in YAML

**Debug:**

```python
# Check actual field names in report
with open('Telemetry_2.0_report_001.txt') as f:
    for line in f:
        if 'WiFi' in line:
            print(line)
```

Update YAML with exact field names.

### Issue: Charts not rendering

**Possible Causes:**

1. Browser JavaScript disabled
2. Plotly library not loaded
3. Data format error

**Solution:**

- Check browser console for errors
- Verify Plotly CDN accessible
- Validate JSON response structure

## Best Practices

### Field Selection

**Focus on:**

- Signal quality metrics (RSSI, SNR, noise)
- Network throughput (TX/RX rates)
- System resources (CPU, memory)
- Error counters
- Client counts

**Avoid:**

- Static configuration values
- Redundant fields
- Very high-frequency data (oversized CSVs)

### Visualization Tips

**Chart Selection:**


| Metric Type       | Chart Type   |
| ----------------- | ------------ |
| Continuous values | Line chart   |
| Discrete states   | Scatter plot |
| Counts            | Bar chart    |
| Distributions     | Histogram    |


**Time Range:**

- Last 24h: Detailed view
- Last 7 days: Trend analysis
- Last 30 days: Long-term patterns

## Related Features

- [Telemetry CSV Export](./TELEMETRY_CSV.md) - Export for external analysis
- [CPE Overview](./CPE_OVERVIEW.md) - Cross-CPE telemetry comparison
- [Multi-CPE Support](./MULTI_CPE.md) - Per-CPE telemetry
- [File Upload](./FILE_UPLOAD.md) - Upload telemetry files

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)
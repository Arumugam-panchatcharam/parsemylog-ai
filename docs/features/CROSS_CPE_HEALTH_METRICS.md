# Cross-CPE Health Metrics Color Coding

## Overview

The Cross-CPE Health Metrics section in the CPE Overview page provides visual health indicators for key system metrics across all CPEs in a project. Each metric is color-coded based on severity thresholds to quickly identify at-risk devices.

## Metrics

### 1. MemAvailable %

Percentage of available memory relative to total system memory.

| Status | Color | Range | Meaning |
|--------|-------|-------|---------|
| Normal | 🟢 Green | > 30% | Healthy memory availability |
| Caution | 🟡 Yellow | 20–30% | Moving to risk zone |
| Warning | 🟠 Orange | 10–20% | Risky - memory pressure building |
| Critical | 🔴 Red | < 10% | Critical shortage |

**Fleet Alert Threshold**: MemAvailable < 20%

---

### 2. CPU Usage %

CPU utilization percentage from telemetry.

| Status | Color | Range | Meaning |
|--------|-------|-------|---------|
| Idle | 🟢 Green | 5–10% | Idle state |
| Normal | 🟢 Green | 10–15% | Normal operation |
| Medium | 🟡 Yellow | 15–20% | Moderate load |
| Busy | 🟠 Orange | > 20% | High CPU usage |

---

### 3. SUnreclaim Ratio %

Ratio of SUnreclaim memory (memory that cannot be reclaimed) to total Slab memory, expressed as a percentage.

| Status | Color | Range | Meaning |
|--------|-------|-------|---------|
| Healthy | 🟢 Green | < 50% | Normal slab allocation |
| Moderate | 🟡 Yellow | 50–70% | Moderate unreclaimable memory |
| Suspicious | 🟠 Orange | 70–80% | High unreclaimable memory |
| High Risk | 🔴 Red | > 80% | Excessive unreclaimable memory |

**Fleet Alert Threshold**: SUnreclaim > 80%

---

### 4. Overcommit Ratio

Ratio of `Committed_AS` (committed address space) to `CommitLimit` (total limit).

| Status | Color | Range | Meaning |
|--------|-------|-------|---------|
| Normal | 🟢 Green | < 1x | Within limits |
| Overcommitted | 🟡 Yellow | 1–2x | System is overcommitted |
| Aggressive | 🟠 Orange | 2–4x | Aggressively overcommitted |
| Very High Risk | 🔴 Red | > 4x | Extreme overcommitment |

**Fleet Alert Threshold**: Overcommit ratio > 4x

---

## Fleet Alerts

A **Fleet Alert** is triggered when ANY of the following conditions are met across the fleet:

1. **MemAvailable < 20%** - Memory shortage across multiple devices
2. **SUnreclaim > 80%** - Memory reclamation issues across multiple devices
3. **Overcommit Ratio > 4** - Severe memory overcommitment across multiple devices

When fleet alerts are triggered, they appear in a dedicated section below the metrics with the affected CPE serial number and the specific alert conditions.

---

## Visualization

The metrics are displayed as interactive bar charts:

- **X-axis**: CPE serial numbers
- **Y-axis**: Metric value (percentage or ratio)
- **Bar Color**: Based on health status (color-coded per thresholds)
- **Hover**: Shows exact value and CPE serial

### Metric Selector

Use the tab buttons at the top of the section to switch between the four metrics. Each metric has its own chart with appropriate threshold indicators.

---

## Implementation Details

### Backend (`api/routes/cpe_overview.py`)

The `_build_flat_metrics()` function extracts system metrics from telemetry reports:

- **MemAvailable**: `Device.MemStatus.MemAvailable`
- **MemTotal**: `Device.MemStatus.MemTotal`
- **SUnreclaim**: `Device.MemStatus.SUnreclaim`
- **Slab**: `Device.MemStatus.Slab`
- **Committed_AS**: `Device.MemStatus.Committed_AS`
- **CommitLimit**: `Device.MemStatus.CommitLimit`

Calculated metrics:
- `mem_available_pct`: (MemAvailable / MemTotal) * 100
- `sunreclaim_ratio`: (SUnreclaim / Slab) * 100
- `overcommit_ratio`: Committed_AS / CommitLimit

### Frontend (`frontend/src/components/CrossCPEGraphs.tsx`)

React component that:
1. Retrieves CPE metrics from the backend response
2. Calculates health status for each metric
3. Renders color-coded bar charts
4. Detects and displays fleet alerts

### Color Utilities (`frontend/src/utils/healthStatus.ts`)

Helper functions for:
- Health status determination based on thresholds
- Color configuration lookup
- Fleet alert detection and messaging

---

## Usage

1. Navigate to **CPE Overview** page
2. Scroll to **Cross-CPE Health Metrics** section
3. View the default metric (MemAvailable) with color-coded bars
4. Click metric tabs to switch between different metrics
5. Check for fleet alerts below the chart
6. Hover over bars for exact values

---

## Future Enhancements

- **Historical trends**: Timeline view of metric changes
- **Anomaly detection**: Automatic flagging of unusual patterns
- **Custom thresholds**: Per-project configurable alert levels
- **Export**: Download health reports as CSV/PDF

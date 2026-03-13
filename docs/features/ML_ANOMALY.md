# ML_ANOMALY.md
# ML Anomaly Detection

## Overview

Machine Learning-based anomaly detection identifies unusual patterns in logs and telemetry using unsupervised algorithms.

## Key Capabilities

- **Log Anomaly Detection** - Isolation Forest on log patterns
- **Telemetry Anomaly Detection** - Time-series analysis (ARIMA, Prophet)
- **Fleet-Level Anomaly** - Cross-CPE comparison for outlier detection
- **User Feedback Loop** - Label true/false positives for model retraining
- **Ground Truth Validation** - Accuracy metrics

## Algorithms

### Isolation Forest (Log Patterns)

Detects unusual log template frequencies and co-occurrences.

```python
from sklearn.ensemble import IsolationForest

# Features: template frequency, time of day, co-occurrence
features = extract_features(log_templates)
model = IsolationForest(contamination=0.1)
model.fit(features)

# Predict anomalies
anomaly_scores = model.decision_function(features)
anomalies = features[anomaly_scores < threshold]
```

### Time-Series (Telemetry)

Detects metric deviations from expected patterns.

```python
from statsmodels.tsa.arima.model import ARIMA

# Fit ARIMA on historical data
model = ARIMA(telemetry_series, order=(5,1,0))
model_fit = model.fit()

# Predict next values
forecast = model_fit.forecast(steps=24)
actual = telemetry_series[-24:]

# Anomalies where |actual - forecast| > 3*std
anomalies = abs(actual - forecast) > 3 * std(residuals)
```

## Usage

### Detect Log Anomalies

```
┌──────────────────────────────────────────────────────┐
│ Log Anomaly Detection                                │
│ CPE: [AABBCCDDEEFF ▼]                                │
│ Sensitivity: [Medium ▼]  (Low/Medium/High)           │
│ [🔍 Detect Anomalies]                                │
└──────────────────────────────────────────────────────┘

Results:
1. Unusual pattern frequency
   Template: [wifi] ERROR: Authentication failed
   Expected: ~10/hour
   Observed: 234/hour (23x higher)
   Time: 2024-03-13 18:30-18:45
   Score: 0.92 (high confidence)

2. Rare co-occurrence
   Patterns: DHCP timeout + WiFi disconnect
   Occurred: 45 times (unusual combination)
   Score: 0.78
```

### Detect Telemetry Anomalies

```
Telemetry Anomalies - Last 24h

Metric: Signal Strength (RSSI)
Expected: -45 to -52 dBm (based on historical)
Observed: -68 to -75 dBm (2024-03-13 18:00-19:00)
Status: 🔴 Anomaly detected
Severity: High

Metric: CPU Usage
Expected: 10-15%
Observed: 85-98% (2024-03-13 17:30-18:30)
Status: 🔴 Anomaly detected
Severity: Critical
```

### Provide Feedback

```
Anomaly #42: Unusual WiFi error frequency

Detected: 2024-03-13 18:30
Pattern: [wifi] ERROR: Authentication failed
Frequency: 234/hour (expected ~10/hour)

Is this a true anomaly?
○ Yes - Real issue (True Positive)
● No - False alarm (False Positive)

Optional notes:
┌────────────────────────────────────────────────────┐
│ This was during a planned firmware update.        │
│ Expected behavior, not an anomaly.                │
└────────────────────────────────────────────────────┘

[Submit Feedback]
```

## API Reference

```http
POST /api/<project_id>/ml/detect-anomalies
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "cpe_id": "AABBCCDDEEFF",
  "type": "log",  // or "telemetry", "fleet"
  "sensitivity": "medium",
  "time_range": {
    "start": "2024-03-13T00:00:00Z",
    "end": "2024-03-14T00:00:00Z"
  }
}

Response:
{
  "anomalies": [
    {
      "id": "anom_123",
      "type": "frequency",
      "description": "Unusual pattern frequency",
      "score": 0.92,
      "timestamp": "2024-03-13T18:30:00Z",
      "details": {...}
    }
  ],
  "model_version": "1.2.3"
}
```

## Best Practices

- **Sensitivity Tuning:** Start with medium, adjust based on false positive rate
- **Feedback Loop:** Label at least 50 anomalies for model retraining
- **Baseline Period:** Need 7-14 days of data for accurate baselines

## Related Features

- [Pattern Analysis](./DRAIN3_PATTERNS.md)
- [Telemetry Dashboard](./TELEMETRY.md)
- [CPE Overview](./CPE_OVERVIEW.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

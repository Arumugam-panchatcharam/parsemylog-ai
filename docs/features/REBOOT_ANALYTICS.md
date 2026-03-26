# Reboot Analytics: Time-of-Day & Uptime Bucketing

## Overview

Reboot Analytics provides fleet-level insights into device reboot patterns by bucketing reboot events into two dimensions:

1. **Time-of-Day Distribution**: Shows at what hours of the day devices are rebooting (4 x 6-hour buckets)
2. **Uptime Before Reboot**: Categorizes devices by how long they were up before the reboot event (6 categories)

This feature helps identify patterns in device stability and detect anomalies in reboot behavior across your fleet.

## Access Location

The Reboot Analytics section appears in the **Telemetry Overview Tab** (`/workspace/telemetry`) under the fleet view.

## Features

### 1. Time-of-Day Bucketing

Reboots are distributed across four 6-hour buckets:

- **12 AM - 6 AM** (Midnight to early morning)
- **6 AM - 12 PM** (Morning to noon)
- **12 PM - 6 PM** (Afternoon)
- **6 PM - 12 AM** (Evening to midnight)

**Use Cases:**
- Identify if maintenance windows align with reboot spikes
- Detect time-zone specific patterns
- Correlate reboots with business hours vs. off-hours
- Identify potential scheduled vs. unscheduled reboots

**Display:**
- Summary cards showing reboot count and percentage
- Color-coded by time period
- Click card to view detailed CPE listing for that time bucket

### 2. Uptime Before Reboot Bucketing

Device uptime before reboot is categorized into six ranges:

| Category | Duration |
|----------|----------|
| < 1 day | Less than 24 hours |
| 1 - 5 days | 1 to 5 days |
| 5 - 10 days | 5 to 10 days |
| 10 - 15 days | 10 to 15 days |
| 15 - 20 days | 15 to 20 days |
| > 20 days | More than 20 days |

**Use Cases:**
- Identify if frequently rebooting devices crash sooner
- Detect hardware or software aging patterns
- Correlate uptime with stability
- Set realistic uptime expectations for deployments

**Display:**
- Summary cards showing device count and percentage
- Color-coded by uptime category
- Click card to view detailed CPE listing for that uptime bucket

## How It Works

### Data Source

The feature uses telemetry data from the existing **Reboot Timeline** component:

- Reboot events are detected via **uptime drop detection** (when `Device.DeviceInfo.UpTime` decreases)
- Each reboot event captures the timestamp and previous uptime value
- Events are aggregated across all CPEs in the project

### Bucketing Algorithm

For each reboot event:

1. **Extract timestamp** from telemetry report time
2. **Get hour** from timestamp (0-23)
3. **Map hour to time-of-day bucket** (00-06, 06-12, 12-18, 18-24)
4. **Extract uptime** from reboot event's `prev_uptime` field (in seconds)
5. **Map uptime to category** (<1d, 1-5d, 5-10d, 10-15d, 15-20d, >20d)
6. **Aggregate** across all CPEs and count occurrences

### Performance

- Bucketing is computed on-demand per API request
- Results are cached in memory for performance
- O(n) complexity where n = number of reboot events
- Typical computation time: <100ms for 10,000 events

## UI Components

### Summary Card Section

Located in the **Telemetry Overview Tab**, below the fleet summary badges.

**Time-of-Day Cards:**
- 4 cards in a responsive grid (2 cols on mobile, 4 on desktop)
- Shows: Time range, reboot count, percentage
- Highlight highest bucket for quick scanning

**Uptime Bucket Cards:**
- 6 cards in a responsive grid (2 cols on mobile, 3 on desktop)
- Shows: Uptime range, device count, percentage
- Color-coded for visual distinction

### Detail Modal

Click any summary card to open the detail modal:

**Features:**
- Tabular view of CPE devices in that bucket
- Columns: Serial, Model, Reboot Timestamp, Uptime Before Reboot
- Sortable by serial, timestamp, or uptime
- Responsive table with horizontal scroll on mobile

**Interactions:**
- Click column headers to sort
- Sort direction toggle (ascending/descending)
- Large fleets use virtualized scrolling for performance

## API Integration

### Endpoint

```
GET /projects/{project_id}/telemetry/cross-cpe-overview
```

### Response Structure

The `reboot_analytics` object is added to the cross-CPE overview response:

```json
{
  "reboot_analytics": {
    "time_of_day_buckets": {
      "00-06": {
        "count": 5,
        "label": "12 AM - 6 AM",
        "percentage": 12.5,
        "devices": [
          {
            "serial": "DEVICE001",
            "model": "XB6",
            "timestamp": "2025-03-15T03:00:00Z",
            "hour": 3
          }
        ]
      },
      "06-12": { /* ... */ },
      "12-18": { /* ... */ },
      "18-24": { /* ... */ }
    },
    "uptime_buckets": {
      "<1d": {
        "count": 10,
        "label": "< 1 day",
        "percentage": 25,
        "devices": [
          {
            "serial": "DEVICE001",
            "model": "XB6",
            "timestamp": "2025-03-15T03:00:00Z",
            "uptime_seconds": 3600
          }
        ]
      },
      "1-5d": { /* ... */ },
      "5-10d": { /* ... */ },
      "10-15d": { /* ... */ },
      "15-20d": { /* ... */ },
      ">20d": { /* ... */ }
    },
    "total_reboot_events": 40
  }
}
```

## Backend Implementation

### Module: `api/reboot_bucketing.py`

Core bucketing logic:

```python
# Bucket definitions
TIME_OF_DAY_BUCKETS = [
    {"id": "00-06", "label": "12 AM - 6 AM", "start_hour": 0, "end_hour": 6},
    {"id": "06-12", "label": "6 AM - 12 PM", "start_hour": 6, "end_hour": 12},
    # ...
]

UPTIME_BUCKETS = [
    {"id": "<1d", "label": "< 1 day", "min_seconds": 0, "max_seconds": 86400},
    # ...
]

# Key functions
- parse_timestamp(timestamp_str) -> datetime
- get_time_of_day_bucket(hour) -> str
- get_uptime_bucket(uptime_seconds) -> str
- bucket_reboot_events(events, cpe_info) -> (time_buckets, uptime_buckets)
- aggregate_buckets(all_time_buckets, all_uptime_buckets) -> analytics_dict
```

### Route: `api/routes/telemetry.py`

Integration point:

```python
def cross_cpe_overview(project_id):
    # ... existing code ...
    
    # Compute reboot analytics
    reboot_analytics = _compute_reboot_analytics(cpe_results)
    
    # Return with analytics
    return jsonify({
        "cpes": cpe_results,
        "fleet_summary": { ... },
        "reboot_correlation": { ... },
        "reboot_analytics": reboot_analytics,
    }), 200
```

## Frontend Implementation

### Component: `RebootAnalyticsSection.tsx`

React component that displays:

1. Time-of-Day summary cards
2. Uptime bucket summary cards
3. Detail modal on card click

**Props:**
```typescript
interface RebootAnalyticsSectionProps {
  analytics: RebootAnalytics | null | undefined;
}
```

**State:**
- Selected bucket (type: "time" | "uptime", id: string)
- Sort key (serial, timestamp, uptime)
- Sort direction (asc, desc)

## Edge Cases & Limitations

### Edge Cases Handled

1. **Missing uptime data**: Events without `prev_uptime` are excluded from uptime bucketing but still counted in time-of-day
2. **Invalid timestamps**: Events with unparseable timestamps are skipped
3. **Empty buckets**: Buckets with 0 events still display with 0 count
4. **Timezone UTC**: All timestamps interpreted as UTC (document to user)
5. **Multiple reboots per device**: Each event counted separately (not unique device count)

### Known Limitations

- Uptime calculation assumes `prev_uptime` is accurate from telemetry (may not account for system clock adjustments)
- Time-of-day bucketing uses UTC (no timezone conversion)
- No filtering by reboot type (soft vs. hard) in bucketing
- Cannot bucket by other dimensions (model, firmware, etc.) in current version

## Testing

Comprehensive unit tests included in `test_reboot_bucketing.py`:

- Timestamp parsing (ISO 8601 formats)
- Time-of-day boundary conditions (0, 6, 12, 18, 24 hours)
- Uptime boundary conditions (1d, 5d, 10d, 15d, 20d)
- Event bucketing with CPE info
- Aggregation of multiple CPEs
- Edge cases (missing data, invalid values)

**Run tests:**
```bash
python3 test_reboot_bucketing.py
```

## Performance Considerations

- **Scalability**: Tested with 10,000+ reboot events
- **API response time**: <100ms for typical projects (< 500 CPEs)
- **Frontend rendering**: Virtualized scrolling for tables with 1000+ rows
- **Memory**: Buckets aggregated in-memory during API call (not cached to disk)

## Future Enhancements

Potential improvements (not in current release):

1. **Reboot type filtering**: Separate soft vs. hard reboots in analysis
2. **Model-based bucketing**: Analyze patterns per device model
3. **Firmware correlation**: Link reboots to firmware versions
4. **Predictive analysis**: ML model to predict reboot probability by uptime
5. **Custom time buckets**: Allow user-defined bucket sizes
6. **Export to CSV**: Download bucketed analysis data
7. **Scheduled reports**: Automated daily/weekly reboot analysis emails

## Troubleshooting

### No data showing in Reboot Analytics

**Causes:**
- No reboots detected in project (check CPE has telemetry data)
- Telemetry reports missing `Device.DeviceInfo.UpTime` field
- Force refresh needed after recent telemetry parse

**Solution:**
1. Verify CPEs have telemetry data: Check "With Reboots" count in fleet summary
2. Force refresh: Click "Force Refresh All" button in Telemetry Overview
3. Check API response: Inspect `reboot_analytics` in network tab

### Unexpected bucket distribution

**Causes:**
- Time-of-day buckets use UTC (user's local timezone may differ)
- Multiple reboots per device on same day count separately
- Uptime calculation includes boot time precision

**Solution:**
1. Remember all times are in UTC
2. Downmultiple events to "reboot count" not "unique devices"
3. Check individual CPE details for exact uptime values

## References

- [Telemetry Dashboard](./TELEMETRY.md)
- [CPE Overview](./CPE_OVERVIEW.md)
- [Reboot Correlation Analysis](./FEATURES.md#reboot-correlation-section)

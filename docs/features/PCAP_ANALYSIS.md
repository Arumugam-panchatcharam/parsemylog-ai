# PCAP Analysis

## Overview

PCAP Analysis enables network packet capture correlation with log events for deep network troubleshooting.

## Key Capabilities

- **Upload .pcap/.pcapng files**
- **Protocol Detection** - TCP, UDP, ICMP, DNS, HTTP
- **Packet Metadata** - IPs, ports, timestamps
- **Flow Reconstruction** - Connection tracking
- **Log Correlation** - Match PCAP events with log timestamps

## Usage

### Upload PCAP

```
┌──────────────────────────────────────────────────────┐
│ PCAP Analysis                                        │
│ [📤 Upload PCAP] capture_2024-03-13.pcap             │
│ Uploaded: 234 MB (1.2M packets)                      │
│ Duration: 2024-03-13 14:00 - 18:00 (4 hours)         │
│ Protocols: TCP (65%), UDP (30%), Other (5%)          │
│ [Analyze]                                            │
└──────────────────────────────────────────────────────┘
```

### View Flows

```
Network Flows (Top 10 by packet count)

1. 192.168.1.100:443 ↔ 1.2.3.4:34567 (TCP)
   Packets: 12,345 | Bytes: 8.9 MB | Duration: 3m 45s

2. 192.168.1.100:53 ↔ 8.8.8.8:53 (UDP)
   Packets: 456 | Bytes: 234 KB | DNS queries

[Filter by IP] [Filter by Port] [Filter by Protocol]
```

### Correlate with Logs

```
Correlation Analysis

Timestamp: 2024-03-13 15:32:10

PCAP Event:
- TCP RST from 1.2.3.4:443
- Connection terminated abruptly

Log Event (simultaneous):
- [network] ERROR: Connection closed unexpectedly
- [network] WARNING: Retry attempt 1

Analysis: Server-side connection reset, likely server overload
```

## API Reference

```http
POST /api/pcap/upload
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file: <pcap_file>
```

## Related Features

- [Log Viewer](./LOG_VIEWER.md)
- [Issue Analysis](./ISSUE_ANALYSIS.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

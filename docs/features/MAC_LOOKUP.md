# MAC Address Lookup (OUI Database)

## Overview

MAC Address Lookup resolves MAC addresses to vendor names using the IEEE OUI (Organizationally Unique Identifier) database.

## Key Capabilities

- **OUI Database** - 30K+ vendor entries from IEEE
- **Bulk Lookup** - CSV input/output
- **Auto-Update** - Weekly database refresh
- **Log Viewer Integration** - Hover tooltips

## Usage

### Single Lookup

```
┌──────────────────────────────────────────────────────┐
│ MAC Address Lookup                                   │
│ MAC: [AA:BB:CC:DD:EE:FF──] [🔍 Lookup]               │
└──────────────────────────────────────────────────────┘

Result:
MAC: AA:BB:CC:DD:EE:FF
Vendor: TechVendor Inc.
OUI: AA:BB:CC
```

### Bulk Lookup

```
Upload CSV:
MAC_Address
AA:BB:CC:DD:EE:FF
11:22:33:44:55:66
FF:EE:DD:CC:BB:AA

[📤 Upload] [📥 Download Results]

Results (3):
MAC_Address,Vendor
AA:BB:CC:DD:EE:FF,TechVendor Inc.
11:22:33:44:55:66,Cisco Systems
FF:EE:DD:CC:BB:AA,Unknown
```

### Update Database

```
┌──────────────────────────────────────────────────────┐
│ OUI Database Status                                  │
│ Last Updated: 2024-03-01 (12 days ago)               │
│ Entries: 30,245                                      │
│ [🔄 Update Now]                                      │
└──────────────────────────────────────────────────────┘

Updating...
✓ Downloaded IEEE OUI database
✓ Parsed 30,456 entries (+211 new)
✓ Database updated successfully
```

## API Reference

```http
POST /api/utilities/mac-lookup
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "mac_addresses": ["AA:BB:CC:DD:EE:FF"]
}

Response:
{
  "results": [
    {
      "mac": "AA:BB:CC:DD:EE:FF",
      "vendor": "TechVendor Inc.",
      "oui": "AA:BB:CC"
    }
  ]
}

POST /api/utilities/oui-update
Authorization: Bearer <access_token>

Response:
{
  "message": "OUI database updated",
  "entries": 30456,
  "new_entries": 211
}
```

## Related Features

- [Log Viewer](./LOG_VIEWER.md)
- [CPE Overview](./CPE_OVERVIEW.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

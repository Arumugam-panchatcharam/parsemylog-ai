# Pattern Import/Export

## Overview

Pattern Import/Export enables bulk operations for sharing, backup, and migration of regex pattern libraries across projects and deployments.

## Supported Formats

### 1. Domain-Grouped JSON

```json
{
  "wifi": [
    {
      "name": "WiFi Connection Failed",
      "regex": "Failed to connect to SSID",
      "enabled": true
    }
  ],
  "platform": [
    {
      "name": "Kernel Panic",
      "regex": "kernel panic|Kernel panic",
      "enabled": true
    }
  ]
}
```

### 2. Flat Array JSON

```json
[
  {
    "domain": "wifi",
    "name": "WiFi Connection Failed",
    "regex": "Failed to connect to SSID",
    "enabled": true
  },
  {
    "domain": "platform",
    "name": "Kernel Panic",
    "regex": "kernel panic|Kernel panic",
    "enabled": true
  }
]
```

### 3. YAML

```yaml
wifi:
  - name: WiFi Connection Failed
    regex: Failed to connect to SSID
    enabled: true
platform:
  - name: Kernel Panic
    regex: kernel panic|Kernel panic
    enabled: true
```

### 4. rule_parser_config.json

```json
{
  "groups": [
    {
      "group": "wifi",
      "patterns": [
        {
          "pattern": "Failed to connect to SSID",
          "description": "WiFi Connection Failed"
        }
      ]
    }
  ]
}
```

## Usage

### Export Patterns

```
┌──────────────────────────────────────────────────────┐
│ Export Patterns                                      │
│ Format: [JSON (Domain-Grouped) ▼]                    │
│ Include: ☑ Enabled only  ☐ All patterns              │
│ Domains: ☑ wifi  ☑ platform  ☐ cellular              │
│ [📥 Export]                                          │
└──────────────────────────────────────────────────────┘
```

### Import Patterns

```
┌──────────────────────────────────────────────────────┐
│ Import Patterns                                      │
│ [📤 Choose File] patterns.json                       │
│ Format: [Auto-Detect ▼]                              │
│ Mode: ○ Merge  ● Replace                             │
│ [Import]                                             │
└──────────────────────────────────────────────────────┘

Importing...
✓ Detected format: Domain-Grouped JSON
✓ Found 25 patterns
✓ Validated all patterns
✓ Imported successfully

Summary:
- Added: 12 new patterns
- Updated: 8 existing patterns
- Skipped: 5 duplicates
```

## API Reference

### Export

```http
GET /api/<project_id>/regex-patterns/export?format=json&domains=wifi,platform
Authorization: Bearer <access_token>

Response:
Content-Type: application/json
Content-Disposition: attachment; filename="patterns.json"

{
  "wifi": [...],
  "platform": [...]
}
```

### Import

```http
POST /api/<project_id>/regex-patterns/import
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file: <patterns_file>
format: json
mode: merge
```

## Related Features

- [Pattern Analyzer](./PATTERN_ANALYZER.md)
- [NATCO Governance](./NATCO_GOVERNANCE.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

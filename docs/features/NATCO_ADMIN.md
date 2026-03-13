# NATCO Administration

## Overview

NATCO Administration provides admin tools for managing NATCOs, global pattern libraries, and reviewing user submissions.

## Key Capabilities

- **NATCO CRUD** - Create, edit, delete NATCOs
- **Global Pattern Editor** - Manage per-NATCO patterns
- **Pattern Submission Review** - Approve/reject user changes
- **Import Tools** - Seed from presets or files
- **Submission History** - Track all submissions

## Usage

### NATCO List

```
┌──────────────────────────────────────────────────────┐
│ NATCO Management                                     │
│ [+ Create NATCO]                                     │
├──────────────────────────────────────────────────────┤
│ Code │ Name           │ Projects │ Patterns │ Actions│
├──────┼────────────────┼──────────┼──────────┼────────┤
│ EU   │ Europe         │ 15       │ 50       │ [✏] [🗑]│
│ US   │ United States  │ 8        │ 45       │ [✏] [🗑]│
│ DE   │ Germany        │ 12       │ 62       │ [✏] [🗑]│
└──────────────────────────────────────────────────────┘
```

### Edit Global Patterns

```
┌──────────────────────────────────────────────────────┐
│ Global Patterns - NATCO: EU                          │
│ [+ Add] [📥 Import Preset] [📥 Import File] [📤 Export]│
├──────────────────────────────────────────────────────┤
│ WiFi (15 patterns)                                   │
│   WiFi Connection Failed                             │
│   WiFi Timeout                                       │
│   ...                                                │
│                                                      │
│ Platform (25 patterns)                               │
│   Kernel Panic                                       │
│   Out of Memory                                      │
│   ...                                                │
└──────────────────────────────────────────────────────┘
```

### Review Submissions

```
┌──────────────────────────────────────────────────────┐
│ Pattern Submissions - Pending (3)                    │
├──────────────────────────────────────────────────────┤
│ #42 - john_doe - EU - 2024-03-13 14:32               │
│ ✨ NEW: WiFi 6E Connection Failed                    │
│ [✅ Approve] [❌ Reject] [💬 Comment]                 │
│                                                      │
│ #41 - jane_smith - US - 2024-03-12 10:15             │
│ ✏️ MODIFIED: DHCP Timeout                            │
│ [✅ Approve] [❌ Reject] [💬 Comment]                 │
└──────────────────────────────────────────────────────┘
```

## API Reference

```http
GET /api/admin/natcos
Authorization: Bearer <access_token>

POST /api/admin/natcos
Content-Type: application/json
{
  "code": "EU",
  "name": "Europe",
  "description": "European deployment"
}

GET /api/admin/natcos/<natco_id>/patterns
PUT /api/admin/natcos/<natco_id>/patterns

GET /api/admin/pattern-submissions?status=pending
PUT /api/admin/pattern-submissions/<submission_id>
Content-Type: application/json
{
  "status": "approved",
  "admin_comment": "Looks good"
}
```

## Related Features

- [NATCO Governance](./NATCO_GOVERNANCE.md)
- [User Management](./USER_MANAGEMENT.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

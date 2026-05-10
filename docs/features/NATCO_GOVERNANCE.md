# NATCO Pattern Governance

## Overview

NATCO (National Company) Pattern Governance provides centralized pattern management with version control, admin review, and bi-directional synchronization between global and local pattern libraries.

## Key Capabilities

- **Global Pattern Library** - Admin-managed per-country/deployment patterns
- **Per-Project Assignment** - Users assign NATCO to projects
- **Sync & Override** - Pull global patterns, customize locally
- **Diff-Based Submissions** - Submit only NEW/MODIFIED patterns
- **Admin Review** - Approve or reject with comments
- **Submission History** - Track all submissions per user
- **Import/Export** - Seed from presets or files

## How It Works

### Architecture

```
Admin → Create NATCO → Define Global Patterns
            ↓
Users → Assign NATCO → Sync → Edit Locally → Submit
            ↓
Admin → Review → Approve/Reject
            ↓
Global Patterns Updated → Users Sync Again
```

### Database Schema

```sql
-- NATCOs (deployment regions)
CREATE TABLE natcos (
    id INTEGER PRIMARY KEY,
    code VARCHAR(10) UNIQUE,  -- e.g., "EU", "DE", "US"
    name VARCHAR(255),
    description TEXT
);

-- Global patterns per NATCO
CREATE TABLE global_patterns (
    id INTEGER PRIMARY KEY,
    natco_id INTEGER,
    domain VARCHAR(50),
    name VARCHAR(255),
    regex TEXT,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (natco_id) REFERENCES natcos(id)
);

-- User submissions
CREATE TABLE pattern_submissions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    project_id INTEGER,
    natco_id INTEGER,
    domain VARCHAR(50),
    name VARCHAR(255),
    regex TEXT,
    change_type VARCHAR(20),  -- 'new', 'modified'
    status VARCHAR(20),       -- 'pending', 'approved', 'rejected'
    admin_comment TEXT,
    submitted_at TIMESTAMP,
    reviewed_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (natco_id) REFERENCES natcos(id)
);
```

## Usage

### For Admins

#### Create NATCO

```
┌──────────────────────────────────────────────────────┐
│ Create NATCO                                         │
│ Code: [EU──]  (2-10 chars, unique)                   │
│ Name: [Europe─────────────────────────────]          │
│ Description:                                         │
│ ┌────────────────────────────────────────────────┐   │
│ │ European deployment with standard patterns     │   │
│ └────────────────────────────────────────────────┘   │
│ [Create]                                             │
└──────────────────────────────────────────────────────┘
```

#### Define Global Patterns

```
┌──────────────────────────────────────────────────────────┐
│ Global Patterns - NATCO: EU                              │
│ [+ Add Pattern] [📥 Import Preset] [📥 Import File]      │
├──────────────────────────────────────────────────────────┤
│ WiFi (15 patterns)                                       │
│   ☑ WiFi Connection Failed                               │
│       Regex: Failed to connect to SSID                   │
│       [✏️ Edit] [🗑️ Delete]                              │
│   ☑ WiFi Timeout                                         │
│       Regex: WiFi.*timeout                               │
│       [✏️ Edit] [🗑️ Delete]                              │
│                                                          │
│ Platform (25 patterns)                                   │
│   ...                                                    │
└──────────────────────────────────────────────────────────┘
```

**Import Presets:**

```
┌──────────────────────────────────────────────────────┐
│ Import Preset Patterns                               │
│ Select preset:                                       │
│ ○ RDK-B Standard (50 patterns)                       │
│ ○ RDK-V Standard (40 patterns)                       │
│ ○ Comcast XB7 (65 patterns)                          │
│ ○ Liberty TG3442 (55 patterns)                       │
│                                                      │
│ ☑ Merge with existing (don't replace)                │
│ [Import]                                             │
└──────────────────────────────────────────────────────┘
```

#### Review Submissions

```
┌──────────────────────────────────────────────────────────┐
│ Pattern Submissions - Pending Review                     │
│ Filter: [All NATCOs ▼] [All Users ▼]                     │
├──────────────────────────────────────────────────────────┤
│                                                          │
│ Submission #42 - User: john_doe - NATCO: EU              │
│ Submitted: 2024-03-13 14:32                              │
│                                                          │
│ ✨ NEW: WiFi 6E Connection Failed                        │
│    Domain: wifi                                          │
│    Regex: Failed to connect.*6GHz                        │
│    [✅ Approve] [❌ Reject]                              │
│                                                          │
│ ✏️ MODIFIED: WiFi Connection Failed                      │
│    Domain: wifi                                          │
│    Old: Failed to connect to SSID                        │
│    New: Failed to connect to (SSID|network)              │
│    [✅ Approve] [❌ Reject]                              │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

When reviewing or editing global patterns, expand **Preview on uploaded logs** to run an admin-only async regex scan against any user's project (pick user → project → optional CPE). Per-pattern `scan_filename` / `scan_time_range` in the pattern list are honored the same as in the workspace. API: [`GET/POST /api/admin/projects/<project_id>/...`](../API_REFERENCE.md#pattern-analyzer-preview-admin).

**Approve:**

- Pattern automatically merged into global library
- User notified
- Available to other users on next sync

**Reject:**

```
┌──────────────────────────────────────────────────────┐
│ Reject Pattern                                       │
│ Pattern: WiFi 6E Connection Failed                   │
│ Reason:                                              │
│ ┌────────────────────────────────────────────────┐   │
│ │ Pattern too specific. Please generalize to     │   │
│ │ match all WiFi 6E errors, not just connection  │   │
│ │ failures.                                      │   │
│ └────────────────────────────────────────────────┘   │
│ [Send Rejection]                                     │
└──────────────────────────────────────────────────────┘
```

### For Users

#### Assign NATCO

```
┌──────────────────────────────────────────────────────┐
│ Project Settings                                     │
│ Name: Fleet Analysis Q1 2024                         │
│ NATCO: [EU - Europe ▼]                               │
│ Created: 2024-01-15                                  │
│ [Save]                                               │
└──────────────────────────────────────────────────────┘
```

#### Sync from Global

```
┌──────────────────────────────────────────────────────┐
│ Pattern Library                                      │
│ NATCO: EU - Last synced: 2 days ago                  │
│ [🔄 Sync from Global]                                │
└──────────────────────────────────────────────────────┘

Syncing...
✓ Retrieved 50 global patterns
✓ Added 3 new patterns
✓ Updated 2 modified patterns
✓ Preserved 5 local-only patterns

Sync complete!
```

#### Edit Locally

Users can freely edit synced patterns:

```
┌──────────────────────────────────────────────────────┐
│ Edit Pattern                                         │
│ Name: [WiFi Connection Failed───────────────]        │
│ Regex: [Failed to connect to (SSID|network)─]        │
│ ☑ Enabled                                            │
│ Source: 🌍 Global (EU) - Modified locally            │
│ [Save] [Revert to Global]                            │
└──────────────────────────────────────────────────────┘
```

**Local Changes:**

- Edit existing patterns
- Add new patterns
- Disable/enable patterns
- Changes stay local until submitted

#### Submit to Global

```
┌──────────────────────────────────────────────────────────┐
│ Submit Changes to Global                                 │
│ NATCO: EU                                                │
│                                                          │
│ Changes detected (compared to global):                   │
│                                                          │
│ ☑ ✨ WiFi 6E Connection Failed (NEW)                     │
│      Domain: wifi                                        │
│      Regex: Failed to connect.*6GHz                      │
│                                                          │
│ ☑ ✏️ WiFi Connection Failed (MODIFIED)                   │
│      Old: Failed to connect to SSID                      │
│      New: Failed to connect to (SSID|network)            │
│                                                          │
│ ☐ ✨ My Custom Pattern (NEW)                             │
│      (Keep local-only, don't submit)                     │
│                                                          │
│ Optional message for admin:                              │
│ ┌────────────────────────────────────────────────────┐   │
│ │ Updated WiFi pattern to handle both SSID and       │   │
│ │ network keywords. Added 6E pattern for new HW.     │   │
│ └────────────────────────────────────────────────────┘   │
│                                                          │
│ [📤 Submit Selected (2 patterns)]                        │
└──────────────────────────────────────────────────────────┘

Submitted successfully!
Submission ID: #42
Status: Pending admin review
```

#### Track Submissions

```
┌──────────────────────────────────────────────────────────┐
│ My Submissions                                           │
├──────────────────────────────────────────────────────────┤
│ #42 - WiFi 6E Connection Failed                          │
│ Status: ⏳ Pending Review                                │
│ Submitted: 2024-03-13 14:32                              │
│                                                          │
│ #41 - DHCP Timeout Pattern                               │
│ Status: ✅ Approved                                      │
│ Reviewed: 2024-03-12 10:15                               │
│ Comment: "Good addition, approved."                      │
│                                                          │
│ #40 - Custom Error Pattern                               │
│ Status: ❌ Rejected                                      │
│ Reviewed: 2024-03-11 16:45                               │
│ Comment: "Too specific. Please generalize."              │
│                                                          │
│ [Clear Resolved Submissions]                             │
└──────────────────────────────────────────────────────────┘
```

## API Reference

### Admin: Create NATCO

```http
POST /api/admin/natcos
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "code": "EU",
  "name": "Europe",
  "description": "European deployment patterns"
}
```

### Admin: Add Global Pattern

```http
POST /api/admin/natcos/<natco_id>/patterns
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "domain": "wifi",
  "name": "WiFi Connection Failed",
  "regex": "Failed to connect to SSID",
  "enabled": true
}
```

### Admin: Review Submission

```http
PUT /api/admin/pattern-submissions/<submission_id>
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "status": "approved",  // or "rejected"
  "admin_comment": "Looks good, approved."
}
```

### User: Get Global Patterns

```http
GET /api/<project_id>/patterns/global
Authorization: Bearer <access_token>

Response:
{
  "natco": {
    "id": 1,
    "code": "EU",
    "name": "Europe"
  },
  "patterns": {
    "wifi": [...],
    "platform": [...]
  },
  "last_updated": "2024-03-10T10:00:00Z"
}
```

### User: Sync from Global

```http
POST /api/<project_id>/patterns/sync
Authorization: Bearer <access_token>

Response:
{
  "synced": true,
  "added": 3,
  "updated": 2,
  "unchanged": 45,
  "local_only": 5
}
```

### User: Get Diff

```http
POST /api/<project_id>/patterns/diff
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "local_patterns": {...}
}

Response:
{
  "new_patterns": [
    {
      "domain": "wifi",
      "name": "WiFi 6E Connection Failed",
      "regex": "Failed to connect.*6GHz"
    }
  ],
  "modified_patterns": [
    {
      "domain": "wifi",
      "name": "WiFi Connection Failed",
      "old_regex": "Failed to connect to SSID",
      "new_regex": "Failed to connect to (SSID|network)"
    }
  ],
  "unchanged_patterns": [...]
}
```

### User: Submit Changes

```http
POST /api/<project_id>/patterns/submit
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "patterns": [
    {
      "domain": "wifi",
      "name": "WiFi 6E Connection Failed",
      "regex": "Failed to connect.*6GHz",
      "change_type": "new"
    }
  ],
  "message": "Updated WiFi patterns for new hardware"
}

Response:
{
  "submission_id": 42,
  "patterns_submitted": 1,
  "status": "pending"
}
```

## Best Practices

### For Admins

**NATCO Organization:**

- Use clear codes: `EU`, `US`, `DE`, `UK`
- Descriptive names: "Europe", "United States"
- Document deployment specifics in description

**Pattern Quality:**

- Test patterns before approving
- Ensure generalization (not too specific)
- Maintain consistent naming
- Document complex regex

**Review Guidelines:**

- Approve: Pattern is useful, well-formed
- Reject with feedback: Too specific, duplicate, or incorrect
- Quick turnaround: Review within 1-2 days

### For Users

**Local Editing:**

- Keep local patterns minimal
- Submit useful patterns to global
- Don't modify patterns you don't understand
- Test before submitting

**Submission Messages:**

- Explain why the change is needed
- Mention affected deployments/hardware
- Reference ticket numbers if applicable

## Troubleshooting

### Issue: Sync overwrites local changes

**Cause:** Conflicting modifications

**Prevention:**
Submit local changes before syncing.

**Recovery:**
Local changes are backed up in:

```
user_uploads/user_X/project_Y/user_patterns.yaml.backup
```

### Issue: Submission stuck in pending

**Cause:** Admin not notified or busy

**Solution:**
Contact admin or wait. Typical review time: 1-2 days.

### Issue: Pattern rejected, don't understand why

**Cause:** Insufficient admin comment

**Solution:**
Reply to rejection with questions. Admin will clarify.

## Related Features

- [Pattern Analyzer](./PATTERN_ANALYZER.md) - Uses NATCO patterns
- [Pattern Import/Export](./PATTERN_IMPORT_EXPORT.md) - Bulk operations
- [User Management](./USER_MANAGEMENT.md) - Admin functions

## Back to Documentation

[← Back to Features](../FEATURES.md) | [Architecture](../ARCHITECTURE.md) | [Quick Start](../QUICK_START.md)
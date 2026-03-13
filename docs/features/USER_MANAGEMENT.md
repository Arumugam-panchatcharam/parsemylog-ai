# USER_MANAGEMENT.md
# User Management

## Overview

User Management provides admin tools for creating, managing, and monitoring user accounts and their projects.

## Key Capabilities

- **User CRUD** - Create, read, update, delete users
- **Admin Privileges** - Assign/revoke admin access
- **Password Reset** - Admin can reset user passwords
- **Project Monitoring** - View projects per user
- **Activity Tracking** - Last login, upload counts
- **Disk Usage** - Monitor storage per user

## Usage

### User List

```
┌──────────────────────────────────────────────────────────────┐
│ User Management                                              │
│ [+ Add User] [📊 Usage Statistics]                           │
├──────────────────────────────────────────────────────────────┤
│ ID │ Username   │ Admin │ Projects │ Last Login  │ Actions   │
├────┼────────────┼───────┼──────────┼─────────────┼───────────┤
│ 1  │ admin      │ ✓     │ 5        │ 2 min ago   │ [👁] [🔒] │
│ 2  │ john_doe   │       │ 12       │ 1 day ago   │ [👁] [✏] [🗑] │
│ 3  │ jane_smith │       │ 8        │ 3 days ago  │ [👁] [✏] [🗑] │
│ 4  │ bob_jones  │ ✓     │ 3        │ 1 hour ago  │ [👁] [🔒] │
└──────────────────────────────────────────────────────────────┘

Total Users: 4
Active (last 7 days): 3
Admins: 2
```

### Create User

```
┌──────────────────────────────────────────────────────┐
│ Create New User                                      │
│ Username: [────────────────────]                     │
│ Password: [────────────────────]                     │
│ Confirm:  [────────────────────]                     │
│ ☐ Admin privileges                                   │
│ [Create User]                                        │
└──────────────────────────────────────────────────────┘
```

### View User Details

```
┌──────────────────────────────────────────────────────┐
│ User Details: john_doe                               │
├──────────────────────────────────────────────────────┤
│ User ID: 2                                           │
│ Created: 2024-01-15 10:30                            │
│ Last Login: 2024-03-12 14:22                         │
│ Admin: No                                            │
│                                                      │
│ Projects (12):                                       │
│ - Fleet Analysis Q1 2024                             │
│ - Debug Session CPE_AABB                             │
│ - Customer Issue Investigation                       │
│ ... (9 more)                                         │
│                                                      │
│ Storage Usage: 4.5 GB / 50 GB (9%)                   │
│                                                      │
│ [Reset Password] [View Projects] [Delete User]       │
└──────────────────────────────────────────────────────┘
```

### Reset Password

```
┌──────────────────────────────────────────────────────┐
│ Reset Password for: john_doe                         │
│ New Password: [────────────────────]                 │
│ Confirm:      [────────────────────]                 │
│ [Reset Password]                                     │
└──────────────────────────────────────────────────────┘

Password reset successfully.
User will be notified to change password on next login.
```

### Delete User

```
┌──────────────────────────────────────────────────────┐
│ Delete User: john_doe                                │
│ ⚠️ WARNING: This action cannot be undone!            │
│                                                      │
│ This will delete:                                    │
│ - User account                                       │
│ - 12 projects                                        │
│ - All uploaded files (4.5 GB)                        │
│ - All analysis results                               │
│                                                      │
│ Type username to confirm: [────────────────]         │
│ [Cancel] [Delete User]                               │
└──────────────────────────────────────────────────────┘
```

## API Reference

### List Users

```http
GET /api/admin/users
Authorization: Bearer <access_token>

Response:
{
  "users": [
    {
      "id": 2,
      "username": "john_doe",
      "is_admin": false,
      "created_at": "2024-01-15T10:30:00Z",
      "last_login": "2024-03-12T14:22:00Z",
      "project_count": 12,
      "storage_usage_bytes": 4831838208
    }
  ]
}
```

### Create User

```http
POST /api/auth/register
Authorization: Bearer <access_token>  (Admin only)
Content-Type: application/json

{
  "username": "new_user",
  "password": "SecurePassword123!",
  "is_admin": false
}
```

### Reset Password

```http
PUT /api/admin/users/<user_id>/password
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "new_password": "NewSecurePassword123!"
}
```

### Delete User

```http
DELETE /api/admin/users/<user_id>
Authorization: Bearer <access_token>
```

## Best Practices

- **Strong Passwords:** Enforce 12+ characters, mixed case, numbers, symbols
- **Regular Audits:** Review user activity monthly
- **Least Privilege:** Grant admin only when necessary
- **Storage Quotas:** Set per-user limits to prevent disk exhaustion

## Related Features

- [NATCO Administration](./NATCO_ADMIN.md)
- [LLM Settings](./LLM_SETTINGS.md)

## Back to Documentation

[← Back to Features](../FEATURES.md)

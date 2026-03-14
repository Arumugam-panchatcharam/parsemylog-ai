# API Documentation Standards

This guide provides standards for documenting API endpoints in feature documentation.

## Endpoint Documentation Format

### Full Endpoint Template

```markdown
**API:**
\`\`\`http
POST /api/<project_id>/<endpoint>
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "param1": "value",
  "param2": 123,
  "optional_param": "value"
}
\`\`\`

**Response (200 OK):**
\`\`\`json
{
  "success": true,
  "data": {
    "result": "value",
    "items": [...]
  }
}
\`\`\`

**Error Response (400 Bad Request):**
\`\`\`json
{
  "error": "Error message",
  "details": "Specific error details"
}
\`\`\`
```

## HTTP Methods

Use the correct HTTP method:

- **GET** - Retrieve data (no body)
- **POST** - Create new resource or complex queries
- **PUT** - Update entire resource
- **PATCH** - Partial update
- **DELETE** - Remove resource

## Path Parameters

Use angle brackets for required parameters:
- `/api/<project_id>/logs/<cpe_id>` ✅
- `/api/{project_id}/logs/{cpe_id}` ❌

## Query Parameters

Document query parameters separately:

```markdown
**Query Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Page number |
| `limit` | integer | No | 50 | Items per page |
| `filter` | string | No | null | Filter pattern |
```

## Request Body

Always show:
1. Content-Type header
2. Complete JSON structure
3. Comment optional fields
4. Use realistic example values

```json
{
  "query": "WiFi disconnects",     // Required
  "top_k": 10,                      // Optional, default: 10
  "domain": null                    // Optional, filters by domain
}
```

## Response Documentation

Document both success and common error cases:

**Success (200/201):**
- Show complete response structure
- Include realistic data
- Document all fields

**Common Errors:**
- 400 Bad Request - Validation errors
- 401 Unauthorized - Auth token missing/invalid
- 403 Forbidden - Insufficient permissions
- 404 Not Found - Resource doesn't exist
- 500 Internal Server Error - Server error

## Authentication

Always include authentication header:
```http
Authorization: Bearer <access_token>
```

Document if endpoint doesn't require auth:
```markdown
**Note:** This endpoint does not require authentication.
```

## Rate Limiting

If applicable, document rate limits:
```markdown
**Rate Limit:** 100 requests per minute per user
```

## Examples

### GET Endpoint

```markdown
**API:**
\`\`\`http
GET /api/<project_id>/logs/<cpe_id>/patterns?domain=wifi&min_freq=10
Authorization: Bearer <access_token>
\`\`\`

**Response:**
\`\`\`json
{
  "patterns": [
    {
      "template": "[wifi] ERROR: Connection failed",
      "frequency": 45,
      "domain": "wifi"
    }
  ],
  "total": 1
}
\`\`\`
```

### POST Endpoint with File Upload

```markdown
**API:**
\`\`\`http
POST /api/<project_id>/upload
Authorization: Bearer <access_token>
Content-Type: multipart/form-data

file: <binary data>
cpe_id: AABBCCDDEEFF (optional)
\`\`\`

**Response:**
\`\`\`json
{
  "success": true,
  "cpe_id": "AABBCCDDEEFF",
  "files_extracted": 15
}
\`\`\`
```

## Versioning

If API is versioned, include version in path:
- `/api/v1/<endpoint>` ✅
- Document which version in the feature doc

## Deprecation

For deprecated endpoints:

```markdown
> **⚠️ DEPRECATED** - Use `/api/v2/new-endpoint` instead. This endpoint will be removed in version 3.0.
```

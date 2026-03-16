# Version Management Guide

## How to Update the Version

When releasing a new version of ParseMyLog-AI, follow these steps:

### 1. Update the VERSION file

Edit the `/VERSION` file at the project root:

```bash
echo "1.1.0" > VERSION
```

### 2. Update frontend/src/config/version.ts

Change the `APP_VERSION` constant:

```typescript
export const APP_VERSION = "1.1.0";
```

### 3. Update frontend/package.json

Change the version field:

```json
{
  "version": "1.1.0"
}
```

### 4. Update Features List (if needed)

If you've added new features, update the `FEATURES` array in `frontend/src/config/version.ts`:

```typescript
export const FEATURES = [
  "🔍 Semantic Search with BGE embeddings",
  "📊 Telemetry Visualization with interactive charts",
  // Add new features here...
  "✨ Your new feature",
];
```

### 5. Update Tech Stack (if needed)

If you've upgraded major dependencies, update the `TECH_STACK` object:

```typescript
export const TECH_STACK = {
  frontend: [
    "React 19",  // Update versions as needed
    // ...
  ],
  // ...
};
```

## Semantic Versioning

We follow [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH):

- **MAJOR** (1.x.x): Breaking changes, major feature overhauls
  - Example: 1.0.0 → 2.0.0 (API redesign)
  
- **MINOR** (x.1.x): New features, non-breaking changes
  - Example: 1.0.0 → 1.1.0 (Added new ML model)
  
- **PATCH** (x.x.1): Bug fixes, small improvements
  - Example: 1.0.0 → 1.0.1 (Fixed login bug)

## Where Version Appears

The version number is displayed in:

1. **About Dialog**: Main location, accessible from sidebar "About" button
2. **API Response**: GET `/api/version` returns version info as JSON
3. **Build Artifacts**: Included in compiled frontend assets
4. **Package Files**: `frontend/package.json`

## Automated Version Updates (Future)

Consider adding to your build scripts:

```bash
# Bump version and update all files
npm version minor  # or major, patch

# Create git tag
git tag -a v1.1.0 -m "Release version 1.1.0"
git push origin v1.1.0
```

## Changelog Best Practices

When releasing a new version, document changes in a `CHANGELOG.md`:

```markdown
## [1.1.0] - 2026-03-16

### Added
- New ML anomaly detection feature
- Batch processing for multiple CPEs

### Changed
- Improved semantic search performance
- Updated Material UI to v7.4

### Fixed
- Fixed telemetry export bug
- Resolved login session timeout issue
```

## Version in Docker Images

When building Docker images, use the VERSION file:

```dockerfile
# In Dockerfile
ARG VERSION
LABEL version=${VERSION}
```

Build command:
```bash
VERSION=$(cat VERSION)
docker build --build-arg VERSION=$VERSION -t parsemylog-ai:$VERSION .
```

## CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Get version
        run: echo "VERSION=$(cat VERSION)" >> $GITHUB_ENV
      - name: Build and tag
        run: |
          docker build -t parsemylog-ai:$VERSION .
          docker tag parsemylog-ai:$VERSION parsemylog-ai:latest
```

## Version Checking in Code

You can access the version in TypeScript:

```typescript
import { APP_VERSION } from '@/config/version';

console.log(`Running ParseMyLog-AI version ${APP_VERSION}`);

// Conditional features based on version
if (APP_VERSION >= "2.0.0") {
  // Enable new feature
}
```

## Backend Version Endpoint

The backend provides version info at `/api/version`:

```bash
curl http://localhost:5000/api/version
```

Response:
```json
{
  "version": "1.0.0",
  "name": "ParseMyLog-AI",
  "description": "...",
  "buildDate": "2026-03-16",
  "techStack": { ... },
  "features": [ ... ]
}
```

Frontend can fetch this for version mismatch detection:

```typescript
// Check if frontend and backend versions match
const response = await fetch('/api/version');
const { version: backendVersion } = await response.json();

if (backendVersion !== APP_VERSION) {
  console.warn('Version mismatch! Frontend:', APP_VERSION, 'Backend:', backendVersion);
}
```

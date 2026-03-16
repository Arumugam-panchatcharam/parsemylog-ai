# Version File Structure

Detailed reference for all files involved in version management.

## Version Files

### 1. `/VERSION`

**Location**: Project root  
**Format**: Plain text, single line  
**Purpose**: Single source of truth for version number

```
1.0.0
```

**Requirements:**
- No newline at end
- Must follow semantic versioning (MAJOR.MINOR.PATCH)
- No "v" prefix
- Can include pre-release suffix: `1.0.0-alpha.1`

---

### 2. `frontend/src/config/version.ts`

**Location**: Frontend configuration  
**Format**: TypeScript module  
**Purpose**: Frontend version constants and metadata

**Key exports:**

```typescript
export const APP_VERSION = "1.0.0";  // ← UPDATE THIS
export const APP_NAME = "ParseMyLog-AI";
export const APP_DESCRIPTION = "...";

export const PROJECT_INFO = {
  version: APP_VERSION,
  name: APP_NAME,
  description: APP_DESCRIPTION,
  repository: "https://github.com/your-org/parsemylog-ai",
  license: "MIT",
  buildDate: new Date().toISOString().split('T')[0],
};

export const TECH_STACK = { /* ... */ };
export const FEATURES = [ /* ... */ ];
```

**Update requirements:**
- Change `APP_VERSION` constant (line 6)
- Keep quotes: double quotes for consistency
- Update `FEATURES` array if new features added
- Update `TECH_STACK` if dependencies changed

---

### 3. `frontend/package.json`

**Location**: Frontend package manifest  
**Format**: JSON  
**Purpose**: NPM package version

```json
{
  "name": "parsemylog-ai-frontend",
  "version": "1.0.0",  // ← UPDATE THIS
  "private": true,
  "type": "module",
  // ... rest of package.json
}
```

**Update requirements:**
- Change `version` field (line 3)
- Must be valid JSON
- Keep consistent with VERSION and version.ts

---

## Changelog File

### `CHANGELOG.md`

**Location**: Project root (create if doesn't exist)  
**Format**: Markdown following [Keep a Changelog](https://keepachangelog.com/)  
**Purpose**: Human-readable history of changes

**Structure:**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Features in development

## [1.1.0] - 2026-03-16

### Added
- Telemetry CSV export feature
- Separate defaults for telemetry export

### Changed
- Improved sidebar responsiveness

### Fixed
- Fixed 404 error on CSV export endpoint

## [1.0.0] - 2026-03-15

### Added
- Initial release
- Semantic search with BGE embeddings
- Telemetry visualization
- ML anomaly detection
- Multi-CPE support

[Unreleased]: https://github.com/your-org/parsemylog-ai/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/your-org/parsemylog-ai/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/your-org/parsemylog-ai/releases/tag/v1.0.0
```

**Categories (in order):**
1. **Added**: New features
2. **Changed**: Changes to existing functionality
3. **Deprecated**: Soon-to-be removed features
4. **Removed**: Removed features
5. **Fixed**: Bug fixes
6. **Security**: Vulnerability fixes

---

## Backend Version Files

### `api/routes/version.py`

**Purpose**: API endpoint for version information  
**Note**: Reads from `/VERSION` file dynamically

```python
@version_bp.route('/', methods=['GET'])
def get_version():
    version = read_version_file()  # Reads from /VERSION
    return jsonify({
        'version': version,
        'name': 'ParseMyLog-AI',
        # ... other metadata
    })
```

**No manual updates needed** - automatically reads VERSION file.

---

## Git Tags

### Tag Format

Tags follow the pattern: `v{MAJOR}.{MINOR}.{PATCH}`

**Examples:**
- `v1.0.0`
- `v1.1.0`
- `v2.0.0`
- `v1.0.1`

**Pre-release tags:**
- `v1.1.0-alpha.1`
- `v1.1.0-beta.1`
- `v1.1.0-rc.1`

### Creating Tags

```bash
# Annotated tag (recommended)
git tag -a v1.1.0 -m "Release version 1.1.0"

# Lightweight tag (not recommended)
git tag v1.1.0
```

**Always use annotated tags** for releases:
- Contains tagger info
- Has message
- Can be verified with GPG

### Pushing Tags

```bash
# Push specific tag
git push origin v1.1.0

# Push all tags
git push --tags
```

---

## Docker Version Labels

When building Docker images, include version label:

```dockerfile
# Read version at build time
ARG VERSION
LABEL version=${VERSION}
LABEL maintainer="your-email@example.com"
```

Build command:

```bash
VERSION=$(cat VERSION)
docker build --build-arg VERSION=$VERSION -t parsemylog-ai:$VERSION .
docker tag parsemylog-ai:$VERSION parsemylog-ai:latest
```

---

## CI/CD Configuration

### GitHub Actions

Example workflow that triggers on version tags:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*.*.*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Extract version
        id: version
        run: echo "VERSION=$(cat VERSION)" >> $GITHUB_OUTPUT
      
      - name: Build Docker image
        run: |
          docker build \
            --build-arg VERSION=${{ steps.version.outputs.VERSION }} \
            -t parsemylog-ai:${{ steps.version.outputs.VERSION }} .
      
      - name: Create GitHub Release
        uses: actions/create-release@v1
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          tag_name: ${{ github.ref }}
          release_name: Release ${{ steps.version.outputs.VERSION }}
          body_path: CHANGELOG.md
```

---

## File Update Order

When bumping versions, update in this order:

1. **VERSION** (source of truth)
2. **frontend/src/config/version.ts** (sync from VERSION)
3. **frontend/package.json** (sync from VERSION)
4. **CHANGELOG.md** (add new version section)
5. **Git commit** (commit all changes)
6. **Git tag** (create version tag)
7. **Git push** (push commits and tag)

---

## Validation Checks

Before finalizing a version bump, verify:

```bash
# All files have same version
VERSION_FILE=$(cat VERSION)
VERSION_TS=$(grep 'APP_VERSION = ' frontend/src/config/version.ts | sed 's/.*"\(.*\)".*/\1/')
VERSION_JSON=$(jq -r .version frontend/package.json)

if [ "$VERSION_FILE" = "$VERSION_TS" ] && [ "$VERSION_FILE" = "$VERSION_JSON" ]; then
  echo "✓ All versions match: $VERSION_FILE"
else
  echo "✗ Version mismatch!"
  echo "  VERSION: $VERSION_FILE"
  echo "  version.ts: $VERSION_TS"
  echo "  package.json: $VERSION_JSON"
fi

# Changelog has entry for new version
if grep -q "\[$VERSION_FILE\]" CHANGELOG.md; then
  echo "✓ Changelog has entry for $VERSION_FILE"
else
  echo "✗ Missing changelog entry for $VERSION_FILE"
fi

# Git tag exists
if git tag -l "v$VERSION_FILE" | grep -q .; then
  echo "✓ Git tag v$VERSION_FILE exists"
else
  echo "✗ Git tag v$VERSION_FILE not found"
fi
```

---

## Common Issues

### Issue: Version Files Out of Sync

**Symptom**: Different versions in VERSION, version.ts, package.json

**Solution**: Use sync command
```bash
python scripts/bump_version.py sync
```

### Issue: Tag Already Exists Remotely

**Symptom**: `error: tag 'v1.1.0' already exists`

**Solution**: Either increment to next version or delete tag
```bash
# Delete remote tag (careful!)
git push origin :refs/tags/v1.1.0

# Delete local tag
git tag -d v1.1.0
```

### Issue: Changelog Merge Conflict

**Symptom**: CHANGELOG.md has conflicts after merge

**Solution**: Keep both entries, sort by version descending
```markdown
## [1.2.0] - 2026-03-17
...

## [1.1.0] - 2026-03-16
...
```

### Issue: Backend Serving Wrong Version

**Symptom**: `/api/version` returns old version

**Solution**: 
1. Verify VERSION file updated
2. Restart Flask server
3. Clear Redis cache if caching enabled

```bash
# Restart backend
pkill -f "flask run"
python api/app.py
```

# Script Implementation Details

Detailed documentation for the version management utility scripts.

## Overview

The version-bump skill includes two Python scripts:

1. **`bump_version.py`**: Increment version numbers and update files
2. **`update_changelog.py`**: Generate CHANGELOG.md entries from git commits

Both scripts are designed to be robust, auto-detect the project root, and provide clear error messages.

---

## bump_version.py

### Purpose

Automates the process of incrementing semantic version numbers and updating all version files to stay in sync.

### Features

- Auto-detects project root by searching for VERSION file
- Supports semantic versioning (MAJOR.MINOR.PATCH)
- Handles pre-release versions (e.g., 1.0.0-alpha.1)
- Updates three files atomically
- Provides clear feedback and next steps
- Includes sync and verify commands

### Commands

#### Major Bump

```bash
python scripts/bump_version.py major
```

Increments major version and resets minor/patch to 0.

**Example**: `1.2.3` → `2.0.0`

**Use for**:
- Breaking API changes
- Major architecture overhauls
- Removing features
- Incompatible changes

#### Minor Bump

```bash
python scripts/bump_version.py minor
```

Increments minor version and resets patch to 0.

**Example**: `1.2.3` → `1.3.0`

**Use for**:
- New features (backward compatible)
- New API endpoints
- Enhancements to existing features

#### Patch Bump

```bash
python scripts/bump_version.py patch
```

Increments patch version only.

**Example**: `1.2.3` → `1.2.4`

**Use for**:
- Bug fixes
- Documentation updates
- Small improvements

#### Sync Versions

```bash
python scripts/bump_version.py sync
```

Syncs all files to the VERSION file (source of truth). Use when files are out of sync.

**Example**:
```
VERSION file: 1.2.0
version.ts:   1.1.0  ← out of sync
package.json: 1.1.0  ← out of sync
```

After sync:
```
VERSION file: 1.2.0
version.ts:   1.2.0  ✓
package.json: 1.2.0  ✓
```

#### Verify Versions

```bash
python scripts/bump_version.py verify
```

Checks if all version files match. Returns exit code 0 if synced, 1 if not.

Useful in CI/CD pipelines:

```bash
# In CI pipeline
python scripts/bump_version.py verify || {
  echo "Version files out of sync!"
  exit 1
}
```

### Implementation Details

#### Version Parsing

The script uses regex to parse semantic versions:

```python
r'^(\d+)\.(\d+)\.(\d+)(.*)$'
```

Supports:
- Standard: `1.0.0`
- Pre-release: `1.0.0-alpha.1`
- Build metadata: `1.0.0+20230316`
- Combined: `1.0.0-rc.1+build.123`

#### File Updates

**VERSION file**:
```python
self.version_file.write_text(new_version + "\n")
```

**version.ts**:
```python
pattern = r'(export const APP_VERSION = ")[^"]+(")'
replacement = rf'\g<1>{new_version}\g<2>'
new_content = re.sub(pattern, replacement, content)
```

**package.json**:
```python
with open(self.package_json, 'r') as f:
    package = json.load(f)

package['version'] = new_version

with open(self.package_json, 'w') as f:
    json.dump(package, f, indent=2)
    f.write('\n')  # Trailing newline
```

### Error Handling

The script handles common errors gracefully:

1. **Project root not found**: Walks up directory tree
2. **Missing files**: Clear error with file path
3. **Invalid version format**: Validates semantic versioning
4. **Update failed**: Checks if regex replacement worked

### Example Output

```bash
$ python scripts/bump_version.py minor

Bumping version: 1.0.0 -> 1.1.0
Bump type: MINOR

✓ Updated VERSION: 1.1.0
✓ Updated frontend/src/config/version.ts: APP_VERSION = "1.1.0"
✓ Updated frontend/package.json: version = "1.1.0"

✓ Successfully bumped version to 1.1.0

Next steps:
  1. Review changes: git diff
  2. Update CHANGELOG.md: python scripts/update_changelog.py
  3. Commit: git add . && git commit -m 'chore: bump version to 1.1.0'
  4. Tag: git tag -a v1.1.0 -m 'Release version 1.1.0'
  5. Push: git push origin HEAD && git push origin v1.1.0
```

---

## update_changelog.py

### Purpose

Generates CHANGELOG.md entries by analyzing git commit messages since the last version tag.

### Features

- Auto-detects project root
- Analyzes git history since last tag
- Categorizes commits into changelog sections
- Supports conventional commits format
- Creates CHANGELOG.md if it doesn't exist
- Preserves existing changelog content
- Dry-run mode for preview

### Commands

#### Generate Entry

```bash
python scripts/update_changelog.py
```

Generates entry for current version (from VERSION file).

#### Specify Version

```bash
python scripts/update_changelog.py --version 1.2.0
```

Generates entry for specified version.

#### Preview (Dry Run)

```bash
python scripts/update_changelog.py --dry-run
```

Shows what would be generated without writing to file.

### Commit Categorization

The script analyzes commit messages and categorizes them:

#### Conventional Commits

Recognizes [conventional commits](https://www.conventionalcommits.org/) format:

```
feat(auth): add JWT token support       → Added
fix(api): resolve timeout issue         → Fixed
refactor(db): optimize query            → Changed
docs(readme): update installation       → Other (not included)
```

**Type mapping**:
- `feat` → Added
- `fix` → Fixed
- `refactor`, `perf` → Changed
- `revert` → Removed
- `docs`, `style`, `test`, `chore`, `build`, `ci` → Other (filtered out)

#### Keyword-Based

For non-conventional commits, uses keyword detection:

| Keywords | Category |
|----------|----------|
| add, new, feature, implement, introduce | Added |
| fix, bug, resolve, correct, patch | Fixed |
| change, update, improve, enhance, refactor, optimize | Changed |
| remove, delete, drop | Removed |
| deprecate, obsolete | Deprecated |
| security, vulnerability, CVE | Security |

#### Examples

```bash
# Input commits:
"Add telemetry CSV export feature"      → Added
"Fix 404 error on export endpoint"      → Fixed
"Update sidebar responsiveness"         → Changed
"Remove deprecated API v1"              → Removed
```

### Changelog Format

Generated entries follow [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
## [1.1.0] - 2026-03-16

### Added
- Telemetry CSV export feature
- Batch processing support

### Changed
- Improved sidebar responsiveness
- Updated Material UI to v7.4

### Fixed
- 404 error on CSV export endpoint
- Login session timeout issue
```

**Category order** (standardized):
1. Added
2. Changed
3. Deprecated
4. Removed
5. Fixed
6. Security

### Implementation Details

#### Git Integration

**Get last tag**:
```python
subprocess.run(
    ['git', 'describe', '--tags', '--abbrev=0'],
    cwd=self.project_root,
    capture_output=True,
    text=True
)
```

**Get commits since tag**:
```python
subprocess.run(
    ['git', 'log', f'{tag}..HEAD', '--oneline', '--no-merges'],
    cwd=self.project_root,
    capture_output=True,
    text=True
)
```

#### Changelog Insertion

The script intelligently inserts new entries:

1. **New CHANGELOG.md**: Creates with proper header
2. **Existing CHANGELOG.md**: Inserts after `[Unreleased]` section
3. **Preserves existing content**: All old entries remain

**Insertion logic**:
```python
# Find [Unreleased] section and insert after it
unreleased_pattern = r'(## \[Unreleased\].*?)(\n\n)(## \[|\Z)'
match = re.search(unreleased_pattern, content, re.DOTALL)
if match:
    before = content[:match.end(2)]
    after = content[match.start(3):]
    return before + new_entry + "\n" + after
```

### Example Output

```bash
$ python scripts/update_changelog.py

Generating changelog for version 1.1.0...
Analyzing commits since v1.0.0
Found 8 commits to analyze

======================================================================
Generated Changelog Entry:
======================================================================
## [1.1.0] - 2026-03-16

### Added
- Telemetry CSV export feature
- Separate defaults for telemetry export

### Changed
- Improved sidebar responsiveness
- Updated profile statistics display

### Fixed
- 404 error on CSV export endpoint
- Profile stats calculation bug
======================================================================

✓ Updated CHANGELOG.md

✓ Changelog entry added for version 1.1.0

Please review and edit CHANGELOG.md to:
  - Refine descriptions for clarity
  - Add issue/PR references
  - Highlight breaking changes
  - Remove irrelevant entries
```

### Manual Refinement

After generation, **always review and refine** the changelog:

#### Add Context

```diff
  ### Added
- - Telemetry export
+ - Telemetry CSV export with configurable separators (#123)
```

#### Add Issue References

```diff
  ### Fixed
- - Export bug
+ - Fixed 404 error on CSV export endpoint (#124)
```

#### Highlight Breaking Changes

```diff
  ### Changed
+ - ⚠️ **BREAKING**: Changed authentication to JWT tokens
  - Improved sidebar responsiveness
```

#### Remove Internal Changes

```diff
  ### Changed
  - Improved sidebar responsiveness
- - Updated ESLint config
- - Fixed typo in comment
```

---

## Script Usage in Workflow

### Complete Release Process

```bash
# 1. Analyze changes and decide bump type
git log --oneline
# Conclusion: Added new feature → minor bump

# 2. Bump version
python .cursor/skills/version-bump/scripts/bump_version.py minor

# 3. Generate changelog
python .cursor/skills/version-bump/scripts/update_changelog.py

# 4. Review and edit CHANGELOG.md
vim CHANGELOG.md  # or your editor

# 5. Verify everything is in sync
python .cursor/skills/version-bump/scripts/bump_version.py verify

# 6. Commit and tag
NEW_VERSION=$(cat VERSION)
git add VERSION frontend/src/config/version.ts frontend/package.json CHANGELOG.md
git commit -m "chore: bump version to $NEW_VERSION"
git tag -a "v$NEW_VERSION" -m "Release version $NEW_VERSION"

# 7. Push
git push origin HEAD
git push origin "v$NEW_VERSION"
```

### CI/CD Integration

**Pre-commit hook** (ensure versions are synced):

```bash
#!/bin/bash
# .git/hooks/pre-commit

python scripts/bump_version.py verify || {
  echo "Error: Version files out of sync!"
  echo "Run: python scripts/bump_version.py sync"
  exit 1
}
```

**GitHub Actions** (validate on PR):

```yaml
name: Version Check

on: [pull_request]

jobs:
  check-versions:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Verify versions are synced
        run: python scripts/bump_version.py verify
```

---

## Extending the Scripts

### Adding New Version Files

If you need to update additional files:

```python
# In bump_version.py, add new method:
def update_helm_chart(self, new_version: str):
    """Update Helm chart version."""
    chart_file = self.project_root / "helm" / "Chart.yaml"
    content = chart_file.read_text()
    
    pattern = r'(version: )[0-9]+\.[0-9]+\.[0-9]+'
    replacement = rf'\g<1>{new_version}'
    new_content = re.sub(pattern, replacement, content)
    
    chart_file.write_text(new_content)
    print(f"✓ Updated {chart_file.relative_to(self.project_root)}")

# Call in bump_and_update():
self.update_helm_chart(new_version)
```

### Custom Changelog Categories

Add custom categories to `update_changelog.py`:

```python
def categorize_commit(self, commit_message: str) -> Tuple[str, str]:
    # ... existing code ...
    
    # Add custom category
    if 'performance' in message_lower:
        category = "Performance"
    
    # ... rest of code ...

# Update category_order:
category_order = ["Added", "Changed", "Performance", "Deprecated", ...]
```

### Adding Commit Prefixes

Filter or modify commit messages:

```python
def categorize_commit(self, commit_message: str) -> Tuple[str, str]:
    # ... existing code ...
    
    # Remove Jira ticket prefixes
    description = re.sub(r'^[A-Z]+-\d+:\s*', '', description)
    
    # Add emoji prefixes
    if category == "Added":
        description = f"✨ {description}"
    elif category == "Fixed":
        description = f"🐛 {description}"
    
    return category, description
```

---

## Troubleshooting

### Script Can't Find Project Root

**Symptom**: `FileNotFoundError: Could not find project root`

**Solution**: Run from project directory or subdirectory containing VERSION file.

### Git Commands Fail

**Symptom**: `Warning: Could not get git commits`

**Solution**: Ensure you're in a git repository and have commits.

```bash
git status  # Check if in git repo
git log     # Check if commits exist
```

### Regex Not Matching

**Symptom**: `RuntimeError: Failed to update APP_VERSION`

**Solution**: Verify version.ts format matches expected pattern:

```typescript
export const APP_VERSION = "1.0.0";  // ← Must match this format
```

### Permission Denied

**Symptom**: `PermissionError: [Errno 13]`

**Solution**: Make scripts executable:

```bash
chmod +x scripts/bump_version.py scripts/update_changelog.py
```

### Unicode Errors

**Symptom**: `UnicodeDecodeError`

**Solution**: Ensure files use UTF-8 encoding:

```python
# If needed, add encoding parameter:
content = file.read_text(encoding='utf-8')
```

---

## Testing the Scripts

### Unit Testing

```python
# test_bump_version.py
import unittest
from bump_version import VersionBumper

class TestVersionBumper(unittest.TestCase):
    def test_parse_version(self):
        bumper = VersionBumper("/path/to/project")
        major, minor, patch, suffix = bumper.parse_version("1.2.3")
        self.assertEqual((major, minor, patch, suffix), (1, 2, 3, ""))
    
    def test_bump_major(self):
        bumper = VersionBumper("/path/to/project")
        new_version = bumper.bump_version("major", "1.2.3")
        self.assertEqual(new_version, "2.0.0")
```

### Integration Testing

```bash
# Create test project
mkdir test-project
cd test-project
echo "1.0.0" > VERSION
mkdir -p frontend/src/config
echo 'export const APP_VERSION = "1.0.0";' > frontend/src/config/version.ts
echo '{"version": "1.0.0"}' > frontend/package.json

# Test bump
python ../../scripts/bump_version.py minor

# Verify
python ../../scripts/bump_version.py verify
```

---

## Performance Considerations

### Git Log Optimization

For large repositories, limit commit history:

```python
# In get_commits_since_tag(), add --max-count:
subprocess.run(
    ['git', 'log', git_range, '--oneline', '--no-merges', '--max-count=100'],
    # ...
)
```

### Caching

For repeated runs, cache git data:

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_commits_since_tag(self, tag: Optional[str] = None) -> List[str]:
    # ... existing implementation ...
```

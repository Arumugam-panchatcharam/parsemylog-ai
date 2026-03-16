---
name: version-bump
description: Automatically increment version numbers (major, minor, patch) based on code changes, update all version files, maintain CHANGELOG.md, and create git tags. Use when the user asks to bump, update, or increment the version, when making significant code changes, or when preparing a release.
---

# Version Bump

Automatically manage semantic versioning for ParseMyLog-AI by analyzing changes, updating version files, maintaining changelog, and creating git tags.

## When to Use This Skill

Use this skill when:
- User explicitly asks to "bump version", "increment version", or "update version"
- User says "prepare for release" or "create a release"
- Making significant feature additions, bug fixes, or breaking changes
- User mentions "major", "minor", or "patch" in context of versioning

## Quick Start

### 1. Analyze Changes to Determine Bump Type

If the user hasn't specified major/minor/patch, analyze recent changes:

```bash
# Check recent commits since last tag
git log $(git describe --tags --abbrev=0)..HEAD --oneline

# Review staged/unstaged changes
git diff HEAD
```

**Decision criteria:**
- **MAJOR** (x.0.0): Breaking changes, API redesign, major architecture changes
- **MINOR** (0.x.0): New features, non-breaking enhancements, new endpoints
- **PATCH** (0.0.x): Bug fixes, small improvements, documentation updates

### 2. Run the Version Bump Script

```bash
cd /Users/parumugam/Documents/Repos/parsemylog-ai
python .cursor/skills/version-bump/scripts/bump_version.py [major|minor|patch]
```

This script automatically:
- Reads current version from `/VERSION`
- Increments the appropriate segment
- Updates all three files:
  - `/VERSION`
  - `frontend/src/config/version.ts` (APP_VERSION)
  - `frontend/package.json` (version field)

### 3. Update CHANGELOG.md

Run the changelog generator:

```bash
python .cursor/skills/version-bump/scripts/update_changelog.py
```

This analyzes git commits and generates a changelog entry. Review and edit if needed:

```markdown
## [NEW_VERSION] - YYYY-MM-DD

### Added
- New features from commits

### Changed
- Modified functionality

### Fixed
- Bug fixes
```

### 4. Commit and Tag

```bash
# Stage all version-related changes
git add VERSION frontend/src/config/version.ts frontend/package.json CHANGELOG.md

# Commit with version message
NEW_VERSION=$(cat VERSION)
git commit -m "chore: bump version to $NEW_VERSION"

# Create annotated tag
git tag -a "v$NEW_VERSION" -m "Release version $NEW_VERSION"

# Push changes and tag
git push origin HEAD
git push origin "v$NEW_VERSION"
```

## Complete Workflow Example

When user says "bump version to add the new telemetry export feature":

1. **Analyze**: New feature → MINOR bump
2. **Run**: `python scripts/bump_version.py minor`
3. **Verify**: Check that 1.0.0 → 1.1.0 in all files
4. **Changelog**: `python scripts/update_changelog.py`
5. **Review**: Edit CHANGELOG.md to refine entries
6. **Commit & Tag**: Follow step 4 above

## Version File Locations

The skill updates these three files to keep versions synchronized:

1. **`/VERSION`**: Single source of truth (plain text)
   ```
   1.1.0
   ```

2. **`frontend/src/config/version.ts`**: Frontend constant
   ```typescript
   export const APP_VERSION = "1.1.0";
   ```

3. **`frontend/package.json`**: NPM package version
   ```json
   {
     "version": "1.1.0"
   }
   ```

## Smart Change Detection

When user doesn't specify the bump type, analyze their changes:

### Indicators of MAJOR bump:
- Removing or renaming API endpoints
- Changing database schema (breaking migrations)
- Removing public functions/components
- Changing authentication system
- Major UI overhaul

### Indicators of MINOR bump:
- Adding new API endpoints
- Adding new features/components
- Adding new configuration options
- Enhancing existing features (non-breaking)
- Adding new dependencies

### Indicators of PATCH bump:
- Fixing bugs
- Improving error messages
- Updating documentation
- Performance improvements (no API changes)
- Dependency updates (patch versions)

## Changelog Best Practices

The changelog generator follows [Keep a Changelog](https://keepachangelog.com/) format:

### Category Mapping from Commits

Analyze commit messages and categorize:

- **Added**: Commits with "add", "new", "feature", "feat"
- **Changed**: Commits with "change", "update", "refactor", "improve"
- **Fixed**: Commits with "fix", "bug", "resolve", "patch"
- **Deprecated**: Commits with "deprecate", "obsolete"
- **Removed**: Commits with "remove", "delete"
- **Security**: Commits with "security", "vulnerability", "CVE"

### Manual Refinement

After generating, review and improve:
- Add user-facing descriptions (not technical jargon)
- Combine related commits into single entries
- Add issue/PR references
- Highlight breaking changes with ⚠️

## Troubleshooting

### Version Files Out of Sync

If files have different versions:

```bash
# Check current versions
echo "VERSION file: $(cat VERSION)"
echo "version.ts: $(grep 'APP_VERSION = ' frontend/src/config/version.ts)"
echo "package.json: $(jq -r .version frontend/package.json)"

# Force sync to VERSION file
python scripts/bump_version.py sync
```

### Tag Already Exists

If git tag fails because it exists:

```bash
# Delete local tag
git tag -d v1.1.0

# Delete remote tag (careful!)
git push origin :refs/tags/v1.1.0

# Recreate tag
git tag -a v1.1.0 -m "Release version 1.1.0"
git push origin v1.1.0
```

### Uncommitted Changes

If there are uncommitted changes before version bump:

```bash
# Stash changes
git stash

# Run version bump
python scripts/bump_version.py minor

# Reapply changes
git stash pop
```

## Integration with CI/CD

The version tag triggers automated builds. When you push a tag:

1. GitHub Actions detects `v*` tag
2. Runs tests and builds
3. Creates Docker images with version label
4. Publishes release artifacts

Ensure your `.github/workflows/release.yml` exists and is configured.

## Pre-Release Versions

For beta/alpha versions, manually edit VERSION:

```bash
# Alpha release
echo "1.1.0-alpha.1" > VERSION
python scripts/bump_version.py sync

# Beta release
echo "1.1.0-beta.1" > VERSION
python scripts/bump_version.py sync

# Release candidate
echo "1.1.0-rc.1" > VERSION
python scripts/bump_version.py sync
```

## Version Bump Checklist

Track your progress when bumping versions:

```
Version Bump Checklist:
- [ ] Determine bump type (major/minor/patch)
- [ ] Run bump_version.py script
- [ ] Verify all three files updated
- [ ] Run update_changelog.py
- [ ] Review and refine CHANGELOG.md
- [ ] Update features list if needed (version.ts)
- [ ] Commit version changes
- [ ] Create annotated git tag
- [ ] Push commits and tag
- [ ] Verify CI/CD pipeline triggered
- [ ] Monitor build/deployment
```

## Additional Resources

- For detailed file structure, see [FILES.md](FILES.md)
- For script implementation details, see [SCRIPTS.md](SCRIPTS.md)
- For versioning strategy, see project root `VERSION_MANAGEMENT.md`

---

## Important Notes

1. **Always commit before bumping**: Ensure working directory is clean
2. **Never skip patch versions**: 1.0.0 → 1.2.0 is invalid (should be 1.1.0 → 1.2.0)
3. **Tags are immutable**: Once pushed, don't change tags (create new version instead)
4. **Changelog is for users**: Write user-facing descriptions, not internal details
5. **Coordinate with team**: Communicate version bumps for shared projects

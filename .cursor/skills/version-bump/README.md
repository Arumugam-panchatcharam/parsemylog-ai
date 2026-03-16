# Version Bump Skill

Automatic semantic version management for ParseMyLog-AI.

## Overview

This skill provides intelligent version bumping with:
- **Smart change detection**: Analyzes commits to suggest major/minor/patch bumps
- **Atomic updates**: Updates VERSION, version.ts, and package.json in sync
- **Changelog automation**: Generates CHANGELOG.md from git history
- **Git integration**: Creates and pushes version tags automatically

## Quick Start

### Bump Version

```bash
# From project root
python3 .cursor/skills/version-bump/scripts/bump_version.py minor
```

### Update Changelog

```bash
python3 .cursor/skills/version-bump/scripts/update_changelog.py
```

### Complete Release Flow

```bash
# 1. Bump version (major/minor/patch)
python3 .cursor/skills/version-bump/scripts/bump_version.py minor

# 2. Generate changelog
python3 .cursor/skills/version-bump/scripts/update_changelog.py

# 3. Review and edit CHANGELOG.md
vim CHANGELOG.md

# 4. Commit and tag
VERSION=$(cat VERSION)
git add VERSION frontend/src/config/version.ts frontend/package.json CHANGELOG.md
git commit -m "chore: bump version to $VERSION"
git tag -a "v$VERSION" -m "Release version $VERSION"

# 5. Push
git push origin HEAD && git push origin "v$VERSION"
```

## Files

- **SKILL.md**: Main skill instructions (read this first!)
- **FILES.md**: Detailed reference for all version files
- **SCRIPTS.md**: Script implementation details
- **scripts/bump_version.py**: Version increment utility
- **scripts/update_changelog.py**: Changelog generator

## Usage Commands

### Version Bumping

```bash
# Increment major version (breaking changes)
python3 scripts/bump_version.py major    # 1.0.0 → 2.0.0

# Increment minor version (new features)
python3 scripts/bump_version.py minor    # 1.0.0 → 1.1.0

# Increment patch version (bug fixes)
python3 scripts/bump_version.py patch    # 1.0.0 → 1.0.1

# Sync all files to VERSION (if out of sync)
python3 scripts/bump_version.py sync

# Verify all files match
python3 scripts/bump_version.py verify
```

### Changelog Management

```bash
# Generate entry for current version
python3 scripts/update_changelog.py

# Preview without writing
python3 scripts/update_changelog.py --dry-run

# Generate for specific version
python3 scripts/update_changelog.py --version 1.2.0
```

## What Gets Updated

1. **`/VERSION`** - Plain text version file (source of truth)
2. **`frontend/src/config/version.ts`** - Frontend APP_VERSION constant
3. **`frontend/package.json`** - NPM package version
4. **`CHANGELOG.md`** - Release notes (if using update_changelog.py)

## Requirements

- Python 3.6+
- Git (for changelog generation)
- Working git repository

## Features

### Smart Change Detection

The skill analyzes your changes to suggest the appropriate bump type:

- **MAJOR**: Breaking changes, API redesign, major refactors
- **MINOR**: New features, enhancements, new endpoints
- **PATCH**: Bug fixes, documentation, small improvements

### Conventional Commits Support

Automatically recognizes conventional commit format:

```
feat(auth): add JWT support     → Added
fix(api): resolve timeout       → Fixed
refactor(db): optimize queries  → Changed
```

### Changelog Categories

Generated changelogs follow [Keep a Changelog](https://keepachangelog.com/):

- **Added**: New features
- **Changed**: Changes to existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security fixes

## Troubleshooting

### Versions Out of Sync

```bash
python3 scripts/bump_version.py verify
# If failed, sync them:
python3 scripts/bump_version.py sync
```

### Tag Already Exists

```bash
# Delete local and remote tag
git tag -d v1.1.0
git push origin :refs/tags/v1.1.0

# Recreate
git tag -a v1.1.0 -m "Release version 1.1.0"
git push origin v1.1.0
```

### No Git Commits Found

If `update_changelog.py` finds no commits, you'll get a generic entry. This happens when:
- No tags exist yet (first release)
- No commits since last tag
- Not in a git repository

## Integration

### Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit
python3 scripts/bump_version.py verify || {
  echo "Version files out of sync!"
  exit 1
}
```

### GitHub Actions

```yaml
name: Version Check
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: python3 scripts/bump_version.py verify
```

## Documentation

- **[SKILL.md](SKILL.md)** - Complete skill instructions and workflow
- **[FILES.md](FILES.md)** - Version file structure and formats
- **[SCRIPTS.md](SCRIPTS.md)** - Script implementation details
- **[VERSION_MANAGEMENT.md](../../VERSION_MANAGEMENT.md)** - Project versioning guide

## License

Same as project (MIT)

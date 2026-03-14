# Documentation Update Skill

Automatically maintains comprehensive documentation for ParseMyLog-AI when features are added or modified.

## Overview

This skill ensures that:
- Feature documentation stays in sync with code
- README.md reflects current capabilities
- FEATURES.md catalog is complete
- ARCHITECTURE.md is updated when infrastructure changes
- All cross-references are valid

## Quick Start

The skill is automatically triggered when:
- Adding new features
- Modifying existing features
- Changing API endpoints
- Updating architecture
- User mentions "update docs" or "documentation"

## What It Does

1. **Analyzes code changes** to determine documentation impact
2. **Updates feature docs** in `./docs/features/`
3. **Updates catalogs** (FEATURES.md, README.md)
4. **Updates architecture** docs when needed
5. **Validates integrity** (links, cross-references, naming)

## Utility Scripts

### analyze_impact.py
Scans git changes and recommends documentation updates.

```bash
python .cursor/skills/update-docs/scripts/analyze_impact.py
```

### validate_docs.py
Checks documentation integrity (links, orphaned files, naming).

```bash
python .cursor/skills/update-docs/scripts/validate_docs.py
```

### generate_feature_stub.py
Creates skeleton feature documentation from template.

```bash
python .cursor/skills/update-docs/scripts/generate_feature_stub.py "Feature Name"
```

## Reference Guides

- **[reference.md](reference.md)** - API documentation standards
- **[diagrams.md](diagrams.md)** - Diagram creation guidelines
- **[screenshots.md](screenshots.md)** - Screenshot best practices

## Documentation Structure

```
docs/
├── README.md                    # Documentation index
├── FEATURES.md                  # Feature catalog
├── ARCHITECTURE.md              # System architecture
├── QUICK_START.md              # Getting started
├── API_REFERENCE.md            # API documentation
├── USER_GUIDE.md               # End-user guide
└── features/                   # Feature-specific docs
    ├── SEMANTIC_SEARCH.md
    ├── TELEMETRY.md
    ├── LOG_VIEWER.md
    └── ...

README.md                        # Main project README
```

## Workflow Example

### Adding a New Feature

```bash
# 1. Write feature code
# 2. Agent auto-detects changes
# 3. Agent creates feature doc using template
# 4. Agent updates FEATURES.md
# 5. Agent updates README.md (if major feature)
# 6. Agent validates all links
# 7. Everything is ready to commit!
```

### Modifying Existing Feature

```bash
# 1. Modify feature code
# 2. Agent identifies affected docs
# 3. Agent updates feature doc
# 4. Agent updates description in FEATURES.md (if needed)
# 5. Agent validates integrity
```

## Manual Usage

You can also manually trigger documentation updates:

```
User: "Update documentation for the new CSV export feature"
Agent: [Follows skill workflow]
  1. Creates/updates docs/features/TELEMETRY_CSV.md
  2. Adds entry to FEATURES.md
  3. Updates README.md
  4. Validates all links
```

## Customization

To customize templates, edit:
- `scripts/generate_feature_stub.py` - Feature doc template
- `SKILL.md` - Workflow and guidelines
- `reference.md` - API documentation standards

## Requirements

- Python 3.7+
- Git (for change detection)
- Write access to docs/ directory

## Troubleshooting

**"Git not found" error**
- Ensure git is installed and in PATH

**"Permission denied" error**
- Check file permissions on scripts
- Run `chmod +x scripts/*.py`

**Links not validating**
- Ensure paths are relative
- Use forward slashes (not backslashes)
- Check file exists at target path

## Contributing

To improve this skill:
1. Update SKILL.md with new workflows
2. Add validation checks to validate_docs.py
3. Enhance impact detection in analyze_impact.py
4. Update templates in generate_feature_stub.py

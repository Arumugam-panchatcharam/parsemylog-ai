---
name: update-docs
description: Automatically update README.md and documentation in ./docs folder when features are added or modified. Updates FEATURES.md, creates feature documentation, updates architecture diagrams, and maintains cross-references. Use when implementing new features, modifying existing features, changing API endpoints, or when the user mentions documentation updates.
---

# Documentation Update Automation

This skill ensures comprehensive documentation updates whenever features are added, modified, or removed from the ParseMyLog-AI project.

## Quick Start

When you add or modify a feature, follow this workflow:

```
Task Progress:
- [ ] Step 1: Identify documentation impact
- [ ] Step 2: Update feature documentation
- [ ] Step 3: Update FEATURES.md catalog
- [ ] Step 4: Update README.md
- [ ] Step 5: Update architecture docs (if needed)
- [ ] Step 6: Validate documentation integrity
```

## Step 1: Identify Documentation Impact

Analyze the code changes to determine what docs need updating:

**Run the impact analyzer:**
```bash
python .cursor/skills/update-docs/scripts/analyze_impact.py
```

This script:
- Scans git diff for changed files
- Identifies affected features
- Lists documentation files to update
- Detects if architecture changes are needed

**Manual assessment if script unavailable:**
- New feature? → Create new feature doc + update catalog
- Modified feature? → Update existing feature doc
- New API endpoint? → Update API_REFERENCE.md
- Changed data flow? → Update ARCHITECTURE.md
- UI changes? → Update screenshots/diagrams

## Step 2: Update Feature Documentation

### For NEW Features

Create a new feature doc in `./docs/features/`:

**Naming convention:**
- Use SCREAMING_SNAKE_CASE
- Be specific: `TELEMETRY_CSV.md` not `EXPORT.md`
- Match feature name in code

**Template structure:**
```markdown
# Feature Name

## Overview
[One paragraph: what problem does this solve?]

## How It Works
[Architecture/pipeline diagram if applicable]

### Components
[List key components with 1-line descriptions]

## Usage

### Basic Usage
[UI mockup or code example]

**API:**
\`\`\`http
POST /api/<endpoint>
Authorization: Bearer <access_token>

{
  "param": "value"
}
\`\`\`

**Response:**
\`\`\`json
{
  "result": "data"
}
\`\`\`

## Key Capabilities
- Bullet point 1
- Bullet point 2

## Configuration
[Environment variables or config files if applicable]

## Implementation Details
[Technical notes for developers]

## Related Features
- [Feature Name](./FEATURE_FILE.md)

## Troubleshooting
[Common issues and solutions]
```

**Real example:** See `docs/features/SEMANTIC_SEARCH.md` for reference

### For MODIFIED Features

1. Read existing feature doc
2. Update only changed sections
3. Keep consistent structure
4. Update "Last Updated" if present
5. Verify all links still work

## Step 3: Update FEATURES.md Catalog

The `docs/FEATURES.md` file is the central catalog. Update it to reflect changes:

**For new features:**

1. Find the appropriate category:
   - Core Analysis Features
   - Multi-CPE Support
   - Pattern Management
   - Advanced Analytics
   - Administration
   - Utilities

2. Add entry using this template:
```markdown
### N. Feature Name

**Description:** One-sentence description of what it does.

**Key Capabilities:**
- Bullet 1
- Bullet 2
- Bullet 3

**Detailed Guide:** [Feature Name](./features/FEATURE_FILE.md)

---
```

3. Update numbering if needed
4. Maintain consistent formatting

**For modified features:**
- Update description if capability changed
- Add/remove key capabilities
- Keep link intact

## Step 4: Update README.md

The README provides high-level overview. Update relevant sections:

### Section: Key Features (lines ~38-75)

Update the feature bullets if:
- New major feature added
- Significant capability change
- Feature removed

**Format:**
```markdown
- **[Feature Name](./docs/features/FEATURE_FILE.md)** -- Brief description with key highlight
```

### Section: Tech Stack (lines ~115-126)

Add new technologies if introduced:
```markdown
| **Layer**            | Technologies |
| **Category**         | New Tool • Existing Tool • ... |
```

### Section: Documentation table (lines ~209-225)

Add new feature doc to the table:
```markdown
| Feature Name         | [FEATURE_FILE.md](./docs/features/FEATURE_FILE.md) |
```

Keep alphabetical order within categories.

## Step 5: Update Architecture Docs (When Needed)

Update `docs/ARCHITECTURE.md` if:
- New service/component added
- Data flow changed
- New database/storage introduced
- Security model changed
- New API layer added

### Common updates:

**System architecture diagram (lines ~15-35):**
```
Update ASCII diagram to show new component
```

**Component descriptions (lines ~40-120):**
```markdown
### New Component Name

**Purpose:** What it does

**Technology:** Framework/library used

**Interactions:**
- Receives data from X
- Sends data to Y
```

**Data flow section (lines ~150-200):**
Add new flows for new features

**API endpoints (lines ~220-280):**
Document new endpoint patterns

## Step 6: Validate Documentation Integrity

**Run the validation script:**
```bash
python .cursor/skills/update-docs/scripts/validate_docs.py
```

This checks:
- All links are valid (no 404s)
- Feature docs are linked in FEATURES.md
- Feature docs are linked in README.md
- Consistent naming conventions
- No orphaned documentation files
- All code references exist

**Fix any errors before committing.**

## Conditional Workflows

### Adding a Major Feature (e.g., new analysis module)

1. Create detailed feature doc in `docs/features/`
2. Add to FEATURES.md catalog
3. Add to README.md Key Features
4. **Update ARCHITECTURE.md** with new component
5. Add to API_REFERENCE.md if it has endpoints
6. Update deployment docs if it needs new dependencies
7. Validate all cross-references

### Modifying Existing Feature

1. Update feature doc in `docs/features/`
2. Update description in FEATURES.md (if capability changed)
3. Update README.md (if it's a key feature)
4. Update ARCHITECTURE.md (only if architectural change)
5. Validate links still work

### Minor Bug Fix or Improvement

1. Update feature doc if behavior changed
2. No need to update FEATURES.md or README.md
3. Validate the specific feature doc

### Removing a Feature

1. Move feature doc to `docs/deprecated/` (create if needed)
2. Remove from FEATURES.md
3. Remove from README.md
4. Add deprecation notice to doc
5. Update ARCHITECTURE.md if it was a component
6. Check for broken links elsewhere

## Documentation Style Guide

### Writing Style
- **Concise**: One idea per sentence
- **Active voice**: "The system processes logs" not "Logs are processed"
- **Present tense**: "Returns results" not "Will return"
- **Second person for UI**: "Click the button" not "The user clicks"
- **Third person for API**: "The endpoint returns" not "You receive"

### Code Examples
- Always include request AND response
- Use real-looking data (not foo/bar)
- Show both success and error cases
- Include authentication headers
- Add comments for non-obvious parts

### Links
- Use relative paths: `./features/FILE.md` not absolute URLs
- Use descriptive link text: `[Semantic Search](...)` not `[click here]`
- Always verify links work after editing

### Formatting
- H1 (`#`) for document title only
- H2 (`##`) for major sections
- H3 (`###`) for subsections
- Code blocks: use language tags (```python, ```json, ```http)
- Inline code: use backticks for file names, functions, parameters

## Utility Scripts

The skill includes three Python scripts:

**analyze_impact.py**: Analyze git diff and determine documentation impact
```bash
python .cursor/skills/update-docs/scripts/analyze_impact.py
# Output: List of files to update with recommendations
```

**validate_docs.py**: Check documentation integrity
```bash
python .cursor/skills/update-docs/scripts/validate_docs.py
# Output: Errors/warnings or "All validations passed"
```

**generate_feature_stub.py**: Generate skeleton for new feature doc
```bash
python .cursor/skills/update-docs/scripts/generate_feature_stub.py "Feature Name"
# Output: Creates docs/features/FEATURE_NAME.md with template
```

## Checklist Before Committing

- [ ] All affected feature docs updated
- [ ] FEATURES.md catalog updated
- [ ] README.md updated (if major feature)
- [ ] ARCHITECTURE.md updated (if structural change)
- [ ] API_REFERENCE.md updated (if new endpoints)
- [ ] All links validated
- [ ] Code examples tested
- [ ] Consistent terminology throughout
- [ ] No spelling errors (use spell checker)
- [ ] Screenshots updated (if UI changed)

## Common Mistakes to Avoid

❌ **Don't** update only code without docs
❌ **Don't** create orphaned feature docs (must be linked)
❌ **Don't** use absolute paths in links
❌ **Don't** leave broken links after refactoring
❌ **Don't** forget to update the Table of Contents
❌ **Don't** use inconsistent naming (PascalCase vs snake_case)
❌ **Don't** skip validation step

✅ **Do** update docs in same commit as code
✅ **Do** test all code examples
✅ **Do** maintain consistent structure
✅ **Do** link related features
✅ **Do** run validation before commit
✅ **Do** follow existing conventions

## Examples

### Example 1: Adding CSV Export to Telemetry

**Changes made:**
- Added `/api/<project_id>/telemetry/<cpe_id>/export/csv` endpoint
- Added export button to UI
- Added CSV generation logic

**Documentation updates:**
1. Created `docs/features/TELEMETRY_CSV.md` with full guide
2. Added to FEATURES.md under "Core Analysis Features"
3. Updated README.md Key Features to mention CSV export
4. Updated `docs/features/TELEMETRY.md` to link to CSV export
5. Added endpoint to API_REFERENCE.md
6. Validated all links

### Example 2: Modifying Semantic Search Algorithm

**Changes made:**
- Switched from BGE-small to BGE-base embeddings
- Changed vector dimensions from 384 to 768
- Updated Qdrant indexing logic

**Documentation updates:**
1. Updated `docs/features/SEMANTIC_SEARCH.md`:
   - Changed embedding model name
   - Updated dimension in pipeline diagram
   - Updated technical implementation section
2. Updated ARCHITECTURE.md data flow diagram
3. Updated README.md tech stack (BGE model version)
4. No changes to FEATURES.md (capability unchanged)
5. Validated all links

### Example 3: Removing deprecated PCAP Analysis

**Changes made:**
- Removed PCAP processing code
- Removed API endpoints

**Documentation updates:**
1. Moved `docs/features/PCAP_ANALYSIS.md` to `docs/deprecated/`
2. Added deprecation notice at top of file
3. Removed from FEATURES.md
4. Removed from README.md
5. Updated ARCHITECTURE.md (removed component)
6. Fixed broken links in related feature docs
7. Validated no other docs reference it

## Additional Resources

- For API documentation standards, see [API_REFERENCE.md](reference.md)
- For diagram creation guidelines, see [diagrams.md](diagrams.md)
- For screenshot guidelines, see [screenshots.md](screenshots.md)

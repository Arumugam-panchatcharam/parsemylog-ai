#!/usr/bin/env python3
"""
Feature Documentation Stub Generator for ParseMyLog-AI

Generates a skeleton feature documentation file following the project template.
"""

import sys
import re
from pathlib import Path
from datetime import datetime

TEMPLATE = """# {feature_name}

## Overview

{feature_name} enables [describe what problem this solves in 1-2 sentences].

## How It Works

### Pipeline Architecture

```
[Add ASCII diagram showing data flow]
Input → Processing → Output
```

### Components

1. **Component 1**
   - Description of what it does
   - Key technology used

2. **Component 2**
   - Description of what it does
   - Key technology used

## Usage

### Basic Usage

**UI:**
```
┌──────────────────────────────────────────────────┐
│ [Feature Interface Description]                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ [Input/controls]                             │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ [Action buttons or results area]                │
└──────────────────────────────────────────────────┘
```

**API:**
```http
POST /api/<project_id>/<endpoint>
Authorization: Bearer <access_token>
Content-Type: application/json

{{{{
  "param1": "value1",
  "param2": "value2"
}}}}
```

**Response:**
```json
{{{{
  "success": true,
  "data": {{{{
    "result": "value"
  }}}}
}}}}
```

### Advanced Usage

[Describe advanced features or parameters]

## Key Capabilities

- **Capability 1** - Brief description
- **Capability 2** - Brief description
- **Capability 3** - Brief description

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VAR_NAME` | `default` | What this controls |

### Configuration Files

[If applicable, describe config files needed]

## Implementation Details

### Backend

- **File:** `api/routes/<filename>.py`
- **Key Functions:**
  - `function_name()` - What it does

### Frontend

- **Component:** `frontend/src/pages/<ComponentName>.tsx`
- **State Management:** [Describe state/context used]

### Database/Storage

- **Collections/Tables:** [List any new collections or tables]
- **Indexes:** [List indexes for performance]

## Related Features

- [Feature Name 1](./FEATURE_FILE_1.md) - How they relate
- [Feature Name 2](./FEATURE_FILE_2.md) - How they relate

## Troubleshooting

### Common Issues

**Issue 1: [Description]**
```
Error message or symptom
```
**Solution:** [How to fix]

**Issue 2: [Description]**
```
Error message or symptom
```
**Solution:** [How to fix]

## Future Enhancements

- [ ] Planned feature 1
- [ ] Planned feature 2

---

*Last Updated: {date}*
"""


def to_screaming_snake_case(text: str) -> str:
    """Convert text to SCREAMING_SNAKE_CASE."""
    # Remove special characters
    text = re.sub(r'[^\w\s-]', '', text)
    # Replace spaces and hyphens with underscores
    text = re.sub(r'[-\s]+', '_', text)
    # Convert to uppercase
    return text.upper()


def generate_stub(feature_name: str, output_dir: Path) -> Path:
    """Generate a feature documentation stub."""
    
    # Convert to proper filename
    filename = to_screaming_snake_case(feature_name) + ".md"
    output_path = output_dir / filename
    
    # Check if file already exists
    if output_path.exists():
        print(f"⚠️  File already exists: {output_path}")
        response = input("Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Aborted.")
            return None
    
    # Generate content
    content = TEMPLATE.format(
        feature_name=feature_name,
        date=datetime.now().strftime("%Y-%m-%d")
    )
    
    # Write file
    output_path.write_text(content, encoding='utf-8')
    
    return output_path


def find_repo_root() -> Path:
    """Find the repository root by looking for .git directory."""
    current = Path.cwd()
    
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    
    return Path.cwd()


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_feature_stub.py \"Feature Name\"")
        print("\nExample:")
        print('  python generate_feature_stub.py "Telemetry CSV Export"')
        sys.exit(1)
    
    feature_name = " ".join(sys.argv[1:])
    
    repo_root = find_repo_root()
    output_dir = repo_root / "docs" / "features"
    
    # Create features directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating feature documentation stub...")
    print(f"Feature: {feature_name}")
    print(f"Output directory: {output_dir}\n")
    
    output_path = generate_stub(feature_name, output_dir)
    
    if output_path:
        print(f"\n✅ Feature documentation stub created:")
        print(f"   {output_path.relative_to(repo_root)}")
        print("\n📝 Next steps:")
        print("   1. Fill in the template sections")
        print("   2. Add to docs/FEATURES.md")
        print("   3. Update README.md (if major feature)")
        print("   4. Run validate_docs.py to check links")


if __name__ == "__main__":
    main()

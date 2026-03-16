#!/usr/bin/env python3
"""
Version Bump Utility

Automatically increments version numbers and updates all version files:
- /VERSION
- frontend/src/config/version.ts
- frontend/package.json

Usage:
    python bump_version.py major    # 1.0.0 -> 2.0.0
    python bump_version.py minor    # 1.0.0 -> 1.1.0
    python bump_version.py patch    # 1.0.0 -> 1.0.1
    python bump_version.py sync     # Sync all files to VERSION file
"""

import os
import re
import sys
import json
from pathlib import Path
from typing import Tuple, Optional


class VersionBumper:
    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            # Auto-detect project root (walk up from script location)
            script_dir = Path(__file__).parent.absolute()
            current = script_dir
            while current != current.parent:
                if (current / "VERSION").exists():
                    project_root = current
                    break
                current = current.parent
            if project_root is None:
                raise FileNotFoundError("Could not find project root with VERSION file")
        
        self.project_root = Path(project_root)
        self.version_file = self.project_root / "VERSION"
        self.version_ts = self.project_root / "frontend" / "src" / "config" / "version.ts"
        self.package_json = self.project_root / "frontend" / "package.json"
        
        # Validate files exist
        if not self.version_file.exists():
            raise FileNotFoundError(f"VERSION file not found at {self.version_file}")
        if not self.version_ts.exists():
            raise FileNotFoundError(f"version.ts not found at {self.version_ts}")
        if not self.package_json.exists():
            raise FileNotFoundError(f"package.json not found at {self.package_json}")
    
    def read_version(self) -> str:
        """Read current version from VERSION file."""
        return self.version_file.read_text().strip()
    
    def parse_version(self, version: str) -> Tuple[int, int, int, str]:
        """
        Parse semantic version string into components.
        
        Returns: (major, minor, patch, suffix)
        Examples:
            "1.0.0" -> (1, 0, 0, "")
            "1.2.3-alpha.1" -> (1, 2, 3, "-alpha.1")
        """
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)(.*)$', version)
        if not match:
            raise ValueError(f"Invalid version format: {version}")
        
        major, minor, patch, suffix = match.groups()
        return int(major), int(minor), int(patch), suffix
    
    def format_version(self, major: int, minor: int, patch: int, suffix: str = "") -> str:
        """Format version components into string."""
        return f"{major}.{minor}.{patch}{suffix}"
    
    def bump_version(self, bump_type: str, current_version: str) -> str:
        """
        Bump version based on type.
        
        Args:
            bump_type: "major", "minor", or "patch"
            current_version: Current version string
            
        Returns:
            New version string
        """
        major, minor, patch, suffix = self.parse_version(current_version)
        
        # Remove pre-release suffix when bumping
        suffix = ""
        
        if bump_type == "major":
            major += 1
            minor = 0
            patch = 0
        elif bump_type == "minor":
            minor += 1
            patch = 0
        elif bump_type == "patch":
            patch += 1
        else:
            raise ValueError(f"Invalid bump type: {bump_type}. Use major, minor, or patch.")
        
        return self.format_version(major, minor, patch, suffix)
    
    def update_version_file(self, new_version: str):
        """Update /VERSION file."""
        self.version_file.write_text(new_version + "\n")
        print(f"✓ Updated {self.version_file.relative_to(self.project_root)}: {new_version}")
    
    def update_version_ts(self, new_version: str):
        """Update frontend/src/config/version.ts."""
        content = self.version_ts.read_text()
        
        # Update APP_VERSION constant
        pattern = r'(export const APP_VERSION = ")[^"]+(")'
        replacement = rf'\g<1>{new_version}\g<2>'
        new_content = re.sub(pattern, replacement, content)
        
        if new_content == content:
            raise RuntimeError("Failed to update APP_VERSION in version.ts")
        
        self.version_ts.write_text(new_content)
        print(f"✓ Updated {self.version_ts.relative_to(self.project_root)}: APP_VERSION = \"{new_version}\"")
    
    def update_package_json(self, new_version: str):
        """Update frontend/package.json."""
        with open(self.package_json, 'r') as f:
            package = json.load(f)
        
        package['version'] = new_version
        
        with open(self.package_json, 'w') as f:
            json.dump(package, f, indent=2)
            f.write('\n')  # Add trailing newline
        
        print(f"✓ Updated {self.package_json.relative_to(self.project_root)}: version = \"{new_version}\"")
    
    def sync_versions(self):
        """Sync all version files to VERSION file (source of truth)."""
        version = self.read_version()
        print(f"Syncing all files to version {version} from VERSION file...")
        
        self.update_version_ts(version)
        self.update_package_json(version)
        
        print(f"\n✓ All files synchronized to version {version}")
    
    def bump_and_update(self, bump_type: str):
        """Bump version and update all files."""
        current_version = self.read_version()
        new_version = self.bump_version(bump_type, current_version)
        
        print(f"Bumping version: {current_version} -> {new_version}")
        print(f"Bump type: {bump_type.upper()}\n")
        
        # Update all three files
        self.update_version_file(new_version)
        self.update_version_ts(new_version)
        self.update_package_json(new_version)
        
        print(f"\n✓ Successfully bumped version to {new_version}")
        print(f"\nNext steps:")
        print(f"  1. Review changes: git diff")
        print(f"  2. Update CHANGELOG.md: python scripts/update_changelog.py")
        print(f"  3. Commit: git add . && git commit -m 'chore: bump version to {new_version}'")
        print(f"  4. Tag: git tag -a v{new_version} -m 'Release version {new_version}'")
        print(f"  5. Push: git push origin HEAD && git push origin v{new_version}")
    
    def verify_versions(self) -> bool:
        """Verify all version files are in sync."""
        version_file_content = self.read_version()
        
        # Check version.ts
        version_ts_content = self.version_ts.read_text()
        version_ts_match = re.search(r'export const APP_VERSION = "([^"]+)"', version_ts_content)
        if not version_ts_match:
            print("✗ Could not find APP_VERSION in version.ts")
            return False
        version_ts_value = version_ts_match.group(1)
        
        # Check package.json
        with open(self.package_json, 'r') as f:
            package = json.load(f)
        version_json_value = package.get('version', '')
        
        # Compare
        all_match = (version_file_content == version_ts_value == version_json_value)
        
        print("Version Check:")
        print(f"  VERSION file:    {version_file_content} {'✓' if version_file_content == version_ts_value == version_json_value else '✗'}")
        print(f"  version.ts:      {version_ts_value} {'✓' if version_ts_value == version_file_content else '✗'}")
        print(f"  package.json:    {version_json_value} {'✓' if version_json_value == version_file_content else '✗'}")
        
        if all_match:
            print(f"\n✓ All versions match: {version_file_content}")
        else:
            print(f"\n✗ Version mismatch detected!")
            print(f"  Run 'python {Path(__file__).name} sync' to fix")
        
        return all_match


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python bump_version.py major    # Bump major version (breaking changes)")
        print("  python bump_version.py minor    # Bump minor version (new features)")
        print("  python bump_version.py patch    # Bump patch version (bug fixes)")
        print("  python bump_version.py sync     # Sync all files to VERSION file")
        print("  python bump_version.py verify   # Check if all versions match")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    try:
        bumper = VersionBumper()
        
        if command in ['major', 'minor', 'patch']:
            bumper.bump_and_update(command)
        elif command == 'sync':
            bumper.sync_versions()
        elif command == 'verify':
            is_synced = bumper.verify_versions()
            sys.exit(0 if is_synced else 1)
        else:
            print(f"Error: Unknown command '{command}'")
            print("Valid commands: major, minor, patch, sync, verify")
            sys.exit(1)
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

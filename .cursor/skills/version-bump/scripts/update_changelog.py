#!/usr/bin/env python3
"""
Changelog Update Utility

Automatically generates CHANGELOG.md entries by analyzing git commits
since the last version tag.

Usage:
    python update_changelog.py              # Generate entry for current version
    python update_changelog.py --dry-run    # Preview without writing
    python update_changelog.py --version 1.1.0  # Specify version explicitly
"""

import os
import re
import sys
import argparse
import subprocess
from pathlib import Path
from datetime import date
from typing import List, Dict, Tuple, Optional
from collections import defaultdict


class ChangelogGenerator:
    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            # Auto-detect project root
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
        self.changelog_file = self.project_root / "CHANGELOG.md"
    
    def read_current_version(self) -> str:
        """Read current version from VERSION file."""
        return self.version_file.read_text().strip()
    
    def get_last_tag(self) -> Optional[str]:
        """Get the most recent git tag."""
        try:
            result = subprocess.run(
                ['git', 'describe', '--tags', '--abbrev=0'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None
    
    def get_commits_since_tag(self, tag: Optional[str] = None) -> List[str]:
        """Get commit messages since the specified tag (or all commits if no tag)."""
        if tag:
            git_range = f"{tag}..HEAD"
        else:
            git_range = "HEAD"
        
        try:
            result = subprocess.run(
                ['git', 'log', git_range, '--oneline', '--no-merges'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True
            )
            return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
        except Exception as e:
            print(f"Warning: Could not get git commits: {e}")
            return []
    
    def categorize_commit(self, commit_message: str) -> Tuple[str, str]:
        """
        Categorize a commit message and extract the description.
        
        Returns: (category, description)
        
        Categories: Added, Changed, Fixed, Deprecated, Removed, Security, Other
        """
        # Remove commit hash (first word)
        parts = commit_message.split(maxsplit=1)
        if len(parts) < 2:
            return "Other", commit_message
        
        message = parts[1]
        message_lower = message.lower()
        
        # Conventional commits format: type(scope): description
        conv_match = re.match(r'^(feat|fix|docs|style|refactor|perf|test|chore|build|ci|revert)(\([^)]+\))?: (.+)$', message)
        if conv_match:
            commit_type = conv_match.group(1)
            description = conv_match.group(3)
            
            if commit_type == 'feat':
                return "Added", description
            elif commit_type == 'fix':
                return "Fixed", description
            elif commit_type in ['refactor', 'perf']:
                return "Changed", description
            elif commit_type == 'revert':
                return "Removed", description
            else:
                # docs, style, test, chore, build, ci -> Other
                return "Other", description
        
        # Keyword-based categorization
        if any(kw in message_lower for kw in ['add', 'new', 'feature', 'implement', 'introduce']):
            category = "Added"
        elif any(kw in message_lower for kw in ['fix', 'bug', 'resolve', 'correct', 'patch']):
            category = "Fixed"
        elif any(kw in message_lower for kw in ['change', 'update', 'improve', 'enhance', 'refactor', 'optimize']):
            category = "Changed"
        elif any(kw in message_lower for kw in ['remove', 'delete', 'drop']):
            category = "Removed"
        elif any(kw in message_lower for kw in ['deprecate', 'obsolete']):
            category = "Deprecated"
        elif any(kw in message_lower for kw in ['security', 'vulnerability', 'cve']):
            category = "Security"
        else:
            category = "Other"
        
        # Clean up description
        description = message
        # Remove "chore:", "docs:", etc. prefixes if present
        description = re.sub(r'^(chore|docs|style|test|build|ci):\s*', '', description, flags=re.IGNORECASE)
        
        return category, description
    
    def generate_changelog_entry(self, version: str, commits: List[str]) -> str:
        """Generate a changelog entry for the given version and commits."""
        today = date.today().isoformat()
        
        # Categorize commits
        categories = defaultdict(list)
        for commit in commits:
            category, description = self.categorize_commit(commit)
            if category != "Other":  # Skip "Other" category
                # Capitalize first letter
                description = description[0].upper() + description[1:] if description else description
                categories[category].append(description)
        
        # Build changelog entry
        entry_lines = [
            f"## [{version}] - {today}",
            ""
        ]
        
        # Category order
        category_order = ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]
        
        for category in category_order:
            if category in categories:
                entry_lines.append(f"### {category}")
                entry_lines.append("")
                for description in categories[category]:
                    entry_lines.append(f"- {description}")
                entry_lines.append("")
        
        # If no categorized commits
        if not categories:
            entry_lines.append("### Changed")
            entry_lines.append("")
            entry_lines.append("- Minor improvements and bug fixes")
            entry_lines.append("")
        
        return "\n".join(entry_lines)
    
    def insert_changelog_entry(self, new_entry: str):
        """Insert new entry into CHANGELOG.md."""
        if not self.changelog_file.exists():
            # Create new CHANGELOG.md
            content = self._create_new_changelog(new_entry)
        else:
            # Insert into existing CHANGELOG.md
            content = self.changelog_file.read_text()
            content = self._insert_entry(content, new_entry)
        
        self.changelog_file.write_text(content)
        print(f"✓ Updated {self.changelog_file.relative_to(self.project_root)}")
    
    def _create_new_changelog(self, first_entry: str) -> str:
        """Create a new CHANGELOG.md with proper header."""
        return f"""# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

{first_entry}
"""
    
    def _insert_entry(self, content: str, new_entry: str) -> str:
        """Insert new entry after [Unreleased] section."""
        # Find [Unreleased] section
        unreleased_pattern = r'(## \[Unreleased\].*?)(\n\n)(## \[|\Z)'
        
        match = re.search(unreleased_pattern, content, re.DOTALL)
        if match:
            # Insert after [Unreleased] section
            before = content[:match.end(2)]
            after = content[match.start(3):]
            return before + new_entry + "\n" + after
        else:
            # No [Unreleased] section, insert at top after header
            header_pattern = r'(# Changelog.*?)(## \[|\Z)'
            match = re.search(header_pattern, content, re.DOTALL)
            if match:
                before = content[:match.end(1)]
                after = content[match.start(2):]
                return before + "\n## [Unreleased]\n\n" + new_entry + "\n" + after
            else:
                # Fallback: prepend to file
                return new_entry + "\n\n" + content
    
    def generate(self, version: Optional[str] = None, dry_run: bool = False):
        """Generate and optionally write changelog entry."""
        if version is None:
            version = self.read_current_version()
        
        print(f"Generating changelog for version {version}...")
        
        # Get commits
        last_tag = self.get_last_tag()
        if last_tag:
            print(f"Analyzing commits since {last_tag}")
        else:
            print("No previous tags found, analyzing all commits")
        
        commits = self.get_commits_since_tag(last_tag)
        
        if not commits:
            print("Warning: No commits found. Using default entry.")
        else:
            print(f"Found {len(commits)} commits to analyze")
        
        # Generate entry
        entry = self.generate_changelog_entry(version, commits)
        
        print("\n" + "="*70)
        print("Generated Changelog Entry:")
        print("="*70)
        print(entry)
        print("="*70)
        
        if dry_run:
            print("\nDry run mode - no files were modified")
            print(f"To apply: python {Path(__file__).name}")
        else:
            # Write to file
            self.insert_changelog_entry(entry)
            print(f"\n✓ Changelog entry added for version {version}")
            print(f"\nPlease review and edit {self.changelog_file.name} to:")
            print("  - Refine descriptions for clarity")
            print("  - Add issue/PR references")
            print("  - Highlight breaking changes")
            print("  - Remove irrelevant entries")


def main():
    parser = argparse.ArgumentParser(
        description="Generate CHANGELOG.md entry from git commits"
    )
    parser.add_argument(
        '--version',
        help='Version number (default: read from VERSION file)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview without writing to file'
    )
    
    args = parser.parse_args()
    
    try:
        generator = ChangelogGenerator()
        generator.generate(version=args.version, dry_run=args.dry_run)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

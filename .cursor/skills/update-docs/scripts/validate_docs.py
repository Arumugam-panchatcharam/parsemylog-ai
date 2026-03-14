#!/usr/bin/env python3
"""
Documentation Validator for ParseMyLog-AI

Validates:
- All markdown links resolve correctly
- Feature docs are properly linked in catalogs
- No orphaned documentation files
- Consistent naming conventions
- Code block syntax
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple

class DocValidator:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.docs_dir = repo_root / "docs"
        self.features_dir = self.docs_dir / "features"
        self.readme = repo_root / "README.md"
        self.errors: List[str] = []
        self.warnings: List[str] = []
        
    def validate_all(self) -> bool:
        """Run all validations. Returns True if no errors."""
        print("🔍 Validating documentation integrity...\n")
        
        self.check_file_existence()
        self.validate_links()
        self.check_feature_catalog()
        self.check_naming_conventions()
        self.check_orphaned_docs()
        self.check_code_blocks()
        
        return self.print_results()
    
    def check_file_existence(self):
        """Verify core documentation files exist."""
        required_files = [
            self.readme,
            self.docs_dir / "FEATURES.md",
            self.docs_dir / "ARCHITECTURE.md",
            self.docs_dir / "QUICK_START.md",
            self.docs_dir / "API_REFERENCE.md",
        ]
        
        for file in required_files:
            if not file.exists():
                self.errors.append(f"Missing required file: {file.relative_to(self.repo_root)}")
    
    def validate_links(self):
        """Check all markdown links resolve to existing files."""
        link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        
        for md_file in self.docs_dir.rglob("*.md"):
            content = md_file.read_text(encoding='utf-8')
            
            for match in link_pattern.finditer(content):
                link_text, link_url = match.groups()
                
                # Skip external URLs
                if link_url.startswith(('http://', 'https://', '#', 'mailto:')):
                    continue
                
                # Resolve relative path
                target = (md_file.parent / link_url).resolve()
                
                if not target.exists():
                    self.errors.append(
                        f"Broken link in {md_file.relative_to(self.repo_root)}: "
                        f"'{link_text}' -> {link_url}"
                    )
        
        # Check README links too
        if self.readme.exists():
            content = self.readme.read_text(encoding='utf-8')
            for match in link_pattern.finditer(content):
                link_text, link_url = match.groups()
                if link_url.startswith(('./docs', 'docs/')):
                    target = (self.repo_root / link_url).resolve()
                    if not target.exists():
                        self.errors.append(
                            f"Broken link in README.md: '{link_text}' -> {link_url}"
                        )
    
    def check_feature_catalog(self):
        """Ensure all feature docs are linked in FEATURES.md."""
        features_md = self.docs_dir / "FEATURES.md"
        
        if not features_md.exists():
            self.errors.append("FEATURES.md not found")
            return
        
        catalog_content = features_md.read_text(encoding='utf-8')
        
        # Find all feature docs
        feature_files = set()
        if self.features_dir.exists():
            for file in self.features_dir.glob("*.md"):
                if file.name != "README.md":
                    feature_files.add(file.name)
        
        # Check each feature is linked
        for feature_file in feature_files:
            if feature_file not in catalog_content:
                self.warnings.append(
                    f"Feature doc exists but not linked in FEATURES.md: {feature_file}"
                )
        
        # Check for broken links in FEATURES.md
        link_pattern = re.compile(r'\]\(\./features/([^)]+)\)')
        for match in link_pattern.finditer(catalog_content):
            linked_file = match.group(1)
            if linked_file not in feature_files and not (self.features_dir / linked_file).exists():
                self.errors.append(
                    f"FEATURES.md links to non-existent file: {linked_file}"
                )
    
    def check_naming_conventions(self):
        """Verify feature docs follow naming conventions."""
        if not self.features_dir.exists():
            return
        
        for file in self.features_dir.glob("*.md"):
            if file.name == "README.md":
                continue
            
            # Check for SCREAMING_SNAKE_CASE
            if not re.match(r'^[A-Z0-9_]+\.md$', file.name):
                self.warnings.append(
                    f"Feature doc not in SCREAMING_SNAKE_CASE: {file.name}"
                )
            
            # Check for vague names
            vague_names = ['HELPER', 'UTILS', 'MISC', 'OTHER', 'TOOL']
            name_without_ext = file.stem
            if name_without_ext in vague_names:
                self.warnings.append(
                    f"Vague feature doc name: {file.name} (be more specific)"
                )
    
    def check_orphaned_docs(self):
        """Find documentation files not linked anywhere."""
        if not self.features_dir.exists():
            return
        
        # Read all markdown files that might contain links
        all_content = ""
        for md_file in self.docs_dir.rglob("*.md"):
            if md_file.parent.name == "features":
                continue  # Don't check feature docs linking each other
            all_content += md_file.read_text(encoding='utf-8')
        
        if self.readme.exists():
            all_content += self.readme.read_text(encoding='utf-8')
        
        # Check each feature doc is referenced
        for file in self.features_dir.glob("*.md"):
            if file.name == "README.md":
                continue
            
            if file.name not in all_content:
                self.warnings.append(
                    f"Orphaned feature doc (not linked in README or FEATURES): {file.name}"
                )
    
    def check_code_blocks(self):
        """Check code blocks have language tags and are properly closed."""
        code_block_pattern = re.compile(r'^```(\w*)\s*$', re.MULTILINE)
        
        for md_file in self.docs_dir.rglob("*.md"):
            content = md_file.read_text(encoding='utf-8')
            
            # Count opening and closing backticks
            blocks = code_block_pattern.findall(content)
            if len(blocks) % 2 != 0:
                self.errors.append(
                    f"Unclosed code block in {md_file.relative_to(self.repo_root)}"
                )
            
            # Check for code blocks without language tags
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                if line.strip() == '```':
                    self.warnings.append(
                        f"Code block without language tag in "
                        f"{md_file.relative_to(self.repo_root)}:{i}"
                    )
    
    def print_results(self) -> bool:
        """Print validation results. Returns True if no errors."""
        print("\n" + "="*60)
        
        if self.errors:
            print(f"❌ {len(self.errors)} ERRORS found:\n")
            for error in self.errors:
                print(f"  ❌ {error}")
            print()
        
        if self.warnings:
            print(f"⚠️  {len(self.warnings)} WARNINGS:\n")
            for warning in self.warnings:
                print(f"  ⚠️  {warning}")
            print()
        
        if not self.errors and not self.warnings:
            print("✅ All validations passed!")
            print("   Documentation integrity verified.")
            return True
        elif not self.errors:
            print("✅ No errors found (warnings only)")
            return True
        else:
            print(f"💥 Validation failed with {len(self.errors)} errors")
            return False
        
        print("="*60)
        return len(self.errors) == 0


def find_repo_root() -> Path:
    """Find the repository root by looking for .git directory."""
    current = Path.cwd()
    
    # First check if we're in the repo
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    
    # If not found, assume current directory
    return Path.cwd()


def main():
    repo_root = find_repo_root()
    
    print(f"Repository root: {repo_root}")
    print(f"Docs directory: {repo_root / 'docs'}\n")
    
    validator = DocValidator(repo_root)
    success = validator.validate_all()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

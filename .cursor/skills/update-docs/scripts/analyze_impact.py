#!/usr/bin/env python3
"""
Documentation Impact Analyzer for ParseMyLog-AI

Analyzes git changes and determines which documentation needs updating.
"""

import subprocess
import re
import sys
from pathlib import Path
from typing import List, Dict, Set

class ImpactAnalyzer:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.changed_files: List[str] = []
        self.impacts: Dict[str, List[str]] = {
            "feature_docs": [],
            "readme": [],
            "features_catalog": [],
            "architecture": [],
            "api_reference": [],
        }
        
    def analyze(self) -> bool:
        """Analyze git changes and determine documentation impact."""
        print("🔍 Analyzing git changes for documentation impact...\n")
        
        if not self.get_changed_files():
            print("⚠️  No git changes detected or not in a git repository")
            return False
        
        print(f"Found {len(self.changed_files)} changed files\n")
        
        self.analyze_changes()
        self.print_recommendations()
        
        return True
    
    def get_changed_files(self) -> bool:
        """Get list of changed files from git."""
        try:
            # Get staged changes
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=True
            )
            staged = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            # Get unstaged changes
            result = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=True
            )
            unstaged = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            # Combine and deduplicate
            self.changed_files = list(set(staged + unstaged))
            self.changed_files = [f for f in self.changed_files if f]  # Remove empty
            
            return len(self.changed_files) > 0
            
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            print("❌ Git not found. Make sure git is installed and in PATH.")
            return False
    
    def analyze_changes(self):
        """Analyze changed files and determine documentation impact."""
        
        # Patterns for different types of changes
        api_patterns = [
            r'api/routes/.*\.py$',
            r'api/.*endpoint.*\.py$',
        ]
        
        frontend_patterns = [
            r'frontend/src/pages/.*\.(tsx|jsx)$',
            r'frontend/src/components/.*\.(tsx|jsx)$',
        ]
        
        backend_logic_patterns = [
            r'logai/.*\.py$',
            r'api/.*\.py$',
        ]
        
        architecture_patterns = [
            r'docker-compose\.yml$',
            r'Dockerfile.*$',
            r'requirements\.txt$',
            r'package\.json$',
            r'.*\.conf$',
            r'nginx/.*$',
        ]
        
        for file in self.changed_files:
            # Determine impact
            
            # API changes always need API reference update
            if any(re.search(pattern, file) for pattern in api_patterns):
                if 'api_reference' not in str(self.impacts['api_reference']):
                    self.impacts['api_reference'].append(
                        "Update API_REFERENCE.md with new/modified endpoints"
                    )
            
            # Feature-specific changes
            feature = self.detect_feature(file)
            if feature:
                doc_file = f"docs/features/{feature}.md"
                if doc_file not in self.impacts['feature_docs']:
                    self.impacts['feature_docs'].append(doc_file)
                
                if feature not in str(self.impacts['features_catalog']):
                    self.impacts['features_catalog'].append(
                        f"Update FEATURES.md entry for {feature}"
                    )
            
            # Frontend changes might need README update (if major UI change)
            if any(re.search(pattern, file) for pattern in frontend_patterns):
                page_name = self.extract_page_name(file)
                if page_name and page_name not in str(self.impacts['readme']):
                    self.impacts['readme'].append(
                        f"Consider updating README.md if {page_name} UI changed significantly"
                    )
            
            # Infrastructure changes need architecture doc update
            if any(re.search(pattern, file) for pattern in architecture_patterns):
                if 'ARCHITECTURE.md' not in str(self.impacts['architecture']):
                    self.impacts['architecture'].append(
                        "Update ARCHITECTURE.md (infrastructure/component change detected)"
                    )
    
    def detect_feature(self, filepath: str) -> str:
        """Detect which feature a file belongs to."""
        feature_map = {
            'telemetry': ['telemetry', 'periodic_report'],
            'SEMANTIC_SEARCH': ['ai-analysis', 'semantic', 'embeddings', 'qdrant'],
            'DRAIN3_PATTERNS': ['drain3', 'patterns', 'template'],
            'LOG_VIEWER': ['log_viewer', 'logs/merged'],
            'FILE_UPLOAD': ['upload', 'extract'],
            'MULTI_CPE': ['cpe', 'multi-cpe'],
            'CPE_OVERVIEW': ['cpe-overview', 'comparison'],
            'NATCO_GOVERNANCE': ['natco', 'governance', 'patterns/sync'],
            'ML_ANOMALY': ['anomaly', 'isolation_forest'],
            'KNOWLEDGE_GRAPH': ['knowledge_graph', 'graph'],
            'BATCH_PROCESSING': ['batch', 'celery'],
            'AI_CHAT': ['chat', 'llm'],
            'USER_MANAGEMENT': ['users', 'admin'],
        }
        
        filepath_lower = filepath.lower()
        
        for feature, keywords in feature_map.items():
            if any(keyword in filepath_lower for keyword in keywords):
                return feature
        
        return None
    
    def extract_page_name(self, filepath: str) -> str:
        """Extract page name from frontend file path."""
        match = re.search(r'pages/(\w+)Page', filepath)
        if match:
            return match.group(1)
        
        match = re.search(r'components/(\w+)', filepath)
        if match:
            return match.group(1)
        
        return None
    
    def print_recommendations(self):
        """Print documentation update recommendations."""
        print("="*60)
        print("📋 DOCUMENTATION UPDATE RECOMMENDATIONS")
        print("="*60 + "\n")
        
        has_impacts = False
        
        if self.impacts['feature_docs']:
            has_impacts = True
            print("📄 FEATURE DOCUMENTATION:")
            for doc in self.impacts['feature_docs']:
                print(f"   • Update/create: {doc}")
            print()
        
        if self.impacts['features_catalog']:
            has_impacts = True
            print("📚 FEATURES CATALOG:")
            for item in self.impacts['features_catalog']:
                print(f"   • {item}")
            print()
        
        if self.impacts['readme']:
            has_impacts = True
            print("📖 README.md:")
            for item in self.impacts['readme']:
                print(f"   • {item}")
            print()
        
        if self.impacts['architecture']:
            has_impacts = True
            print("🏗️  ARCHITECTURE.md:")
            for item in self.impacts['architecture']:
                print(f"   • {item}")
            print()
        
        if self.impacts['api_reference']:
            has_impacts = True
            print("🔌 API_REFERENCE.md:")
            for item in self.impacts['api_reference']:
                print(f"   • {item}")
            print()
        
        if not has_impacts:
            print("✅ No major documentation updates needed")
            print("   (minor code changes detected)")
        
        print("="*60)
        print("\n💡 TIP: Run validate_docs.py after updates to check integrity\n")


def find_repo_root() -> Path:
    """Find the repository root by looking for .git directory."""
    current = Path.cwd()
    
    while current != current.parent:
        if (current / '.git').exists():
            return current
        current = current.parent
    
    return Path.cwd()


def main():
    repo_root = find_repo_root()
    
    print(f"Repository root: {repo_root}\n")
    
    analyzer = ImpactAnalyzer(repo_root)
    analyzer.analyze()


if __name__ == "__main__":
    main()

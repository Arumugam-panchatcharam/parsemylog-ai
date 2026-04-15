"""
RDK-B Module Graph Loader and Utilities

Loads and processes the rdkb_module_graph.yaml file to provide:
- Module to domain mapping
- Cross-domain relationships
- Log hint to module mapping
- Graph traversal utilities
"""

import yaml
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ModuleNode:
    """Represents a module/component in the RDK-B graph."""
    module_id: str
    display_name: str
    description: str
    primary_domains: List[str]
    log_hints: List[str]
    dependencies: List[str] = None
    dependents: List[str] = None
    source: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []
        if self.dependents is None:
            self.dependents = []


class ModuleGraphLoader:
    """Loads and provides access to RDK-B module graph data."""
    
    def __init__(self, yaml_path: str = None):
        if yaml_path is None:
            # Default to the config file in the repo
            yaml_path = Path(__file__).parent.parent.parent / "configs" / "rdkb_module_graph.yaml"
        
        self.yaml_path = Path(yaml_path)
        self.modules: Dict[str, ModuleNode] = {}
        self.domain_to_modules: Dict[str, List[str]] = {}
        self.log_hint_to_modules: Dict[str, List[str]] = {}
        self.version: str = ""
        
        self._load_graph()
    
    def _load_graph(self):
        """Load the module graph from YAML file."""
        try:
            with open(self.yaml_path, 'r') as f:
                data = yaml.safe_load(f)
            
            self.version = str(data.get('version', ''))
            
            # Parse nodes
            for node_data in data.get('nodes', []):
                module = ModuleNode(
                    module_id=node_data['module_id'],
                    display_name=node_data.get('display_name', node_data['module_id']),
                    description=node_data.get('description', ''),
                    primary_domains=node_data.get('primary_domains', []),
                    log_hints=node_data.get('log_hints', []),
                    dependencies=node_data.get('dependencies', []),
                    source=node_data.get('source', {})
                )
                
                self.modules[module.module_id] = module
                
                # Build domain mapping
                for domain in module.primary_domains:
                    if domain not in self.domain_to_modules:
                        self.domain_to_modules[domain] = []
                    self.domain_to_modules[domain].append(module.module_id)
                
                # Build log hint mapping
                for hint in module.log_hints:
                    if hint not in self.log_hint_to_modules:
                        self.log_hint_to_modules[hint] = []
                    self.log_hint_to_modules[hint].append(module.module_id)
            
            # Build reverse dependencies
            for module in self.modules.values():
                for dep_id in module.dependencies:
                    if dep_id in self.modules:
                        self.modules[dep_id].dependents.append(module.module_id)
            
            logger.info(f"Loaded {len(self.modules)} modules from RDK-B graph version {self.version}")
            
        except Exception as e:
            logger.error(f"Failed to load module graph from {self.yaml_path}: {e}")
            raise
    
    def get_module(self, module_id: str) -> Optional[ModuleNode]:
        """Get a module by ID."""
        return self.modules.get(module_id)
    
    def get_modules_for_domain(self, domain: str) -> List[ModuleNode]:
        """Get all modules for a given domain."""
        module_ids = self.domain_to_modules.get(domain, [])
        return [self.modules[mid] for mid in module_ids]
    
    def get_modules_for_log_hint(self, log_hint: str) -> List[ModuleNode]:
        """Get modules that might be related to a log hint."""
        module_ids = self.log_hint_to_modules.get(log_hint, [])
        return [self.modules[mid] for mid in module_ids]
    
    def find_modules_by_hint_partial(self, hint_fragment: str) -> List[ModuleNode]:
        """Find modules by partial log hint matching."""
        matching_modules = []
        hint_fragment_lower = hint_fragment.lower()
        
        for hint, module_ids in self.log_hint_to_modules.items():
            if hint_fragment_lower in hint.lower():
                for mid in module_ids:
                    if self.modules[mid] not in matching_modules:
                        matching_modules.append(self.modules[mid])
        
        return matching_modules
    
    def get_domain_relationships(self) -> Dict[str, Set[str]]:
        """
        Get cross-domain relationships based on module dependencies.
        
        Returns:
            Dictionary mapping each domain to set of related domains
        """
        domain_relations = {}
        
        for domain in self.domain_to_modules:
            related_domains = set()
            modules = self.get_modules_for_domain(domain)
            
            for module in modules:
                # Add domains of dependencies
                for dep_id in module.dependencies:
                    dep_module = self.get_module(dep_id)
                    if dep_module:
                        related_domains.update(dep_module.primary_domains)
                
                # Add domains of dependents
                for dep_id in module.dependents:
                    dep_module = self.get_module(dep_id)
                    if dep_module:
                        related_domains.update(dep_module.primary_domains)
            
            # Remove self
            related_domains.discard(domain)
            domain_relations[domain] = related_domains
        
        return domain_relations
    
    def enrich_domain_data(self, domain: str) -> Dict[str, Any]:
        """
        Enrich domain data with module graph information.
        
        Args:
            domain: Domain name (e.g., "cellular", "wireless")
            
        Returns:
            Dictionary with module information for the domain
        """
        modules = self.get_modules_for_domain(domain)
        
        return {
            "domain": domain,
            "module_count": len(modules),
            "modules": [
                {
                    "module_id": m.module_id,
                    "display_name": m.display_name,
                    "description": m.description,
                    "dependencies": m.dependencies,
                    "dependents": m.dependents
                } for m in modules
            ],
            "related_domains": list(self.get_domain_relationships().get(domain, set())),
            "all_log_hints": [hint for m in modules for hint in m.log_hints]
        }
    
    def get_all_domains(self) -> List[str]:
        """Get list of all domains."""
        return list(self.domain_to_modules.keys())
    
    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        return {
            "version": self.version,
            "total_modules": len(self.modules),
            "total_domains": len(self.domain_to_modules),
            "domains": list(self.domain_to_modules.keys()),
            "modules_per_domain": {
                domain: len(modules) for domain, modules in self.domain_to_modules.items()
            }
        }


# Global instance for easy access
_graph_loader = None

def get_module_graph() -> ModuleGraphLoader:
    """Get the global module graph loader instance."""
    global _graph_loader
    if _graph_loader is None:
        _graph_loader = ModuleGraphLoader()
    return _graph_loader
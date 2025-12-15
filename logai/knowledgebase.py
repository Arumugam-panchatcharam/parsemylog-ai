import os
import time
import json
import pandas as pd
from pathlib import Path
from gui.app_instance import EMBEDDING_MODEL
from logai.qdrant_manager import QdrantManager
from typing import List, Dict, Any, Optional

# ---------- Helpers ----------
def status_file(project_dir: Path) -> Path:
    return Path(project_dir / "status.json")

def read_status(project_dir: Path) -> Dict[str, Any]:
    sf = status_file(project_dir)
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}

def write_status_atomically(project_dir: Path, status_obj: Dict[str, Any]) -> None:
    sf = status_file(project_dir)
    tmp = sf.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status_obj, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(sf))

def update_file_status(project_dir: Path, filename: str, state: str, meta: Optional[Dict[str,Any]] = None):
    """Update status.json for a single file with atomic write."""
    status = read_status(project_dir)
    status.setdefault(filename, {})
    status[filename].update({
        "state": state,
        "timestamp": time.time()
    })
    if meta:
        status[filename].update(meta)
    write_status_atomically(project_dir, status)

class TemplateKnowledgeBase:
    def __init__(self, embedding_dim=768):
        self.qdrant = QdrantManager(embedding_dim=embedding_dim)
        self.model = EMBEDDING_MODEL

    def add_project_templates(self, project_id, templates: List[str], ignore_list: List[str] = [], meanings: Dict[str,str] = {}):
        vectors = self.model.encode(templates, convert_to_numpy=True, normalize_embeddings=True)
        payloads = [{"template": t, "ignored": t in ignore_list, "meaning": meanings.get(t, ""), "frequency": 1} for t in templates]
        self.qdrant.add_templates(project_id, vectors, payloads)

    def suggest_existing_templates(self, templates: List[str], top_k=3):
        vectors = self.model.encode(templates, convert_to_numpy=True, normalize_embeddings=True)
        suggestions = {}
        for tmpl, vec in zip(templates, vectors):
            results = self.qdrant.search_global(vec.tolist(), top_k=top_k)
            if results:
                suggestions[tmpl] = results
        return suggestions

    def get_new_templates_for_user(self, templates: List[str]):
        existing = self.suggest_existing_templates(templates)
        new_templates = [t for t in templates if t not in existing]
        return new_templates
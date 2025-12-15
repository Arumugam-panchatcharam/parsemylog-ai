import os
import time
import faiss
import pandas as pd
import numpy as np
import pickle
import json
from pathlib import Path
from filelock import FileLock
from typing import Dict, Any, Optional
from logai.qdrant_vector_db import QdrantVectorDB

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


# ---------- Main Class ----------
class VectorEmbedding:
    
    COLLECTION_NAME = "templates"

    def __init__(self):
        #self.model_name = MODEL
        self.embeddings = {}
        self.index = None
        self.template_ids = []
        from gui.app_instance import EMBEDDING_MODEL
        self.model = EMBEDDING_MODEL
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        #print(f"Initialized SentenceTransformer")
    
    def _load_result_df(self,file_path):
        if not os.path.exists(file_path):
            return pd.DataFrame()
        return pd.read_parquet(file_path)

    # ---------- Add Templates ----------
    def add_templates(self, project_dir, result_df_path, filename):
        try:
            df = self._load_result_df(result_df_path)
            if 'template' not in df.columns:
                raise ValueError('Parquet must contain "template" column')

            # Unique templates + counts
            dff = df['template'].value_counts().reset_index()
            dff.columns = ['template', 'count']
            templates = dff['template'].astype(str).tolist()

            # Embeddings
            embeddings = self.model.encode(
                templates,
                convert_to_numpy=True,
                normalize_embeddings=True
            ).astype('float32')

            # Initialize ProjectQdrant for this project
            qdr = QdrantVectorDB(
                project_dir=project_dir
            )

            # Ensure collection exists
            qdr.create_collection(
                name=self.COLLECTION_NAME,
                vector_size=self.embedding_dim
            )

            # Build payloads
            payloads = []
            for _, row in dff.iterrows():
                payloads.append({
                    "template": row["template"],
                    "frequency": int(row["count"]),
                    "filename": filename
                })

            # Insert into Qdrant (synchronous)
            qdr.insert(
                collection=self.COLLECTION_NAME,
                embeddings=list(embeddings),
                payloads=payloads
            )

            update_file_status(project_dir, filename, "indexed", {"added": len(templates)})
            #print(f"Added {len(templates)} templates for file {filename}")
            return {"status": "ok", "added": len(templates)}

        except Exception as e:
            update_file_status(project_dir, filename, "error", {"message": str(e)})
            return {"status": "error", "message": str(e)}

    # ---------- Search ----------
    def search(self, project_dir, text, top_k=5):
        qdr = QdrantVectorDB(
            project_dir=project_dir
        )

        q_emb = self.model.encode(
            [text],
            convert_to_numpy=True,
            normalize_embeddings=True
        ).astype("float32")[0]

        query_vector = q_emb.flatten().astype(float).tolist()

        hits = qdr.search(
            collection=self.COLLECTION_NAME,
            embedding=query_vector,
            top_k=top_k
        )
        results = []
        for hit in hits.points:
            payload = hit.payload
            payload["similarity"] = float(hit.score)
            results.append(payload)

        return sorted(results, key=lambda x: x["similarity"], reverse=True)
import os
import time
import faiss
import pandas as pd
import numpy as np
import pickle
import json
from pathlib import Path
from filelock import FileLock
from typing import List, Dict, Any, Optional
import threading
import queue

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
    def __init__(self):
        #self.model_name = MODEL
        self.embeddings = {}
        self.index = None
        self.template_ids = []
        from gui.app_instance import EMBEDDING_MODEL
        self.model = EMBEDDING_MODEL
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        print(f"Initialized SentenceTransformer")
    
    def _load_result_df(self,file_path):
        if not os.path.exists(file_path):
            return pd.DataFrame()
        return pd.read_parquet(file_path)

    def _paths_for_project(self, project_dir):
        d = project_dir
        return {
            'index': os.path.join(d, 'faiss.index'),
            'meta': os.path.join(d, 'meta.pkl'),
            'lock': os.path.join(d, 'faiss.lock')
        }

    def _load_index(self, path):
        if os.path.exists(path):
            try:
                idx = faiss.read_index(path)
                return idx
            except Exception as e:
                # corrupted index -> remove and create new
                print('Failed to read index, removing corrupted file:', e)
                try:
                    os.remove(path)
                except:
                    pass
        # create fresh
        return faiss.IndexFlatIP(self.embedding_dim)

    def _save_index_atomic(self, index, path):
        tmp = path + '.tmp'
        faiss.write_index(index, tmp)
        os.replace(tmp, path)

    def _load_meta(self, path):
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return pickle.load(f)
        return []

    def _save_meta(self, path, meta):
        with open(path, 'wb') as f:
            pickle.dump(meta, f)

    def add_templates(self, project_dir, result_df_path, filename):
        #print("add template ", project_dir)
        paths = self._paths_for_project(project_dir)
        #lock = FileLock(paths['lock'])
        df = self._load_result_df(result_df_path)
        if 'template' not in df.columns:
            raise ValueError('Parquet must contain "template" column')
        
        dff = df['template'].value_counts().reset_index()
        dff.columns = ['template', 'count']
        templates = dff['template'].unique().astype(str).tolist()
        embeddings = self.model.encode(templates, convert_to_numpy=True, normalize_embeddings=True)
        embeddings = np.array(embeddings, dtype='float32')
        #print("acquire lock")
        #with lock:
        index = self._load_index(paths['index'])
        meta = self._load_meta(paths['meta'])
        #print("add embedding")
        # add embeddings
        index.add(embeddings)
        # extend metadata
        for _, row in dff.iterrows():
            m = {
                'template': str(row['template']),
                'frequency': int(row['count']),
                'filename': filename,
            }
            meta.append(m)
        self._save_index_atomic(index, paths['index'])
        self._save_meta(paths['meta'], meta)
        print('added: {0} for filename {1}'.format(len(templates), filename))
        return {'status':'ok', 'added': len(templates)}

    def search(self, project_dir, text, top_k=5):
        paths = self._paths_for_project(project_dir)
        lock = FileLock(paths['lock'])
        qemb = self.model.encode([text], convert_to_numpy=True, normalize_embeddings=True).astype('float32')
        # no need to lock for read index, but ensure safe read
        with lock:
            index = self._load_index(paths['index'])
            meta = self._load_meta(paths['meta'])
            if index.ntotal == 0:
                return []
            k = min(top_k, index.ntotal)
            D, I = index.search(qemb, k)
            #print("vectors ", I[0])
        results = []
        for dist, idx in zip(D[0], I[0]):
            if idx < len(meta):
                m = meta[int(idx)].copy()
                m['similarity'] = float(dist)
                results.append(m)
        results = sorted(results, key=lambda x: x['similarity'], reverse=True)
        return results

# ---------- Scheduler ----------
class FaissScheduler:
    def __init__(self):
        self.queue = queue.Queue()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        self.embedding_model = VectorEmbedding()

    def enqueue_file(self, project_dir, file_path):
        self.queue.put((project_dir, file_path))

    def _worker(self):
        while True:
            project_dir, file_path = self.queue.get()
            try:
                # read parquet, generate embeddings, add to FAISS
                df = pd.read_parquet(file_path)
                self.embedding_model.add_to_faiss(df)
                update_file_status(project_dir, Path(file_path).stem, "indexed")
            except Exception as e:
                update_file_status(project_dir, Path(file_path).stem, "error", {"message": str(e)})
            finally:
                self.queue.task_done()

#faiss_scheduler = FaissScheduler()
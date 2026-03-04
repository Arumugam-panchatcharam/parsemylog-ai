"""
Qdrant Embedding Store Module
==============================

Provides vector storage and semantic similarity search for log patterns
using Qdrant vector database and BGE (BAAI General Embedding) models.

BGE (BAAI General Embedding) is a family of open-source text embedding models
developed by BAAI (Beijing Academy of Artificial Intelligence),
specifically designed for high-quality semantic retrieval in RAG systems.

Key Features:
    - Automatic collection management (create if not exists).
    - BGE embeddings with cosine similarity (384-dim).
    - Template deduplication using content hashing.
    - Batch upsert operations.
    - Semantic similarity search.
    - Per-project collection isolation.

Multi-user / Multi-project Safety:
    - **Shared model**: ``QdrantEmbeddingStore`` accepts a ``shared_model``
      parameter to reuse a pre-loaded SentenceTransformer, avoiding ~700MB
      RAM per concurrent indexer thread.
    - **Per-project collections**: Qdrant collections are named
      ``project_{project_id}`` so different projects never interfere.
    - **Thread-safe status writes**: ``update_file_status()`` uses a
      per-project lock to serialize the read-modify-write cycle on
      ``status.json``.
    - **Atomic file I/O**: ``write_status_atomically()`` uses
      ``os.replace()`` for crash-safe writes.

Architecture:
    Templates (from Drain3)
        -> encode with SentenceTransformer (BAAI/bge-small-en-v1.5)
            -> upsert to Qdrant (deterministic UUIDs via MD5)
                -> search via cosine similarity

Example:
    >>> from logai.embedding import QdrantEmbeddingStore, EmbeddingConfig
    >>>
    >>> config = EmbeddingConfig(
    ...     qdrant_url="http://localhost:6333",
    ...     collection="project_abc123",
    ... )
    >>> store = QdrantEmbeddingStore(config)
    >>>
    >>> templates = [{
    ...     "template": "WiFi client <*> connected to AP <*>",
    ...     "count": 42,
    ...     "filename": "WiFilog.txt",
    ...     "domain": "wireless",
    ... }]
    >>> store.upsert_templates(templates)
    >>>
    >>> hits = store.search("WiFi connection issues", top_k=5)
    >>> for hit in hits:
    ...     print(f"{hit['template']} (similarity: {hit['similarity']:.3f})")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


# ---------- Status helpers (thread-safe, multi-project) ----------
#
# status.json is updated via a per-project lock to make the
# read-modify-write cycle atomic.  Different projects never contend.

import threading as _threading

_status_locks: Dict[str, _threading.Lock] = {}
_status_locks_guard = _threading.Lock()


def _get_status_lock(project_dir: Path) -> _threading.Lock:
    """Get or create a per-project lock for status.json writes."""
    key = str(project_dir)
    with _status_locks_guard:
        if key not in _status_locks:
            _status_locks[key] = _threading.Lock()
        return _status_locks[key]


def status_file(project_dir: Path) -> Path:
    """Return the path to the status.json file for a project."""
    return Path(project_dir / "status.json")


def read_status(project_dir: Path) -> Dict[str, Any]:
    """
    Read the pipeline status file for a project.

    Thread-safe: reads are always consistent because writes use
    atomic ``os.replace``.

    Args:
        project_dir: Project directory containing status.json.

    Returns:
        Dictionary of filename -> status info.
    """
    sf = status_file(project_dir)
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_status_atomically(project_dir: Path, status_obj: Dict[str, Any]) -> None:
    """
    Write status.json atomically (write to tmp, then rename).

    Args:
        project_dir: Project directory for status.json.
        status_obj: Status dictionary to persist.
    """
    sf = status_file(project_dir)
    tmp = sf.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status_obj, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(sf))


def update_file_status(
    project_dir: Path,
    filename: str,
    state: str,
    meta: Optional[Dict[str, Any]] = None,
):
    """
    Update status.json for a single file with atomic write.

    Thread-safe: uses a per-project lock to serialize the
    read-modify-write cycle.  Different projects never contend.

    Args:
        project_dir: Project directory.
        filename: Name of the file being tracked.
        state: New state (queued, parsed, indexed, error).
        meta: Optional extra metadata to attach.
    """
    with _get_status_lock(project_dir):
        status = read_status(project_dir)
        status.setdefault(filename, {})
        status[filename].update({
            "state": state,
            "timestamp": time.time(),
        })
        if meta:
            status[filename].update(meta)
        write_status_atomically(project_dir, status)


# ---------- Embedding Config ----------

@dataclass(frozen=True)
class EmbeddingConfig:
    """
    Configuration for Qdrant embedding store.

    Attributes:
        qdrant_url: URL of Qdrant server (e.g., "http://localhost:6333").
        collection: Name of Qdrant collection to use.
        model_name: HuggingFace model for embeddings (default: BAAI/bge-small-en-v1.5).
                   BGE models are optimized for semantic similarity tasks.
        model_path: Optional local path to pre-downloaded model for offline use.
                   If provided, takes precedence over model_name.

    Example:
        >>> config = EmbeddingConfig(
        ...     qdrant_url="http://localhost:6333",
        ...     collection="project_abc123",
        ...     model_name="BAAI/bge-small-en-v1.5"  # 384-dim embeddings
        ... )
    """
    qdrant_url: str
    collection: str
    model_name: str = "BAAI/bge-small-en-v1.5"
    model_path: Optional[str] = None


# ---------- Embedding Store ----------

class QdrantEmbeddingStore:
    """
    Vector store for log pattern embeddings using Qdrant and BGE models.

    This class handles:
    - Automatic collection creation with cosine similarity.
    - Template embedding generation using BGE (BAAI General Embedding).
    - Deduplication via content-based hashing (MD5 -> UUID).
    - Semantic similarity search.
    - Batch upsert operations.

    The store uses MD5 hashing to generate deterministic UUIDs for templates,
    ensuring idempotent upserts (same template+metadata = same vector point).

    Attributes:
        config: EmbeddingConfig with Qdrant and model settings.
        client: QdrantClient instance for vector operations.
        model: SentenceTransformer for generating embeddings.
        dim: Embedding dimension (384 for bge-small-en-v1.5).

    Example:
        >>> store = QdrantEmbeddingStore(config)
        >>> store.upsert_templates(templates)
        >>> hits = store.search("system error messages", top_k=3)
    """

    def __init__(self, config: EmbeddingConfig, shared_model: "SentenceTransformer | None" = None):
        """
        Initialize the Qdrant embedding store.

        Multi-user safe: if ``shared_model`` is provided, reuses the
        pre-loaded SentenceTransformer instead of loading a new one.
        This saves ~700MB RAM per concurrent indexer thread.

        This will:
        1. Connect to Qdrant server.
        2. Reuse shared_model or load a new embedding model.
        3. Warmup the model with a dummy encoding (only for new models).
        4. Create collection if it doesn't exist.

        Args:
            config: EmbeddingConfig with connection and model settings.
            shared_model: Optional pre-loaded SentenceTransformer instance.
                         When provided, skips model loading entirely.
                         This is the recommended approach for multi-user
                         deployments to avoid memory explosion.

        Raises:
            ConnectionError: If Qdrant server is unreachable.
            RuntimeError: If model loading fails.
        """
        self.config = config
        self.client = QdrantClient(url=config.qdrant_url)

        if shared_model is not None:
            # Reuse the pre-loaded model (multi-user safe, saves memory)
            self.model = shared_model
            self.dim = self.model.get_sentence_embedding_dimension()
            logger.info(
                f"[QdrantEmbeddingStore] Reusing shared model "
                f"(dim={self.dim}, collection='{config.collection}')"
            )
        else:
            # Load a new model instance (standalone / first-time init)
            model_location = (
                config.model_path
                or os.environ.get("EMBEDDING_MODEL_PATH")
                or config.model_name
            )

            if config.model_path:
                logger.info(f"[QdrantEmbeddingStore] Loading model from config path: {model_location}")
            elif os.environ.get("EMBEDDING_MODEL_PATH"):
                logger.info(f"[QdrantEmbeddingStore] Loading model from EMBEDDING_MODEL_PATH: {model_location}")
            else:
                logger.info(f"[QdrantEmbeddingStore] Loading model from HuggingFace: {model_location}")

            # Force CPU device to prevent MPS crashes in forked processes (Celery workers on macOS)
            # MPS (Metal Performance Shaders) doesn't work with fork-based multiprocessing
            device = "cpu"
            logger.info(f"[QdrantEmbeddingStore] Loading model with device={device}")
            self.model = SentenceTransformer(model_location, device=device)
            self.dim = self.model.get_sentence_embedding_dimension()

            # Warmup: Force model to fully load by encoding a dummy string
            logger.info("[QdrantEmbeddingStore] Warming up model...")
            _ = self.model.encode(["warmup test"], normalize_embeddings=True)

        # Ensure collection exists
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """
        Ensure the Qdrant collection exists, create if missing.

        Collection is configured with:
        - Vector size: Model embedding dimension (e.g., 384 for bge-small-en-v1.5).
        - Distance metric: COSINE (for semantic similarity).

        This is idempotent - safe to call multiple times.
        """
        collections = self.client.get_collections().collections
        if any(c.name == self.config.collection for c in collections):
            logger.debug(f"[QdrantEmbeddingStore] Collection '{self.config.collection}' already exists")
            return

        logger.info(f"[QdrantEmbeddingStore] Creating collection '{self.config.collection}' with dim={self.dim}")
        self.client.create_collection(
            collection_name=self.config.collection,
            vectors_config=qdrant_models.VectorParams(
                size=self.dim,
                distance=qdrant_models.Distance.COSINE,
            ),
        )

    def _point_id(self, template: str, filename: str, domain: str) -> str:
        """
        Generate a deterministic UUID for a template based on its content.

        This ensures idempotent upserts - the same template from the same
        source will always have the same ID, preventing duplicates.

        Args:
            template: Log pattern template (e.g., "Error <*> at line <*>").
            filename: Source log filename.
            domain: Log domain (wireless, platform, etc.).

        Returns:
            UUID string derived from MD5 hash of concatenated fields.
        """
        key = f"{template}|{filename}|{domain}"
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        return str(uuid.UUID(digest))

    def upsert_templates(self, templates: List[Dict[str, Any]], extra_metadata: Optional[Dict[str, Any]] = None) -> int:
        """
        Upsert log pattern templates with their embeddings to Qdrant.

        This operation is idempotent - upserting the same template multiple
        times will update the existing point rather than creating duplicates.

        Process:
        1. Generate embeddings for all templates (batched).
        2. Create deterministic UUIDs for deduplication.
        3. Prepare point structures with vectors and metadata.
        4. Upsert to Qdrant (insert or update).

        Args:
            templates: List of template dictionaries, each containing:
                - template (str): Log pattern with <*> placeholders (required).
                - filename (str): Source log filename (required).
                - domain (str): Log domain (e.g., "wireless") (required).
                - count (int): Occurrence count (optional, default: 0).
                - parquet_path (str): Path to cached parquet file (optional).
            extra_metadata: Optional additional metadata to attach to all vectors
                          (e.g., {"cpe_serial": "CP2318ADA7F"} for multi-CPE projects).

        Returns:
            Number of points upserted.
        """
        if not templates:
            logger.debug("[QdrantEmbeddingStore] No templates to upsert")
            return 0

        extra_metadata = extra_metadata or {}

        # Extract template texts for batch embedding
        logger.debug(f"[QdrantEmbeddingStore] Encoding {len(templates)} templates")
        texts = [t["template"] for t in templates]

        embeddings = self.model.encode(texts, normalize_embeddings=True)

        # Prepare Qdrant points with deterministic IDs and metadata
        points = []
        for template, vector in zip(templates, embeddings):
            # Generate deterministic UUID for idempotent upserts
            point_id = self._point_id(
                template["template"],
                template["filename"],
                template.get("domain", ""),
            )

            # Prepare metadata payload (merge extra_metadata)
            payload = {
                "template": template["template"],
                "count": template.get("count", 0),
                "filename": template["filename"],
                "domain": template.get("domain", ""),
                "parquet_path": template.get("parquet_path", ""),
                "source": template.get("source", ""),
                "rg_context": template.get("rg_context", {}),
                **extra_metadata,  # Merge extra metadata (e.g., cpe_serial)
            }

            points.append(
                qdrant_models.PointStruct(
                    id=point_id,
                    vector=vector.tolist(),
                    payload=payload,
                )
            )

        # Upsert to Qdrant (idempotent operation)
        logger.info(f"[QdrantEmbeddingStore] Upserting {len(points)} points to '{self.config.collection}'")
        self.client.upsert(collection_name=self.config.collection, points=points)

        return len(points)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search for log patterns semantically similar to the query.

        Uses cosine similarity between query embedding and stored template
        embeddings. Results are ranked by similarity score (1.0 = identical).

        Args:
            query: Natural language or template query
                  (e.g., "WiFi connection issues").
            top_k: Maximum number of results to return (default: 5).

        Returns:
            List of matching templates with metadata, sorted by similarity
            (highest first). Each result dict contains:
                - template, count, filename, domain, parquet_path, similarity.

        Example:
            >>> hits = store.search("WiFi disconnection problems", top_k=3)
            >>> for hit in hits:
            ...     print(f"Template: {hit['template']}")
            ...     print(f"Similarity: {hit['similarity']:.3f}")
        """
        # Generate query embedding (normalized for cosine similarity)
        query_vec = self.model.encode([query], normalize_embeddings=True)[0]

        # Search Qdrant
        results = self.client.query_points(
            collection_name=self.config.collection,
            query=query_vec.tolist(),
            limit=top_k,
        )

        # Format results with similarity scores
        hits: List[Dict[str, Any]] = []
        for res in results.points:
            payload = res.payload or {}
            payload["similarity"] = float(res.score)
            hits.append(payload)

        logger.debug(
            f"[QdrantEmbeddingStore] Search returned {len(hits)} results"
        )

        return hits

    def delete_collection(self) -> None:
        """
        Delete the current collection from Qdrant.

        Use with caution - this removes all indexed data for this collection.
        """
        try:
            self.client.delete_collection(self.config.collection)
            logger.info(f"[QdrantEmbeddingStore] Deleted collection '{self.config.collection}'")
        except Exception as e:
            logger.warning(f"[QdrantEmbeddingStore] Failed to delete collection: {e}")

    def collection_info(self) -> Dict[str, Any]:
        """
        Get information about the current collection.

        Returns:
            Dictionary with collection stats (point count, etc.).
        """
        try:
            info = self.client.get_collection(self.config.collection)
            return {
                "name": self.config.collection,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": str(info.status),
            }
        except Exception as e:
            return {"error": str(e)}


def quick_search(
    query: str,
    collection: str,
    model: "SentenceTransformer",
    qdrant_url: str = "http://localhost:6333",
    top_k: int = 10,
    metadata_filter: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Lightweight search that reuses an already-loaded SentenceTransformer model.

    This avoids the expensive model load + warmup that QdrantEmbeddingStore.__init__
    performs.  Use this for interactive search callbacks where latency matters.

    Args:
        query: Natural language search query.
        collection: Qdrant collection name (e.g., "project_{id}").
        model: Pre-loaded SentenceTransformer instance.
        qdrant_url: Qdrant server URL.
        top_k: Maximum results to return.
        metadata_filter: Optional dict to filter by metadata (e.g., {"cpe_serial": "ABC123"}).

    Returns:
        List of result dicts with template metadata and similarity score.
    """
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    
    client = QdrantClient(url=qdrant_url)
    query_vec = model.encode([query], normalize_embeddings=True)[0]

    # Build filter if metadata_filter is provided
    query_filter = None
    if metadata_filter:
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in metadata_filter.items()
        ]
        query_filter = Filter(must=conditions)

    results = client.query_points(
        collection_name=collection,
        query=query_vec.tolist(),
        limit=top_k,
        query_filter=query_filter,
    )

    hits: List[Dict[str, Any]] = []
    for res in results.points:
        payload = res.payload or {}
        payload["similarity"] = float(res.score)
        hits.append(payload)

    return hits

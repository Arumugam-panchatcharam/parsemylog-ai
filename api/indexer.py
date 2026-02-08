"""
API Indexer Module
===================

Self-contained background indexer for the API layer.

Replicates the per-project locking, active-tracking, and async
indexer logic from gui/callbacks/log_viewer.py -- but without
importing anything from the gui/ package (which would create a
second DBManager and crash SQLAlchemy).

Only imports from logai/ (processing) and api.app (lazy model).
"""

import time
import threading
import logging
from pathlib import Path

from logai.utils.constants import (
    NON_TEXT_EXTENSIONS,
    IGNORE_FILENAME_LIST,
    QDRANT_URL,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-project locking + active tracking (thread-safe)
# ---------------------------------------------------------------------------
_indexing_locks: dict = {}              # project_id -> threading.Lock
_indexing_locks_guard = threading.Lock()

_active_indexing: set = set()           # project_ids currently indexing
_active_guard = threading.Lock()


def _get_project_lock(project_id: str) -> threading.Lock:
    """Get or create the per-project indexing lock (thread-safe)."""
    with _indexing_locks_guard:
        if project_id not in _indexing_locks:
            _indexing_locks[project_id] = threading.Lock()
        return _indexing_locks[project_id]


def is_indexing(project_id: str) -> bool:
    """Check if an indexer thread is currently running for a project."""
    with _active_guard:
        return project_id in _active_indexing


# ---------------------------------------------------------------------------
# Collect scannable text files
# ---------------------------------------------------------------------------

def _collect_text_files(project_dir: Path) -> list:
    """
    Collect all text-type log files in the project directory.

    Excludes non-text files, parquet caches, status files, and
    ignored filenames.
    """
    text_files = []
    if not project_dir.exists():
        logger.warning(f"[CollectFiles] Directory does not exist: {project_dir}")
        return text_files

    for f in project_dir.iterdir():
        if not f.is_file():
            continue
        if any(f.name.endswith(ext) for ext in NON_TEXT_EXTENSIONS):
            continue
        if f.suffix in ('.parquet', '.json', '.tmp'):
            continue
        if any(ign.lower() in f.name.lower() for ign in IGNORE_FILENAME_LIST):
            continue
        if f.stat().st_size == 0:
            continue
        text_files.append(f)

    logger.info(f"[CollectFiles] Found {len(text_files)} text files in {project_dir}")
    return text_files


# ---------------------------------------------------------------------------
# Async indexer
# ---------------------------------------------------------------------------

def run_indexer_async(project_dir: Path, project_id: str, domains=None):
    """
    Run the rg+Drain3 domain-based indexer in a background thread.

    Multi-user safe: uses a per-project lock so different projects can
    index in parallel but the same project never has two concurrent
    indexer threads.

    Uses the lazy-loaded embedding model from api.app (not gui.app_instance).
    """
    lock = _get_project_lock(project_id)
    if not lock.acquire(blocking=False):
        logger.info(
            f"[AsyncIndexer] Skipping -- indexer already running for project {project_id}"
        )
        return

    with _active_guard:
        _active_indexing.add(project_id)

    t0 = time.perf_counter()
    try:
        label = f"domains={domains}" if domains else "all domains"
        logger.info(f"[AsyncIndexer] Starting indexing ({label}) for project {project_id}")

        file_paths = _collect_text_files(project_dir)
        logger.info(f"[AsyncIndexer] Found {len(file_paths)} text files to scan")

        if not file_paths:
            logger.warning(f"[AsyncIndexer] No text files found in {project_dir}")
            return

        # Lazy-load the shared embedding model from the API layer
        from api.app import get_embedding_model
        try:
            shared_model = get_embedding_model()
        except Exception as e:
            logger.warning(f"[AsyncIndexer] Could not load embedding model: {e}")
            shared_model = None

        from logai.indexer import RagIndexer

        indexer = RagIndexer(
            project_dir=project_dir,
            qdrant_url=QDRANT_URL,
            collection_name=f"project_{project_id}",
            shared_model=shared_model,
        )
        counts = indexer.index_all_domains(
            log_dir=project_dir,
            file_paths=file_paths,
            domains=domains,
        )
        elapsed = time.perf_counter() - t0
        logger.info(f"[AsyncIndexer] Completed in {elapsed:.1f}s: {counts}")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.error(f"[AsyncIndexer] Error after {elapsed:.1f}s: {e}")
    finally:
        lock.release()
        with _active_guard:
            _active_indexing.discard(project_id)


def launch_async_indexer(project_dir: Path, project_id: str, domains=None):
    """Launch the indexer in a daemon thread."""
    logger.info(f"[Upload] Launching async indexer for project {project_id}")
    t = threading.Thread(
        target=run_indexer_async,
        args=(project_dir, project_id, domains),
        daemon=True,
    )
    t.start()

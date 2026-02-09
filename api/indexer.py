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


def is_indexing(project_id: str, cpe_id: str = None) -> bool:
    """Check if an indexer thread is currently running for a project (or project+CPE)."""
    key = _make_lock_key(project_id, cpe_id)
    with _active_guard:
        return key in _active_indexing


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

def _make_lock_key(project_id: str, cpe_id: str = None) -> str:
    """Build a unique lock key for project or project+cpe."""
    if cpe_id:
        return f"{project_id}__cpe__{cpe_id}"
    return project_id


def run_indexer_async(project_dir: Path, project_id: str, domains=None, cpe_id: str = None):
    """
    Run the rg+Drain3 domain-based indexer in a background thread.

    Multi-user safe: uses a per-project lock so different projects can
    index in parallel but the same project never has two concurrent
    indexer threads.

    When cpe_id is provided:
      - Scans files inside project_dir (should already point to the CPE subdir)
      - Uses Qdrant collection ``project_{project_id}_cpe_{cpe_id}``

    Uses the lazy-loaded embedding model from api.app (not gui.app_instance).
    """
    lock_key = _make_lock_key(project_id, cpe_id)
    lock = _get_project_lock(lock_key)
    if not lock.acquire(blocking=False):
        logger.info(
            f"[AsyncIndexer] Skipping -- indexer already running for {lock_key}"
        )
        return

    with _active_guard:
        _active_indexing.add(lock_key)

    t0 = time.perf_counter()
    try:
        label = f"domains={domains}" if domains else "all domains"
        cpe_label = f" cpe={cpe_id}" if cpe_id else ""
        logger.info(f"[AsyncIndexer] Starting indexing ({label}{cpe_label}) for project {project_id}")

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

        # Per-CPE or per-project Qdrant collection
        if cpe_id:
            collection_name = f"project_{project_id}_cpe_{cpe_id}"
        else:
            collection_name = f"project_{project_id}"

        indexer = RagIndexer(
            project_dir=project_dir,
            qdrant_url=QDRANT_URL,
            collection_name=collection_name,
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
            _active_indexing.discard(lock_key)


def launch_async_indexer(project_dir: Path, project_id: str, domains=None, cpe_id: str = None):
    """Launch the indexer in a daemon thread."""
    cpe_label = f" cpe={cpe_id}" if cpe_id else ""
    logger.info(f"[Upload] Launching async indexer for project {project_id}{cpe_label}")
    t = threading.Thread(
        target=run_indexer_async,
        args=(project_dir, project_id, domains, cpe_id),
        daemon=True,
    )
    t.start()


def _run_batch_sequential(batch: list):
    """
    Process a batch of CPE indexing jobs sequentially in a single thread.

    This avoids concurrent access to the shared SentenceTransformer model,
    prevents I/O contention from parallel ripgrep processes, and eliminates
    the risk of Qdrant upsert timeouts under heavy load.

    All CPE lock keys are pre-registered in _active_indexing so the
    frontend's ``is_indexing()`` poll returns True for queued CPEs too
    (not just the one currently being processed).

    Args:
        batch: List of tuples (project_dir: Path, project_id: str, cpe_id: str).
    """
    total = len(batch)
    logger.info(f"[BatchIndexer] Starting sequential indexing of {total} CPE(s)")

    # Pre-register ALL CPEs as active so frontend polling shows them
    # as "indexing" even while waiting in the queue.
    all_keys = []
    for project_dir, project_id, cpe_id in batch:
        key = _make_lock_key(project_id, cpe_id)
        all_keys.append(key)
    with _active_guard:
        _active_indexing.update(all_keys)

    for idx, (project_dir, project_id, cpe_id) in enumerate(batch, 1):
        key = _make_lock_key(project_id, cpe_id)
        logger.info(f"[BatchIndexer] [{idx}/{total}] Indexing CPE {cpe_id}")
        try:
            run_indexer_async(project_dir, project_id, domains=None, cpe_id=cpe_id)
        finally:
            # run_indexer_async already removes the key from _active_indexing
            # in its finally block, so no extra cleanup needed here.
            pass

    # Safety: ensure no stale keys remain if run_indexer_async skipped any
    with _active_guard:
        for key in all_keys:
            _active_indexing.discard(key)

    logger.info(f"[BatchIndexer] Completed all {total} CPE(s)")


def launch_async_indexer_batch(batch: list):
    """
    Launch a single daemon thread that indexes multiple CPEs sequentially.

    Use this instead of calling launch_async_indexer() in a loop, which
    would spawn one thread per CPE and risk:
      - Shared SentenceTransformer model corruption (not thread-safe)
      - I/O contention from parallel ripgrep subprocesses
      - Qdrant upsert timeouts under concurrent writes

    Args:
        batch: List of tuples (project_dir: Path, project_id: str, cpe_id: str).
    """
    if not batch:
        return
    if len(batch) == 1:
        # Single CPE -- just launch normally
        project_dir, project_id, cpe_id = batch[0]
        launch_async_indexer(project_dir, project_id, cpe_id=cpe_id)
        return

    logger.info(
        f"[Upload] Launching sequential batch indexer for "
        f"{len(batch)} CPE(s): {[b[2] for b in batch]}"
    )
    t = threading.Thread(
        target=_run_batch_sequential,
        args=(batch,),
        daemon=True,
    )
    t.start()

"""
RAG Indexer Module -- rg+Drain3 Two-Stage Pipeline
===================================================

Indexes RDK log files using a sequential three-stage pipeline:
1. ripgrep pre-filtering (fast, native speed scan for error-class lines).
2. Drain3 template extraction (only on filtered lines -- 6-10x faster).
3. Qdrant vector storage (BGE embeddings for semantic search).

The indexer replaces the old parallel ProcessPoolExecutor approach with
a single-threaded sequential pipeline that leverages ripgrep's speed to
make parallelism unnecessary.

Multi-user / Multi-project Safety
-----------------------------------
Each ``RagIndexer`` instance is fully isolated:

- **File paths**: Per-user/per-project directories (``user_uploads/{uid}/{pid}``).
- **Drain3 state**: Per-project AND per-domain state files
  (``drain3_{domain}.json``).  No cross-project leakage.
- **Qdrant collections**: Per-project collection names
  (``project_{project_id}``).
- **Embedding model**: Accepts a ``shared_model`` parameter to reuse
  the globally pre-loaded SentenceTransformer, avoiding ~700MB RAM
  per concurrent indexer thread.
- **Parquet caches**: Atomic writes via ``os.replace()`` prevent
  partial reads.

Concurrency is managed externally by the per-project lock in
``gui.callbacks.log_viewer._run_indexer_async`` -- only one indexer
thread may run per project, but different projects index in parallel.

Pipeline:
    rg_scanner.scan_domain(log_dir, domain)
        --> Drain3 template extraction (per-domain state)
            --> embed + upsert to Qdrant

Example:
    >>> from logai.indexer import RagIndexer
    >>> from pathlib import Path
    >>>
    >>> indexer = RagIndexer(
    ...     project_dir=Path("user_uploads/1/proj123"),
    ...     qdrant_url="http://localhost:6333",
    ... )
    >>> counts = indexer.index_all_domains(
    ...     log_dir=Path("user_uploads/1/proj123/merged_logs"),
    ... )
    >>> print(f"Indexed: {counts}")
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from logai.embedding import (
    QdrantEmbeddingStore,
    EmbeddingConfig,
    update_file_status,
)
from logai.pattern import Pattern
from logai.rg_scanner import RgScanner, RgMatch, check_rg_available
from logai.utils.constants import (
    BASE_DIR,
    NON_TEXT_EXTENSIONS,
    IGNORE_FILENAME_LIST,
)

logger = logging.getLogger(__name__)

# Default path to rg pattern configs (relative to project root)
DEFAULT_RG_PATTERNS_DIR = Path(BASE_DIR) / "configs" / "rg_patterns"


class RagIndexer:
    """
    RAG indexer using the rg+Drain3 two-stage pipeline.

    Replaces the old PatternScheduler (parallel ProcessPoolExecutor) with
    a sequential pipeline that is faster thanks to ripgrep pre-filtering.

    Pipeline per domain:
        rg_scanner.scan_domain(log_dir, domain)
            --> Pattern.parse_lines(filtered_lines)
                --> QdrantEmbeddingStore.upsert_templates()

    Attributes:
        project_dir: Project directory for caches and state.
        rg_scanner: Ripgrep scanner with loaded domain patterns.
        embed_store: Qdrant embedding store for vector operations.

    Example:
        >>> indexer = RagIndexer(
        ...     project_dir=Path("uploads/user1/proj1"),
        ...     qdrant_url="http://localhost:6333",
        ... )
        >>> counts = indexer.index_all_domains(log_dir)
    """

    def __init__(
        self,
        project_dir: Path,
        qdrant_url: str = "http://localhost:6333",
        collection_name: Optional[str] = None,
        rg_patterns_dir: Optional[Path] = None,
        model_path: Optional[str] = None,
        shared_model: Optional[Any] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the RAG indexer.

        Multi-user safe: when ``shared_model`` is provided, the embedding
        store reuses the pre-loaded SentenceTransformer instead of loading
        a new 700MB+ model per indexer thread.

        Args:
            project_dir: Project directory for Drain3 state and parquet caches.
            qdrant_url: Qdrant server URL (default: http://localhost:6333).
            collection_name: Qdrant collection name. If None, derives from
                           project_dir name.
            rg_patterns_dir: Directory with rg pattern YAML files. Defaults to
                           configs/rg_patterns/ in project root.
            model_path: Optional local path for the embedding model.
            shared_model: Optional pre-loaded SentenceTransformer instance.
                        Strongly recommended for multi-user deployments.
            extra_metadata: Optional metadata dict to attach to all indexed vectors
                          (e.g., {"cpe_serial": "CP2318ADA7F"} for multi-CPE projects).

        Raises:
            RuntimeError: If ripgrep binary is not available.
        """
        self.project_dir = project_dir
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.extra_metadata = extra_metadata or {}

        # Derive collection name from project directory if not specified
        if collection_name is None:
            collection_name = f"project_{project_dir.name}"

        # Initialize RgScanner
        patterns_dir = rg_patterns_dir or DEFAULT_RG_PATTERNS_DIR
        if not check_rg_available():
            raise RuntimeError(
                "ripgrep binary 'rg' not found. "
                "Install ripgrep: apt-get install ripgrep (Debian/Ubuntu), "
                "brew install ripgrep (macOS)"
            )

        self.rg_scanner = RgScanner(
            pattern_config_dir=patterns_dir,
        )
        logger.info(
            f"[RagIndexer] RgScanner initialized: "
            f"{self.rg_scanner.get_available_domains()} domains"
        )

        # Initialize Qdrant embedding store (reuse shared model if available)
        self.embed_store = QdrantEmbeddingStore(
            EmbeddingConfig(
                qdrant_url=qdrant_url,
                collection=collection_name,
                model_path=model_path,
            ),
            shared_model=shared_model,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_all_domains(
        self,
        log_dir: Path,
        domains: Optional[List[str]] = None,
        file_paths: Optional[List[Path]] = None,
    ) -> Dict[str, int]:
        """
        Index logs for all (or specified) domains using rg+Drain3 pipeline.

        For each domain:
        1. Filter files to only those whose name matches the domain's
           file glob patterns from the YAML config.
        2. rg_scanner.scan_files() or scan_domain() -- ripgrep pre-filter.
        3. Pattern.parse_lines(matched_lines) -- Drain3 templates.
        4. QdrantEmbeddingStore.upsert_templates() -- embed + store.

        Args:
            log_dir: Directory containing the merged log files.
            domains: Domain names to index. If None, indexes all available.
            file_paths: Optional explicit list of file paths to scan.
                       When provided, files are filtered per domain using
                       the domain's file glob patterns from YAML config.

        Returns:
            Dict mapping domain name to number of templates indexed.
        """
        available = self.rg_scanner.get_available_domains()
        target_domains = domains or available

        logger.info(
            f"[RagIndexer] Starting indexing: log_dir={log_dir}, "
            f"domains={target_domains}, explicit_files={len(file_paths) if file_paths else 0}"
        )

        indexed_counts: Dict[str, int] = {}

        for domain in target_domains:
            if domain not in available:
                logger.warning(f"[RagIndexer] No rg patterns for domain: {domain}")
                indexed_counts[domain] = 0
                continue

            # Filter files so each domain only scans those whose name
            # matches the domain's file glob patterns from YAML config.
            domain_files = file_paths
            if file_paths:
                domain_files = self._filter_files_for_domain(
                    file_paths, domain
                )
                if not domain_files:
                    logger.info(
                        f"[RagIndexer] No files match domain '{domain}' "
                        f"file globs -- skipping"
                    )
                    # Write empty marker parquet so resume logic doesn't
                    # keep retrying this domain endlessly.
                    self._write_empty_parquet(domain)
                    indexed_counts[domain] = 0
                    continue

            count = self._index_domain(log_dir, domain, file_paths=domain_files)
            indexed_counts[domain] = count

        logger.info(
            f"[RagIndexer] Indexing complete. Counts by domain: {indexed_counts}"
        )
        return indexed_counts

    def index_files_sequential(
        self,
        files: list,
    ) -> Dict[str, str]:
        """
        Index individual files sequentially (non-rg path).

        This is the replacement for PatternScheduler.schedule_files().
        It processes each file through Drain3 and upserts to Qdrant.

        Args:
            files: List of tuples (filename, file_path, original_name, file_size, _)
                  as returned by dbm.get_project_files().

        Returns:
            Dict mapping original_name -> status ("indexed" or "error").
        """
        results = {}

        for filename, file_path, original_name, file_size, _ in files:
            if not os.path.exists(file_path) or not os.path.getsize(file_path):
                continue
            if any(filename.endswith(ext) for ext in NON_TEXT_EXTENSIONS):
                continue
            if any(ign.lower() in original_name.lower() for ign in IGNORE_FILENAME_LIST):
                continue

            result_path = Path(file_path + ".parquet")
            if result_path.exists():
                results[original_name] = "parsed"
                continue

            try:
                # Parse with Drain3
                update_file_status(self.project_dir, original_name, "queued")
                parser = Pattern(project_dir=self.project_dir)
                result_df, result_df_path = parser.parse_logs(file_path)

                if result_df is not None and not result_df.empty and result_df_path:
                    update_file_status(self.project_dir, original_name, "parsed")

                    # Extract templates and upsert to Qdrant
                    template_counts = result_df['template'].value_counts().reset_index()
                    template_counts.columns = ['template', 'count']

                    templates = []
                    for _, row in template_counts.iterrows():
                        templates.append({
                            "template": str(row["template"]),
                            "count": int(row["count"]),
                            "filename": original_name,
                            "domain": "general",
                            "parquet_path": str(result_df_path),
                            "source": "drain3",
                        })

                    if templates:
                        self.embed_store.upsert_templates(templates, extra_metadata=self.extra_metadata)

                    update_file_status(self.project_dir, original_name, "indexed")
                    results[original_name] = "indexed"
                else:
                    update_file_status(self.project_dir, original_name, "parsed")
                    results[original_name] = "parsed"

            except Exception as e:
                logger.error(f"[RagIndexer] Error indexing {original_name}: {e}")
                update_file_status(
                    self.project_dir, original_name, "error",
                    {"message": str(e)},
                )
                results[original_name] = "error"

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_empty_parquet(self, domain: str) -> None:
        """
        Write an empty parquet marker for a domain with no results.

        This prevents the resume-indexer from endlessly retrying domains
        that have no matching files or no rg matches (e.g. "cellular"
        when no cellular log files are present in the upload).
        """
        import pandas as pd
        marker = self.project_dir / f"{domain}_rg.parquet"
        if not marker.exists():
            pd.DataFrame(columns=["timestamp", "loglines", "template"]).to_parquet(
                marker, index=False
            )
            logger.info(f"[RagIndexer] Wrote empty marker: {marker.name}")

    def _filter_files_for_domain(
        self,
        file_paths: List[Path],
        domain: str,
    ) -> List[Path]:
        """
        Filter file paths to only those whose name matches the domain's
        file glob patterns from the YAML config.

        For example, the "mesh" domain defines:
            files: ["wifi_vendor_apps.log*", "airties.log*"]
        So only files matching these globs are returned. This prevents
        scanning all project files for every domain.

        Args:
            file_paths: All file Paths in the project directory.
            domain: Domain name to look up file globs from config.

        Returns:
            Filtered list of Paths matching the domain's file patterns.
        """
        config = self.rg_scanner.get_domain_config(domain)
        if not config or not config.files:
            logger.warning(
                f"[RagIndexer] No file globs for domain '{domain}' "
                f"-- scanning all files"
            )
            return file_paths

        matched = []
        for fp in file_paths:
            # Check if filename matches any of the domain's file globs
            if any(
                fnmatch.fnmatch(fp.name, glob_pat)
                for glob_pat in config.files
            ):
                matched.append(fp)

        logger.info(
            f"[RagIndexer] Domain '{domain}': {len(matched)}/{len(file_paths)} "
            f"files match file globs {config.files}"
        )
        return matched

    def _index_domain(
        self,
        log_dir: Path,
        domain: str,
        file_paths: Optional[List[Path]] = None,
    ) -> int:
        """
        Index a single domain: rg scan -> Drain3 -> embed + upsert.

        Args:
            log_dir: Directory containing log files.
            domain: Canonical rg domain name.
            file_paths: Optional explicit file paths to scan (already
                       filtered to match this domain's file globs).

        Returns:
            Number of unique templates indexed for this domain.
        """
        logger.info(f"[RagIndexer] Processing domain={domain}")

        # Skip if parquet cache already exists (domain already indexed or
        # marked as empty -- no matching files for this domain).
        existing_parquet = self.project_dir / f"{domain}_rg.parquet"
        if existing_parquet.exists():
            logger.info(
                f"[RagIndexer] Skipping domain '{domain}' -- "
                f"parquet cache already exists ({existing_parquet})"
            )
            return 0

        # Stage 1: ripgrep pre-filter
        # If explicit file_paths are provided (pre-filtered for this domain),
        # use scan_files() which applies only the content patterns.
        if file_paths:
            matches = self.rg_scanner.scan_files(file_paths, domain)
        else:
            matches = self.rg_scanner.scan_domain(log_dir, domain)

        if not matches:
            logger.info(
                f"[RagIndexer] No rg matches in domain '{domain}' "
                f"-- no error-class lines found."
            )
            # Write empty marker so resume logic doesn't retry endlessly
            self._write_empty_parquet(domain)
            return 0

        logger.info(
            f"[RagIndexer] rg pre-filter: {len(matches)} matches "
            f"in domain '{domain}'"
        )

        # Stage 2: Drain3 on all filtered lines (per-domain state file)
        matched_lines = [m.match_text for m in matches]
        source_files = [Path(m.file).name for m in matches]  # original filenames
        parser = Pattern(project_dir=self.project_dir, state_name=domain)
        source_name = f"{domain}_rg"
        df, parquet_path = parser.parse_lines(
            matched_lines, source_name, source_files=source_files
        )

        if df.empty or parquet_path is None:
            logger.warning(
                f"[RagIndexer] Drain3 produced no templates for domain '{domain}'"
            )
            return 0

        # Stage 3: Extract templates with rg context and upsert
        templates = self._extract_templates_with_rg_context(
            df, domain, parquet_path, matches
        )

        logger.info(
            f"[RagIndexer] Upserting {len(templates)} templates "
            f"for domain '{domain}' (rg+Drain3)"
        )
        self.embed_store.upsert_templates(templates, extra_metadata=self.extra_metadata)
        return len(templates)

    def _extract_templates_with_rg_context(
        self,
        df: pd.DataFrame,
        domain: str,
        parquet_path: Path,
        rg_matches: List[RgMatch],
    ) -> List[Dict[str, Any]]:
        """
        Extract templates enriched with ripgrep context metadata.

        Builds a lookup from raw rg match lines to their context (before/after),
        then attaches that context to each unique template for richer search.

        Args:
            df: DataFrame with columns [timestamp, loglines, template].
            domain: Domain name.
            parquet_path: Path to cached parquet file.
            rg_matches: Raw RgMatch objects from ripgrep.

        Returns:
            List of template dicts ready for upsert_templates().
        """
        # Build lookup: match_text -> context info
        _TS_RE = re.compile(
            r"^(?:"
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*"
            r"|\d{6}-\d{2}:\d{2}:\d{2}\.\d+"
            r"|[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"
            r"|\d+\.\d+"
            r")[:\s]+"
        )

        context_lookup: Dict[str, Dict[str, Any]] = {}
        for m in rg_matches:
            entry = {
                "before": m.context_before,
                "after": m.context_after,
                "file": m.file,
                "line_number": m.line_number,
            }
            # Key by full raw line
            if m.match_text not in context_lookup:
                context_lookup[m.match_text] = entry
            # Also key by logline (timestamp stripped)
            stripped = _TS_RE.sub("", m.match_text).strip()
            if stripped and stripped not in context_lookup:
                context_lookup[stripped] = entry

        # Count unique templates
        counts = df["template"].value_counts().reset_index()
        counts.columns = ["template", "count"]

        templates: List[Dict[str, Any]] = []
        for _, row in counts.iterrows():
            template_text = str(row["template"])

            # Find representative rg context for this template
            matching_rows = df[df["template"] == template_text].head(1)
            rg_context = None
            if not matching_rows.empty:
                sample_logline = str(matching_rows.iloc[0]["loglines"])
                rg_context = context_lookup.get(sample_logline)

            # Derive filename from the rg match's source file
            filename = Path(rg_context["file"]).name if rg_context else domain

            template_dict: Dict[str, Any] = {
                "template": template_text,
                "count": int(row["count"]),
                "filename": filename,
                "domain": domain,
                "parquet_path": str(parquet_path),
                "source": "rg_drain3",
            }

            if rg_context:
                template_dict["rg_context"] = {
                    "context_before": rg_context.get("before", []),
                    "context_after": rg_context.get("after", []),
                    "source_file": rg_context.get("file", ""),
                    "line_number": rg_context.get("line_number", 0),
                }

            templates.append(template_dict)

        return templates

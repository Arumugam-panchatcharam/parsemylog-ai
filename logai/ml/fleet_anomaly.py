"""
Fleet-Level Anomaly Analyzer
=============================

Orchestrates ML anomaly detection across 500+ CPE devices with:

1. **Parallel Processing** -- ProcessPoolExecutor with chunked batching
   for CPU-bound analysis, ThreadPoolExecutor for I/O-bound cache loading.

2. **Cross-CPE Log Clustering** -- Aggregates template distributions across
   all CPEs, applies fleet-wide TF-IDF + DBSCAN to identify CPE groups
   with similar (or divergent) log patterns.

3. **Fleet Telemetry Profiling** -- Builds metric baselines from the fleet
   and detects individual CPEs whose metrics deviate from the fleet norm.

4. **Fleet Summary** -- Generates a concise fleet-wide report with:
   - Health distribution histogram
   - Common vs. unique anomaly patterns
   - Outlier CPEs ranked by severity
   - Cross-CPE correlation insights

Scaling Strategy
----------------
- Each CPE analysis is independent (embarrassingly parallel).
- Shared embedding model loaded once, reused across threads.
- DeepLog LSTM is optional per CPE (fast skip on small datasets).
- Results are streamed to a dict so partial results are available.
- Memory-bounded: only one CPE's DataFrame in memory at a time per worker.

Usage:
    >>> from logai.ml.fleet_analyzer import FleetAnalyzer
    >>> analyzer = FleetAnalyzer(max_workers=8)
    >>> report = analyzer.analyze_fleet(
    ...     project_dir=Path("uploads/user1/project1"),
    ...     cpe_ids=["cpe_001", "cpe_002", ...],
    ... )
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from logai.ml.log_anomaly import LogAnomalyPipeline, LogAnomalyReport
from logai.ml.telemetry_anomaly import (
    TelemetryAnomalyPipeline,
    TelemetryAnomalyReport,
    DeviceHealthScore,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FleetCPEResult:
    """Analysis result for a single CPE within the fleet."""
    cpe_id: str
    log_report: Optional[LogAnomalyReport] = None
    telemetry_report: Optional[TelemetryAnomalyReport] = None
    health_label: str = "unknown"
    overall_score: float = 0.0
    error: Optional[str] = None


@dataclass
class FleetCluster:
    """A cluster of CPEs with similar log patterns."""
    cluster_id: int
    cpe_ids: List[str]
    size: int
    common_templates: List[str]
    label: str  # "normal", "error_heavy", "unique"
    representative_cpe: str


@dataclass
class FleetReport:
    """Complete fleet-level analysis report."""
    total_cpes: int
    analyzed_cpes: int
    failed_cpes: int
    health_distribution: Dict[str, int]
    health_histogram: List[Dict[str, Any]]
    cpe_results: Dict[str, FleetCPEResult]
    clusters: List[FleetCluster]
    fleet_anomaly_patterns: List[Dict[str, Any]]
    outlier_cpes: List[Dict[str, Any]]
    fleet_summary: Dict[str, Any]
    processing_time_ms: float


# ---------------------------------------------------------------------------
# Fleet Analyzer
# ---------------------------------------------------------------------------

class FleetAnalyzer:
    """
    Orchestrates ML anomaly detection across a fleet of 500+ CPEs.

    Uses thread-pool parallelism for I/O-bound telemetry cache loading
    and CPU-efficient per-CPE analysis. Each CPE is processed independently
    to bound memory usage.
    """

    def __init__(
        self,
        max_workers: int = 8,
        enable_vector_similarity: bool = True,  # NEW
        enable_gru: bool = True,  # NEW
        enable_isolation_forest: bool = True,  # NEW
        enable_deeplog: bool = False,
        enable_semantic: bool = False,
        enable_log_analysis: bool = True,
        enable_telemetry_analysis: bool = True,
        shared_embedding_model: Optional[Any] = None,
        log_domains: Optional[List[str]] = None,
        qdrant_url: str = "http://localhost:6333",  # NEW
        qdrant_collection: Optional[str] = None,  # NEW
    ):
        """
        Args:
            max_workers: Thread pool size for parallel CPE processing.
            enable_vector_similarity: Enable vector similarity detection (NEW).
            enable_gru: Enable GRU on embeddings (NEW).
            enable_isolation_forest: Enable IsolationForest on embeddings (NEW).
            enable_deeplog: Enable DeepLog LSTM (deprecated).
            enable_semantic: Enable semantic novelty detection (deprecated).
            enable_log_analysis: Analyze log patterns.
            enable_telemetry_analysis: Analyze telemetry metrics.
            shared_embedding_model: Pre-loaded SentenceTransformer for
                                   semantic detection if enabled.
            log_domains: Specific domains to analyze. None = all available.
            qdrant_url: Qdrant server URL (NEW).
            qdrant_collection: Qdrant collection name (NEW).
        """
        self.max_workers = max_workers
        self.enable_vector_similarity = enable_vector_similarity
        self.enable_gru = enable_gru
        self.enable_isolation_forest = enable_isolation_forest
        self.enable_deeplog = enable_deeplog
        self.enable_semantic = enable_semantic
        self.enable_log_analysis = enable_log_analysis
        self.enable_telemetry_analysis = enable_telemetry_analysis
        self.shared_embedding_model = shared_embedding_model
        self.log_domains = log_domains
        self.qdrant_url = qdrant_url
        self.qdrant_collection = qdrant_collection

    def analyze_fleet(
        self,
        project_dir: Path,
        cpe_ids: Optional[List[str]] = None,
        progress_callback: Optional[Any] = None,
    ) -> FleetReport:
        """
        Analyze all CPEs in a project directory.

        Args:
            project_dir: Root project directory containing CPE subdirs.
            cpe_ids: Specific CPE IDs to analyze. None = auto-discover.
            progress_callback: Optional callable(cpe_id, index, total) for
                             progress reporting (e.g. Celery task updates).

        Returns:
            FleetReport with per-CPE results and fleet-level insights.
        """
        start_time = time.perf_counter()

        if cpe_ids is None:
            cpe_ids = self._discover_cpes(project_dir)

        if not cpe_ids:
            logger.warning("[FleetAnalyzer] No CPEs found to analyze")
            return self._empty_report(0.0)

        total = len(cpe_ids)
        logger.info(f"[FleetAnalyzer] Starting fleet analysis: {total} CPEs")

        cpe_results: Dict[str, FleetCPEResult] = {}
        completed = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self._analyze_single_cpe, project_dir, cpe_id): cpe_id
                for cpe_id in cpe_ids
            }

            for future in as_completed(futures):
                cpe_id = futures[future]
                try:
                    result = future.result(timeout=300)
                    cpe_results[cpe_id] = result
                    if result.error:
                        failed += 1
                except Exception as e:
                    logger.error(f"[FleetAnalyzer] CPE {cpe_id} failed: {e}")
                    cpe_results[cpe_id] = FleetCPEResult(
                        cpe_id=cpe_id, error=str(e)
                    )
                    failed += 1

                completed += 1
                if progress_callback:
                    try:
                        progress_callback(cpe_id, completed, total)
                    except Exception:
                        pass

                if completed % 50 == 0:
                    logger.info(
                        f"[FleetAnalyzer] Progress: {completed}/{total} CPEs "
                        f"({failed} failed)"
                    )

        health_dist = self._compute_health_distribution(cpe_results)
        health_hist = self._compute_health_histogram(cpe_results)
        clusters = self._cluster_cpes(cpe_results)
        fleet_patterns = self._extract_fleet_anomaly_patterns(cpe_results)
        outliers = self._identify_outlier_cpes(cpe_results)
        fleet_summary = self._build_fleet_summary(
            cpe_results, health_dist, clusters, fleet_patterns, outliers
        )

        elapsed = (time.perf_counter() - start_time) * 1000

        return FleetReport(
            total_cpes=total,
            analyzed_cpes=completed - failed,
            failed_cpes=failed,
            health_distribution=health_dist,
            health_histogram=health_hist,
            cpe_results=cpe_results,
            clusters=clusters,
            fleet_anomaly_patterns=fleet_patterns,
            outlier_cpes=outliers,
            fleet_summary=fleet_summary,
            processing_time_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # Single CPE analysis
    # ------------------------------------------------------------------

    def _analyze_single_cpe(
        self, project_dir: Path, cpe_id: str
    ) -> FleetCPEResult:
        """Analyze a single CPE (runs in a thread pool worker)."""
        cpe_dir = project_dir / cpe_id
        result = FleetCPEResult(cpe_id=cpe_id)

        if not cpe_dir.exists():
            result.error = "CPE directory not found"
            return result

        if self.enable_log_analysis:
            result.log_report = self._run_log_analysis(cpe_dir, cpe_id)

        if self.enable_telemetry_analysis:
            result.telemetry_report = self._run_telemetry_analysis(cpe_dir, cpe_id)

        if result.telemetry_report:
            result.health_label = result.telemetry_report.health.health_label
            result.overall_score = result.telemetry_report.health.overall_score
        elif result.log_report and result.log_report.anomaly_count > 0:
            score = max(0, 100 - result.log_report.anomaly_count * 5)
            result.overall_score = score
            if score >= 80:
                result.health_label = "healthy"
            elif score >= 60:
                result.health_label = "degraded"
            elif score >= 40:
                result.health_label = "at_risk"
            else:
                result.health_label = "critical"

        return result

    def _run_log_analysis(
        self, cpe_dir: Path, cpe_id: str
    ) -> Optional[LogAnomalyReport]:
        """Run log anomaly detection on all available domain parquets."""
        try:
            pipeline = LogAnomalyPipeline(
                # NEW: Vector-based parameters
                enable_vector_similarity=self.enable_vector_similarity,
                enable_gru=self.enable_gru,
                enable_isolation_forest=self.enable_isolation_forest,
                qdrant_url=self.qdrant_url,
                qdrant_collection=self.qdrant_collection,
                # Legacy parameters
                enable_deeplog=self.enable_deeplog,
                enable_semantic=self.enable_semantic,
                shared_embedding_model=self.shared_embedding_model,
            )

            parquet_files = list(cpe_dir.glob("*_rg.parquet"))
            if not parquet_files:
                return None

            all_dfs = []
            for pf in parquet_files:
                try:
                    df = pd.read_parquet(pf)
                    if not df.empty:
                        domain = pf.stem.replace("_rg", "")
                        df["_domain"] = domain
                        all_dfs.append(df)
                except Exception:
                    continue

            if not all_dfs:
                return None

            combined = pd.concat(all_dfs, ignore_index=True)
            return pipeline.analyze(
                df=combined, cpe_id=cpe_id, domain="all", top_n=30,
            )
        except Exception as e:
            logger.debug(f"[FleetAnalyzer] Log analysis failed for {cpe_id}: {e}")
            return None

    def _run_telemetry_analysis(
        self, cpe_dir: Path, cpe_id: str
    ) -> Optional[TelemetryAnomalyReport]:
        """Run telemetry anomaly detection from cached data."""
        try:
            cache_path = cpe_dir / "raw_telemetry_cache.json"
            if not cache_path.exists():
                return None

            pipeline = TelemetryAnomalyPipeline()
            return pipeline.analyze(
                cache_path=str(cache_path), cpe_id=cpe_id,
            )
        except Exception as e:
            logger.debug(f"[FleetAnalyzer] Telemetry analysis failed for {cpe_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # CPE Discovery
    # ------------------------------------------------------------------

    def _discover_cpes(self, project_dir: Path) -> List[str]:
        """Auto-discover CPE subdirectories in the project."""
        cpe_ids = []
        if not project_dir.exists():
            return cpe_ids

        for child in sorted(project_dir.iterdir()):
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith(".") or name in (
                "telemetry", "merged_logs", "__pycache__", "node_modules",
            ):
                continue
            has_logs = (
                list(child.glob("*_rg.parquet"))
                or (child / "raw_telemetry_cache.json").exists()
                or list(child.glob("*.txt"))
            )
            if has_logs:
                cpe_ids.append(name)

        logger.info(f"[FleetAnalyzer] Discovered {len(cpe_ids)} CPEs in {project_dir}")
        return cpe_ids

    # ------------------------------------------------------------------
    # Fleet-level aggregation
    # ------------------------------------------------------------------

    def _compute_health_distribution(
        self, results: Dict[str, FleetCPEResult]
    ) -> Dict[str, int]:
        dist = Counter()
        for r in results.values():
            dist[r.health_label] += 1
        return dict(dist)

    def _compute_health_histogram(
        self, results: Dict[str, FleetCPEResult]
    ) -> List[Dict[str, Any]]:
        """Build a histogram of health scores in 10-point buckets."""
        buckets = defaultdict(int)
        for r in results.values():
            bucket = int(r.overall_score // 10) * 10
            buckets[bucket] += 1

        return [
            {"range_start": b, "range_end": b + 10, "count": c}
            for b, c in sorted(buckets.items())
        ]

    def _cluster_cpes(
        self, results: Dict[str, FleetCPEResult]
    ) -> List[FleetCluster]:
        """
        Cluster CPEs by their log template distributions using TF-IDF + KMeans.

        For fleet-scale analysis, this identifies groups of CPEs experiencing
        similar issues (e.g. a firmware bug affecting a specific model).
        """
        template_vectors: Dict[str, Counter] = {}
        for cpe_id, result in results.items():
            if result.log_report and result.log_report.anomalies:
                counts = Counter()
                for anom in result.log_report.anomalies:
                    counts[anom.template] += 1
                if counts:
                    template_vectors[cpe_id] = counts

        if len(template_vectors) < 3:
            return []

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.cluster import KMeans

            docs = []
            cpe_order = []
            for cpe_id, counts in template_vectors.items():
                doc = " ".join(
                    f"T{hash(t) % 100000:05d}" for t, c in counts.items() for _ in range(c)
                )
                docs.append(doc)
                cpe_order.append(cpe_id)

            vectorizer = TfidfVectorizer(max_features=1000)
            tfidf = vectorizer.fit_transform(docs)

            n_clusters = min(max(2, len(docs) // 10), 10)
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(tfidf)

            clusters_map: Dict[int, List[str]] = defaultdict(list)
            for i, label in enumerate(labels):
                clusters_map[label].append(cpe_order[i])

            clusters = []
            for cid, members in clusters_map.items():
                common_templates = self._find_common_templates(
                    {m: template_vectors[m] for m in members}
                )
                size = len(members)
                label = "normal" if size > len(cpe_order) * 0.3 else (
                    "unique" if size <= 2 else "error_heavy"
                )
                clusters.append(FleetCluster(
                    cluster_id=cid,
                    cpe_ids=members,
                    size=size,
                    common_templates=common_templates[:10],
                    label=label,
                    representative_cpe=members[0],
                ))

            clusters.sort(key=lambda c: -c.size)
            return clusters

        except Exception as e:
            logger.warning(f"[FleetAnalyzer] Clustering failed: {e}")
            return []

    def _find_common_templates(
        self, cpe_counts: Dict[str, Counter]
    ) -> List[str]:
        """Find templates common to all CPEs in a cluster."""
        if not cpe_counts:
            return []
        all_templates = None
        for counts in cpe_counts.values():
            templates = set(counts.keys())
            if all_templates is None:
                all_templates = templates
            else:
                all_templates &= templates

        return sorted(all_templates or set())

    def _extract_fleet_anomaly_patterns(
        self, results: Dict[str, FleetCPEResult]
    ) -> List[Dict[str, Any]]:
        """
        Identify anomaly patterns that appear across multiple CPEs.

        Patterns appearing in many CPEs are likely systemic (firmware bug,
        infrastructure issue). Patterns in few CPEs are device-specific.
        """
        template_cpes: Dict[str, List[str]] = defaultdict(list)
        template_scores: Dict[str, List[float]] = defaultdict(list)

        for cpe_id, result in results.items():
            if not result.log_report:
                continue
            for anom in result.log_report.anomalies:
                template_cpes[anom.template].append(cpe_id)
                template_scores[anom.template].append(anom.score)

        patterns = []
        total_cpes = len(results)
        for template, cpes in template_cpes.items():
            prevalence = len(cpes) / total_cpes if total_cpes > 0 else 0
            avg_score = np.mean(template_scores[template])
            patterns.append({
                "template": template,
                "affected_cpes": len(cpes),
                "prevalence": float(prevalence),
                "avg_anomaly_score": float(avg_score),
                "pattern_type": "systemic" if prevalence > 0.3 else (
                    "widespread" if prevalence > 0.1 else "isolated"
                ),
                "cpe_ids": cpes[:20],
            })

        patterns.sort(key=lambda x: (-x["affected_cpes"], -x["avg_anomaly_score"]))
        return patterns[:100]

    def _identify_outlier_cpes(
        self, results: Dict[str, FleetCPEResult]
    ) -> List[Dict[str, Any]]:
        """
        Identify CPEs that deviate significantly from the fleet norm.

        Uses health score distance from the fleet median to rank outliers.
        """
        scores = []
        for cpe_id, r in results.items():
            if r.overall_score > 0 or r.health_label != "unknown":
                scores.append((cpe_id, r.overall_score))

        if len(scores) < 3:
            return []

        score_vals = np.array([s[1] for s in scores])
        median_score = np.median(score_vals)
        std_score = np.std(score_vals) if np.std(score_vals) > 0 else 1.0

        outliers = []
        for cpe_id, score in scores:
            z = (score - median_score) / std_score
            if z < -1.5:
                r = results[cpe_id]
                risk_factors = []
                if r.telemetry_report:
                    risk_factors = r.telemetry_report.health.risk_factors
                elif r.log_report:
                    risk_factors = [
                        f"{r.log_report.anomaly_count} log anomalies detected"
                    ]

                outliers.append({
                    "cpe_id": cpe_id,
                    "health_score": float(score),
                    "fleet_median": float(median_score),
                    "z_score": float(z),
                    "health_label": r.health_label,
                    "risk_factors": risk_factors[:5],
                    "anomaly_count": (
                        r.log_report.anomaly_count if r.log_report else 0
                    ) + (
                        len(r.telemetry_report.anomalies) if r.telemetry_report else 0
                    ),
                })

        outliers.sort(key=lambda x: x["z_score"])
        return outliers[:50]

    def _build_fleet_summary(
        self,
        results: Dict[str, FleetCPEResult],
        health_dist: Dict[str, int],
        clusters: List[FleetCluster],
        patterns: List[Dict[str, Any]],
        outliers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build the fleet-level summary."""
        total = len(results)
        scores = [
            r.overall_score for r in results.values()
            if r.overall_score > 0 or r.health_label != "unknown"
        ]

        systemic = [p for p in patterns if p["pattern_type"] == "systemic"]
        isolated = [p for p in patterns if p["pattern_type"] == "isolated"]

        summary_lines = []
        summary_lines.append(
            f"Fleet of {total} CPEs analyzed. "
            f"Health: {health_dist.get('healthy', 0)} healthy, "
            f"{health_dist.get('degraded', 0)} degraded, "
            f"{health_dist.get('at_risk', 0)} at risk, "
            f"{health_dist.get('critical', 0)} critical."
        )

        if scores:
            summary_lines.append(
                f"Fleet health score: mean={np.mean(scores):.1f}, "
                f"median={np.median(scores):.1f}, "
                f"min={np.min(scores):.1f}, max={np.max(scores):.1f}."
            )

        if systemic:
            summary_lines.append(
                f"{len(systemic)} systemic anomaly patterns detected "
                f"(affecting >30% of fleet)."
            )
            for p in systemic[:3]:
                summary_lines.append(
                    f"  - \"{p['template'][:80]}...\" "
                    f"({p['affected_cpes']} CPEs, {p['prevalence']:.0%} prevalence)"
                )

        if outliers:
            summary_lines.append(
                f"{len(outliers)} outlier CPEs identified "
                f"(significantly below fleet health median)."
            )

        if clusters:
            summary_lines.append(
                f"{len(clusters)} CPE behavior clusters identified."
            )

        return {
            "total_cpes": total,
            "fleet_health_mean": float(np.mean(scores)) if scores else 0.0,
            "fleet_health_median": float(np.median(scores)) if scores else 0.0,
            "systemic_patterns": len(systemic),
            "isolated_patterns": len(isolated),
            "outlier_count": len(outliers),
            "cluster_count": len(clusters),
            "narrative": " ".join(summary_lines),
        }

    def _empty_report(self, elapsed: float) -> FleetReport:
        return FleetReport(
            total_cpes=0, analyzed_cpes=0, failed_cpes=0,
            health_distribution={}, health_histogram=[],
            cpe_results={}, clusters=[], fleet_anomaly_patterns=[],
            outlier_cpes=[], fleet_summary={}, processing_time_ms=elapsed,
        )

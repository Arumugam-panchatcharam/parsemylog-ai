"""
Knowledge-Graph-Driven Issue Analyzer
======================================

Generic analysis engine that reads a user-defined knowledge graph
(nodes + causal edges stored in SQLite) and evaluates CPE log data
against it.

Algorithm
---------
For each CPE:

1. Load ``*_rg.parquet`` + telemetry (reuses existing parsers).
2. Build a networkx DiGraph from the knowledge graph definition.
3. For every EVENT node, match its ``detection_config`` against log
   lines in the relevant parquet domains.
4. Evaluate edges: if an EVENT's evidence meets the edge's conditions
   (e.g. count >= threshold), propagate activation through the graph.
5. Collect activated ISSUE and ROOT_CAUSE nodes with evidence chains.
6. Score root causes by confidence weights and evidence strength.

The output format is consumed by ``IssueAnalysisPage.tsx``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    import networkx as nx
except ImportError:
    nx = None  # type: ignore[assignment]

from logai.info_extractor import (
    find_and_extract_reboots,
    find_and_parse_version_txt,
    find_and_build_fallback_device_info,
)
from logai.rdkb_knowledge import chain_module_plausibility, resolve_modules
from logai.telemetry_parser import parse_telemetry_file
from logai.timestamp_parser import parse_timestamp

logger = logging.getLogger(__name__)

REBOOT_WINDOW_BEFORE_MIN = 60
REBOOT_WINDOW_AFTER_MIN = 10
OUTPUT_DIR_NAME = "issue_analysis"
PER_CPE_FILE = "issue_analysis_per_cpe.json"
FLEET_FILE = "fleet_issue_analysis.json"

_TS_FMTS = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f")

# RX/TX telemetry field aliases
_RXTX_FIELDS = {
    "wan": {
        "rx_bytes": ["wan_bytesReceived", "Device.WAN.BytesReceived"],
        "tx_bytes": ["wan_bytesSent", "Device.WAN.BytesSent"],
        "rx_packets": ["wan_packetsReceived", "Device.WAN.PacketsReceived"],
        "tx_packets": ["wan_packetsSent", "Device.WAN.PacketsSent"],
        "rx_errors": ["wan_errorsReceived", "Device.WAN.ErrorsReceived"],
        "tx_errors": ["wan_errorsSent", "Device.WAN.ErrorsSent"],
    },
    "wifi_ssid1": {
        "rx_bytes": ["wifi_ssid_1_stats_bytesreceived"],
        "tx_bytes": ["wifi_ssid_1_stats_bytessent"],
        "rx_errors": ["wifi_ssid_1_stats_errorsreceived"],
        "tx_errors": ["wifi_ssid_1_stats_errorssent"],
    },
    "wifi_ssid2": {
        "rx_bytes": ["wifi_ssid_2_stats_bytesreceived"],
        "tx_bytes": ["wifi_ssid_2_stats_bytessent"],
    },
    "ethernet": {
        "rx_bytes": ["ethernet_link_1_stats_bytesreceived"],
        "tx_bytes": ["ethernet_link_1_stats_bytessent"],
    },
    "ppp": {
        "rx_bytes": ["ppp_interface_1_stats_bytesreceived"],
        "tx_bytes": ["ppp_interface_1_stats_bytessent"],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json_serial(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, '__dict__'):
        return str(obj)
    return str(obj)


def _parse_ts(s: str) -> Optional[datetime]:
    if not s:
        return None
    # Use generic timestamp parser
    return parse_timestamp(s)


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def load_graph_definition(
    graph_id: str,
    _visited: Optional[set] = None,
) -> Dict[str, Any]:
    """Load a knowledge graph from SQLite and return nodes + edges as dicts.

    For SUBGRAPH nodes the referenced graph is loaded recursively and
    attached under ``node["_resolved_subgraph"]``.  Circular references
    are detected via *_visited*.
    """
    from api.user_db_mngr import KnowledgeGraph, KnowledgeNode, KnowledgeEdge, db

    if _visited is None:
        _visited = set()
    if graph_id in _visited:
        raise ValueError(
            f"Circular subgraph reference detected: graph '{graph_id}' "
            "is already in the evaluation chain"
        )
    _visited.add(graph_id)

    graph = db.session.get(KnowledgeGraph, graph_id)
    if not graph:
        raise ValueError(f"Knowledge graph '{graph_id}' not found")

    nodes = []
    for n in db.session.query(KnowledgeNode).filter_by(graph_id=graph_id).all():
        node_dict: Dict[str, Any] = {
            "id": n.id,
            "node_type": n.node_type,
            "name": n.name,
            "label": n.label,
            "domain": n.domain,
            "detection_config": json.loads(n.detection_config) if n.detection_config else None,
            "description": n.description,
        }
        if n.node_type == "SUBGRAPH":
            dc = node_dict.get("detection_config") or {}
            ref_id = dc.get("referenced_graph_id")
            if ref_id and ref_id not in _visited:
                try:
                    node_dict["_resolved_subgraph"] = load_graph_definition(
                        ref_id, _visited=set(_visited),
                    )
                except Exception as exc:
                    logger.warning("Could not resolve subgraph %s: %s", ref_id, exc)
        nodes.append(node_dict)

    edges = []
    for e in db.session.query(KnowledgeEdge).filter_by(graph_id=graph_id).all():
        edges.append({
            "id": e.id,
            "source_node_id": e.source_node_id,
            "target_node_id": e.target_node_id,
            "relationship_type": e.relationship_type,
            "conditions": json.loads(e.conditions) if e.conditions else {},
            "label": e.label,
            "description": e.description,
        })

    return {"id": graph_id, "name": graph.name, "nodes": nodes, "edges": edges}


def build_networkx_graph(graph_def: Dict[str, Any]):
    """Build a networkx DiGraph from the graph definition dict."""
    if nx is None:
        raise ImportError("networkx is required for graph analysis. pip install networkx")

    G = nx.DiGraph()
    for n in graph_def["nodes"]:
        G.add_node(n["id"], **n)
    for e in graph_def["edges"]:
        G.add_edge(
            e["source_node_id"], e["target_node_id"],
            edge_id=e["id"], **e,
        )
    return G


def _compile_node_patterns(node: Dict) -> Tuple[List[re.Pattern], List[re.Pattern]]:
    """Compile regex/keyword patterns from a node's detection_config."""
    dc = node.get("detection_config") or {}
    patterns: List[re.Pattern] = []
    exclusions: List[re.Pattern] = []

    for kw in dc.get("keywords", []):
        try:
            patterns.append(re.compile(kw, re.IGNORECASE))
        except re.error:
            logger.warning(f"Bad regex in node {node['name']}: {kw}")

    for rx in dc.get("patterns", []):
        try:
            patterns.append(re.compile(rx, re.IGNORECASE))
        except re.error:
            logger.warning(f"Bad regex in node {node['name']}: {rx}")

    for ex in dc.get("exclusions", []):
        try:
            exclusions.append(re.compile(ex, re.IGNORECASE))
        except re.error:
            pass

    return patterns, exclusions


def _detection_uses_parquet(node: Dict[str, Any]) -> bool:
    """When True, use parquet-backed detection for this node (avoids double-count with rg)."""
    dc = node.get("detection_config") or {}
    return bool(dc.get("template_patterns") or dc.get("template_keywords"))


def _compile_template_patterns(
    dc: Dict[str, Any],
) -> Tuple[List[re.Pattern], List[str]]:
    """Compile ``template_patterns`` (regex) and lowercase ``template_keywords``."""
    patterns: List[re.Pattern] = []
    keywords: List[str] = []
    for rx in dc.get("template_patterns") or []:
        if not rx:
            continue
        try:
            patterns.append(re.compile(str(rx), re.IGNORECASE))
        except re.error:
            logger.warning("Bad template regex in detection_config: %s", rx)
    for kw in dc.get("template_keywords") or []:
        if kw:
            keywords.append(str(kw).lower())
    return patterns, keywords


def _template_field_matches(
    template_value: str,
    tmpl_pats: List[re.Pattern],
    tmpl_kwds: List[str],
) -> bool:
    if not tmpl_pats and not tmpl_kwds:
        return False
    t = template_value or ""
    if any(p.search(t) for p in tmpl_pats):
        return True
    tl = t.lower()
    return any(k in tl for k in tmpl_kwds if k)


# ---------------------------------------------------------------------------
# Ripgrep-based detection
# ---------------------------------------------------------------------------

_RG_BIN: Optional[str] = shutil.which("rg")
_TS_RX = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")

_RG_SKIP_DIRS = frozenset({
    "raw", "staging", "issue_analysis", "telemetry",
    ".git", "__pycache__",
})

_RG_SKIP_FILES = frozenset({
    "raw_telemetry_cache.json", ".version_cache.json",
    ".device_info_cache.json", ".reboots_cache.json",
})

# Avoid huge argv / regex limits; spill union pattern to a temp file for rg -f.
_RG_UNION_PATTERN_INLINE_MAX = 120_000


def _rg_path_and_glob_args(cpe_dir: Path) -> List[str]:
    """Ripgrep path + skip globs (shared by all rg invocations)."""
    args: List[str] = ["--max-filesize", "50M"]
    for skip in _RG_SKIP_DIRS:
        args.extend(["--glob", f"!{skip}/"])
    for skip in _RG_SKIP_FILES:
        args.extend(["--glob", f"!{skip}"])
    args.append(str(cpe_dir))
    return args


def _parse_rg_json_stdout(stdout: str, cpe_dir: Path) -> List[Dict[str, Any]]:
    """Parse ``rg --json`` lines into match dicts (text, file, timestamp)."""
    matches: List[Dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "match":
            continue
        data = obj.get("data", {})
        text = data.get("lines", {}).get("text", "").strip()
        if not text:
            continue

        fpath = data.get("path", {}).get("text", "")
        rel = fpath.replace(str(cpe_dir) + "/", "", 1) if fpath else ""

        ts_match = _TS_RX.search(text)
        ts_str = ts_match.group(1).replace("T", " ") if ts_match else ""

        matches.append({
            "text": text[:400],
            "file": rel,
            "timestamp": ts_str,
        })
    return matches


def _run_rg_with_pattern(cpe_dir: Path, pattern: str) -> List[Dict[str, Any]]:
    """Run a single ripgrep search with ``-e pattern`` (or ``-f`` if very long)."""
    if not _RG_BIN or not pattern.strip():
        return []

    tmp_path: Optional[str] = None
    try:
        if len(pattern) > _RG_UNION_PATTERN_INLINE_MAX:
            fd, tmp_path = tempfile.mkstemp(suffix=".rgpat", text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(pattern)
            except Exception:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                raise
            cmd = [
                _RG_BIN, "--json", "-i", "-f", tmp_path,
                *_rg_path_and_glob_args(cpe_dir),
            ]
        else:
            cmd = [
                _RG_BIN, "--json", "-i", "-e", pattern,
                *_rg_path_and_glob_args(cpe_dir),
            ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[GraphAnalyzer] rg timeout (unified or single pattern)")
        return []
    except Exception as exc:
        logger.warning("[GraphAnalyzer] rg error: %s", exc)
        return []
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if proc.returncode not in (0, 1):
        err = (proc.stderr or "").strip()
        if err:
            logger.warning("[GraphAnalyzer] rg exit %s: %s", proc.returncode, err[:500])
        return []

    return _parse_rg_json_stdout(proc.stdout, cpe_dir)


def _build_union_pattern_for_rg_nodes(rg_nodes: List[Dict]) -> str:
    """Single alternation over all keywords/patterns so one ``rg`` pass suffices."""
    parts: List[str] = []
    for node in rg_nodes:
        dc = node.get("detection_config") or {}
        raw_patterns = list(dc.get("keywords", [])) + list(dc.get("patterns", []))
        for p in raw_patterns:
            ps = str(p).strip()
            if not ps:
                continue
            parts.append(f"(?:{ps})")
    return "|".join(parts)


def _empty_rg_evidence() -> Dict[str, Any]:
    return {
        "count": 0,
        "sample_lines": [],
        "timestamps": [],
        "rdk_modules": [],
    }


def _classify_unified_rg_matches(
    matches: List[Dict[str, Any]],
    rg_nodes: List[Dict],
    compiled_map: Dict[str, Tuple[List[re.Pattern], List[re.Pattern]]],
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """Turn one unified ``rg`` result into per-node evidence (exclusions + windows)."""
    out: Dict[str, Dict[str, Any]] = {
        n["id"]: _empty_rg_evidence() for n in rg_nodes
    }
    if not matches or not rg_nodes:
        return out

    node_rows: List[Tuple[str, List[re.Pattern], List[re.Pattern]]] = []
    for n in rg_nodes:
        nid = n["id"]
        pats, excl = compiled_map[nid]
        if not pats:
            continue
        node_rows.append((nid, pats, excl))

    for m in matches:
        text = m["text"]
        ts = _parse_ts(m["timestamp"]) if m.get("timestamp") else None
        if window_start is not None and (ts is None or ts < window_start):
            continue
        if window_end is not None and (ts is None or ts > window_end):
            continue

        for nid, pats, excl in node_rows:
            if excl and any(ex.search(text) for ex in excl):
                continue
            if not any(p.search(text) for p in pats):
                continue
            ev = out[nid]
            ev["count"] += 1
            if ts:
                ev["timestamps"].append(ts.isoformat())
            if len(ev["sample_lines"]) < 5:
                ev["sample_lines"].append(text)

    return out


def _run_rg_for_node(
    node: Dict,
    cpe_dir: Path,
) -> List[Dict[str, Any]]:
    """Run ripgrep for a single EVENT node and return structured matches.

    Each match dict contains ``text`` (the matched line, up to 400 chars),
    ``file`` (relative filename), and ``timestamp`` (ISO string or ``""``).
    """
    dc = node.get("detection_config") or {}
    raw_patterns = list(dc.get("keywords", [])) + list(dc.get("patterns", []))
    if not raw_patterns:
        return []

    combined = "|".join(f"({p})" for p in raw_patterns)
    return _run_rg_with_pattern(cpe_dir, combined)


def _unified_rg_matches_for_nodes(
    cpe_dir: Path,
    rg_nodes: List[Dict],
) -> List[Dict[str, Any]]:
    """One directory scan for all *rg_nodes*; empty list if rg unavailable."""
    union = _build_union_pattern_for_rg_nodes(rg_nodes)
    if not union:
        return []
    return _run_rg_with_pattern(cpe_dir, union)


def _detect_events_via_rg(
    node: Dict,
    cpe_dir: Path,
    compiled_exclusions: List[re.Pattern],
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Detect events for a node using ripgrep on the raw CPE directory.

    Prefer :func:`_classify_unified_rg_matches` with a precomputed match list
    when analyzing many nodes on the same directory.
    """
    evidence: Dict[str, Any] = {
        "count": 0,
        "sample_lines": [],
        "timestamps": [],
        "rdk_modules": [],
    }

    rg_matches = _run_rg_for_node(node, cpe_dir)
    if not rg_matches:
        return evidence

    for m in rg_matches:
        text = m["text"]

        if compiled_exclusions and any(ex.search(text) for ex in compiled_exclusions):
            continue

        ts = _parse_ts(m["timestamp"]) if m["timestamp"] else None
        if window_start is not None and (ts is None or ts < window_start):
            continue
        if window_end is not None and (ts is None or ts > window_end):
            continue

        evidence["count"] += 1
        if ts:
            evidence["timestamps"].append(ts.isoformat())
        if len(evidence["sample_lines"]) < 5:
            evidence["sample_lines"].append(text)

    return evidence


# ---------------------------------------------------------------------------
# Parquet loading (kept as fallback when rg is unavailable)
# ---------------------------------------------------------------------------

def _load_all_parquet_events(cpe_dir: Path) -> pd.DataFrame:
    """Load all *_rg.parquet files into one DataFrame."""
    frames = []
    for pq_path in sorted(cpe_dir.glob("*_rg.parquet")):
        domain = pq_path.stem.replace("_rg", "")
        try:
            df = pd.read_parquet(pq_path)
            if df.empty:
                continue
            df = df.copy()
            df["_domain"] = domain
            frames.append(df)
        except Exception as exc:
            logger.warning(f"Could not read {pq_path}: {exc}")

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    if "loglines" not in combined.columns:
        return pd.DataFrame()

    if "timestamp" in combined.columns:
        combined["_ts"] = combined["timestamp"].apply(
            lambda x: _parse_ts(str(x)) if pd.notna(x) else None
        )
    else:
        combined["_ts"] = None

    return combined


# ---------------------------------------------------------------------------
# Evidence detection
# ---------------------------------------------------------------------------

def _detect_events_for_node(
    node: Dict,
    df: pd.DataFrame,
    compiled_patterns: List[re.Pattern],
    compiled_exclusions: List[re.Pattern],
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Match a single node's patterns against a (windowed) DataFrame.

    Uses logline regex/keywords (``patterns`` / ``keywords``) and/or
    ``template_patterns`` / ``template_keywords`` on the Drain3 template
    column. Resolves ``rdk_modules`` from ``configs/rdkb_module_graph.yaml``.
    """
    dc = node.get("detection_config") or {}
    source_domains = set(dc.get("source_domains", []))
    tmpl_pats, tmpl_kwds = _compile_template_patterns(dc)

    evidence: Dict[str, Any] = {
        "count": 0,
        "sample_lines": [],
        "timestamps": [],
        "rdk_modules": [],
    }

    has_log = bool(compiled_patterns)
    has_tmpl = bool(tmpl_pats or tmpl_kwds)
    if df.empty or (not has_log and not has_tmpl):
        return evidence

    mask = pd.Series(True, index=df.index)
    if source_domains and "_domain" in df.columns:
        mask &= df["_domain"].isin(source_domains)
    if window_start is not None and "_ts" in df.columns:
        mask &= df["_ts"].notna() & (df["_ts"] >= window_start)
    if window_end is not None and "_ts" in df.columns:
        mask &= df["_ts"].notna() & (df["_ts"] <= window_end)

    subset = df.loc[mask]
    if subset.empty:
        return evidence

    has_template_col = "template" in subset.columns
    rdk_acc: Dict[str, Dict[str, Any]] = {}

    for _, row in subset.iterrows():
        text = str(row.get("loglines", ""))
        tmpl = str(row.get("template", "")) if has_template_col else ""

        if compiled_exclusions:
            if text and any(ex.search(text) for ex in compiled_exclusions):
                continue
            if tmpl and any(ex.search(tmpl) for ex in compiled_exclusions):
                continue

        log_ok = bool(text) and any(p.search(text) for p in compiled_patterns)
        tmpl_ok = has_template_col and _template_field_matches(tmpl, tmpl_pats, tmpl_kwds)

        if has_log and has_tmpl:
            matched = log_ok or tmpl_ok
        elif has_log:
            matched = log_ok
        else:
            matched = tmpl_ok

        if not matched:
            continue

        evidence["count"] += 1
        ts = row.get("_ts")
        if ts:
            evidence["timestamps"].append(ts.isoformat())
        if len(evidence["sample_lines"]) < 5:
            evidence["sample_lines"].append((text or tmpl)[:400])

        dom = str(row.get("_domain", "")) if "_domain" in row.index else ""
        src_file = str(row.get("source_file", "")) if "source_file" in row.index else ""
        for m in resolve_modules(dom, src_file, tmpl, text):
            mid = m.get("module_id")
            if mid and mid not in rdk_acc:
                rdk_acc[mid] = m

    evidence["rdk_modules"] = list(rdk_acc.values())[:12]
    return evidence


# ---------------------------------------------------------------------------
# Graph evaluation (edge condition checking + activation propagation)
# ---------------------------------------------------------------------------

def _evaluate_graph(
    G,
    node_evidence: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Walk the graph and activate edges whose conditions are met.

    Returns:
        activated_edges: list of edge dicts that fired
        activated_issues: dict of issue/root_cause node_id -> activation info
        causal_chains: list of paths from EVENT -> ISSUE/ROOT_CAUSE
    """
    activated_edges = []
    activated_nodes = {}

    for src_id, tgt_id, edata in G.edges(data=True):
        src_ev = node_evidence.get(src_id, {})
        count = src_ev.get("count", 0)
        conditions = edata.get("conditions", {})
        min_count = conditions.get("source_min_count", 0)
        confidence = conditions.get("confidence", 0.5)

        if count >= min_count and count > 0:
            activated_edges.append({
                "edge_id": edata.get("edge_id"),
                "source": src_id,
                "target": tgt_id,
                "relationship_type": edata.get("relationship_type"),
                "confidence": confidence,
                "source_count": count,
                "label": edata.get("label"),
            })

            tgt_node = G.nodes.get(tgt_id, {})
            tgt_type = tgt_node.get("node_type", "")
            if tgt_type in ("ISSUE", "ROOT_CAUSE"):
                if tgt_id not in activated_nodes:
                    activated_nodes[tgt_id] = {
                        "name": tgt_node.get("name"),
                        "label": tgt_node.get("label"),
                        "node_type": tgt_type,
                        "contributing_events": [],
                        "max_confidence": 0,
                        "total_evidence_count": 0,
                    }
                info = activated_nodes[tgt_id]
                info["contributing_events"].append({
                    "node_id": src_id,
                    "name": G.nodes[src_id].get("name"),
                    "count": count,
                    "confidence": confidence,
                })
                info["max_confidence"] = max(info["max_confidence"], confidence)
                info["total_evidence_count"] += count

    causal_chains = []
    event_ids = [
        nid for nid, ndata in G.nodes(data=True)
        if ndata.get("node_type") == "EVENT"
        and node_evidence.get(nid, {}).get("count", 0) > 0
    ]
    issue_ids = [
        nid for nid, ndata in G.nodes(data=True)
        if ndata.get("node_type") in ("ISSUE", "ROOT_CAUSE")
    ]

    for eid in event_ids:
        for iid in issue_ids:
            if iid in activated_nodes:
                try:
                    for path in nx.all_simple_paths(G, eid, iid, cutoff=5):
                        chain_active = True
                        for i in range(len(path) - 1):
                            edge_data = G.edges[path[i], path[i + 1]]
                            conds = edge_data.get("conditions", {})
                            needed = conds.get("source_min_count", 0)
                            have = node_evidence.get(path[i], {}).get("count", 0)
                            if have < needed:
                                chain_active = False
                                break
                        if chain_active:
                            causal_chains.append({
                                "path": [G.nodes[n].get("name") for n in path],
                                "path_ids": path,
                                "length": len(path),
                            })
                except nx.NetworkXNoPath:
                    pass

    return {
        "activated_edges": activated_edges,
        "activated_issues": activated_nodes,
        "causal_chains": causal_chains,
    }


def _apply_module_plausibility_to_chains_and_roots(
    chains: List[Dict[str, Any]],
    root_causes: List[Dict[str, Any]],
    G: Any,
    event_nodes: List[Dict[str, Any]],
    node_evidence: Dict[str, Dict[str, Any]],
) -> None:
    """Augment *chains* and *root_causes* in place using RDK-B module graph."""
    name_to_mods: Dict[str, List[str]] = {}
    for n in event_nodes:
        ev = node_evidence.get(n["id"], {})
        mods = [
            str(x["module_id"])
            for x in (ev.get("rdk_modules") or [])
            if x.get("module_id")
        ]
        name_to_mods[n["name"]] = mods

    for c in chains:
        path_ids = c.get("path_ids") or []
        mids: List[str] = []
        for nid in path_ids:
            nd = G.nodes.get(nid, {})
            if nd.get("node_type") != "EVENT":
                continue
            nm = nd.get("name")
            lst = name_to_mods.get(nm, [])
            if lst:
                mids.append(lst[0])
        c["module_plausibility"] = round(chain_module_plausibility(mids), 3)

    for rc in root_causes:
        issue_name = rc.get("name")
        rel = [
            float(ch.get("module_plausibility", 0.85))
            for ch in chains
            if ch.get("path") and ch["path"] and ch["path"][-1] == issue_name
        ]
        pl = max(rel) if rel else 0.85
        base = float(rc.get("score", 0))
        rc["score"] = round(base * (0.75 + 0.25 * pl), 3)
        rc["module_plausibility"] = round(pl, 3)


def _determine_likely_trigger(
    node_evidence: Dict[str, Dict[str, Any]],
    graph_eval: Dict[str, Any],
    G,
) -> Tuple[str, str]:
    """Determine the most likely reboot trigger using graph-based scoring."""
    issues = graph_eval.get("activated_issues", {})
    if not issues:
        max_node = None
        max_count = 0
        for nid, ev in node_evidence.items():
            if ev.get("count", 0) > max_count:
                max_count = ev["count"]
                max_node = nid
        if max_node:
            name = G.nodes[max_node].get("name", max_node)
            return name, f"Highest activity: {name}"
        return "unknown", "No significant events detected in reboot window"

    best_id = max(issues, key=lambda k: (
        issues[k]["max_confidence"],
        issues[k]["total_evidence_count"],
    ))
    best = issues[best_id]
    top_contributor = max(
        best["contributing_events"],
        key=lambda c: c["confidence"] * c["count"],
    )
    return top_contributor["name"], f"{best['label']} (via {top_contributor['name']})"


# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------

def _get_device_identity(
    cpe_dir: Path,
    serial: str,
    telemetry_reports: Optional[List[Dict[str, Any]]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    identity: Dict[str, Any] = {"cpe_serial": serial}
    try:
        version_info = find_and_parse_version_txt(cpe_dir, force=force)
        if version_info:
            fw_list = version_info.get("firmware_versions", [])
            if fw_list:
                identity["firmware"] = fw_list[-1].get("image_name", "")
            identity["model"] = version_info.get("machine_name", "")
    except Exception:
        pass
    try:
        fallback = find_and_build_fallback_device_info(cpe_dir, force=force)
        if fallback:
            identity.setdefault("mac", fallback.get("mac", ""))
            if not identity.get("model"):
                identity["model"] = fallback.get("model", "")
            if not identity.get("firmware"):
                identity.setdefault("firmware", fallback.get("version", ""))
    except Exception:
        pass
    if not identity.get("mac") and telemetry_reports:
        for r in telemetry_reports:
            mac = r.get("mac", "")
            if mac:
                identity["mac"] = mac.replace(":", "").lower()
                break
    return identity


def _ts_to_str(ts: Any, fallback: str = "") -> str:
    """Convert a time value to an ISO string, handling both datetime and str."""
    if ts is None:
        return fallback
    if isinstance(ts, str):
        return ts
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)


def _detect_uptime_resets(reports: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    if len(reports) < 2:
        return []
    resets = []
    prev = reports[0]
    for cur in reports[1:]:
        prev_up = prev.get("uptime", 0) or 0
        cur_up = cur.get("uptime", 0) or 0
        if isinstance(prev_up, (int, float)) and isinstance(cur_up, (int, float)):
            if cur_up < prev_up and prev_up > 300:
                ts_str = _ts_to_str(cur.get("time"), cur.get("log_timestamp", ""))
                resets.append({"timestamp": ts_str, "reason": "uptime_reset_detected"})
        prev = cur
    return resets


# ---------------------------------------------------------------------------
# Telemetry time-series extraction
# ---------------------------------------------------------------------------

def _extract_telemetry_timeseries(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    ts_data: Dict[str, List] = {
        "timestamps": [],
        "cpu": [], "memory_pct": [], "memory_free": [], "memory_total": [],
        "memory_available": [], "shmem": [], "slab_memory": [],
        "temperature": [], "uptime": [], "connected_devices": [],
    }
    for iface, fields in _RXTX_FIELDS.items():
        for metric in fields:
            ts_data[f"{iface}_{metric}"] = []

    for r in reports:
        fields = r.get("fields", {})
        ts_str = _ts_to_str(r.get("time"), r.get("log_timestamp", ""))
        ts_data["timestamps"].append(ts_str)

        cpu_raw = fields.get("Device.DeviceInfo.ProcessStatus.CPUUsage",
                             fields.get("CPUUsage"))
        ts_data["cpu"].append(_safe_int(cpu_raw))

        mem_free = _safe_int(fields.get("Device.DeviceInfo.MemoryStatus.Free",
                                        fields.get("MemInfoFree")))
        mem_total = _safe_int(fields.get("Device.DeviceInfo.MemoryStatus.Total",
                                         fields.get("MemInfoTotal")))
        ts_data["memory_free"].append(mem_free)
        ts_data["memory_total"].append(mem_total)
        if mem_free is not None and mem_total and mem_total > 0:
            ts_data["memory_pct"].append(round((mem_total - mem_free) / mem_total * 100, 1))
        else:
            ts_data["memory_pct"].append(None)

        mem_avail = _safe_int(fields.get("Device.DeviceInfo.MemoryStatus.Available",
                                         fields.get("meminfoavailable_split")))
        ts_data["memory_available"].append(mem_avail)

        shmem = _safe_int(fields.get("Device.DeviceInfo.MemoryStatus.SharedMemory",
                                     fields.get("shmem_split")))
        ts_data["shmem"].append(shmem)

        slab = _safe_int(fields.get("Device.DeviceInfo.MemoryStatus.SlabMemory",
                                    fields.get("slab_memory_split")))
        ts_data["slab_memory"].append(slab)

        ts_data["temperature"].append(_safe_float(fields.get("cpu_temp_split")))
        ts_data["uptime"].append(r.get("uptime") or None)

        cd = fields.get("Device.Hosts.X_CISCO_COM_ConnectedDeviceNumber",
                        fields.get("hosts_connected_device_number"))
        ts_data["connected_devices"].append(_safe_int(cd))

        for iface, metrics in _RXTX_FIELDS.items():
            for metric, key_aliases in metrics.items():
                val = None
                for alias in key_aliases:
                    v = fields.get(alias)
                    if v is not None:
                        val = _safe_int(v)
                        break
                ts_data[f"{iface}_{metric}"].append(val)

    # Delta rates for RX/TX
    rate_data: Dict[str, List] = {}
    for iface, metrics in _RXTX_FIELDS.items():
        for metric in metrics:
            series_key = f"{iface}_{metric}"
            rate_key = f"{iface}_{metric}_rate"
            values = ts_data[series_key]
            timestamps = ts_data["timestamps"]
            rates: List[Optional[float]] = [None]
            for i in range(1, len(values)):
                if values[i] is not None and values[i - 1] is not None:
                    dt_prev = _parse_ts(timestamps[i - 1])
                    dt_curr = _parse_ts(timestamps[i])
                    if dt_prev and dt_curr:
                        delta_sec = (dt_curr - dt_prev).total_seconds()
                        if delta_sec > 0:
                            delta_val = values[i] - values[i - 1]
                            rates.append(round(delta_val / delta_sec, 1) if delta_val >= 0 else None)
                        else:
                            rates.append(None)
                    else:
                        rates.append(None)
                else:
                    rates.append(None)
            rate_data[rate_key] = rates

    ts_data.update(rate_data)

    snapshot = {}
    if reports:
        last_fields = reports[-1].get("fields", {})
        snapshot["gpon"] = _extract_snapshot(last_fields, [
            "gpon_connectionStatus", "gpon_rxSignalLevel", "gpon_txSignalLevel",
            "gpon_signalDegrade", "gpon_signalFail", "gpon_framesLost",
            "gpon_downstreamSpeed", "gpon_upstreamSpeed",
        ])
        snapshot["wan"] = _extract_snapshot(last_fields, [
            "wanoe_connectionStatus", "wanoe_lastConnError",
            "wanoe_downstreamSpeed", "wanoe_upstreamSpeed",
            "ppp_interface_1_status", "wan_access_mode_split",
        ])
        snapshot["wifi"] = _extract_snapshot(last_fields, [
            "wifi_radio_1_channel", "wifi_radio_2_channel",
            "wifi_radio_1_stats_noise", "wifi_radio_2_stats_noise",
            "wifi_radio_1_transmitpower", "wifi_radio_2_transmitpower",
            "wifi_radio_1_status", "wifi_radio_2_status",
            "wifi_radio_1_operatingfrequencyband", "wifi_radio_2_operatingfrequencyband",
        ])
    ts_data["snapshot"] = snapshot
    return ts_data


def _extract_snapshot(fields: Dict, keys: List[str]) -> Dict[str, Any]:
    return {k: fields[k] for k in keys if fields.get(k) is not None}


# ---------------------------------------------------------------------------
# Subgraph resolution
# ---------------------------------------------------------------------------

def _resolve_subgraph_nodes(
    graph_def: Dict[str, Any],
    node_evidence: Dict[str, Dict[str, Any]],
    cpe_dir: Optional[Path] = None,
    all_events: Optional[pd.DataFrame] = None,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    evaluation_stack: Optional[set] = None,
) -> None:
    """Recursively evaluate SUBGRAPH nodes and populate *node_evidence*.

    For each SUBGRAPH node whose referenced graph was resolved at load
    time (``_resolved_subgraph``), run the full detection + evaluation
    pipeline on the referenced graph using the *same* CPE log data.
    The resulting activation is injected into *node_evidence* so the
    parent graph's edge evaluation sees the SUBGRAPH node as if it were
    a regular EVENT node.
    """
    use_rg = _RG_BIN and cpe_dir

    if evaluation_stack is None:
        evaluation_stack = set()
    parent_id = graph_def.get("id", "")
    evaluation_stack = evaluation_stack | {parent_id}

    for node in graph_def["nodes"]:
        if node["node_type"] != "SUBGRAPH":
            continue
        cfg = node.get("detection_config") or {}
        ref_id = cfg.get("referenced_graph_id")
        if not ref_id or ref_id in evaluation_stack:
            continue
        sub_def = node.get("_resolved_subgraph")
        if not sub_def:
            continue

        sub_event_nodes = [n for n in sub_def["nodes"] if n["node_type"] == "EVENT"]
        sub_compiled: Dict[str, Tuple[List[re.Pattern], List[re.Pattern]]] = {}
        for sn in sub_event_nodes:
            sub_compiled[sn["id"]] = _compile_node_patterns(sn)

        sub_evidence: Dict[str, Dict[str, Any]] = {}
        sub_needs_parquet = any(_detection_uses_parquet(sn) for sn in sub_event_nodes)
        sub_df = all_events
        if sub_needs_parquet or not use_rg:
            if sub_df is None or getattr(sub_df, "empty", True):
                sub_df = _load_all_parquet_events(cpe_dir) if cpe_dir else pd.DataFrame()
        if sub_df is None:
            sub_df = pd.DataFrame()

        sub_rg_nodes = [
            sn for sn in sub_event_nodes
            if use_rg and not _detection_uses_parquet(sn)
        ]
        sub_rg_ids = {sn["id"] for sn in sub_rg_nodes}
        sub_unified = (
            _unified_rg_matches_for_nodes(cpe_dir, sub_rg_nodes)
            if (cpe_dir and sub_rg_nodes)
            else []
        )

        for sn in sub_event_nodes:
            if sn["id"] in sub_rg_ids:
                continue
            pats, excl = sub_compiled[sn["id"]]
            sub_evidence[sn["id"]] = _detect_events_for_node(
                sn, sub_df, pats, excl, window_start, window_end,
            )
        if sub_rg_nodes:
            sub_evidence.update(
                _classify_unified_rg_matches(
                    sub_unified, sub_rg_nodes, sub_compiled,
                    window_start, window_end,
                )
            )

        _resolve_subgraph_nodes(
            sub_def, sub_evidence, cpe_dir=cpe_dir,
            all_events=all_events,
            window_start=window_start, window_end=window_end,
            evaluation_stack=evaluation_stack,
        )

        sub_G = build_networkx_graph(sub_def)
        sub_result = _evaluate_graph(sub_G, sub_evidence)

        activated = sub_result.get("activated_issues") or {}
        activation_mode = cfg.get("activation_mode", "any_issue")

        if activation_mode == "all_issues":
            issue_ids = [
                nid for nid, ndata in sub_G.nodes(data=True)
                if ndata.get("node_type") in ("ISSUE", "ROOT_CAUSE")
            ]
            all_fired = issue_ids and all(i in activated for i in issue_ids)
            if not all_fired:
                activated = {}

        if activated:
            total_count = sum(
                a.get("total_evidence_count", 0) for a in activated.values()
            )
            max_conf = max(
                a.get("max_confidence", 0) for a in activated.values()
            )
            sample_lines: List[str] = []
            for a in activated.values():
                for ce in a.get("contributing_events", []):
                    sample_lines.append(
                        f"[subgraph:{sub_def['name']}] {ce.get('name','')}: "
                        f"count={ce.get('count',0)}"
                    )
            node_evidence[node["id"]] = {
                "count": total_count,
                "confidence": max_conf,
                "sample_lines": sample_lines[:10],
                "timestamps": [],
                "rdk_modules": [],
                "subgraph_name": sub_def.get("name", ""),
                "subgraph_result": sub_result,
            }


# ---------------------------------------------------------------------------
# Per-CPE analysis
# ---------------------------------------------------------------------------

def analyze_cpe(
    cpe_dir: Path,
    serial: str,
    graph_def: Dict[str, Any],
    project_id: str = "",
    job_id: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    """
    Graph-driven per-CPE analysis.

    Detects events using ripgrep (preferred) or parquet fallback,
    evaluates causal edges from the knowledge graph, and produces a
    result structure for the IssueAnalysisPage frontend.

    Args:
        force: When True, bypass telemetry / device-info caches and
            re-parse from raw files.
    """
    t0 = time.time()
    use_rg = bool(_RG_BIN)

    G = build_networkx_graph(graph_def)

    event_nodes = [n for n in graph_def["nodes"] if n["node_type"] == "EVENT"]
    compiled_map: Dict[str, Tuple[List[re.Pattern], List[re.Pattern]]] = {}
    for n in event_nodes:
        compiled_map[n["id"]] = _compile_node_patterns(n)

    needs_parquet = (not use_rg) or any(
        _detection_uses_parquet(n) for n in event_nodes
    )
    parquet_events: Optional[pd.DataFrame] = (
        _load_all_parquet_events(cpe_dir) if needs_parquet else None
    )
    if parquet_events is not None and parquet_events.empty:
        parquet_events = None

    # Telemetry (uses raw cache when available)
    t2_path = cpe_dir / "telemetry2_0.txt"
    dcm_path = cpe_dir / "dcmscript.log"
    tel_reports, tel_merged, tel_summary, tel_source = parse_telemetry_file(
        t2_path, dcmscript_path=dcm_path, cpe_dir=cpe_dir, force=force,
    )
    
    # Identity (uses caches when available)
    identity = _get_device_identity(cpe_dir, serial, telemetry_reports=tel_reports, force=force)
    identity["project_id"] = project_id
    identity["job_id"] = job_id

    # Reboot events
    reboots = find_and_extract_reboots(cpe_dir)
    uptime_reboots = _detect_uptime_resets(tel_reports)
    existing_ts = {r["timestamp"][:16] for r in reboots}
    for ur in uptime_reboots:
        if ur["timestamp"][:16] not in existing_ts:
            reboots.append({"timestamp": ur["timestamp"], "reason": ur["reason"]})
    reboots.sort(key=lambda r: r.get("timestamp", ""))

    all_events: Optional[pd.DataFrame] = parquet_events

    rg_nodes = [n for n in event_nodes if use_rg and not _detection_uses_parquet(n)]
    rg_node_ids = {n["id"] for n in rg_nodes}
    unified_rg_matches: List[Dict[str, Any]] = (
        _unified_rg_matches_for_nodes(cpe_dir, rg_nodes) if rg_nodes else []
    )

    # -- Global evidence (across all time) --
    global_evidence: Dict[str, Dict[str, Any]] = {}
    for n in event_nodes:
        if n["id"] in rg_node_ids:
            continue
        pats, excl = compiled_map[n["id"]]
        df = parquet_events if parquet_events is not None else pd.DataFrame()
        global_evidence[n["id"]] = _detect_events_for_node(
            n, df, pats, excl,
        )
    if rg_nodes:
        global_evidence.update(
            _classify_unified_rg_matches(
                unified_rg_matches, rg_nodes, compiled_map,
            )
        )

    # Resolve SUBGRAPH nodes (recursive evaluation of referenced graphs)
    _resolve_subgraph_nodes(
        graph_def, global_evidence, cpe_dir=cpe_dir, all_events=all_events,
    )

    # Global graph evaluation
    global_graph_eval = _evaluate_graph(G, global_evidence)

    # -- Per-reboot windowed analysis --
    reboot_analyses = []
    for rb in reboots:
        rb_ts = _parse_ts(rb.get("timestamp", ""))
        if not rb_ts:
            reboot_analyses.append({
                "timestamp": rb.get("timestamp", ""),
                "reason": rb.get("reason", ""),
                "window_events": {},
                "likely_trigger": "unknown",
                "trigger_description": "Could not parse reboot timestamp",
                "total_events_in_window": 0,
            })
            continue

        win_start = rb_ts - timedelta(minutes=REBOOT_WINDOW_BEFORE_MIN)
        win_end = rb_ts + timedelta(minutes=REBOOT_WINDOW_AFTER_MIN)

        window_evidence: Dict[str, Dict[str, Any]] = {}
        for n in event_nodes:
            if n["id"] in rg_node_ids:
                continue
            pats, excl = compiled_map[n["id"]]
            df = parquet_events if parquet_events is not None else pd.DataFrame()
            window_evidence[n["id"]] = _detect_events_for_node(
                n, df, pats, excl, win_start, win_end,
            )
        if rg_nodes:
            window_evidence.update(
                _classify_unified_rg_matches(
                    unified_rg_matches, rg_nodes, compiled_map,
                    win_start, win_end,
                )
            )

        _resolve_subgraph_nodes(
            graph_def, window_evidence, cpe_dir=cpe_dir,
            all_events=all_events,
            window_start=win_start, window_end=win_end,
        )

        # Convert to name-keyed dict for backward compat with frontend
        window_events: Dict[str, Dict[str, Any]] = {}
        for n in event_nodes:
            ev = window_evidence[n["id"]]
            window_events[n["name"]] = {
                "count": ev["count"],
                "sample_lines": ev["sample_lines"],
                "timestamps": ev["timestamps"],
                "rdk_modules": ev.get("rdk_modules", []),
            }
        for n in graph_def["nodes"]:
            if n["node_type"] == "SUBGRAPH" and n["id"] in window_evidence:
                ev = window_evidence[n["id"]]
                window_events[n["name"]] = {
                    "count": ev["count"],
                    "sample_lines": ev.get("sample_lines", []),
                    "timestamps": ev.get("timestamps", []),
                }

        window_graph_eval = _evaluate_graph(G, window_evidence)
        trigger, trigger_desc = _determine_likely_trigger(
            window_evidence, window_graph_eval, G,
        )

        reboot_analyses.append({
            "timestamp": rb.get("timestamp", ""),
            "reason": rb.get("reason", ""),
            "window": {"start": win_start.isoformat(), "end": win_end.isoformat()},
            "window_events": window_events,
            "likely_trigger": trigger,
            "trigger_description": trigger_desc,
            "total_events_in_window": sum(
                ev.get("count", 0) for ev in window_events.values()
            ),
        })

    # Telemetry time-series
    telemetry_ts = _extract_telemetry_timeseries(tel_reports) if tel_reports else {}

    # Memory summary
    mem_pcts = [v for v in telemetry_ts.get("memory_pct", []) if v is not None]
    memory_summary = {}
    if mem_pcts:
        memory_summary = {
            "avg_pct": round(sum(mem_pcts) / len(mem_pcts), 1),
            "peak_pct": round(max(mem_pcts), 1),
            "min_pct": round(min(mem_pcts), 1),
            "samples": len(mem_pcts),
        }

    # Aggregate issues
    aggregate_issues: Dict[str, int] = defaultdict(int)
    for ra in reboot_analyses:
        for cat, ev in ra.get("window_events", {}).items():
            aggregate_issues[cat] += ev.get("count", 0)

    # Causal chains from global analysis
    chains = global_graph_eval.get("causal_chains", [])
    activated_issues = global_graph_eval.get("activated_issues", {})

    # Root cause ranking
    root_causes = []
    for nid, info in activated_issues.items():
        score = info["max_confidence"] * min(info["total_evidence_count"], 100) / 100
        root_causes.append({
            "node_id": nid,
            "name": info["name"],
            "label": info["label"],
            "node_type": info["node_type"],
            "confidence": info["max_confidence"],
            "evidence_count": info["total_evidence_count"],
            "score": round(score, 3),
            "contributing_events": info["contributing_events"],
        })
    root_causes.sort(key=lambda x: x["score"], reverse=True)

    _apply_module_plausibility_to_chains_and_roots(chains, root_causes, G, event_nodes, global_evidence)

    from logai.template_flow import build_template_flow_summary

    template_flow_summary = build_template_flow_summary(
        cpe_dir,
        reboots,
        before_min=REBOOT_WINDOW_BEFORE_MIN,
        after_min=REBOOT_WINDOW_AFTER_MIN,
        parquet_df=parquet_events,
    )

    elapsed_ms = round((time.time() - t0) * 1000)

    return {
        "identity": identity,
        "telemetry_source": tel_source,
        "total_reboots": len(reboots),
        "reboots": reboot_analyses,
        "telemetry_timeseries": telemetry_ts,
        "memory_summary": memory_summary,
        "aggregate_issues": dict(aggregate_issues),
        "causal_chains": chains,
        "root_causes": root_causes,
        "graph_name": graph_def.get("name", ""),
        "analysis_elapsed_ms": elapsed_ms,
        "template_flow": template_flow_summary,
    }


# ---------------------------------------------------------------------------
# Fleet aggregate
# ---------------------------------------------------------------------------

def build_fleet_report(
    per_cpe_records: List[Dict[str, Any]],
    graph_def: Dict[str, Any],
    project_id: str = "",
    job_id: str = "",
) -> Dict[str, Any]:
    total_cpes = len(per_cpe_records)
    if total_cpes == 0:
        return {"error": "No CPE records", "total_cpes": 0}

    models: Counter = Counter()
    firmwares: Counter = Counter()
    total_reboots = 0
    cpes_with_reboots = 0
    trigger_dist: Counter = Counter()
    telemetry_sources: Counter = Counter()
    category_cpe_counts: Dict[str, int] = defaultdict(int)
    category_event_counts: Dict[str, int] = defaultdict(int)
    worst_wifi: List[Dict] = []
    worst_wan: List[Dict] = []
    worst_memory: List[Dict] = []
    root_cause_dist: Counter = Counter()

    wifi_cats = {"wifi_disconnect_storm", "btm_steering", "dfs_channel_switch", "wifi_driver_errors"}
    wan_cats = {"wan_disconnections"}

    for rec in per_cpe_records:
        ident = rec.get("identity", {})
        serial = ident.get("cpe_serial", "")
        model = ident.get("model", "unknown") or "unknown"
        fw = ident.get("firmware", "unknown") or "unknown"
        models[model] += 1
        firmwares[fw] += 1
        telemetry_sources[rec.get("telemetry_source", "unknown")] += 1

        n_reboots = rec.get("total_reboots", 0)
        total_reboots += n_reboots
        if n_reboots > 0:
            cpes_with_reboots += 1

        for ra in rec.get("reboots", []):
            trigger_dist[ra.get("likely_trigger", "unknown")] += 1

        agg = rec.get("aggregate_issues", {})
        for cat, count in agg.items():
            if count > 0:
                category_cpe_counts[cat] += 1
                category_event_counts[cat] += count

        wifi_total = sum(agg.get(c, 0) for c in wifi_cats)
        if wifi_total > 0:
            worst_wifi.append({"serial": serial, "total_events": wifi_total})

        wan_total = sum(agg.get(c, 0) for c in wan_cats)
        if wan_total > 0:
            worst_wan.append({"serial": serial, "total_events": wan_total})

        mem = rec.get("memory_summary", {})
        if mem.get("peak_pct", 0) > 85:
            worst_memory.append({
                "serial": serial,
                "avg_pct": mem.get("avg_pct"),
                "peak_pct": mem.get("peak_pct"),
            })

        for rc in rec.get("root_causes", []):
            root_cause_dist[rc["name"]] += 1

    worst_wifi.sort(key=lambda x: x["total_events"], reverse=True)
    worst_wan.sort(key=lambda x: x["total_events"], reverse=True)
    worst_memory.sort(key=lambda x: x.get("peak_pct", 0), reverse=True)

    pct = lambda n: round(n / total_cpes * 100, 1) if total_cpes else 0

    event_nodes = [
        n for n in graph_def.get("nodes", [])
        if n["node_type"] in ("EVENT", "SUBGRAPH")
    ]

    return {
        "project_id": project_id,
        "job_id": job_id,
        "graph_name": graph_def.get("name", ""),
        "generated_at": datetime.utcnow().isoformat(),
        "total_cpes": total_cpes,
        "hardware_breakdown": dict(models),
        "firmware_breakdown": dict(firmwares),
        "reboot_overview": {
            "total_reboots": total_reboots,
            "cpes_with_reboots": cpes_with_reboots,
            "pct_with_reboots": pct(cpes_with_reboots),
            "avg_reboots_per_cpe": round(total_reboots / max(cpes_with_reboots, 1), 1),
        },
        "trigger_distribution": dict(trigger_dist.most_common()),
        "issue_categories": {
            n["name"]: {
                "cpes_affected": category_cpe_counts.get(n["name"], 0),
                "pct_affected": pct(category_cpe_counts.get(n["name"], 0)),
                "total_events": category_event_counts.get(n["name"], 0),
            }
            for n in event_nodes
        },
        "problem_areas": {
            "wifi": {
                "cpes_affected": len(worst_wifi),
                "pct_affected": pct(len(worst_wifi)),
                "worst_case": worst_wifi[:5],
            },
            "wan": {
                "cpes_affected": len(worst_wan),
                "pct_affected": pct(len(worst_wan)),
                "worst_case": worst_wan[:5],
            },
            "memory": {
                "cpes_above_85pct": len(worst_memory),
                "pct_above_85pct": pct(len(worst_memory)),
                "worst_case": worst_memory[:5],
            },
        },
        "root_cause_distribution": dict(root_cause_dist.most_common()),
        "telemetry_source_distribution": dict(telemetry_sources),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _atomic_json_write(
    path: Path, data: Any, indent: Optional[int] = None,
) -> None:
    """Write JSON to *path* atomically via a temp file + rename.

    This prevents readers from seeing a half-written file when the writer
    is still serialising (the race condition that causes JSONDecodeError
    when the API reads while Celery is writing).
    """
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=path.stem + "_",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent, default=_json_serial)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def generate_batch_analysis(
    project_dir: Path,
    project_id: str,
    job_id: str,
    graph_id: str = "",
    graph_def: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Generate analysis for a batch job using the specified knowledge graph.

    Accepts either a pre-loaded ``graph_def`` dict (preferred when called
    from Celery where the caller already has an app context) or a
    ``graph_id`` to load from the database (requires Flask app context).
    """
    t0 = time.time()
    if graph_def is None:
        graph_def = load_graph_definition(graph_id)

    use_rg = bool(_RG_BIN)

    output_dir = project_dir / OUTPUT_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    cpe_dirs = sorted([
        d for d in project_dir.iterdir()
        if d.is_dir()
        and d.name != OUTPUT_DIR_NAME
        and not d.name.startswith(".")
    ])

    per_cpe_records = []
    for cpe_dir in cpe_dirs:
        serial = cpe_dir.name
        if not use_rg and not any(cpe_dir.glob("*_rg.parquet")):
            continue

        try:
            record = analyze_cpe(
                cpe_dir, serial, graph_def, project_id, job_id,
                force=force,
            )
            per_cpe_records.append(record)
            logger.info(
                f"[GraphAnalyzer] {serial}: "
                f"{record['total_reboots']} reboots, "
                f"source={record['telemetry_source']}, "
                f"{record['analysis_elapsed_ms']}ms"
            )
        except Exception as exc:
            logger.error(f"[GraphAnalyzer] Error analyzing {serial}: {exc}", exc_info=True)

    per_cpe_path = output_dir / PER_CPE_FILE
    _atomic_json_write(per_cpe_path, per_cpe_records)

    fleet = build_fleet_report(per_cpe_records, graph_def, project_id, job_id)
    fleet_path = output_dir / FLEET_FILE
    _atomic_json_write(fleet_path, fleet, indent=2)

    elapsed = round(time.time() - t0, 1)
    logger.info(
        f"[GraphAnalyzer] Batch analysis complete: "
        f"{len(per_cpe_records)} CPEs in {elapsed}s"
    )

    return {
        "per_cpe_path": str(per_cpe_path),
        "fleet_path": str(fleet_path),
        "total_cpes": len(per_cpe_records),
        "elapsed_sec": elapsed,
        "graph_name": graph_def.get("name", ""),
    }


def load_analysis_outputs(project_dir: Path) -> Dict[str, Any]:
    """Load previously generated analysis files."""
    output_dir = project_dir / OUTPUT_DIR_NAME
    result: Dict[str, Any] = {"available": False}

    fleet_path = output_dir / FLEET_FILE
    per_cpe_path = output_dir / PER_CPE_FILE

    if fleet_path.exists():
        try:
            with open(fleet_path) as f:
                result["fleet_report"] = json.load(f)
            result["available"] = True
        except json.JSONDecodeError as exc:
            logger.error(f"[GraphAnalyzer] Failed to load fleet report: {exc}")
            # Try to recover by returning partial data
            result["available"] = False

    if per_cpe_path.exists():
        try:
            with open(per_cpe_path) as f:
                per_cpe_list = json.load(f)
            result["per_cpe_count"] = len(per_cpe_list)
            result["per_cpe_serials"] = [
                r.get("identity", {}).get("cpe_serial", "")
                for r in per_cpe_list
            ]
        except json.JSONDecodeError as exc:
            logger.error(
                f"[GraphAnalyzer] Failed to load per-CPE analysis at "
                f"position {exc.pos}: {exc.msg}"
            )
            # If per-CPE fails but fleet exists, still mark as available
            if result.get("fleet_report"):
                result["per_cpe_count"] = 0
                result["per_cpe_serials"] = []

    return result


def load_cpe_analysis(project_dir: Path, cpe_serial: str) -> Optional[Dict[str, Any]]:
    """Load a single CPE's analysis data."""
    per_cpe_path = project_dir / OUTPUT_DIR_NAME / PER_CPE_FILE
    if not per_cpe_path.exists():
        return None

    try:
        with open(per_cpe_path) as f:
            records = json.load(f)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(
            f"[GraphAnalyzer] Corrupt per-CPE JSON at {per_cpe_path}: {exc}"
        )
        return None

    for rec in records:
        if rec.get("identity", {}).get("cpe_serial", "") == cpe_serial:
            return rec
    return None

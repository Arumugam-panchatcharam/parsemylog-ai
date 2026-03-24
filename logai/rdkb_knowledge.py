"""
RDK-B curated module graph loader and log-to-module resolution.

Data: ``configs/rdkb_module_graph.yaml`` (versioned, auditable).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from logai.utils.constants import BASE_DIR

logger = logging.getLogger(__name__)

_DEFAULT_GRAPH_PATH = Path(BASE_DIR) / "configs" / "rdkb_module_graph.yaml"


@lru_cache(maxsize=1)
def load_module_graph(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and validate the module graph YAML. Cached by path."""
    p = Path(path) if path else _DEFAULT_GRAPH_PATH
    if not p.is_file():
        logger.warning("[rdkb_knowledge] Module graph not found at %s", p)
        return {
            "version": 0,
            "nodes": [],
            "edges": [],
            "architecture_references": [],
        }
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    seen: Set[str] = set()
    for n in nodes:
        mid = n.get("module_id")
        if mid:
            seen.add(mid)
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s not in seen or t not in seen:
            logger.debug(
                "[rdkb_knowledge] Edge %s -> %s references unknown module",
                s,
                t,
            )
    return {
        "version": data.get("version", 0),
        "nodes": nodes,
        "edges": edges,
        "architecture_references": data.get("architecture_references") or [],
    }


def clear_module_graph_cache() -> None:
    """Invalidate cached graph (tests)."""
    load_module_graph.cache_clear()


def _normalize_domain(domain: str) -> str:
    return (domain or "").strip().lower().replace(" ", "_")


def resolve_modules(
    domain: str,
    source_file: str,
    template: str,
    logline: str,
    graph: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Return matching modules for a log row (0..n), each
    ``{module_id, display_name, match_reason}``.
    """
    g = graph if graph is not None else load_module_graph()
    nodes = g.get("nodes") or []
    dom = _normalize_domain(domain)
    text = f"{template}\n{logline}\n{source_file}".lower()
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for n in nodes:
        mid = n.get("module_id")
        if not mid or mid in seen:
            continue
        primary = [_normalize_domain(d) for d in (n.get("primary_domains") or [])]
        if primary and dom and dom not in primary:
            continue
        hints = n.get("log_hints") or []
        for h in hints:
            if not h:
                continue
            if h.lower() in text:
                seen.add(mid)
                out.append(
                    {
                        "module_id": mid,
                        "display_name": n.get("display_name", mid),
                        "match_reason": f"log_hint:{h}",
                    }
                )
                break

    return out


def build_undirected_adjacency(graph: Optional[Dict[str, Any]] = None) -> Dict[str, Set[str]]:
    """Adjacency for architectural distance (depends_on + ipc + data_path + correlates_with)."""
    g = graph if graph is not None else load_module_graph()
    adj: Dict[str, Set[str]] = {}
    for e in g.get("edges") or []:
        s, t = e.get("source"), e.get("target")
        if not s or not t:
            continue
        adj.setdefault(s, set()).add(t)
        adj.setdefault(t, set()).add(s)
    return adj


def module_distance(a: str, b: str, graph: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """BFS shortest path length in undirected architectural graph; None if disconnected."""
    if a == b:
        return 0
    adj = build_undirected_adjacency(graph)
    if a not in adj or b not in adj:
        return None
    frontier = [(a, 0)]
    visited = {a}
    while frontier:
        cur, d = frontier.pop(0)
        for nb in adj.get(cur, ()):
            if nb == b:
                return d + 1
            if nb not in visited:
                visited.add(nb)
                frontier.append((nb, d + 1))
    return None


def chain_module_plausibility(
    module_ids: List[str],
    max_good_distance: int = 3,
    graph: Optional[Dict[str, Any]] = None,
) -> float:
    """
    Soft score in [0.35, 1.0] from consecutive module pairs in an ordered list.
    Disconnected pairs get a penalty; single module or empty -> neutral 0.85.
    """
    mids = [m for m in module_ids if m]
    if len(mids) <= 1:
        return 0.85
    scores: List[float] = []
    for i in range(len(mids) - 1):
        dist = module_distance(mids[i], mids[i + 1], graph=graph)
        if dist is None:
            scores.append(0.5)
        elif dist <= max_good_distance:
            scores.append(1.0)
        else:
            scores.append(max(0.35, 1.0 - (dist - max_good_distance) * 0.15))
    return sum(scores) / len(scores) if scores else 0.85


def plausibility_for_causal_chain(
    chain_path_names: List[str],
    name_to_modules: Dict[str, List[str]],
    graph: Optional[Dict[str, Any]] = None,
) -> float:
    """
    Map graph node *names* to module ids (first resolved module per node) and score chain.
    """
    mids: List[str] = []
    for name in chain_path_names:
        mods = name_to_modules.get(name) or []
        if mods:
            mids.append(mods[0])
    return chain_module_plausibility(mids, graph=graph)

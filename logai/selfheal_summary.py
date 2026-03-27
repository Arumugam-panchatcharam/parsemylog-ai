"""
Deterministic narrative summaries for SelfHeal single-CPE and Cross-CPE views.

Thresholds are documented and shared with docs/features/SELFHEAL_ANALYSIS.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SUMMARY_SCHEMA_VERSION = 1

# --- Thresholds (fleet / single-CPE) ---
MEM_AVAILABLE_PRESSURE_PCT = 15.0
OOM_OVERCOMMIT_RATIO = 0.9
KERNEL_SUNRECLAIM_PCT_WARN = 50.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_pct(v: Optional[float], digits: int = 1) -> str:
    if v is None:
        return "N/A"
    return f"{round(float(v), digits)}%"


def _memory_status_label(
    alerts: List[str],
    pressure_score: Optional[float],
    mem_min_pct: Optional[float],
) -> str:
    if "KERNEL_LEAK" in alerts or "OVERCOMMIT_RISK" in alerts:
        return "Critical"
    if pressure_score is not None and pressure_score >= 70:
        return "Critical"
    if mem_min_pct is not None and mem_min_pct < 10:
        return "Critical"
    if (
        "LOW_MEMORY" in alerts
        or "NO_SWAP" in alerts
        or (pressure_score is not None and pressure_score >= 40)
        or (mem_min_pct is not None and mem_min_pct < MEM_AVAILABLE_PRESSURE_PCT)
    ):
        return "Degrading"
    return "Healthy"


def _single_cpe_conclusion(
    alerts: List[str], mp: Dict[str, Any], top_procs: List[Dict[str, Any]]
) -> str:
    has_k = "KERNEL_LEAK" in alerts
    has_u = any(float(x.get("rss_trend_slope_kb") or 0) > 0 for x in top_procs)
    oc = mp.get("overcommit_ratio")
    oc_risk = oc is not None and float(oc) >= OOM_OVERCOMMIT_RATIO
    if has_k and has_u and oc_risk:
        return (
            "Combined kernel and user-space pressure with elevated commit — prioritize drivers/daemons and OOM mitigation."
        )
    if has_k and has_u:
        return "Kernel and user-space trends both present — check networking stack and top RSS processes."
    if has_k:
        return "Kernel-side memory signals — review slab/SUnreclaim and firmware."
    if oc_risk:
        return "High commit vs limit — OOM risk; reduce allocations or increase limits if applicable."
    if has_u:
        return "User-space RSS growth — focus on top trending processes."
    return "No severe combined signals in this capture; extend capture window if problems continue."


def build_single_cpe_summary(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build persisted narrative for one CPE from the parse API response dict.

    Returns:
        {"narrative_summary": {"plain_text", "generated_at_utc", "schema_version"}}
    """
    serial = (
        (response.get("device_info") or {}).get("serial")
        or "Unknown"
    )
    km = response.get("key_metrics") or {}
    mp = response.get("memory_pressure") or {}
    alerts = list(response.get("alerts") or [])
    top_procs: List[Dict[str, Any]] = list(response.get("top_processes") or [])

    mem_min_pct = km.get("mem_available_min_pct")
    mem_avg_pct = km.get("mem_available_avg_pct")
    pressure_score = mp.get("pressure_score_0_100")
    status_lbl = _memory_status_label(
        alerts,
        float(pressure_score) if pressure_score is not None else None,
        float(mem_min_pct) if mem_min_pct is not None else None,
    )

    lines: List[str] = [
        f"CPE: {serial}",
        "",
        f"Memory status: {status_lbl}",
        "",
        "Highlights:",
        f"- MemAvailable (min / avg vs MemTotal): {_fmt_pct(float(mem_min_pct) if mem_min_pct is not None else None)} / {_fmt_pct(float(mem_avg_pct) if mem_avg_pct is not None else None)}",
    ]

    sun = mp.get("sunreclaim_pct")
    if sun is not None:
        lines.append(
            f"- SUnreclaim (% of slab): {round(float(sun), 1)}%"
            + (
                " — elevated (kernel unreclaimable)"
                if float(sun) > KERNEL_SUNRECLAIM_PCT_WARN
                else ""
            )
        )
    slab_slope = km.get("slab_ols_slope_kb_per_step")
    if slab_slope is not None and float(slab_slope) > 0:
        lines.append(
            f"- Slab growth (OLS slope): {float(slab_slope):.2f} KB per snapshot step"
        )

    oc = mp.get("overcommit_ratio")
    if oc is not None:
        risk = float(oc) >= OOM_OVERCOMMIT_RATIO
        lines.append(
            f"- Committed_AS / CommitLimit: {round(float(oc) * 100, 1)}% of limit"
            + (" — OOM risk" if risk else "")
        )

    cached = mp.get("cached_pct_of_memtotal")
    if cached is not None:
        lines.append(f"- Cached / MemTotal (avg): {round(float(cached), 1)}%")

    if alerts:
        lines.append(f"- Alerts: {', '.join(alerts)}")

    lines.extend(["", "CPU (sample window):", f"- Peak: {km.get('peak_cpu_usage_pct', 0)}%"])
    avg_cpu = km.get("avg_cpu_usage_pct")
    if avg_cpu is not None:
        lines.append(f"- Average: {round(float(avg_cpu), 1)}%")
    else:
        lines.append("- Average: N/A (no CPU samples)")

    lines.extend(["", "Top process RSS trends (by slope, KB per snapshot step):"])
    shown = 0
    for row in sorted(
        top_procs,
        key=lambda r: float(r.get("rss_trend_slope_kb") or 0),
        reverse=True,
    )[:5]:
        cmd = str(row.get("command") or "").strip()
        if not cmd:
            continue
        slope = row.get("rss_trend_slope_kb")
        if slope is None:
            continue
        lines.append(f"- {cmd}: {float(slope):.2f}")
        shown += 1
    if shown == 0:
        lines.append("- (none with positive trend in ranked list)")

    lines.extend(
        [
            "",
            "Conclusion:",
            _single_cpe_conclusion(alerts, mp, top_procs),
        ]
    )

    plain = "\n".join(lines)
    return {
        "narrative_summary": {
            "plain_text": plain,
            "generated_at_utc": _utc_now_iso(),
            "schema_version": SUMMARY_SCHEMA_VERSION,
        }
    }


def build_cross_cpe_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fleet narrative from cross-cpe-overview response body (before jsonify).

    payload keys: overview, cpes, fleet_process_leaks, fleet_meta (optional)
    """
    overview = payload.get("overview") or {}
    cpes: List[Dict[str, Any]] = list(payload.get("cpes") or [])
    leaks: List[Dict[str, Any]] = list(payload.get("fleet_process_leaks") or [])
    total = int(overview.get("total_cpes") or 0)
    if total <= 0:
        plain = "Cross-CPE overview: no CPEs with SelfHeal data."
        return {
            "narrative_summary": {
                "plain_text": plain,
                "generated_at_utc": _utc_now_iso(),
                "schema_version": SUMMARY_SCHEMA_VERSION,
            }
        }

    under_pressure = sum(
        1
        for c in cpes
        if c.get("mem_available_min_pct") is not None
        and float(c["mem_available_min_pct"]) < MEM_AVAILABLE_PRESSURE_PCT
    )
    pct_pressure = round(100.0 * under_pressure / total, 1)

    kernel_growth = sum(
        1
        for c in cpes
        if "KERNEL_LEAK" in (c.get("alerts") or [])
        or (
            c.get("sunreclaim_pct") is not None
            and float(c["sunreclaim_pct"]) > KERNEL_SUNRECLAIM_PCT_WARN
        )
        or (
            c.get("slab_ols_slope_kb_per_step") is not None
            and float(c["slab_ols_slope_kb_per_step"]) > 0
        )
    )
    pct_kernel = round(100.0 * kernel_growth / total, 1)

    oom_risk = sum(
        1
        for c in cpes
        if c.get("overcommit_ratio") is not None
        and float(c["overcommit_ratio"]) > OOM_OVERCOMMIT_RATIO
    )
    pct_oom = round(100.0 * oom_risk / total, 1)

    top_name = ""
    top_pct_devices = 0.0
    if leaks:
        row0 = leaks[0]
        top_name = str(row0.get("process") or "")
        aff = int(row0.get("cpes_affected") or 0)
        top_pct_devices = round(100.0 * aff / total, 1)

    lines = [
        f"Cross-CPE overview ({total} CPEs with SelfHeal data)",
        "",
        f"- {pct_pressure}% devices under memory pressure (min MemAvailable < {MEM_AVAILABLE_PRESSURE_PCT:g}% of MemTotal)",
        f"- {pct_kernel}% show kernel memory growth signals (KERNEL_LEAK alert, elevated SUnreclaim, or positive slab slope)",
    ]
    if top_name:
        lines.append(
            f"- Top leaking process (by fleet table): {top_name} (affects ~{top_pct_devices}% of devices)"
        )
    else:
        lines.append("- Top leaking process: (none above fleet threshold)")
    lines.append(
        f"- {pct_oom}% devices at OOM risk (Committed_AS / CommitLimit > {OOM_OVERCOMMIT_RATIO * 100:.0f}%)"
    )
    lines.extend(
        [
            "",
            "Recommendation:",
            _fleet_recommendation(top_name, pct_oom, pct_pressure),
        ]
    )

    plain = "\n".join(lines)
    return {
        "narrative_summary": {
            "plain_text": plain,
            "generated_at_utc": _utc_now_iso(),
            "schema_version": SUMMARY_SCHEMA_VERSION,
        }
    }


def _fleet_recommendation(top_process: str, pct_oom: float, pct_pressure: float) -> str:
    if top_process and pct_pressure > 10:
        return (
            f"Investigate systemic issues affecting {top_process} and memory headroom; "
            f"compare firmware builds and add targeted captures on worst cohorts."
        )
    if pct_oom > 5:
        return "Several devices show high commit vs limit — review OOM thresholds and workload growth."
    return "Monitor trends across releases; drill into single-CPE SelfHeal for outliers."

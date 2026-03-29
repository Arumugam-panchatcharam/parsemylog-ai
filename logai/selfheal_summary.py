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

    # 1. Fleet Distributions
    dist = {
        "mem_avail": {"critical": 0, "warning": 0, "caution": 0, "normal": 0},
        "cpu": {"warning": 0, "caution": 0, "normal": 0},
        "sunreclaim": {"critical": 0, "warning": 0, "caution": 0, "normal": 0},
        "overcommit": {"critical": 0, "warning": 0, "caution": 0, "normal": 0},
    }

    # 2. Quadrants
    quadrants = {"q1": 0, "q2": 0, "q3": 0, "q4": 0}

    for c in cpes:
        # MemAvailable
        mem_pct = c.get("mem_available_avg_pct")
        if mem_pct is not None:
            if mem_pct < 10: dist["mem_avail"]["critical"] += 1
            elif mem_pct < 20: dist["mem_avail"]["warning"] += 1
            elif mem_pct < 30: dist["mem_avail"]["caution"] += 1
            else: dist["mem_avail"]["normal"] += 1

        # CPU
        cpu_pct = c.get("avg_cpu_usage_pct")
        if cpu_pct is not None:
            if cpu_pct > 20: dist["cpu"]["warning"] += 1
            elif cpu_pct > 15: dist["cpu"]["caution"] += 1
            else: dist["cpu"]["normal"] += 1

        # SUnreclaim
        sun_pct = c.get("sunreclaim_pct")
        if sun_pct is not None:
            if sun_pct > 80: dist["sunreclaim"]["critical"] += 1
            elif sun_pct > 70: dist["sunreclaim"]["warning"] += 1
            elif sun_pct > 50: dist["sunreclaim"]["caution"] += 1
            else: dist["sunreclaim"]["normal"] += 1

        # Overcommit
        oc_ratio = c.get("overcommit_ratio")
        if oc_ratio is not None:
            if oc_ratio > 4: dist["overcommit"]["critical"] += 1
            elif oc_ratio > 2: dist["overcommit"]["warning"] += 1
            elif oc_ratio > 1: dist["overcommit"]["caution"] += 1
            else: dist["overcommit"]["normal"] += 1

        # Quadrants
        slab_slope = c.get("slab_ols_slope_kb_per_step")
        rss_slope = c.get("total_user_rss_ols_slope_kb_per_step")
        if slab_slope is not None and rss_slope is not None:
            if slab_slope > 0 and rss_slope > 0: quadrants["q1"] += 1
            elif slab_slope <= 0 and rss_slope > 0: quadrants["q2"] += 1
            elif slab_slope <= 0 and rss_slope <= 0: quadrants["q3"] += 1
            elif slab_slope > 0 and rss_slope <= 0: quadrants["q4"] += 1

    lines = [f"EXECUTIVE SUMMARY (FLEET) - {total} CPEs Analyzed\n"]

    # Section 1: Distributions
    lines.append("FLEET HEALTH DISTRIBUTIONS:")
    lines.append(f"  • MemAvailable: {dist['mem_avail']['critical']} Critical (<10%), {dist['mem_avail']['warning']} Warning (<20%), {dist['mem_avail']['caution']} Caution (<30%), {dist['mem_avail']['normal']} Normal")
    lines.append(f"  • CPU Usage: {dist['cpu']['warning']} Warning (>20%), {dist['cpu']['caution']} Caution (>15%), {dist['cpu']['normal']} Normal")
    lines.append(f"  • SUnreclaim: {dist['sunreclaim']['critical']} Critical (>80%), {dist['sunreclaim']['warning']} Warning (>70%), {dist['sunreclaim']['caution']} Caution (>50%), {dist['sunreclaim']['normal']} Normal")
    lines.append(f"  • Overcommit: {dist['overcommit']['critical']} Critical (>4x), {dist['overcommit']['warning']} Warning (>2x), {dist['overcommit']['caution']} Caution (>1x), {dist['overcommit']['normal']} Normal\n")

    # Section 2: Quadrants
    lines.append("SYSTEM MEMORY TRENDS (Slab vs RSS):")
    lines.append(f"  • Q1 (System leak - Slab ↑, RSS ↑): {quadrants['q1']} devices 🚨")
    lines.append(f"  • Q2 (App leak - Slab ↓, RSS ↑): {quadrants['q2']} devices ⚠️")
    lines.append(f"  • Q3 (Healthy - Slab ↓, RSS ↓): {quadrants['q3']} devices ✅")
    lines.append(f"  • Q4 (Kernel growth - Slab ↑, RSS ↓): {quadrants['q4']} devices ⚠️\n")

    # Section 3: Process Leaks
    lines.append("TOP LEAKING PROCESSES (FLEET):")
    if not leaks:
        lines.append("  • ✓ No fleet-wide memory leaks detected.")
    else:
        for i, leak in enumerate(leaks[:3]):
            proc = leak.get("process", "Unknown")
            cpes_affected = int(leak.get("cpes_affected", 0))
            spread_pct = (cpes_affected / total) * 100 if total > 0 else 0
            avg_slope = float(leak.get("avg_slope_kb", 0))
            max_slope = float(leak.get("max_slope_kb", 0))

            # Spread Class
            if spread_pct < 5: spread_class = "Isolated 🟢"
            elif spread_pct < 20: spread_class = "Limited 🟡"
            elif spread_pct < 50: spread_class = "Widespread 🟠"
            else: spread_class = "Systemic 🔴"

            # Avg Slope Class
            if avg_slope < 1: avg_class = "Noise 🟢"
            elif avg_slope < 3: avg_class = "Slow growth 🟡"
            elif avg_slope < 10: avg_class = "Moderate leak 🟠"
            else: avg_class = "Strong leak 🔴"

            # Max Slope Class
            if max_slope < 5: max_class = "Mild 🟢"
            elif max_slope < 15: max_class = "Noticeable 🟡"
            elif max_slope < 30: max_class = "Severe 🟠"
            else: max_class = "Critical 🔴"

            lines.append(f"  {i+1}. {proc} (affects {cpes_affected} devices, {spread_pct:.1f}%)")
            lines.append(f"     - Spread: {spread_class}")
            lines.append(f"     - Avg Slope: {avg_slope:.2f} KB/step ({avg_class})")
            lines.append(f"     - Max Slope: {max_slope:.2f} KB/step ({max_class})")

    lines.append("\nRECOMMENDATION:")
    
    pct_oom = (dist["overcommit"]["critical"] + dist["overcommit"]["warning"]) / total * 100 if total > 0 else 0
    pct_pressure = (dist["mem_avail"]["critical"] + dist["mem_avail"]["warning"]) / total * 100 if total > 0 else 0
    
    top_process = leaks[0].get("process", "") if leaks else ""
    lines.append(_fleet_recommendation(top_process, pct_oom, pct_pressure))

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

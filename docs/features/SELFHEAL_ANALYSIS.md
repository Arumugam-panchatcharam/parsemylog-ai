# SelfHeal Analysis -- User Guide

This guide explains how to read **single-CPE** and **Cross-CPE** SelfHeal views: charts, tables, and histograms. SelfHeal is built from periodic `SelfHeal.txt` snapshots (memory, `/proc/meminfo`, process RSS, and CPU samples).

For navigation: open a project, choose **SelfHeal**, select a **CPE** for per-device analysis, or open the **Cross-CPE Overview** tab for fleet-wide analytics.

---

## Key design principles (how to think about the data)

1. **Aggregate by process name, not PID**  
   Trends and rankings use a normalized application key (first executable name), so the same daemon matches across restarts and paths.

2. **Use slopes (trends), not only snapshots**  
   A single `top` row can look fine while RSS drifts up over hours. Prefer **RSS trend slope** and **slab growth** over one-point RSS.

3. **Separate kernel memory from user memory**  
   - **Kernel / slab**: **Slab**, **SUnreclaim**, slab **OLS slope** (growth per snapshot step).  
   - **User space**: Per-process **RSS**, summed process RSS, **RSS trend slope**.

4. **Correlate CPU and memory**  
   A leak may show as RSS slope + CPU use (e.g. runaway thread). Use CPU charts and process tables together.

5. **Strongest signals (what to weight)**  
   - **RSS slope** (user-space leaks).  
   - **SUnreclaim** trend and share of slab (kernel unreclaimable growth).  
   - **Committed_AS / CommitLimit** (overcommit / OOM risk).  
   - **CPU** trend or sustained high average (runaway or churn).

---

## Single CPE -- What you see

### Summary strip (key metrics)

- **Snapshots / CPU samples**: Longer windows make slopes more reliable.  
- **Peak memory %** and **min / avg MemAvailable** (KB): Headroom over the capture.  
- **MemAvailable %** (min and average vs MemTotal): Quick read of how tight memory was.  
- **Peak / average CPU %**: Average is only meaningful when CPU samples exist.

### Status and alerts

Alerts such as **LOW_MEMORY**, **KERNEL_LEAK**, **OVERCOMMIT_RISK**, **NO_SWAP** are derived from thresholds on meminfo and trends. Use them as flags, then confirm on charts.

### Memory pressure indicators (Meminfo tab)

- **Pressure score (0–100)**: Higher is worse. Combines low MemAvailable%, high overcommit ratio, high SUnreclaim share of slab, and positive slab growth (see in-app tooltip text).  
- **Cached / MemTotal**: Large page cache is often normal; if MemAvailable is fine and Cached is high, pressure may be elsewhere.  
- **SUnreclaim (% of slab)** and **Overcommit ratio**: Primary fleet and single-CPE indicators for kernel unreclaimable pressure and virtual memory commit risk.

### Charts

- **CPU usage over time**: Spikes vs sustained load; correlate timestamps with memory charts.  
- **Memory / RSS by application**: Totals over time; rising lines warrant checking the process table.  
- **Memory pressure (meminfo)**: Slab, SUnreclaim, Committed_AS vs CommitLimit, etc., when present in the build.

### Process-level analysis

- **Top processes by RSS trend**: Positive **RSS trend slope** (KB per snapshot step) highlights likely leaks.  
- **Process series / tables**: Inspect normalized process name, not PID.

### Export

- **Export XLSX**: Spreadsheet for offline review (snapshots, meminfo, per-process sheets).

---

## Single CPE -- How to analyze (workflow)

1. **Check time coverage**  
   Confirm enough snapshots and (if relevant) CPU samples.

2. **Scan MemAvailable % and pressure score**  
   If min MemAvailable% is very low or the pressure score is high, treat memory as a first-class problem.

3. **Split kernel vs user**  
   - Rising **SUnreclaim** / slab indicators or slab slope → kernel / driver path.  
   - Rising **RSS slopes** on named apps → user-space or daemons.

4. **Check overcommit**  
   Overcommit ratio near or above policy limits (warnings in UI) → OOM risk under load.

5. **Name the top offenders**  
   From RSS trend table: which **commands** dominate slope and peak RSS?

6. **Correlate CPU**  
   Match high CPU processes with RSS growth (same app or related services).

---

## Single CPE -- Written summary (template)

Use this structure in tickets or reports. Replace placeholders with values from the UI.

```text
CPE: <serial>

Memory status: <Healthy | Degrading | Critical> (brief reason)

- MemAvailable: <min%> to <avg%> of MemTotal over window (or "dropped from X% → Y%" if comparing windows)
- Kernel: SUnreclaim / Slab <value>; slab trend <slope or "stable">
- Overcommit: Committed_AS / CommitLimit <ratio> → <OK | elevated OOM risk>
- Cached: <stable | rising> vs MemTotal → <likely not primary issue | worth noting>

Top offenders:
1. <process> → RSS trend <+N KB/step or qualitative>; peak RSS <…>
2. <process> → CPU <avg/peak%> if relevant

Conclusion:
<one or two sentences, e.g. combined kernel + user-space pressure; which subsystem to inspect>
```

### Example (illustrative)

```text
CPE: XYZ123

Memory status: Degrading (low MemAvailable and rising SUnreclaim)

- MemAvailable dropped from about 30% → 12% (min over capture)
- SUnreclaim share of slab rising; slab growth positive vs snapshot index
- Committed_AS at ~92% of CommitLimit → elevated OOM risk
- Cached stable vs MemTotal → not the primary story

Top offenders:
1. CcspWifiSsp → RSS trend positive (user-space growth)
2. parodus → sustained high CPU (~35% avg in sample)

Conclusion:
Combined kernel-adjacent and user-space pressure; prioritize WiFi / networking stack and validate on a second capture.
```

---

## Cross-CPE overview -- What you see

### Fleet summary badges

Counts of CPEs with **low memory**, **high RSS**, **memory pressure** (SUnreclaim-heavy slab), **no swap**, **kernel leak** alerts. Use as a first pass on fleet health.

### Fleet distributions (histograms)

- **MemAvailable %** (min or avg per CPE): How many devices sit in each headroom bucket.  
- **Average CPU %** per CPE: Fleet spread of typical CPU load (where samples exist).  
- **SUnreclaim (% of slab)** and **Overcommit ratio**: Histograms across devices (not per-serial bars), scalable for 500+ CPEs.

### Slab vs total process RSS (scatter)

Each point is one CPE: **X** = slab OLS slope (KB per snapshot step), **Y** = total process RSS OLS slope. Helps separate **kernel slab growth** from **userspace RSS growth**.

### Top leaking processes (fleet table)

Aggregated across CPEs with the **same normalized process name**. Columns include **# CPEs affected**, **avg slope**, **max slope**. Only processes with RSS trend slope above a small fleet threshold are counted (see on-screen note).

### Heatmap (process × CPE)

**Color** = RSS **trend** slope (not a one-shot RSS). Dimensions are **capped** (top processes × worst-pressure CPEs) so the view stays readable at large fleet sizes.

### CPE detail table

Sortable columns: status, **pressure score**, MemAvailable%, memory and CPU peaks, **slab** and **total RSS** slopes, etc. Use this to drill from fleet view to specific serials.

---

## Cross-CPE -- How to analyze (workflow)

1. **Start with histograms**  
   See whether the fleet clusters at low MemAvailable% or high overcommit.

2. **Read the fleet leak table**  
   Systemic issues show as one process affecting many CPEs with high max slope.

3. **Use the heatmap**  
   Widespread rows vs a single column isolate **firmware-wide** vs **one-device** behavior.

4. **Scatter: slab vs RSS**  
   Upper-right (both growing) vs high-X / low-Y (slab-led) informs kernel vs app investigations.

5. **Pick serials from the table**  
   Open those CPEs in **single-CPE SelfHeal** for full traces.

---

## Cross-CPE -- Written summary (template)

```text
Cross-CPE overview (<N> CPEs with SelfHeal data)

- Devices under memory pressure: ~<%> with min MemAvailable below <threshold you define, e.g. 15%>
- Kernel-side signal: ~<%> with elevated SUnreclaim / slab trend (use badges + histogram)
- Top leaking process: <name> (affects ~<%> of devices in table)
- OOM risk: ~<%> with Committed_AS / CommitLimit above <e.g. 90%>

Recommendation:
<one line, e.g. firmware or module to bisect, lab repro, or telemetry follow-up>
```

### Example (illustrative)

```text
Cross-CPE overview (500 CPEs)

- About 18% of devices show min MemAvailable under 15% of MemTotal
- About 12% show kernel memory growth signals (SUnreclaim / slab)
- Top leaking process: CcspWifiSsp (present on ~37% of affected devices in the fleet table)
- About 9% at OOM risk (Committed_AS over 90% of CommitLimit)

Recommendation:
Treat as candidate firmware regression in WiFi / networking; compare builds and add targeted SelfHeal captures on failing vs healthy cohorts.
```

---

## Automated executive summary (UI + API)

The app generates a **deterministic text summary** from the same metrics as the charts (no LLM). It is **not** recomputed in the browser on every navigation.

### Single CPE

- Built server-side when SelfHeal parse completes (`POST /selfheal/parse`), including after **Re-parse** (`force=1`).
- Stored in the per-CPE API cache next to charts: `narrative_summary` with `plain_text`, `generated_at_utc`, and `schema_version`.
- Each successful parse run refreshes the summary to match **RSS trend rows** and meminfo-derived fields.

### Cross-CPE overview

- Built when `GET .../selfheal/cross-cpe-overview` finishes aggregating the fleet (including **Refresh overview** with `force=1`).
- Returned as `narrative_summary` on the same JSON response.
- Also written under the project upload directory for audit: `selfheal/cross_cpe_narrative.json` (contains the narrative and `source_force`).

### Thresholds used in prose (initial)

| Concept | Rule |
|--------|------|
| Memory pressure (fleet %) | `mem_available_min_pct < 15` |
| OOM risk | `overcommit_ratio > 0.9` (Committed_AS / CommitLimit) |
| Kernel growth signals (fleet %) | `KERNEL_LEAK` alert, or SUnreclaim % of slab > 50, or positive slab OLS slope |
| Top leaking process | First row of the fleet leak table (by `cpes_affected` / max slope) |

Implementation constants live in `logai/selfheal_summary.py` and should stay aligned with this doc.

---

## Practical tips

- **Refresh** Cross-CPE after uploading new `SelfHeal.txt` files or use force-refresh if your workflow supports it.  
- **Slopes** need at least **two** snapshots; sparse captures weaken trend lines.  
- **500+ CPEs**: Rely on histograms and aggregated tables; use the heatmap as a **sampled** view, not an exhaustive matrix.  
- When in doubt, write the **single-CPE** narrative first, then compare **Cross-CPE** for prevalence.

---

## Related documentation

- [Multi-CPE Support](./MULTI_CPE.md) -- Project and device layout  
- [Telemetry Dashboard](./TELEMETRY.md) -- Complementary device health signals  
- [CPE Overview](./CPE_OVERVIEW.md) -- Broader cross-device dashboards  

---

## Revision history

- Initial version: SelfHeal single-CPE and Cross-CPE analysis guide and summary templates.
- Added: persisted executive summaries (`narrative_summary`), thresholds, and on-disk fleet narrative file.

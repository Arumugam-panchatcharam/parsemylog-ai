import { useState, useMemo, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { telemetryApi } from "@/api/endpoints";
import type {
  CrossCpeTelemetryEntry,
  WifiFleetRadioChannelRow,
  WifiFleetRadioTable,
  WifiFleetRadioTransition,
  WifiRfPayload,
} from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import RebootAnalyticsSection from "@/components/RebootAnalyticsSection";
import Plot from "react-plotly.js";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import CircularProgress from "@mui/material/CircularProgress";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import StorageIcon from "@mui/icons-material/Storage";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import ErrorIcon from "@mui/icons-material/Error";
import CloseIcon from "@mui/icons-material/Close";
import MemoryIcon from "@mui/icons-material/Memory";
import RefreshIcon from "@mui/icons-material/Refresh";
import WifiIcon from "@mui/icons-material/Wifi";

/* ---------------------------------------------------------------- Types */

type SortKey = "serial" | "model" | "reboot_count" | "memory_usage_pct_peak" | "memory_free_min";

/* ---------------------------------------------------------------- Helpers */

const STATUS_CFG: Record<string, { color: string; bg: string; darkBg: string; border: string; darkBorder: string; label: string; icon: React.ElementType }> = {
  SOFT_REBOOT: { color: "#3b82f6", bg: "bg-blue-100",   darkBg: "dark:bg-blue-900/30",   border: "border-blue-200",   darkBorder: "dark:border-blue-800",   label: "SOFT REBOOT", icon: RestartAltIcon },
  REBOOT:  { color: "#d93025", bg: "bg-red-100",    darkBg: "dark:bg-red-900/30",    border: "border-red-200",    darkBorder: "dark:border-red-800",    label: "REBOOT",  icon: RestartAltIcon },
  LOW_MEM: { color: "#d93025", bg: "bg-red-100",    darkBg: "dark:bg-red-900/30",    border: "border-red-200",    darkBorder: "dark:border-red-800",    label: "LOW MEM", icon: ErrorIcon },
  MEMLEAK: { color: "#e8710a", bg: "bg-orange-100", darkBg: "dark:bg-orange-900/30", border: "border-orange-200", darkBorder: "dark:border-orange-800", label: "MEMLEAK", icon: WarningAmberIcon },
  OK:      { color: "#188038", bg: "bg-green-100",  darkBg: "dark:bg-green-900/30",  border: "border-green-200",  darkBorder: "dark:border-green-800",  label: "OK",      icon: StorageIcon },
};

function statusCfg(entry: CrossCpeTelemetryEntry) {
  return STATUS_CFG[entry.status ?? "OK"] ?? STATUS_CFG.OK;
}

function severityRowClass(entry: CrossCpeTelemetryEntry): string {
  const s = entry.status ?? "OK";
  if (s === "REBOOT" || s === "LOW_MEM") return "bg-red-50 dark:bg-red-900/15 border-red-200 dark:border-red-800";
  if (s === "MEMLEAK") return "bg-orange-50 dark:bg-orange-900/10 border-orange-200 dark:border-orange-800";
  return "border-border";
}

function fmtDurationSec(sec: number): string {
  if (sec >= 86400) {
    const days = sec / 86400;
    return `${days.toFixed(1)}d`;
  }
  if (sec >= 3600) return `${(sec / 3600).toFixed(1)}h`;
  return `${Math.round(sec / 60)}m`;
}

function fmtMemory(val: number | undefined | null, unit: string): string {
  if (val == null) return "N/A";
  const u = unit.toLowerCase();
  if (u === "gb") return `${val.toFixed(2)} GB`;
  if (u === "mb") return `${val.toFixed(1)} MB`;
  if (u === "kb") {
    if (val >= 1_000_000) return `${(val / (1024 * 1024)).toFixed(2)} GB`;
    if (val >= 1024) return `${(val / 1024).toFixed(1)} MB`;
    return `${val} KB`;
  }
  return `${val} ${unit}`;
}

type Dash = "solid" | "dot" | "dash" | "longdash" | "dashdot" | "longdashdot";

const MEMORY_TRACE_COLORS: Record<string, { color: string; dash?: Dash }> = {
  "Memory Free":      { color: "#1a73e8" },
  "Free":             { color: "#1a73e8" },
  "Memory Available":  { color: "#188038" },
  "Available":         { color: "#188038" },
  "Memory Total":      { color: "#9aa0a6", dash: "dash" },
  "Total":             { color: "#9aa0a6", dash: "dash" },
  "Shared Memory":     { color: "#e8710a", dash: "dot" },
  "Slab Memory":       { color: "#7b1fa2", dash: "dot" },
};

/* ---------------------------------------------------------------- Component */

export default function TelemetryOverviewTab() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();

  const [sortKey, setSortKey] = useState<SortKey>("memory_free_min");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [selectedCpe, setSelectedCpe] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [filterShortReboots, setFilterShortReboots] = useState(true);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["telemetry-cross-cpe-overview", projectId, filterShortReboots],
    queryFn: async () => (await telemetryApi.crossCpeOverview(projectId!, false, filterShortReboots)).data,
    enabled: !!projectId,
    staleTime: 5 * 60 * 1000,
  });

  const handleForceRefresh = async () => {
    if (!projectId || isRefreshing) return;
    setIsRefreshing(true);
    try {
      const result = await telemetryApi.crossCpeOverview(projectId, true, filterShortReboots);
      // Update the query cache directly with the new data instead of invalidating
      queryClient.setQueryData(["telemetry-cross-cpe-overview", projectId, filterShortReboots], result.data);
    } catch (err) {
      console.error("Force refresh failed:", err);
    } finally {
      setIsRefreshing(false);
    }
  };

  /* Per-CPE telemetry chart data */
  const { data: cpeChartData, isLoading: cpeChartLoading } = useQuery({
    queryKey: ["telemetry-cpe-chart", projectId, selectedCpe],
    queryFn: async () => (await telemetryApi.parse(projectId!, selectedCpe)).data,
    enabled: !!projectId && !!selectedCpe,
    staleTime: 10 * 60 * 1000,
  });

  const memoryTraces = useMemo(() => {
    if (!cpeChartData?.charts) return null;
    const MEM_GROUPS = new Set(["Memory", "System Resources", "Available memory"]);
    const memChart = cpeChartData.charts.find(
      (c: { group: string }) => MEM_GROUPS.has(c.group)
    );
    if (!memChart) return null;
    return (memChart.traces as Array<{ label: string; unit: string; times: string[]; values: number[] }>)
      .filter((t) => MEMORY_TRACE_COLORS[t.label])
      .map((t) => ({
        ...t,
        style: MEMORY_TRACE_COLORS[t.label],
      }));
  }, [cpeChartData]);

  const rebootShapes = useMemo(() => {
    const allEvents = (cpeChartData?.reboot_timeline?.all_events ?? []) as Array<{ 
      time: string; 
      source?: string; 
      label?: string;
      reboot_type?: "soft" | "hard";
    }>;
    
    return allEvents.map((evt) => {
      const isBootTime = evt.source === "boottime";
      const isSoft = evt.reboot_type === "soft";
      const isHard = evt.reboot_type === "hard";
      
      // Determine color: use reboot_type if available, otherwise use source-based color
      let lineColor = isBootTime ? "#1a73e8" : "#d93025"; // Default: blue for BootTime, red for Telemetry
      if (isSoft) lineColor = "#3b82f6"; // Soft reboot = blue
      else if (isHard) lineColor = "#d93025"; // Hard reboot = red
      
      return {
        type: "line" as const,
        xref: "x" as const,
        yref: "paper" as const,
        x0: evt.time,
        x1: evt.time,
        y0: 0,
        y1: 1,
        line: { 
          color: lineColor,
          width: isBootTime ? 2 : 1.5, 
          dash: (isBootTime ? "solid" : "dot") as "solid" | "dot" | "dash" | "longdash" | "dashdot" | "longdashdot"
        },
      };
    });
  }, [cpeChartData]);

  const rebootAnnotations = useMemo(() => {
    const allEvents = (cpeChartData?.reboot_timeline?.all_events ?? []) as Array<{ 
      time: string; 
      source?: string; 
      label?: string;
      reason?: string;
      reboot_type?: "soft" | "hard";
    }>;
    
    return allEvents.map((evt) => {
      const isBootTime = evt.source === "boottime";
      const sourceLabel = evt.label || (isBootTime ? "B" : "TR");
      const isSoft = evt.reboot_type === "soft";
      const isHard = evt.reboot_type === "hard";
      
      // Show both source and type: "B-S", "TR-H", etc.
      const typeLabel = isSoft ? "S" : isHard ? "H" : "";
      const fullLabel = typeLabel ? `${sourceLabel}-${typeLabel}` : sourceLabel;
      
      // Determine color based on reboot_type
      let fontColor = isBootTime ? "#1a73e8" : "#d93025";
      if (isSoft) fontColor = "#3b82f6";
      else if (isHard) fontColor = "#d93025";
      
      return {
        x: evt.time,
        y: 1,
        xref: "x" as const,
        yref: "paper" as const,
        text: fullLabel,  // Only show the source-type label, not the reason
        showarrow: false,
        font: { 
          size: 8, 
          color: fontColor
        },
        yanchor: "bottom" as const,
      };
    });
  }, [cpeChartData]);

  const rebootHoverTrace = useMemo(() => {
    const allEvents = (cpeChartData?.reboot_timeline?.all_events ?? []) as Array<{
      time: string;
      source?: string;
      reason?: string;
      reboot_type?: "soft" | "hard";
    }>;
    
    return {
      type: "scatter" as const,
      mode: "markers" as const,
      x: allEvents.map(e => e.time),
      y: allEvents.map(() => 0),
      marker: { size: 10, opacity: 0 },
      hovertemplate: allEvents.map(e => {
        const isBootTime = e.source === "boottime";
        const sourceLabel = isBootTime ? "BootTime" : "Telemetry Recovery";
        const typeLabel = e.reboot_type === "soft" ? "Soft Reboot" : 
                         e.reboot_type === "hard" ? "Hard Reboot" : "Reboot";
        const reasonText = e.reason && e.reason !== "" ? 
                          `<br><b>Reason:</b> ${e.reason}` : "";
        
        return `<b>${sourceLabel}</b> (${typeLabel})<br><b>Time:</b> %{x}${reasonText}<extra></extra>`;
      }),
      showlegend: false,
      name: "Reboot Events",
    };
  }, [cpeChartData]);

  const rebootXRange = useMemo<[string, string] | undefined>(() => {
    const allEvents = (cpeChartData?.reboot_timeline?.all_events ?? []) as Array<{ time: string }>;
    if (allEvents.length !== 1) return undefined;
    const TWO_HOURS_MS = 2 * 60 * 60 * 1000;
    const ts = new Date(allEvents[0].time).getTime();
    if (isNaN(ts)) return undefined;
    const pad = (n: number) => String(n).padStart(2, "0");
    const toLocal = (ms: number) => {
      const d = new Date(ms);
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    };
    return [toLocal(ts - TWO_HOURS_MS), toLocal(ts + TWO_HOURS_MS)];
  }, [cpeChartData]);

  const sortedCpes = useMemo(() => {
    if (!data?.cpes) return [];
    return [...data.cpes].sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      switch (sortKey) {
        case "serial": av = a.serial; bv = b.serial; break;
        case "model": av = a.model; bv = b.model; break;
        case "reboot_count": av = a.reboot_count ?? 0; bv = b.reboot_count ?? 0; break;
        case "memory_usage_pct_peak": av = a.memory_usage_pct_peak ?? -1; bv = b.memory_usage_pct_peak ?? -1; break;
        case "memory_free_min": av = a.memory_free_min ?? Infinity; bv = b.memory_free_min ?? Infinity; break;
        default: av = 0; bv = 0;
      }
      if (typeof av === "string" && typeof bv === "string") {
        return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
  }, [data, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      const defaultDesc: SortKey[] = ["reboot_count", "memory_usage_pct_peak"];
      setSortDir(defaultDesc.includes(key) ? "desc" : "asc");
    }
  };

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return null;
    return sortDir === "asc"
      ? <ArrowUpwardIcon style={{ fontSize: 12 }} />
      : <ArrowDownwardIcon style={{ fontSize: 12 }} />;
  };

  const handleRowClick = (serial: string) => {
    setSelectedCpe(selectedCpe === serial ? null : serial);
  };

  /* ---- Render ---- */

  if (!projectId) {
    return (
      <div className="flex items-center justify-center h-40 text-muted-foreground">
        Select a project from the Dashboard.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="bg-card border border-border rounded-xl p-6 flex items-center justify-center gap-2 text-muted-foreground">
        <CircularProgress size={20} />
        <span className="text-sm">Loading cross-CPE telemetry data...</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-4 bg-destructive/10 text-destructive rounded-xl text-sm flex items-center gap-2">
        <ErrorIcon style={{ fontSize: 18 }} />
        {(error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Failed to load cross-CPE overview"}
      </div>
    );
  }

  if (!data || data.cpes.length === 0) {
    return (
      <div className="bg-card border border-border rounded-xl p-8 text-center text-sm text-muted-foreground">
        No CPEs with telemetry data found. Parse telemetry for individual CPEs first.
      </div>
    );
  }

  const fs = data.fleet_summary;

  return (
    <div className="space-y-3">
      {/* Header with Toggle and Force Refresh Buttons */}
      <div className="flex justify-end gap-2">
        <button
          onClick={() => setFilterShortReboots(!filterShortReboots)}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
            filterShortReboots
              ? "bg-purple-100 dark:bg-purple-900/30 border-purple-300 text-purple-700 dark:text-purple-300"
              : "border-border bg-card hover:bg-muted"
          }`}
          title="Toggle to show only short reboots"
        >
          <RestartAltIcon style={{ fontSize: 14 }} />
          {filterShortReboots ? "Short Reboots Only" : "All Reboots"}
        </button>
        <button
          onClick={handleForceRefresh}
          disabled={isRefreshing || isLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-card hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title="Force re-parse telemetry data for all CPEs"
        >
          <RefreshIcon style={{ fontSize: 14 }} className={isRefreshing ? "animate-spin" : ""} />
          {isRefreshing ? "Re-parsing..." : "Force Refresh All"}
        </button>
      </div>

      {/* Summary badges */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <SummaryBadge
          icon={<StorageIcon style={{ fontSize: 18, color: "#1a73e8" }} />}
          label="Total CPEs"
          value={fs.total}
          bgClass="bg-blue-50 dark:bg-blue-900/20"
        />
        <SummaryBadge
          icon={<RestartAltIcon style={{ fontSize: 18, color: "#f9ab00" }} />}
          label="With Reboots"
          value={fs.with_reboots}
          sub={fs.total > 0 ? `${Math.round((fs.with_reboots / fs.total) * 100)}%` : undefined}
          bgClass="bg-yellow-50 dark:bg-yellow-900/20"
        />
        <SummaryBadge
          icon={<WarningAmberIcon style={{ fontSize: 18, color: "#e8710a" }} />}
          label="Low Memory"
          value={fs.with_low_memory}
          sub={fs.total > 0 ? `${Math.round((fs.with_low_memory / fs.total) * 100)}%` : undefined}
          bgClass="bg-orange-50 dark:bg-orange-900/20"
        />
        <SummaryBadge
          icon={<ErrorIcon style={{ fontSize: 18, color: "#d93025" }} />}
          label="Reboots + Low Mem"
          value={fs.with_both}
          sub={fs.total > 0 ? `${Math.round((fs.with_both / fs.total) * 100)}%` : undefined}
          bgClass="bg-red-50 dark:bg-red-900/20"
        />
        <SummaryBadge
          icon={<RestartAltIcon style={{ fontSize: 18, color: "#7b1fa2" }} />}
          label="Short Reboots"
          value={data.reboot_analytics?.short_reboots_count ?? 0}
          sub={data.reboot_analytics?.total_reboot_events ? `${Math.round(((data.reboot_analytics?.short_reboots_count ?? 0) / data.reboot_analytics.total_reboot_events) * 100)}%` : undefined}
          bgClass="bg-purple-50 dark:bg-purple-900/20"
        />
      </div>

      <Accordion
        className="bg-card border border-border rounded-xl overflow-hidden shadow-none !mb-2"
        sx={{ boxShadow: "none", "&:before": { display: "none" } }}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ fontSize: 18 }} />} className="min-h-12 bg-muted/30">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <RestartAltIcon style={{ fontSize: 16, color: "#f9ab00" }} />
            Reboot — time of day &amp; uptime buckets
          </span>
        </AccordionSummary>
        <AccordionDetails className="pt-0 pb-3 px-2 space-y-3">
          {data.reboot_analytics && data.reboot_analytics.total_reboot_events > 0 ? (
            <RebootAnalyticsSection analytics={data.reboot_analytics} />
          ) : (
            <p className="text-xs text-muted-foreground px-1">No reboot events for the current filter.</p>
          )}
        </AccordionDetails>
      </Accordion>

      <Accordion
        className="bg-card border border-border rounded-xl overflow-hidden shadow-none !mb-2"
        sx={{ boxShadow: "none", "&:before": { display: "none" } }}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ fontSize: 18 }} />} className="min-h-12 bg-muted/30">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <MemoryIcon style={{ fontSize: 16, color: "#1a73e8" }} />
            CPE reboot &amp; memory — table &amp; timeline
          </span>
        </AccordionSummary>
        <AccordionDetails className="pt-0 pb-3 px-2 space-y-3">
          <div className="w-full bg-card border border-border rounded-xl overflow-hidden">
            <div className="px-3 py-1 border-b border-border bg-muted/20">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Fleet CPE detail — reboots &amp; memory ({sortedCpes.length} CPEs)
              </h3>
            </div>
            <div className="overflow-auto max-h-[min(72vh,720px)]">
              <table className="text-[11px] border-collapse w-full min-w-[880px]">
                <thead className="sticky top-0 z-10 bg-card shadow-sm">
                  <tr className="border-b border-border bg-muted/20">
                    <ThSort col="serial" label="Serial" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} />
                    <ThSort col="model" label="Model" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} />
                    <ThSort col="reboot_count" label="Reboots" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} align="right" />
                    <th className="text-left px-2 py-1 font-semibold text-muted-foreground">Types</th>
                    <th className="text-right px-2 py-1 font-semibold text-muted-foreground">Uptime before</th>
                    <ThSort col="memory_usage_pct_peak" label="Mem %" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} align="right" />
                    <ThSort col="memory_free_min" label="Min Free" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} align="right" />
                    <th className="text-right px-2 py-1 font-semibold text-muted-foreground">Min Avail</th>
                    <th className="text-right px-2 py-1 font-semibold text-muted-foreground">Total</th>
                    <th className="text-center px-2 py-1 font-semibold text-muted-foreground">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedCpes.length === 0 && (
                    <tr>
                      <td colSpan={10} className="px-2 py-6 text-center text-muted-foreground">
                        No CPEs with telemetry data found.
                      </td>
                    </tr>
                  )}
                  {sortedCpes.map((cpe) => {
                    const isSelected = selectedCpe === cpe.serial;
                    const unit = cpe.memory_unit ?? "KB";
                    const cfg = statusCfg(cpe);
                    return (
                      <tr
                        key={cpe.serial}
                        className={`border-b border-border/60 cursor-pointer hover:bg-muted/30 transition-colors ${isSelected ? "ring-2 ring-primary/40 ring-inset" : ""} ${severityRowClass(cpe)}`}
                        onClick={() => handleRowClick(cpe.serial)}
                      >
                        <td className="px-2 py-1.5 font-mono font-medium text-foreground whitespace-nowrap">{cpe.serial}</td>
                        <td className="px-2 py-1.5 text-muted-foreground">{cpe.model}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums font-medium">
                          {cpe.reboot_count > 0 ? (
                            <span className="text-red-600 dark:text-red-400">{cpe.reboot_count}</span>
                          ) : (
                            <span className="text-muted-foreground">0</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-[9px]">
                          {cpe.reboot_types && (cpe.reboot_types.soft > 0 || cpe.reboot_types.hard > 0) ? (
                            <span className="flex gap-1 flex-wrap">
                              {cpe.reboot_types.soft > 0 && (
                                <span className="px-1 rounded bg-blue-100 dark:bg-blue-900/30">{cpe.reboot_types.soft}S</span>
                              )}
                              {cpe.reboot_types.hard > 0 && (
                                <span className="px-1 rounded bg-red-100 dark:bg-red-900/30">{cpe.reboot_types.hard}H</span>
                              )}
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
                          {(cpe.reboot_events ?? []).length > 0
                            ? (cpe.reboot_events ?? []).map((evt) => fmtDurationSec(evt.prev_uptime)).join(" / ")
                            : "—"}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums" title="Peak memory usage: (Total - Min Free) / Total × 100">
                          {cpe.memory_usage_pct_peak != null ? (
                            <span className={cpe.memory_usage_pct_peak > 90 ? "text-red-600 dark:text-red-400 font-bold" : cpe.memory_usage_pct_peak > 80 ? "text-orange-600 dark:text-orange-400 font-medium" : ""}>
                              {cpe.memory_usage_pct_peak}%
                            </span>
                          ) : (
                            <span className="text-muted-foreground">N/A</span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
                          {fmtMemory(cpe.memory_free_min, unit)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
                          {fmtMemory(cpe.memory_available_min, unit)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">{fmtMemory(cpe.memory_total, unit)}</td>
                        <td className="px-2 py-1.5 text-center">
                          <StatusBadge status={cpe.status ?? "OK"} cfg={cfg} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-[10px] text-muted-foreground px-3 py-1.5 border-t border-border bg-muted/5">
              Click a row to load the memory timeline below. Scroll vertically for large fleets.
            </p>
          </div>

          {selectedCpe && (
            <div className="bg-card border border-border rounded-xl overflow-hidden max-h-[calc(100vh-280px)]">
              <div className="px-3 py-1.5 border-b border-border bg-muted/30 flex items-center justify-between">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                  <MemoryIcon style={{ fontSize: 14, color: "#1a73e8" }} />
                  Memory Timeline &mdash; {selectedCpe}
                </h3>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setSelectedCpe(null); }}
                  className="text-muted-foreground hover:text-foreground p-0.5 rounded hover:bg-muted transition-colors"
                >
                  <CloseIcon style={{ fontSize: 14 }} />
                </button>
              </div>
              {(rebootShapes.length > 0 || (cpeChartData?.reboot_timeline?.all_events ?? []).length > 0) && (
                <div className="px-3 py-1.5 border-b border-border bg-muted/10">
                  <div className="flex items-center gap-4 text-[10px] text-muted-foreground flex-wrap">
                    <span className="font-semibold">Reboot Markers:</span>
                    <div className="flex items-center gap-1">
                      <div className="w-5 h-0.5 bg-[#1a73e8]" />
                      <span><span className="font-mono font-semibold text-[#1a73e8]">B</span> = BootTime</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <div className="w-5 h-0.5 border-t-2 border-dashed border-[#d93025]" />
                      <span><span className="font-mono font-semibold text-[#d93025]">TR</span> = Telemetry</span>
                    </div>
                    <div className="border-l border-border pl-4 ml-2 flex items-center gap-3">
                      <div className="flex items-center gap-1">
                        <span className="font-mono font-semibold text-[#3b82f6]">S</span>
                        <span>= Soft</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="font-mono font-semibold text-[#d93025]">H</span>
                        <span>= Hard</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div className="px-2 py-1 overflow-auto">
                {cpeChartLoading && (
                  <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
                    <CircularProgress size={18} />
                    <span className="text-xs">Loading memory data...</span>
                  </div>
                )}
                {!cpeChartLoading && memoryTraces && memoryTraces.length > 0 && (
                  <Plot
                    data={[
                      ...memoryTraces.map((t) => ({
                        type: "scatter" as const,
                        mode: "lines" as const,
                        x: t.times,
                        y: t.values,
                        name: `${t.label} (${t.unit})`,
                        line: { color: t.style.color, width: 2, dash: t.style.dash },
                      })),
                      rebootHoverTrace,
                    ]}
                    layout={{
                      height: 340,
                      margin: { l: 50, r: 20, t: 16, b: 40 },
                      xaxis: {
                        tickfont: { size: 10 },
                        title: { text: "Time", font: { size: 11 } },
                        tickformat: "%H:%M\n%b %d",
                        dtick: 20 * 60 * 1000,
                        ...(rebootXRange ? { range: rebootXRange } : {}),
                      },
                      yaxis: {
                        tickfont: { size: 10 },
                        title: { text: `Memory (${memoryTraces[0]?.unit ?? "MB"})`, font: { size: 11 } },
                        rangemode: "tozero",
                      },
                      shapes: rebootShapes,
                      annotations: rebootAnnotations,
                      legend: { orientation: "h", y: -0.18, font: { size: 10 } },
                      hovermode: "x unified",
                      paper_bgcolor: "transparent",
                      plot_bgcolor: "transparent",
                      font: { family: "Roboto, sans-serif", size: 11 },
                    }}
                    config={{ displayModeBar: true, modeBarButtonsToRemove: ["lasso2d", "select2d", "toImage"], displaylogo: false }}
                    useResizeHandler
                    style={{ width: "100%" }}
                  />
                )}
                {!cpeChartLoading && (!memoryTraces || memoryTraces.length === 0) && (
                  <div className="py-8 text-center text-xs text-muted-foreground">No memory chart data available for this CPE.</div>
                )}
              </div>
            </div>
          )}
        </AccordionDetails>
      </Accordion>

      <Accordion
        className="bg-card border border-border rounded-xl overflow-hidden shadow-none !mb-2"
        sx={{ boxShadow: "none", "&:before": { display: "none" } }}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ fontSize: 18 }} />} className="min-h-12 bg-muted/30">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <WifiIcon style={{ fontSize: 16, color: "#00897b" }} />
            WiFi RF — fleet channels, switches &amp; utilization
          </span>
        </AccordionSummary>
        <AccordionDetails className="pt-0 pb-3 px-2 space-y-3">
          {data.wifi_fleet_summary && (
            <div className="space-y-2">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <SummaryBadge
                  icon={<WifiIcon style={{ fontSize: 18, color: "#00897b" }} />}
                  label="WiFi channel changes"
                  value={data.wifi_fleet_summary.cpes_with_channel_changes}
                  sub={fs.total > 0 ? `${Math.round((data.wifi_fleet_summary.cpes_with_channel_changes / fs.total) * 100)}% of CPEs` : undefined}
                  bgClass="bg-teal-50 dark:bg-teal-900/20"
                />
                <SummaryBadge
                  icon={<WifiIcon style={{ fontSize: 18, color: "#6a1b9a" }} />}
                  label="DFS hint (5 GHz)"
                  value={data.wifi_fleet_summary.cpes_with_dfs_hint_events}
                  sub="EU-indicative"
                  bgClass="bg-violet-50 dark:bg-violet-900/20"
                />
                <SummaryBadge
                  icon={<WifiIcon style={{ fontSize: 18, color: "#e65100" }} />}
                  label="Crowded WiFi util"
                  value={data.wifi_fleet_summary.cpes_wifi_crowded}
                  sub={fs.total > 0 ? `${Math.round((data.wifi_fleet_summary.cpes_wifi_crowded / fs.total) * 100)}%` : undefined}
                  bgClass="bg-amber-50 dark:bg-amber-900/20"
                />
                <SummaryBadge
                  icon={<WifiIcon style={{ fontSize: 18, color: "#1565c0" }} />}
                  label="Channel events (total)"
                  value={data.wifi_fleet_summary.total_channel_events}
                  bgClass="bg-sky-50 dark:bg-sky-900/20"
                />
              </div>
            </div>
          )}

          {(data.wifi_fleet_summary?.wifi_radio_fleet?.length ?? 0) > 0 ? (
            <>
              <p className="text-[10px] text-muted-foreground px-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                <span>
                  <span className="inline-block w-2 h-2 rounded-sm bg-violet-200 dark:bg-violet-800 align-middle mr-1" aria-hidden />
                  5 GHz DFS channels (EU)
                </span>
                <span>
                  <span className="inline-block w-2 h-2 rounded-sm bg-orange-200 dark:bg-orange-900 align-middle mr-1" aria-hidden />
                  5 GHz radar overlap (EU-indicative)
                </span>
                <span className="text-muted-foreground/90">Tint when the radio&apos;s dominant band from CPEs is 5 GHz.</span>
              </p>
              <WifiFleetRadioGrid fleet={data.wifi_fleet_summary!.wifi_radio_fleet!} />
            </>
          ) : (
            <p className="text-xs text-muted-foreground px-1">No per-radio WiFi fleet aggregates yet (needs WiFi channel data in telemetry cache).</p>
          )}

          {selectedCpe && (
            <WifiRfDetailPanel serial={selectedCpe} wifi={sortedCpes.find((c) => c.serial === selectedCpe)?.wifi_rf} />
          )}
        </AccordionDetails>
      </Accordion>
    </div>
  );
}

/* ---------------------------------------------------------------- Sub-components */

/** Match api/telemetry_wifi_metrics._band_hint for 5 GHz detection. */
function bandHintIs5Ghz(band: string | null | undefined): boolean {
  if (band == null || String(band).trim() === "") return false;
  const s = String(band).toUpperCase().replace(/_/g, ".");
  if (s.includes("6G") || (s.includes("6") && s.includes("GHZ")) || s.includes("6.0")) return false;
  if (s.includes("2.4") || s.includes("24") || s.includes("2_4")) return false;
  return s.includes("5G") || s.includes("5GHZ") || (s.includes("5") && s.includes("GHZ"));
}

/** EU (ETSI-style) 5 GHz DFS: 52–64, 100–140; aligns with telemetry_wifi_metrics._DFS_CHANNELS_5GHZ_EU. */
const EU_DFS_5GHZ_CHANNELS: ReadonlySet<number> = new Set([
  ...Array.from({ length: 65 - 52 }, (_, i) => 52 + i),
  ...Array.from({ length: 141 - 100 }, (_, i) => 100 + i),
]);

/** EU-indicative radar-heavy overlap; aligns with telemetry_wifi_metrics._RADAR_CHANNELS_5GHZ_EU. */
const EU_RADAR_5GHZ_CHANNELS: ReadonlySet<number> = new Set([116, 120, 124, 128, 132]);

type FiveGhzChannelKind = "none" | "dfs" | "radar";

function fiveGhzEuDefaultChannelKind(channel: number): FiveGhzChannelKind {
  const ch = Math.round(channel);
  if (EU_RADAR_5GHZ_CHANNELS.has(ch)) return "radar";
  if (EU_DFS_5GHZ_CHANNELS.has(ch)) return "dfs";
  return "none";
}

function wifiChannelRowClass(channel: number, is5GHzRadio: boolean): string {
  if (!is5GHzRadio) return "border-b border-border/50";
  const k = fiveGhzEuDefaultChannelKind(channel);
  if (k === "radar") {
    return "border-b border-orange-200/60 dark:border-orange-900/45 bg-orange-100/90 dark:bg-orange-950/35";
  }
  if (k === "dfs") {
    return "border-b border-violet-200/50 dark:border-violet-900/40 bg-violet-100/85 dark:bg-violet-950/30";
  }
  return "border-b border-border/50";
}

function wifiChannelValueCellClass(channel: number, is5GHzRadio: boolean): string {
  const base = "py-1 px-2 font-mono tabular-nums";
  if (!is5GHzRadio) return base;
  const k = fiveGhzEuDefaultChannelKind(channel);
  if (k === "radar") {
    return `${base} bg-orange-100/90 dark:bg-orange-950/35 text-orange-950 dark:text-orange-100`;
  }
  if (k === "dfs") {
    return `${base} bg-violet-100/85 dark:bg-violet-950/30 text-violet-950 dark:text-violet-100`;
  }
  return base;
}

/** Scroll height from row count (capped); extra room for sticky header. */
function wifiTableScrollMaxPx(rowCount: number): number {
  const HEADER_BAND = 44;
  const TABLE_HEAD = 28;
  const ROW_PX = 26;
  const CAP = 560;
  const FLOOR = 96;
  const body = Math.max(rowCount, 0) * ROW_PX;
  const raw = HEADER_BAND + TABLE_HEAD + body;
  return Math.min(CAP, Math.max(FLOOR, raw));
}

function WifiSortTh({
  label,
  active,
  dir,
  align,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: "asc" | "desc";
  align: "left" | "right";
  onClick: () => void;
}) {
  return (
    <th
      className={`py-1.5 px-2 font-semibold text-muted-foreground cursor-pointer select-none hover:text-foreground whitespace-nowrap ${
        align === "right" ? "text-right" : "text-left"
      }`}
      onClick={onClick}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {active ? (dir === "asc" ? <ArrowUpwardIcon style={{ fontSize: 12 }} /> : <ArrowDownwardIcon style={{ fontSize: 12 }} />) : null}
      </span>
    </th>
  );
}

type ChannelSortKey = "channel" | "cpe_count" | "mean_util_pct" | "max_util_pct";

function WifiRadioChannelsPanel({ radioNum, tbl }: { radioNum: 1 | 2; tbl: WifiFleetRadioTable | undefined }) {
  const [sort, setSort] = useState<{ key: ChannelSortKey; dir: "asc" | "desc" }>({
    key: "channel",
    dir: "asc",
  });

  const toggleSort = useCallback((nextKey: ChannelSortKey) => {
    setSort((s) => {
      if (s.key !== nextKey) {
        return {
          key: nextKey,
          dir: nextKey === "cpe_count" || nextKey === "mean_util_pct" || nextKey === "max_util_pct" ? "desc" : "asc",
        };
      }
      return { key: s.key, dir: s.dir === "asc" ? "desc" : "asc" };
    });
  }, []);

  const rows = tbl?.channels ?? [];
  const is5GHzRadio = bandHintIs5Ghz(tbl?.band);

  const sorted = useMemo(() => {
    const list = [...rows];
    const numOr = (v: number | null | undefined, fallback: number) =>
      v == null || Number.isNaN(v) ? fallback : v;
    list.sort((a, b) => {
      let cmp = 0;
      switch (sort.key) {
        case "channel":
          cmp = a.channel - b.channel;
          break;
        case "cpe_count":
          cmp = a.cpe_count - b.cpe_count;
          break;
        case "mean_util_pct":
          cmp = numOr(a.mean_util_pct, sort.dir === "asc" ? Infinity : -Infinity) -
            numOr(b.mean_util_pct, sort.dir === "asc" ? Infinity : -Infinity);
          break;
        case "max_util_pct":
          cmp = numOr(a.max_util_pct, sort.dir === "asc" ? Infinity : -Infinity) -
            numOr(b.max_util_pct, sort.dir === "asc" ? Infinity : -Infinity);
          break;
        default:
          cmp = 0;
      }
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return list;
  }, [rows, sort]);

  const maxH = wifiTableScrollMaxPx(sorted.length);

  return (
    <div className="border border-border rounded-lg overflow-hidden bg-card flex flex-col min-h-0 min-w-0">
      <div className="shrink-0 px-2 py-1.5 bg-muted/20 border-b border-border">
        <div className="text-[11px] font-semibold text-foreground">Radio {radioNum}</div>
        <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Channels &amp; utilization</div>
        {tbl != null && (
          <div className="text-[9px] text-muted-foreground mt-0.5">
            {tbl.cpes_reporting} CPE radio row{tbl.cpes_reporting === 1 ? "" : "s"}
            {tbl.band != null && String(tbl.band).trim() !== "" ? ` · ${tbl.band}` : ""}
            {" · "}last sampled channel
          </div>
        )}
      </div>
      <div className="overflow-y-auto overflow-x-auto" style={{ maxHeight: maxH }}>
        {!tbl ? (
          <div className="p-4 text-[11px] text-muted-foreground">No fleet data for Radio {radioNum}.</div>
        ) : sorted.length === 0 ? (
          <div className="p-4 text-[11px] text-muted-foreground">No channel rows.</div>
        ) : (
          <table className="text-[10px] w-full border-collapse">
            <thead className="sticky top-0 bg-card z-[1] border-b border-border shadow-sm">
              <tr>
                <WifiSortTh label="Channel" active={sort.key === "channel"} dir={sort.dir} align="left" onClick={() => toggleSort("channel")} />
                <WifiSortTh label="CPEs" active={sort.key === "cpe_count"} dir={sort.dir} align="right" onClick={() => toggleSort("cpe_count")} />
                <WifiSortTh label="Mean %" active={sort.key === "mean_util_pct"} dir={sort.dir} align="right" onClick={() => toggleSort("mean_util_pct")} />
                <WifiSortTh label="Max %" active={sort.key === "max_util_pct"} dir={sort.dir} align="right" onClick={() => toggleSort("max_util_pct")} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((c: WifiFleetRadioChannelRow) => (
                <tr key={c.channel} className={wifiChannelRowClass(c.channel, is5GHzRadio)}>
                  <td className="py-1 px-2 font-mono tabular-nums">{c.channel}</td>
                  <td className="py-1 px-2 text-right tabular-nums">{c.cpe_count}</td>
                  <td className="py-1 px-2 text-right tabular-nums">{c.mean_util_pct ?? "—"}</td>
                  <td className="py-1 px-2 text-right tabular-nums">{c.max_util_pct ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

type SwitchSortKey = "from" | "to" | "count" | "share_pct";

function WifiRadioSwitchesPanel({ radioNum, tbl }: { radioNum: 1 | 2; tbl: WifiFleetRadioTable | undefined }) {
  const [sort, setSort] = useState<{ key: SwitchSortKey; dir: "asc" | "desc" }>({
    key: "count",
    dir: "desc",
  });

  const toggleSort = useCallback((nextKey: SwitchSortKey) => {
    setSort((s) => {
      if (s.key !== nextKey) {
        return { key: nextKey, dir: nextKey === "count" || nextKey === "share_pct" ? "desc" : "asc" };
      }
      return { key: s.key, dir: s.dir === "asc" ? "desc" : "asc" };
    });
  }, []);

  const rows = tbl?.top_transitions ?? [];
  const is5GHzRadio = bandHintIs5Ghz(tbl?.band);

  const sorted = useMemo(() => {
    const list = [...rows];
    list.sort((a, b) => {
      let cmp = 0;
      switch (sort.key) {
        case "from":
          cmp = a.from - b.from;
          break;
        case "to":
          cmp = a.to - b.to;
          break;
        case "count":
          cmp = a.count - b.count;
          break;
        case "share_pct":
          cmp = a.share_pct - b.share_pct;
          break;
        default:
          cmp = 0;
      }
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return list;
  }, [rows, sort]);

  const maxH = wifiTableScrollMaxPx(sorted.length);

  return (
    <div className="border border-border rounded-lg overflow-hidden bg-card flex flex-col min-h-0 min-w-0">
      <div className="shrink-0 px-2 py-1.5 bg-muted/20 border-b border-border">
        <div className="text-[11px] font-semibold text-foreground">Radio {radioNum}</div>
        <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Most common channel switches</div>
        {tbl != null && tbl.band != null && String(tbl.band).trim() !== "" ? (
          <div className="text-[9px] text-muted-foreground mt-0.5">{tbl.band}</div>
        ) : null}
      </div>
      <div className="overflow-y-auto overflow-x-auto" style={{ maxHeight: maxH }}>
        {!tbl ? (
          <div className="p-4 text-[11px] text-muted-foreground">No fleet data for Radio {radioNum}.</div>
        ) : sorted.length === 0 ? (
          <div className="p-4 text-[11px] text-muted-foreground">No switch events recorded.</div>
        ) : (
          <table className="text-[10px] w-full border-collapse">
            <thead className="sticky top-0 bg-card z-[1] border-b border-border shadow-sm">
              <tr>
                <WifiSortTh label="From" active={sort.key === "from"} dir={sort.dir} align="left" onClick={() => toggleSort("from")} />
                <WifiSortTh label="To" active={sort.key === "to"} dir={sort.dir} align="left" onClick={() => toggleSort("to")} />
                <WifiSortTh label="Events" active={sort.key === "count"} dir={sort.dir} align="right" onClick={() => toggleSort("count")} />
                <WifiSortTh label="Share %" active={sort.key === "share_pct"} dir={sort.dir} align="right" onClick={() => toggleSort("share_pct")} />
              </tr>
            </thead>
            <tbody>
              {sorted.map((tr: WifiFleetRadioTransition, i: number) => (
                <tr key={`${tr.from}-${tr.to}-${i}`} className="border-b border-border/50">
                  <td className={wifiChannelValueCellClass(tr.from, is5GHzRadio)}>{tr.from}</td>
                  <td className={wifiChannelValueCellClass(tr.to, is5GHzRadio)}>{tr.to}</td>
                  <td className="py-1 px-2 text-right tabular-nums">{tr.count}</td>
                  <td className="py-1 px-2 text-right tabular-nums">{tr.share_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function WifiFleetRadioGrid({ fleet }: { fleet: WifiFleetRadioTable[] }) {
  const r1 = useMemo(() => fleet.find((t) => t.radio === 1), [fleet]);
  const r2 = useMemo(() => fleet.find((t) => t.radio === 2), [fleet]);
  return (
    <div className="grid grid-cols-2 gap-3">
      <WifiRadioChannelsPanel radioNum={1} tbl={r1} />
      <WifiRadioSwitchesPanel radioNum={1} tbl={r1} />
      <WifiRadioChannelsPanel radioNum={2} tbl={r2} />
      <WifiRadioSwitchesPanel radioNum={2} tbl={r2} />
    </div>
  );
}

function WifiRfDetailPanel({ serial, wifi }: { serial: string; wifi: WifiRfPayload | undefined }) {
  const empty = !wifi || (wifi.radios.length === 0 && (wifi.channel_events?.length ?? 0) === 0);
  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-3 py-1.5 border-b border-border bg-muted/30">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
          <WifiIcon style={{ fontSize: 14, color: "#00897b" }} />
          WiFi RF &mdash; {serial}
        </h3>
      </div>
      {empty && (
        <div className="px-3 py-6 text-xs text-muted-foreground">
          No WiFi radio time series in cache (channel / utilization charts need at least two numeric samples per field). Latest band/BW may still appear if status cards were parsed.
        </div>
      )}
      {!empty && wifi && (
        <div className="px-2 py-2 space-y-3 text-[11px]">
          <p className="text-[10px] text-muted-foreground px-1">
            Crowded = max ch util ≥ {wifi.util_crowded_max_pct}% or avg ≥ {wifi.util_crowded_avg_pct}%. DFS hint = 5 GHz and channel in common EU (ETSI-style) DFS range (indicative).
          </p>
          {wifi.radios.length > 0 && (
            <div className="overflow-auto">
              <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1 px-1">Radios</div>
              <table className="w-full border-collapse text-[10px]">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-1 pr-2">R</th>
                    <th className="py-1 pr-2">Band</th>
                    <th className="py-1 pr-2">BW</th>
                    <th className="py-1 pr-2">Channel</th>
                    <th className="py-1 pr-2">Δ</th>
                    <th className="py-1 pr-2">Util max</th>
                    <th className="py-1 pr-2">Util avg</th>
                    <th className="py-1 pr-2">Util last</th>
                    <th className="py-1 pr-2">Crowded</th>
                  </tr>
                </thead>
                <tbody>
                  {wifi.radios.map((r) => (
                    <tr key={r.radio} className="border-b border-border/60">
                      <td className="py-1 pr-2 font-mono">{r.radio}</td>
                      <td className="py-1 pr-2">{r.band ?? "—"}</td>
                      <td className="py-1 pr-2">{r.bandwidth ?? "—"}</td>
                      <td className="py-1 pr-2 tabular-nums">
                        {r.channel_first != null && r.channel_last != null && r.channel_first !== r.channel_last
                          ? `${r.channel_first}→${r.channel_last}`
                          : r.channel_last ?? r.channel_first ?? "—"}
                      </td>
                      <td className="py-1 pr-2 tabular-nums">{r.channel_change_count}</td>
                      <td className="py-1 pr-2 tabular-nums">{r.util_max != null ? `${r.util_max}%` : "—"}</td>
                      <td className="py-1 pr-2 tabular-nums">{r.util_avg != null ? `${r.util_avg}%` : "—"}</td>
                      <td className="py-1 pr-2 tabular-nums">{r.util_last != null ? `${r.util_last}%` : "—"}</td>
                      <td className="py-1 pr-2">{r.crowded ? <span className="text-orange-600 dark:text-orange-400 font-semibold">Yes</span> : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {(wifi.channel_events?.length ?? 0) > 0 && (
            <div className="overflow-auto max-h-48">
              <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1 px-1">Channel changes</div>
              <table className="w-full border-collapse text-[10px]">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-1 pr-2">Time</th>
                    <th className="py-1 pr-2">R</th>
                    <th className="py-1 pr-2">From→to</th>
                    <th className="py-1 pr-2">Band</th>
                    <th className="py-1 pr-2">DFS hint</th>
                  </tr>
                </thead>
                <tbody>
                  {wifi.channel_events.map((e, i) => (
                    <tr key={`${e.at_time}-${e.radio}-${i}`} className="border-b border-border/60">
                      <td className="py-1 pr-2 whitespace-nowrap font-mono text-[9px]">{e.at_time || "—"}</td>
                      <td className="py-1 pr-2 font-mono">{e.radio}</td>
                      <td className="py-1 pr-2 tabular-nums">{e.from_channel}→{e.to_channel}</td>
                      <td className="py-1 pr-2">{e.band ?? "—"}</td>
                      <td className="py-1 pr-2">{e.dfs_related ? <span className="text-violet-700 dark:text-violet-400">Yes</span> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status, cfg }: { status: string; cfg: typeof STATUS_CFG[string] }) {
  const Icon = cfg.icon;
  const textColor = status === "OK"
    ? "text-green-700 dark:text-green-400"
    : status === "MEMLEAK"
      ? "text-orange-700 dark:text-orange-400"
      : "text-red-700 dark:text-red-400";
  return (
    <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full ${cfg.bg} ${cfg.darkBg} ${textColor} text-[9px] font-bold`}>
      <Icon style={{ fontSize: 10 }} /> {cfg.label}
    </span>
  );
}

function SummaryBadge({
  icon,
  label,
  value,
  sub,
  bgClass,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  sub?: string;
  bgClass: string;
}) {
  return (
    <div className={`${bgClass} border border-border rounded-xl p-3 flex items-center gap-3`}>
      <div className="rounded-lg bg-white/60 dark:bg-black/20 p-2">{icon}</div>
      <div>
        <div className="text-xl font-bold tabular-nums">
          {value}
          {sub && <span className="text-xs font-normal text-muted-foreground ml-1">({sub})</span>}
        </div>
        <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">{label}</div>
      </div>
    </div>
  );
}

function ThSort({
  col,
  label,
  sortKey: _sortKey,
  sortDir: _sortDir,
  onSort,
  SortIcon,
  align = "left",
}: {
  col: SortKey;
  label: string;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onSort: (k: SortKey) => void;
  SortIcon: React.FC<{ col: SortKey }>;
  align?: "left" | "right";
}) {
  return (
    <th
      className={`text-${align} px-2 py-1 font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap`}
      onClick={() => onSort(col)}
    >
      {label} <SortIcon col={col} />
    </th>
  );
}

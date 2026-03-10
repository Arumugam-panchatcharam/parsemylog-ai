import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { telemetryApi } from "@/api/endpoints";
import type { CrossCpeTelemetryEntry } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import Plot from "react-plotly.js";
import CircularProgress from "@mui/material/CircularProgress";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import StorageIcon from "@mui/icons-material/Storage";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import ErrorIcon from "@mui/icons-material/Error";
import CloseIcon from "@mui/icons-material/Close";
import MemoryIcon from "@mui/icons-material/Memory";
import RefreshIcon from "@mui/icons-material/Refresh";

/* ---------------------------------------------------------------- Types */

type SortKey = "serial" | "model" | "reboot_count" | "memory_usage_pct_peak" | "memory_free_min";

/* ---------------------------------------------------------------- Helpers */

const STATUS_CFG: Record<string, { color: string; bg: string; darkBg: string; border: string; darkBorder: string; label: string; icon: React.ElementType }> = {
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

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["telemetry-cross-cpe-overview", projectId],
    queryFn: async () => (await telemetryApi.crossCpeOverview(projectId!)).data,
    enabled: !!projectId,
    staleTime: 5 * 60 * 1000,
  });

  const handleForceRefresh = async () => {
    if (!projectId || isRefreshing) return;
    setIsRefreshing(true);
    try {
      const result = await telemetryApi.crossCpeOverview(projectId, true);
      // Update the query cache directly with the new data instead of invalidating
      queryClient.setQueryData(["telemetry-cross-cpe-overview", projectId], result.data);
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
    const events = (cpeChartData?.reboot_timeline?.events ?? []) as Array<{ time: string }>;
    return events.map((evt) => ({
      type: "line" as const,
      xref: "x" as const,
      yref: "paper" as const,
      x0: evt.time,
      x1: evt.time,
      y0: 0,
      y1: 1,
      line: { color: "#d93025", width: 1.5, dash: "dot" as const },
    }));
  }, [cpeChartData]);

  const rebootAnnotations = useMemo(() => {
    const events = (cpeChartData?.reboot_timeline?.events ?? []) as Array<{ time: string }>;
    return events.map((evt) => ({
      x: evt.time,
      y: 1,
      xref: "x" as const,
      yref: "paper" as const,
      text: "Reboot",
      showarrow: false,
      font: { size: 8, color: "#d93025" },
      yanchor: "bottom" as const,
    }));
  }, [cpeChartData]);

  const rebootXRange = useMemo<[string, string] | undefined>(() => {
    const events = (cpeChartData?.reboot_timeline?.events ?? []) as Array<{ time: string }>;
    if (events.length !== 1) return undefined;
    const TWO_HOURS_MS = 2 * 60 * 60 * 1000;
    const ts = new Date(events[0].time).getTime();
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
      setSortDir("desc");
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
      {/* Header with Force Refresh Button */}
      <div className="flex justify-end">
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
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
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
      </div>

      {/* CPE Detail Table */}
      <div className="flex justify-center">
        <div className="bg-card border border-border rounded-xl overflow-hidden inline-block">
          <div className="px-3 py-1 border-b border-border bg-muted/30">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              CPE Memory &amp; Reboot Detail
            </h3>
          </div>

          <div className="overflow-auto max-h-[calc(100vh-300px)]">
            <table className="text-[11px] border-collapse">
              <colgroup>
                <col style={{ width: "140px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "80px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "100px" }} />
                <col style={{ width: "120px" }} />
                <col style={{ width: "100px" }} />
              </colgroup>
              <thead className="sticky top-0 z-10 bg-card">
                <tr className="border-b border-border bg-muted/20">
                  <ThSort col="serial" label="Serial" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} />
                  <ThSort col="model" label="Model" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} />
                  <ThSort col="reboot_count" label="Reboots" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} align="right" />
                  <ThSort col="memory_usage_pct_peak" label="Mem Usage" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} align="right" />
                  <ThSort col="memory_free_min" label="Min Free" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} SortIcon={SortIcon} align="right" />
                  <th className="text-right px-2 py-1 font-semibold text-muted-foreground">Min Avail</th>
                  <th className="text-right px-2 py-1 font-semibold text-muted-foreground">Total</th>
                  <th className="text-right px-2 py-1 font-semibold text-muted-foreground">Uptime</th>
                  <th className="text-center px-2 py-1 font-semibold text-muted-foreground">Status</th>
                </tr>
              </thead>
              <tbody>
                {sortedCpes.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-2 py-6 text-center text-muted-foreground">
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
                      className={`border-b cursor-pointer hover:bg-muted/30 transition-colors ${isSelected ? "ring-2 ring-primary/40 ring-inset" : ""} ${severityRowClass(cpe)}`}
                      onClick={() => handleRowClick(cpe.serial)}
                    >
                      <td className="px-2 py-1.5 font-mono font-medium text-foreground">
                        {cpe.serial}
                      </td>
                      <td className="px-2 py-1.5 text-muted-foreground">{cpe.model}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums font-medium">
                        {cpe.reboot_count > 0 ? (
                          <span className="text-red-600 dark:text-red-400">{cpe.reboot_count}</span>
                        ) : (
                          <span className="text-muted-foreground">0</span>
                        )}
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
                      <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                        {fmtMemory(cpe.memory_free_min, unit)}
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                        {fmtMemory(cpe.memory_available_min, unit)}
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                        {fmtMemory(cpe.memory_total, unit)}
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground whitespace-nowrap">
                        {(cpe.reboot_events ?? []).length > 0
                          ? (cpe.reboot_events ?? []).map((evt) => fmtDurationSec(evt.prev_uptime)).join(" / ")
                          : "—"}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        <StatusBadge status={cpe.status ?? "OK"} cfg={cfg} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Memory Timeline Chart */}
      {selectedCpe && (
        <div className="bg-card border border-border rounded-xl overflow-hidden max-h-[calc(100vh-280px)]">
          <div className="px-3 py-1.5 border-b border-border bg-muted/30 flex items-center justify-between">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <MemoryIcon style={{ fontSize: 14, color: "#1a73e8" }} />
                Memory Timeline &mdash; {selectedCpe}
              </h3>
              <button
                onClick={(e) => { e.stopPropagation(); setSelectedCpe(null); }}
                className="text-muted-foreground hover:text-foreground p-0.5 rounded hover:bg-muted transition-colors"
              >
                <CloseIcon style={{ fontSize: 14 }} />
              </button>
            </div>
            <div className="px-2 py-1 overflow-auto">
              {cpeChartLoading && (
                <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground">
                  <CircularProgress size={18} />
                  <span className="text-xs">Loading memory data...</span>
                </div>
              )}
              {!cpeChartLoading && memoryTraces && memoryTraces.length > 0 && (
                <Plot
                  data={memoryTraces.map((t) => ({
                    type: "scatter" as const,
                    mode: "lines" as const,
                    x: t.times,
                    y: t.values,
                    name: `${t.label} (${t.unit})`,
                    line: { color: t.style.color, width: 2, dash: t.style.dash },
                  }))}
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
                <div className="py-8 text-center text-xs text-muted-foreground">
                  No memory chart data available for this CPE.
                </div>
              )}
            </div>
          </div>
        )}
    </div>
  );
}

/* ---------------------------------------------------------------- Sub-components */

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

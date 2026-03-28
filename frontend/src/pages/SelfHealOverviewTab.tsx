import { Fragment, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { selfhealApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import Plot from "react-plotly.js";
import type { Data } from "plotly.js";
import CircularProgress from "@mui/material/CircularProgress";
import MemoryIcon from "@mui/icons-material/Memory";
import StorageIcon from "@mui/icons-material/Storage";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import ErrorIcon from "@mui/icons-material/Error";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import RefreshIcon from "@mui/icons-material/Refresh";

/* Color Thresholds for Health Status */
const COLOR_SCHEME = {
  // MemAvailable %: Green > 30%, Yellow 20-30%, Orange 10-20%, Red < 10%
  memAvailable: {
    green: "#16a34a",    // > 30%
    yellow: "#eab308",   // 20-30%
    orange: "#ea580c",   // 10-20%
    red: "#dc2626",      // < 10%
  },
  // CPU %: Green 5-15%, Yellow 15-20%, Orange > 20%
  cpu: {
    green: "#16a34a",    // 5-15%
    yellow: "#eab308",   // 15-20%
    orange: "#ea580c",   // > 20%
  },
  // SUnreclaim: Green < 50%, Yellow 50-70%, Orange 70-80%, Red > 80%
  sunreclaim: {
    green: "#16a34a",    // < 50%
    yellow: "#eab308",   // 50-70%
    orange: "#ea580c",   // 70-80%
    red: "#dc2626",      // > 80%
  },
  // Overcommit: Green < 1x, Yellow 1-2x, Orange 2-4x, Red > 4x
  overcommit: {
    green: "#16a34a",    // < 1x
    yellow: "#eab308",   // 1-2x
    orange: "#ea580c",   // 2-4x
    red: "#dc2626",      // > 4x
  },
};

/* ================================================================ Color Coding Functions */

/**
 * Get color for MemAvailable percentage value
 */
function getMemAvailableColor(percent: number): string {
  if (percent > 30) return COLOR_SCHEME.memAvailable.green;
  if (percent >= 20) return COLOR_SCHEME.memAvailable.yellow;
  if (percent >= 10) return COLOR_SCHEME.memAvailable.orange;
  return COLOR_SCHEME.memAvailable.red;
}

/**
 * Get color for CPU percentage value
 */
function getCpuColor(percent: number): string {
  if (percent < 15) return COLOR_SCHEME.cpu.green;
  if (percent < 20) return COLOR_SCHEME.cpu.yellow;
  return COLOR_SCHEME.cpu.orange;
}

/**
 * Get color for SUnreclaim ratio (percentage)
 */
function getSUnreclaimColor(percent: number): string {
  if (percent < 50) return COLOR_SCHEME.sunreclaim.green;
  if (percent < 70) return COLOR_SCHEME.sunreclaim.yellow;
  if (percent < 80) return COLOR_SCHEME.sunreclaim.orange;
  return COLOR_SCHEME.sunreclaim.red;
}

/**
 * Get color for Overcommit ratio
 */
function getOvercommitColor(ratio: number): string {
  if (ratio < 1) return COLOR_SCHEME.overcommit.green;
  if (ratio < 2) return COLOR_SCHEME.overcommit.yellow;
  if (ratio < 4) return COLOR_SCHEME.overcommit.orange;
  return COLOR_SCHEME.overcommit.red;
}

/**
 * Create multi-colored histogram traces for each color group
 * This overlays histograms to show color-coding without changing x-axis
 */
function createColorCodedHistogramTraces(
  values: number[],
  nbins: number,
  colorFn: (value: number) => string,
): Data[] {
  if (values.length === 0) return [];

  // Group values by their assigned color
  const colorGroups: Record<string, number[]> = {};
  
  values.forEach((val) => {
    const color = colorFn(val);
    if (!colorGroups[color]) {
      colorGroups[color] = [];
    }
    colorGroups[color].push(val);
  });

  // Create a trace for each color group
  return Object.entries(colorGroups).map(([color, vals]) => ({
    x: vals,
    type: "histogram" as const,
    nbinsx: nbins,
    marker: { color },
    showlegend: false,
    hovertemplate: "Value: %{x}<br>Count: %{y}<extra></extra>",
  })) as unknown as Data[];
}

/* ================================================================ Types */
interface SelfHealCPEEntry {
  serial: string;
  status: string;
  peak_memory_usage_pct: number;
  min_memory_available_kb?: number;
  avg_memory_available_kb?: number;
  mem_available_min_pct?: number | null;
  mem_available_avg_pct?: number | null;
  peak_cpu_usage_pct: number;
  avg_cpu_usage_pct?: number | null;
  cpu_sample_count?: number;
  snapshot_count?: number;
  slab_ols_slope_kb_per_step?: number | null;
  total_user_rss_ols_slope_kb_per_step?: number | null;
  alerts: string[];
  memory_pressure: {
    low_memory?: boolean;
    sunreclaim_pct?: number;
    overcommit_ratio?: number;
    pressure_score_0_100?: number;
    cached_pct_of_memtotal?: number;
  };
  sunreclaim_pct: number;
  overcommit_ratio: number;
  pressure_score_0_100?: number;
  cached_pct_of_memtotal?: number;
}

interface OverviewStats {
  total_cpes: number;
  cpes_low_memory: number;
  cpes_high_rss: number;
  cpes_memory_pressure: number;
  cpes_no_swap: number;
  cpes_kernel_leak: number;
}

interface FleetProcessLeakRow {
  process: string;
  cpes_affected: number;
  cpe_serials?: string[];
  avg_slope_kb: number;
  max_slope_kb: number;
}

interface FleetHeatmapPayload {
  processes: string[];
  cpes: string[];
  z: number[][];
  heatmap_max_processes: number;
  heatmap_max_cpes: number;
}

interface FleetMeta {
  leak_slope_threshold_kb: number;
  top_process_limit: number;
}

interface NarrativeSummary {
  plain_text: string;
  generated_at_utc: string;
  schema_version: number;
}

interface CrossCPEOverviewData {
  overview: OverviewStats;
  cpes: SelfHealCPEEntry[];
  fleet_process_leaks?: FleetProcessLeakRow[];
  heatmap?: FleetHeatmapPayload;
  fleet_meta?: FleetMeta;
  narrative_summary?: NarrativeSummary;
}

/* ================================================================ Helpers */
type SortKey =
  | "serial"
  | "status"
  | "peak_memory_usage_pct"
  | "min_memory_available_kb"
  | "mem_available_min_pct"
  | "pressure_score_0_100"
  | "peak_cpu_usage_pct"
  | "avg_cpu_usage_pct"
  | "slab_ols_slope_kb_per_step"
  | "total_user_rss_ols_slope_kb_per_step";

const STATUS_CFG: Record<
  string,
  { color: string; bg: string; darkBg: string; border: string; darkBorder: string; label: string; icon: React.ElementType }
> = {
  KERNEL_LEAK: {
    color: "#d93025",
    bg: "bg-red-100",
    darkBg: "dark:bg-red-900/30",
    border: "border-red-200",
    darkBorder: "dark:border-red-800",
    label: "KERNEL LEAK",
    icon: ErrorIcon,
  },
  OVERCOMMIT_RISK: {
    color: "#e8710a",
    bg: "bg-orange-100",
    darkBg: "dark:bg-orange-900/30",
    border: "border-orange-200",
    darkBorder: "dark:border-orange-800",
    label: "OVERCOMMIT",
    icon: WarningAmberIcon,
  },
  NO_SWAP: {
    color: "#d93025",
    bg: "bg-red-100",
    darkBg: "dark:bg-red-900/30",
    border: "border-red-200",
    darkBorder: "dark:border-red-800",
    label: "NO SWAP",
    icon: StorageIcon,
  },
  LOW_MEMORY: {
    color: "#e8710a",
    bg: "bg-orange-100",
    darkBg: "dark:bg-orange-900/30",
    border: "border-orange-200",
    darkBorder: "dark:border-orange-800",
    label: "LOW MEM",
    icon: WarningAmberIcon,
  },
  OK: {
    color: "#188038",
    bg: "bg-green-100",
    darkBg: "dark:bg-green-900/30",
    border: "border-green-200",
    darkBorder: "dark:border-green-800",
    label: "OK",
    icon: StorageIcon,
  },
};

function statusCfg(status: string) {
  return STATUS_CFG[status] ?? STATUS_CFG.OK;
}

function severityRowClass(status: string): string {
  if (status === "KERNEL_LEAK" || status === "NO_SWAP")
    return "bg-red-50 dark:bg-red-900/15 border-red-200 dark:border-red-800";
  if (status === "OVERCOMMIT_RISK" || status === "LOW_MEMORY")
    return "bg-orange-50 dark:bg-orange-900/10 border-orange-200 dark:border-orange-800";
  return "border-border";
}

/** Top-level project dirs mistaken for CPE serials (aligned with API cross-CPE exclusions). */
const RESERVED_FLEET_CPE_SERIALS = new Set(
  ["selfheal", "issue_analysis", "staging", "raw", "telemetry"].map((s) => s.toLowerCase()),
);

function isReservedFleetCpeSerial(serial: string): boolean {
  return RESERVED_FLEET_CPE_SERIALS.has(serial.trim().toLowerCase());
}

const FLEET_CPE_TABLE_COLS: { key: SortKey; label: string; align: "left" | "right" }[] = [
  { key: "serial", label: "Serial", align: "left" },
  { key: "status", label: "Status", align: "left" },
  { key: "pressure_score_0_100", label: "Pressure", align: "right" },
  { key: "mem_available_min_pct", label: "Min MemAvail %", align: "right" },
  { key: "peak_memory_usage_pct", label: "Peak Mem %", align: "right" },
  { key: "min_memory_available_kb", label: "Min Avail", align: "right" },
  { key: "peak_cpu_usage_pct", label: "Peak CPU", align: "right" },
  { key: "avg_cpu_usage_pct", label: "Avg CPU", align: "right" },
  { key: "slab_ols_slope_kb_per_step", label: "Slab Δ", align: "right" },
  { key: "total_user_rss_ols_slope_kb_per_step", label: "RSS Σ Δ", align: "right" },
];

function fleetCpeTableCell(cpe: SelfHealCPEEntry, colKey: SortKey): ReactNode {
  switch (colKey) {
    case "serial":
      return <span className="font-mono font-medium text-foreground">{cpe.serial}</span>;
    case "status": {
      const cfg = statusCfg(cpe.status);
      const Icon = cfg.icon;
      return (
        <div className="flex items-center gap-1 min-w-0">
          <div
            className="px-1.5 py-0.5 rounded text-[10px] font-medium text-white flex items-center gap-0.5 shrink-0"
            style={{ backgroundColor: cfg.color }}
          >
            <Icon style={{ fontSize: 12 }} />
            {cfg.label}
          </div>
        </div>
      );
    }
    case "pressure_score_0_100":
      return cpe.pressure_score_0_100 != null ? cpe.pressure_score_0_100.toFixed(1) : "—";
    case "mem_available_min_pct":
      return cpe.mem_available_min_pct != null ? `${cpe.mem_available_min_pct.toFixed(1)}%` : "—";
    case "peak_memory_usage_pct":
      return `${cpe.peak_memory_usage_pct.toFixed(1)}%`;
    case "min_memory_available_kb":
      return fmtMemory(cpe.min_memory_available_kb);
    case "peak_cpu_usage_pct":
      return `${cpe.peak_cpu_usage_pct}%`;
    case "avg_cpu_usage_pct":
      return cpe.avg_cpu_usage_pct != null ? `${cpe.avg_cpu_usage_pct.toFixed(1)}%` : "—";
    case "slab_ols_slope_kb_per_step":
      return cpe.slab_ols_slope_kb_per_step != null ? cpe.slab_ols_slope_kb_per_step.toFixed(2) : "—";
    case "total_user_rss_ols_slope_kb_per_step":
      return cpe.total_user_rss_ols_slope_kb_per_step != null
        ? cpe.total_user_rss_ols_slope_kb_per_step.toFixed(2)
        : "—";
    default:
      return "—";
  }
}

function fleetCpeCellClass(colKey: SortKey, align: "left" | "right"): string {
  const alignCls = align === "right" ? "text-right tabular-nums" : "text-left";
  const muted =
    colKey === "mem_available_min_pct" ||
    colKey === "min_memory_available_kb" ||
    colKey === "slab_ols_slope_kb_per_step" ||
    colKey === "total_user_rss_ols_slope_kb_per_step";
  const colorCls = muted
    ? "text-muted-foreground"
    : colKey === "serial" || colKey === "status"
      ? ""
      : "text-foreground";
  return `px-2 py-1.5 whitespace-nowrap align-middle ${alignCls} ${colorCls}`.trim();
}

function fmtMemory(val?: number | null, unit = "KB"): string {
  if (val == null) return "N/A";
  const u = unit.toLowerCase();
  if (u === "kb") {
    if (val >= 1_000_000) return `${(val / (1024 * 1024)).toFixed(2)} GB`;
    if (val >= 1024) return `${(val / 1024).toFixed(1)} MB`;
    return `${val} KB`;
  }
  return `${val} ${unit}`;
}

/** Match SelfHeal CPE Analysis metric cards (typography + layout) */
function OverviewStatBadge({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-border p-2.5 bg-card">
      <div className="flex items-center gap-2">
        <div className="rounded-md p-1 shrink-0 bg-primary/10">{icon}</div>
        <span className="text-xs font-semibold flex-1 text-foreground">{label}</span>
      </div>
      <p className="text-[11px] mt-1 pl-7 font-semibold tabular-nums text-foreground">
        {value}
        {sub != null && sub !== "" && (
          <span className="text-muted-foreground font-normal ml-1">({sub})</span>
        )}
      </p>
    </div>
  );
}

const PLOT_PAGE_FS = 10;
const PLOT_TICK_FS = 9;
const PLOT_CHART_TITLE_FS = 11;

function basePlotLayout(title: string, darkMode: boolean): Record<string, unknown> {
  const fg = darkMode ? "#e4e4e7" : "#18181b";
  return {
    title: { text: title, font: { size: PLOT_CHART_TITLE_FS, color: fg, family: "system-ui, sans-serif" } },
    paper_bgcolor: darkMode ? "#0b0b0c" : "#ffffff",
    plot_bgcolor: darkMode ? "#121214" : "#fafafa",
    font: { family: "system-ui, sans-serif", size: PLOT_PAGE_FS, color: fg },
    height: 320,
    margin: { t: 38, b: 42, l: 46, r: 16 },
    legend: { font: { size: PLOT_TICK_FS } },
  };
}

/* ================================================================ Component */
export default function SelfHealOverviewTab() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();

  const [sortKey, setSortKey] = useState<SortKey>("min_memory_available_kb");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [memAvailField, setMemAvailField] = useState<"min" | "avg">("min");
  const [fleetExecSummaryOpen, setFleetExecSummaryOpen] = useState(false);
  const [leakRowOpen, setLeakRowOpen] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const prefersDark =
    typeof document !== "undefined" && document.documentElement.classList.contains("dark");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["selfheal-cross-cpe-overview", projectId],
    queryFn: async () => {
      if (!projectId) throw new Error("Missing projectId");
      const res = await selfhealApi.crossCpeOverview(projectId, false);
      return res.data as CrossCPEOverviewData;
    },
    enabled: !!projectId,
    // Server caches fleet overview; avoid redundant refetches while navigating
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
  });

  const handleForceRefresh = async () => {
    if (!projectId || isRefreshing) return;
    setIsRefreshing(true);
    try {
      const res = await selfhealApi.crossCpeOverview(projectId, true);
      queryClient.setQueryData(["selfheal-cross-cpe-overview", projectId], res.data);
    } catch (err) {
      console.error("Force refresh failed:", err);
    } finally {
      setIsRefreshing(false);
    }
  };

  const sortedCpes = useMemo(() => {
    if (!data?.cpes) return [];
    const rows = data.cpes.filter((c) => !isReservedFleetCpeSerial(c.serial));
    const sorted = [...rows].sort((a, b) => {
      let aVal: number | string | null | undefined = a[sortKey] as unknown as number | string | undefined;
      let bVal: number | string | null | undefined = b[sortKey] as unknown as number | string | undefined;

      if (sortKey === "status") {
        const order: Record<string, number> = {
          KERNEL_LEAK: 0,
          OVERCOMMIT_RISK: 1,
          NO_SWAP: 2,
          LOW_MEMORY: 3,
          OK: 4,
        };
        aVal = order[String(a.status)] ?? 5;
        bVal = order[String(b.status)] ?? 5;
      }

      if (aVal == null) aVal = sortKey === "serial" ? "" : Infinity;
      if (bVal == null) bVal = sortKey === "serial" ? "" : Infinity;

      const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [data?.cpes, sortKey, sortDir]);

  const memAvailHistogramX = useMemo(() => {
    const field = memAvailField === "min" ? "mem_available_min_pct" : "mem_available_avg_pct";
    return sortedCpes
      .map((c) => c[field as keyof SelfHealCPEEntry] as number | null | undefined)
      .filter((v): v is number => typeof v === "number" && !Number.isNaN(v));
  }, [sortedCpes, memAvailField]);

  const avgCpuHistogramX = useMemo(
    () =>
      sortedCpes
        .map((c) => c.avg_cpu_usage_pct)
        .filter((v): v is number => typeof v === "number" && !Number.isNaN(v)),
    [sortedCpes],
  );

  const slabUserScatter = useMemo(() => {
    const pts = sortedCpes.filter(
      (c) =>
        c.slab_ols_slope_kb_per_step != null &&
        c.total_user_rss_ols_slope_kb_per_step != null,
    );
    return {
      x: pts.map((c) => c.slab_ols_slope_kb_per_step as number),
      y: pts.map((c) => c.total_user_rss_ols_slope_kb_per_step as number),
      text: pts.map((c) => c.serial),
    };
  }, [sortedCpes]);

  const sunreclaimHist = useMemo(
    () =>
      sortedCpes
        .map((c) => c.sunreclaim_pct)
        .filter((v) => typeof v === "number" && !Number.isNaN(v)),
    [sortedCpes],
  );

  const overcommitHist = useMemo(
    () =>
      sortedCpes
        .map((c) => c.overcommit_ratio)
        .filter((v) => typeof v === "number" && !Number.isNaN(v)),
    [sortedCpes],
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <CircularProgress />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 rounded-lg p-6">
        <div className="flex items-center gap-3 mb-2">
          <ErrorIcon className="text-red-600" />
          <h3 className="font-semibold text-red-800 dark:text-red-200">Error loading SelfHeal overview</h3>
        </div>
        <p className="text-red-700 dark:text-red-300 text-sm">{String(error)}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-center py-12">
        <p className="text-muted-foreground text-base">Loading SelfHeal data for all CPEs...</p>
      </div>
    );
  }

  const overview = data.overview;
  const fleetLeaks = data.fleet_process_leaks ?? [];
  const fleetMeta = data.fleet_meta;

  if (overview.total_cpes === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-muted-foreground text-base">
          No CPEs with SelfHeal data available. SelfHeal.txt parsing will be triggered when data is available.
        </p>
      </div>
    );
  }

  const layoutBase = basePlotLayout("", prefersDark);
  const axisFg = prefersDark ? "#e4e4e7" : "#18181b";
  const plotAxis = (label: string, extra: Record<string, unknown> = {}) => ({
    title: { text: label, font: { size: PLOT_PAGE_FS, color: axisFg } },
    tickfont: { size: PLOT_TICK_FS, color: axisFg },
    ...extra,
  });
  const plotChartTitle = (text: string) => ({
    text,
    font: { size: PLOT_CHART_TITLE_FS, color: axisFg, family: "system-ui, sans-serif" as const },
  });

  return (
    <div className="space-y-3">
      {/* Header with Force Refresh Button */}
      <div className="flex justify-end gap-2">
        <button
          onClick={handleForceRefresh}
          disabled={isRefreshing || isLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-card hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-foreground"
          title="Force parse and update fleet-wide analytics"
        >
          {isRefreshing ? (
            <CircularProgress size={14} className="text-muted-foreground" />
          ) : (
            <RefreshIcon style={{ fontSize: 14 }} />
          )}
          {isRefreshing ? "Refreshing..." : "Force Refresh"}
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <OverviewStatBadge
          icon={<MemoryIcon style={{ fontSize: 16, color: "#1a73e8" }} />}
          label="Total CPEs"
          value={overview.total_cpes}
        />
        <OverviewStatBadge
          icon={<WarningAmberIcon style={{ fontSize: 16, color: "#e8710a" }} />}
          label="Low Memory"
          value={overview.cpes_low_memory}
          sub={overview.total_cpes > 0 ? `${Math.round((overview.cpes_low_memory / overview.total_cpes) * 100)}%` : undefined}
        />
        <OverviewStatBadge
          icon={<StorageIcon style={{ fontSize: 16, color: "#f9ab00" }} />}
          label="High RSS"
          value={overview.cpes_high_rss}
          sub={overview.total_cpes > 0 ? `${Math.round((overview.cpes_high_rss / overview.total_cpes) * 100)}%` : undefined}
        />
        <OverviewStatBadge
          icon={<WarningAmberIcon style={{ fontSize: 16, color: "#e8710a" }} />}
          label="Memory Pressure"
          value={overview.cpes_memory_pressure}
          sub={overview.total_cpes > 0 ? `${Math.round((overview.cpes_memory_pressure / overview.total_cpes) * 100)}%` : undefined}
        />
        <OverviewStatBadge
          icon={<ErrorIcon style={{ fontSize: 16, color: "#d93025" }} />}
          label="No Swap"
          value={overview.cpes_no_swap}
          sub={overview.total_cpes > 0 ? `${Math.round((overview.cpes_no_swap / overview.total_cpes) * 100)}%` : undefined}
        />
        <OverviewStatBadge
          icon={<ErrorIcon style={{ fontSize: 16, color: "#d93025" }} />}
          label="Kernel Leak"
          value={overview.cpes_kernel_leak}
          sub={overview.total_cpes > 0 ? `${Math.round((overview.cpes_kernel_leak / overview.total_cpes) * 100)}%` : undefined}
        />
      </div>

      {data.narrative_summary?.plain_text && (
        <div className="rounded-lg border border-border bg-card p-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setFleetExecSummaryOpen((o) => !o)}
              className="flex items-center gap-1 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
            >
              {fleetExecSummaryOpen ? (
                <ExpandLessIcon style={{ fontSize: 18 }} />
              ) : (
                <ExpandMoreIcon style={{ fontSize: 18 }} />
              )}
              Executive summary (fleet)
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] hover:bg-muted"
              onClick={() => {
                void navigator.clipboard.writeText(data.narrative_summary!.plain_text);
              }}
            >
              <ContentCopyIcon style={{ fontSize: 14 }} />
              Copy
            </button>
          </div>
          {fleetExecSummaryOpen && (
            <>
              <pre className="text-[11px] whitespace-pre-wrap font-sans text-foreground leading-relaxed max-h-80 overflow-y-auto mt-2">
                {data.narrative_summary.plain_text}
              </pre>
              {data.narrative_summary.generated_at_utc && (
                <p className="text-[10px] text-muted-foreground mt-2">
                  Generated {data.narrative_summary.generated_at_utc} UTC
                </p>
              )}
            </>
          )}
        </div>
      )}

      {/* Fleet distributions */}
      <div className="bg-card border border-border rounded-lg p-2.5 space-y-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Fleet distributions</h3>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs text-muted-foreground">MemAvailable (% of MemTotal)</span>
              <select
                className="text-xs border rounded px-2 py-0.5 bg-background"
                value={memAvailField}
                onChange={(e) => setMemAvailField(e.target.value as "min" | "avg")}
              >
                <option value="min">Min over window</option>
                <option value="avg">Avg over window</option>
              </select>
            </div>
            <Plot
              data={createColorCodedHistogramTraces(
                memAvailHistogramX,
                24,
                getMemAvailableColor,
              )}
              layout={{
                ...layoutBase,
                title: plotChartTitle(
                  memAvailField === "min"
                    ? "MemAvailable % (minimum per CPE)"
                    : "MemAvailable % (average per CPE)",
                ),
                xaxis: plotAxis("MemAvailable / MemTotal (%)"),
                yaxis: plotAxis("# CPEs"),
                barmode: "stack" as const,
              }}
              useResizeHandler
              style={{ width: "100%" }}
              config={{ displayModeBar: false }}
            />
          </div>
          <div>
            <Plot
              data={createColorCodedHistogramTraces(
                avgCpuHistogramX,
                24,
                getCpuColor,
              )}
              layout={{
                ...layoutBase,
                title: plotChartTitle("Average CPU % (per CPE)"),
                xaxis: plotAxis("Avg CPU usage %"),
                yaxis: plotAxis("# CPEs"),
                barmode: "stack" as const,
              }}
              useResizeHandler
              style={{ width: "100%" }}
              config={{ displayModeBar: false }}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <Plot
            data={createColorCodedHistogramTraces(
              sunreclaimHist,
              20,
              getSUnreclaimColor,
            )}
            layout={{
              ...layoutBase,
              title: plotChartTitle("SUnreclaim (% of Slab)"),
              xaxis: plotAxis("SUnreclaim / Slab (%)"),
              yaxis: plotAxis("# CPEs"),
              barmode: "stack" as const,
            }}
            useResizeHandler
            style={{ width: "100%" }}
            config={{ displayModeBar: false }}
          />
          <Plot
            data={createColorCodedHistogramTraces(
              overcommitHist,
              20,
              getOvercommitColor,
            )}
            layout={{
              ...layoutBase,
              title: plotChartTitle("Overcommit (Committed_AS / CommitLimit)"),
              xaxis: plotAxis("Ratio"),
              yaxis: plotAxis("# CPEs"),
              barmode: "stack" as const,
              shapes: [
                {
                  type: "line",
                  x0: 0.8,
                  x1: 0.8,
                  y0: 0,
                  y1: 1,
                  xref: "x",
                  yref: "paper",
                  line: { color: "#d93025", width: 2, dash: "dash" },
                },
              ],
            }}
            useResizeHandler
            style={{ width: "100%" }}
            config={{ displayModeBar: false }}
          />
        </div>
      </div>

      {/* Slab vs total user RSS trend */}
      {slabUserScatter.x.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-2.5">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
            Slab growth vs total process RSS growth (OLS KB/step)
          </h3>
          <Plot
            data={[
              {
                x: slabUserScatter.x,
                y: slabUserScatter.y,
                text: slabUserScatter.text,
                type: "scatter",
                mode: "markers",
                marker: { size: 8, color: "#1a73e8" },
                hovertemplate: "%{text}<br>Slab: %{x:.2f}<br>RSS Σ: %{y:.2f}<extra></extra>",
              },
            ]}
            layout={{
              ...layoutBase,
              height: 360,
              title: plotChartTitle("Kernel slab vs userspace RSS trend"),
              xaxis: plotAxis("Slab OLS slope (KB per snapshot step)"),
              yaxis: plotAxis("Total process RSS OLS slope (KB/step)"),
            }}
            useResizeHandler
            style={{ width: "100%" }}
            config={{ displayModeBar: false }}
          />
        </div>
      )}

      {/* Fleet process leaks */}
      {fleetLeaks.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-2.5">
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Top leaking processes (fleet)
            </h3>
            {fleetMeta && (
              <p className="text-[10px] text-muted-foreground">
                Positive RSS trend &gt; {fleetMeta.leak_slope_threshold_kb} KB/step · top {fleetMeta.top_process_limit}{" "}
                processes
              </p>
            )}
          </div>
          <div className="w-full max-w-full overflow-x-auto overflow-y-auto max-h-64 min-h-0">
            <table className="text-[11px] border-collapse min-w-[520px] w-full">
              <thead>
                <tr className="border-b border-border bg-muted/20">
                  <th className="text-left py-1 px-2 font-semibold text-muted-foreground">Process</th>
                  <th className="text-right py-1 px-2 font-semibold text-muted-foreground"># CPEs</th>
                  <th className="text-right py-1 px-2 font-semibold text-muted-foreground">Avg slope</th>
                  <th className="text-right py-1 px-2 font-semibold text-muted-foreground">Max slope</th>
                </tr>
              </thead>
              <tbody>
                {fleetLeaks.map((row) => (
                  <Fragment key={row.process}>
                    <tr
                      className="border-b border-border/60 cursor-pointer hover:bg-muted/40"
                      onClick={() =>
                        setLeakRowOpen((p) => (p === row.process ? null : row.process))
                      }
                      title="Click to show CPE serials"
                    >
                      <td className="py-1 px-2 font-mono text-foreground">
                        <span className="inline-flex items-center gap-1">
                          {leakRowOpen === row.process ? (
                            <ExpandLessIcon style={{ fontSize: 16 }} className="text-muted-foreground shrink-0" />
                          ) : (
                            <ExpandMoreIcon style={{ fontSize: 16 }} className="text-muted-foreground shrink-0" />
                          )}
                          {row.process}
                        </span>
                      </td>
                      <td className="py-1 px-2 text-right tabular-nums">{row.cpes_affected}</td>
                      <td className="py-1 px-2 text-right tabular-nums">{row.avg_slope_kb.toFixed(2)}</td>
                      <td className="py-1 px-2 text-right tabular-nums">{row.max_slope_kb.toFixed(2)}</td>
                    </tr>
                    {leakRowOpen === row.process && (
                      <tr className="border-b border-border/60 bg-muted/20">
                        <td colSpan={4} className="py-2 px-2 text-[10px] text-muted-foreground">
                          <span className="font-semibold text-foreground">CPE serials: </span>
                          {(row.cpe_serials?.length ?? 0) > 0
                            ? row.cpe_serials!.map((s) => (
                                <span
                                  key={s}
                                  className="inline-block mr-1.5 mb-0.5 font-mono rounded border border-border bg-card px-1.5 py-0.5 text-foreground"
                                >
                                  {s}
                                </span>
                              ))
                            : "—"}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Heatmap - REMOVED */}

      {/* CPE detail table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden min-w-0">
        <div className="w-full max-w-full overflow-x-auto overflow-y-auto max-h-[calc(100vh-300px)]">
          <table className="text-[11px] border-collapse table-fixed w-full min-w-[960px]">
            <colgroup>
              {FLEET_CPE_TABLE_COLS.map(({ key }) => (
                <col key={key} className="w-[10%]" />
              ))}
            </colgroup>
            <thead className="sticky top-0 z-10 border-b border-border bg-card">
              <tr className="bg-muted/20">
                {FLEET_CPE_TABLE_COLS.map(({ key, label, align }) => (
                  <th
                    key={key}
                    scope="col"
                    className={`px-2 py-1.5 font-semibold text-muted-foreground cursor-pointer hover:text-foreground select-none whitespace-nowrap align-middle ${
                      align === "right" ? "text-right" : "text-left"
                    }`}
                    onClick={() => {
                      setSortKey(key);
                      setSortDir(sortKey === key && sortDir === "asc" ? "desc" : "asc");
                    }}
                  >
                    <span className="inline-flex items-center gap-1">
                      {label}
                      {sortKey === key && <span>{sortDir === "asc" ? "↑" : "↓"}</span>}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedCpes.map((cpe) => (
                <tr
                  key={cpe.serial}
                  className={`border-b border-border hover:bg-muted/30 transition ${severityRowClass(cpe.status)}`}
                >
                  {FLEET_CPE_TABLE_COLS.map(({ key, align }) => (
                    <td key={key} className={fleetCpeCellClass(key, align)}>
                      {fleetCpeTableCell(cpe, key)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { selfhealApi, telemetryApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import SelfHealOverviewTab from "@/pages/SelfHealOverviewTab";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";
import Plot from "react-plotly.js";
import Autocomplete from "@mui/material/Autocomplete";
import TextField from "@mui/material/TextField";
import CircularProgress from "@mui/material/CircularProgress";
import MemoryIcon from "@mui/icons-material/Memory";
import StorageIcon from "@mui/icons-material/Storage";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import TimelineIcon from "@mui/icons-material/Timeline";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import ErrorIcon from "@mui/icons-material/Error";
import RefreshIcon from "@mui/icons-material/Refresh";
import CachedIcon from "@mui/icons-material/Cached";
import DownloadIcon from "@mui/icons-material/Download";
import SpeedIcon from "@mui/icons-material/Speed";
import ListAltIcon from "@mui/icons-material/ListAlt";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import CloseIcon from "@mui/icons-material/Close";
import Dialog from "@mui/material/Dialog";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";

/* ================================================================ Types */
interface KeyMetrics {
  snapshot_count: number;
  process_row_count?: number;
  cpu_sample_count?: number;
  peak_memory_usage_pct: number;
  min_memory_available_kb?: number;
  avg_memory_available_kb?: number;
  peak_cpu_usage_pct: number;
  avg_cpu_usage_pct: number;
  overall_time_range?: { first?: string; last?: string };
}

interface MemoryPressure {
  low_memory?: boolean;
  sunreclaim_pct?: number;
  overcommit_ratio?: number;
}

interface ProcessMemoryRow {
  pid: number;
  vsz_kb: number;
  rss_kb: number;
  shr_kb: number;
  dirty_kb: number;
  stack_kb: number;
  command: string;
}

interface LatestProcessTable {
  snapshot_timestamp: string;
  snapshot_wall_clock: string;
  rows: ProcessMemoryRow[];
}

interface ProcessSeriesRow {
  timestamp: string;
  wall_clock: string;
  pid: number;
  vsz_kb: number;
  rss_kb: number;
  shr_kb: number;
  dirty_kb: number;
  stack_kb: number;
  command: string;
}

type ProcessSeriesTableSortKey =
  | "pid"
  | "vsz_kb"
  | "rss_kb"
  | "shr_kb"
  | "dirty_kb"
  | "stack_kb";

type ActiveSection = "cpu" | "process" | "meminfo";

interface SelfHealData {
  device_info: {
    serial: string;
    telemetry2_enabled?: boolean;
    ipv6_support?: boolean;
  };
  charts: Array<{
    group: string;
    traces: Array<{
      label: string;
      unit: string;
      times: string[];
      values: number[];
    }>;
    display?: {
      smoothed?: boolean;
      source_samples?: number;
      chart_points?: number;
      bucket_seconds?: number;
    };
  }>;
  key_metrics: KeyMetrics;
  memory_pressure: MemoryPressure;
  top_processes: Array<{
    command: string;
    rss_trend_slope_kb: number;
    rss_ols_slope_kb?: number;
    rss_first_kb: number;
    rss_last_kb: number;
    rss_delta_kb: number;
    peak_rss_kb: number;
    avg_rss_kb: number;
    sample_count: number;
  }>;
  alerts: string[];
  status: string;
  cached?: boolean;
  narrative_summary?: {
    plain_text: string;
    generated_at_utc: string;
    schema_version: number;
  };
  latest_process_table?: LatestProcessTable;
  process_series_by_app?: Record<string, ProcessSeriesRow[]>;
}

/* ================================================================ Helpers */
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

/** First→last RSS Δ: whole KB when |Δ| < 1 MiB (1024 KB), else MiB (2dp). */
function fmtRssDeltaFirstLast(deltaKb: number): string {
  if (Math.abs(deltaKb) < 1024) {
    return `${Math.round(deltaKb).toLocaleString()} KB`;
  }
  const mib = deltaKb / 1024;
  return `${mib.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} MiB`;
}

/**
 * Slope in KiB per snapshot → B/snapshot if |slope| < 1 KiB/snapshot, else KiB/snapshot (2dp).
 */
function fmtSlopePerSnapshotKb(kbPerSnapshot: number): string {
  if (Math.abs(kbPerSnapshot) < 1) {
    const b = Math.round(kbPerSnapshot * 1024);
    return `${b.toLocaleString()} bytes/snapshot`;
  }
  return `${kbPerSnapshot.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} KB/snapshot`;
}

const PLOT_XAXIS_TICKFORMAT = "%Y-%m-%d %H:%M";

/** Tailwind `lg` — side-by-side process panels */
const LG_BREAKPOINT_PX = 1024;

/** Reference: /proc/meminfo-style fields (for Meminfo tab Info modal). */
const MEMINFO_REFERENCE_ROWS: ReadonlyArray<{
  parameter: string;
  meaning: string;
  corners: string;
}> = [
  { parameter: "MemTotal", meaning: "Total physical RAM", corners: "Fixed hardware limit" },
  {
    parameter: "MemFree",
    meaning: "Completely unused RAM",
    corners: "Low value is normal due to caching",
  },
  {
    parameter: "MemAvailable",
    meaning: "Usable memory (best health indicator)",
    corners: "Depends on reclaimable cache/slab accuracy",
  },
  {
    parameter: "Active",
    meaning: "Recently used memory",
    corners: "Includes hot file cache + active processes",
  },
  {
    parameter: "Inactive",
    meaning: "Reclaimable memory",
    corners: "Can spike during burst workloads",
  },
  {
    parameter: "Cached",
    meaning: "File/page cache",
    corners:
      "Includes mmap'ed files, tmpfs, and **deleted-but-open files**",
  },
  {
    parameter: "Buffers",
    meaning: "Block I/O buffers",
    corners: "Can grow during heavy disk/network I/O",
  },
  {
    parameter: "Slab",
    meaning: "Kernel allocations",
    corners: "Includes caches like inode, dentry, networking",
  },
  {
    parameter: "SReclaimable",
    meaning: "Reclaimable slab",
    corners: "Can be freed under pressure",
  },
  {
    parameter: "SUnreclaim",
    meaning: "Non-reclaimable slab",
    corners: "**Kernel memory leaks**, driver issues, network stack growth",
  },
  {
    parameter: "AnonPages",
    meaning: "Process private memory (heap/stack)",
    corners: "Memory leaks in apps, long-running processes",
  },
  {
    parameter: "Mapped",
    meaning: "Memory-mapped files",
    corners: "Shared libraries, mmap-heavy apps",
  },
  {
    parameter: "Shmem",
    meaning: "Shared memory usage",
    corners:
      "**tmpfs (/dev/shm), IPC, containers, browsers, DBs, deleted open files**",
  },
  {
    parameter: "PageTables",
    meaning: "Virtual memory mappings",
    corners: "Grows with many processes/threads",
  },
  {
    parameter: "KernelStack",
    meaning: "Kernel stack per thread",
    corners: "High thread count increases usage",
  },
  {
    parameter: "CommitLimit",
    meaning: "Safe allocation limit",
    corners: "Lower because **no swap configured**",
  },
  {
    parameter: "Committed_AS",
    meaning: "Total allocated (incl. overcommit)",
    corners: "**Overcommit risk → OOM if actually used**",
  },
  {
    parameter: "SwapTotal",
    meaning: "Swap space",
    corners: "No fallback memory → higher crash risk",
  },
  { parameter: "SwapFree", meaning: "Free swap", corners: "Not applicable" },
  {
    parameter: "Dirty",
    meaning: "Data waiting to be written to disk",
    corners: "Can spike during heavy writes",
  },
  {
    parameter: "Writeback",
    meaning: "Data actively being written",
    corners: "High values → I/O bottleneck",
  },
  {
    parameter: "Slab (network)",
    meaning: "Kernel network buffers",
    corners: "**Connection tracking, DoS attacks, packet buffers**",
  },
  {
    parameter: "Cached (network)",
    meaning: "Network-related cache",
    corners: "DNS cache, socket buffers",
  },
];

/** Renders strings with **bold** segments as <strong>. */
function meminfoCornerCell(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-foreground">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

/* ================================================================ Component */
export default function SelfHealPage() {
  const { projectId } = useProject();
  const { cpeId } = useCPE();
  const queryClient = useQueryClient();
  const mergePlot = usePlotlyLayoutMerge();
  const [activeTab, setActiveTab] = useState<"cpe" | "overview">("cpe");
  const [activeSection, setActiveSection] = useState<ActiveSection>("cpu");
  const [reparsing, setReparsing] = useState(false);
  const [selectedProcessApp, setSelectedProcessApp] = useState<string>("");
  const [exporting, setExporting] = useState(false);
  const [execSummaryOpen, setExecSummaryOpen] = useState(false);
  const [meminfoInfoOpen, setMeminfoInfoOpen] = useState(false);
  const processLeftCardRef = useRef<HTMLDivElement>(null);
  const [processRightHeightPx, setProcessRightHeightPx] = useState<number | undefined>(
    undefined,
  );

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["selfheal-parse", projectId, cpeId],
    queryFn: async () => {
      if (!projectId || !cpeId) throw new Error("Missing projectId or cpeId");
      const res = await selfhealApi.parse(projectId, cpeId, false);
      return res.data as SelfHealData;
    },
    enabled: !!projectId && !!cpeId,
    staleTime: 10 * 60 * 1000,
  });

  const selfhealData = data;

  // Fetch reboots from telemetry API
  const { data: telemetryData } = useQuery({
    queryKey: ["telemetry-reboots", projectId, cpeId],
    queryFn: async () => {
      if (!projectId || !cpeId) return null;
      try {
        const res = await telemetryApi.parse(projectId, cpeId, false);
        const rebootTimeline = res.data?.reboot_timeline ?? {};
        // Extract reboot events from all_events (the combined list of reboots from all sources)
        const allReboots = rebootTimeline.all_events ?? [];
        return allReboots;
      } catch (err) {
        return [];
      }
    },
    enabled: !!projectId && !!cpeId,
    staleTime: 30 * 60 * 1000,
  });

  // Convert reboot data for use in charts (already has timestamps and metadata)
  const rebootTimestamps = useMemo(() => {
    if (!telemetryData || telemetryData.length === 0) return [];
    // Return the full reboot event objects which contain timestamp, type, source, label, etc.
    return telemetryData;
  }, [telemetryData]);

  const processAppKeys = useMemo(() => {
    const map = selfhealData?.process_series_by_app;
    if (!map) return [] as string[];
    return Object.keys(map).sort((a, b) => a.localeCompare(b));
  }, [selfhealData?.process_series_by_app]);

  useEffect(() => {
    if (!processAppKeys.length) {
      setSelectedProcessApp("");
      return;
    }
    setSelectedProcessApp((prev) =>
      prev && processAppKeys.includes(prev) ? prev : processAppKeys[0],
    );
  }, [processAppKeys]);

  useLayoutEffect(() => {
    if (activeSection !== "process") {
      setProcessRightHeightPx(undefined);
      return;
    }
    const el = processLeftCardRef.current;
    if (!el) {
      setProcessRightHeightPx(undefined);
      return;
    }

    const mq = window.matchMedia(`(min-width: ${LG_BREAKPOINT_PX}px)`);

    const syncHeight = () => {
      if (!mq.matches) {
        setProcessRightHeightPx(undefined);
        return;
      }
      setProcessRightHeightPx(Math.round(el.getBoundingClientRect().height));
    };

    const ro = new ResizeObserver(syncHeight);
    ro.observe(el);
    mq.addEventListener("change", syncHeight);
    window.addEventListener("resize", syncHeight);
    syncHeight();

    return () => {
      ro.disconnect();
      mq.removeEventListener("change", syncHeight);
      window.removeEventListener("resize", syncHeight);
    };
  }, [
    activeSection,
    selfhealData?.top_processes,
    selfhealData?.process_series_by_app,
    cpeId,
  ]);

  const resolvedProcessApp =
    selectedProcessApp && processAppKeys.includes(selectedProcessApp)
      ? selectedProcessApp
      : processAppKeys[0] ?? "";

  const processSeriesRowsRaw =
    selfhealData?.process_series_by_app?.[resolvedProcessApp] ?? [];

  const sortedProcessSeriesRows = useMemo(() => {
    const rows = [...processSeriesRowsRaw];
    // Always sort chronologically (by timestamp, then wall_clock) to show RSS trend over time
    rows.sort((a, b) => {
      const t = a.timestamp.localeCompare(b.timestamp);
      if (t !== 0) return t;
      return a.wall_clock.localeCompare(b.wall_clock);
    });
    return rows;
  }, [processSeriesRowsRaw]);

  const snapshotPidChangedChronological = useMemo(() => {
    const rows = [...processSeriesRowsRaw];
    rows.sort((a, b) => {
      const t = a.timestamp.localeCompare(b.timestamp);
      if (t !== 0) return t;
      return a.wall_clock.localeCompare(b.wall_clock);
    });
    const map = new Map<string, boolean>();
    for (let i = 0; i < rows.length; i++) {
      const key = `${rows[i].timestamp}\0${rows[i].wall_clock}`;
      map.set(key, i > 0 && rows[i].pid !== rows[i - 1].pid);
    }
    return map;
  }, [processSeriesRowsRaw]);

  const handleReparse = async () => {
    if (!projectId || !cpeId || reparsing) return;
    setReparsing(true);
    try {
      const res = await selfhealApi.parse(projectId, cpeId, true);
      queryClient.setQueryData(["selfheal-parse", projectId, cpeId], res.data as SelfHealData);
    } catch {
      /* ignore */
    } finally {
      setReparsing(false);
    }
  };

  const handleExportXlsx = async () => {
    if (!projectId || !cpeId || exporting) return;
    setExporting(true);
    try {
      const response = await selfhealApi.exportXlsx(projectId, cpeId);
      const contentDisposition = response.headers["content-disposition"] as string | undefined;
      let filename = `selfheal-${cpeId}.xlsx`;
      if (contentDisposition) {
        const match = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
        if (match?.[1]) filename = match[1].replace(/['"]/g, "").trim();
      }
      const blob =
        response.data instanceof Blob
          ? response.data
          : new Blob([response.data as BlobPart], {
              type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error("SelfHeal export failed:", err);
    } finally {
      setExporting(false);
    }
  };

  if (!projectId || !cpeId) {
    return (
      <div className="p-4 max-w-full overflow-y-auto">
        <div className="bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
          <p className="text-blue-800 dark:text-blue-200">
            Please select a CPE from the dropdown in the sidebar to view SelfHeal data
          </p>
        </div>
      </div>
    );
  }

  const km = selfhealData?.key_metrics;
  const summaryParts: string[] = [];
  if (km?.snapshot_count != null) {
    summaryParts.push(`${km.snapshot_count} meminfo snapshots`);
    summaryParts.push(`${km.snapshot_count} process snapshots`);
  }
  if (km?.process_row_count != null) {
    summaryParts.push(`${km.process_row_count} process rows total`);
  }
  if (km?.cpu_sample_count != null) summaryParts.push(`${km.cpu_sample_count} CPU samples`);
  const range = km?.overall_time_range;
  const rangeSuffix =
    range?.first && range?.last
      ? ` | ${range.first.slice(0, 19)} — ${range.last.slice(0, 19)}`
      : "";

  const memoryChart = selfhealData?.charts.find((c) => c.group.includes("System Memory"));
  const cpuChart = selfhealData?.charts.find((c) => c.group.includes("CPU"));
  const pressureChart = selfhealData?.charts.find((c) => c.group.includes("Memory Pressure"));
  const hasMeminfoPressureSection =
    selfhealData != null &&
    (selfhealData.memory_pressure.sunreclaim_pct !== undefined ||
      selfhealData.memory_pressure.overcommit_ratio !== undefined);
  const hasMemoryChartData = !!(memoryChart && memoryChart.traces.length > 0);

  const meminfoReferenceButton = (
    <button
      type="button"
      onClick={() => setMeminfoInfoOpen(true)}
      className="shrink-0 inline-flex items-center gap-1 rounded-lg border-2 border-primary bg-primary/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary shadow-md shadow-primary/15 ring-2 ring-primary/25 hover:bg-primary/25 hover:ring-primary/45 transition-colors dark:bg-primary/20 dark:shadow-primary/25 dark:hover:bg-primary/30"
      title="Open /proc/meminfo parameter reference"
    >
      <InfoOutlinedIcon style={{ fontSize: 17 }} />
      Info
    </button>
  );

  return (
    <div className="p-4 space-y-4 max-w-full overflow-y-auto">
      <div className="flex items-center gap-2 flex-wrap">
        <TimelineIcon style={{ fontSize: 24, color: "#1a73e8" }} />
        <h2 className="text-lg font-semibold">SelfHeal</h2>
        {activeTab === "cpe" && selfhealData?.cached && (
          <span className="inline-flex items-center gap-1 rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-600 dark:border-blue-700 dark:bg-blue-900/20 dark:text-blue-400">
            <CachedIcon style={{ fontSize: 12 }} /> cached
          </span>
        )}
        {activeTab === "cpe" && summaryParts.length > 0 && (
          <span className="text-[11px] text-muted-foreground">
            {summaryParts.join(" · ")}
            {rangeSuffix}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {activeTab === "cpe" && selfhealData && (
            <button
              type="button"
              onClick={handleExportXlsx}
              disabled={exporting}
              className="inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs transition-colors hover:bg-muted disabled:opacity-50"
              title="Export meminfo and process tables to Excel"
            >
              {exporting ? <CircularProgress size={14} /> : <DownloadIcon style={{ fontSize: 15 }} />}
              Export Excel
            </button>
          )}
          {activeTab === "cpe" && (
            <button
              type="button"
              onClick={handleReparse}
              disabled={reparsing || isLoading}
              className="inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs transition-colors hover:bg-muted disabled:opacity-50"
              title="Re-parse from raw SelfHeal.txt"
            >
              {reparsing ? <CircularProgress size={14} /> : <RefreshIcon style={{ fontSize: 15 }} />}
              Re-parse
            </button>
          )}
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-0 border-b border-border">
        <button
          onClick={() => setActiveTab("cpe")}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "cpe"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
          }`}
        >
          <TimelineIcon style={{ fontSize: 16 }} />
          CPE Analysis
        </button>
        <button
          onClick={() => setActiveTab("overview")}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "overview"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
          }`}
        >
          <CompareArrowsIcon style={{ fontSize: 16 }} />
          Cross-CPE Overview
        </button>
      </div>

      {/* Cross-CPE Overview Tab */}
      {activeTab === "overview" && <SelfHealOverviewTab />}

      {/* CPE Analysis Tab */}
      {activeTab === "cpe" && isLoading && (
        <div className="flex items-center justify-center gap-3 py-16 text-muted-foreground">
          <CircularProgress size={24} />
          <span className="text-sm">Parsing SelfHeal data...</span>
        </div>
      )}
      {activeTab === "cpe" && isError && (
        <div className="flex items-center gap-2 rounded-xl bg-destructive/10 p-4 text-sm text-destructive">
          <ErrorIcon style={{ fontSize: 18 }} />
          {(error as { response?: { data?: { error?: string } } })?.response?.data?.error ||
            String(error)}
        </div>
      )}
      {activeTab === "cpe" && !isLoading && !isError && !selfhealData && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-6 dark:border-yellow-800 dark:bg-yellow-900/10">
          <p className="text-yellow-800 dark:text-yellow-200">No SelfHeal data available</p>
        </div>
      )}
      {activeTab === "cpe" && selfhealData && (
        <>
          {selfhealData.narrative_summary?.plain_text && (
            <div className="rounded-lg border border-border bg-card p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setExecSummaryOpen((o) => !o)}
                  className="flex items-center gap-1 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
                >
                  {execSummaryOpen ? (
                    <ExpandLessIcon style={{ fontSize: 18 }} />
                  ) : (
                    <ExpandMoreIcon style={{ fontSize: 18 }} />
                  )}
                  Executive summary
                </button>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] hover:bg-muted"
                    onClick={() => {
                      void navigator.clipboard.writeText(selfhealData.narrative_summary!.plain_text);
                    }}
                  >
                    <ContentCopyIcon style={{ fontSize: 14 }} />
                    Copy
                  </button>
                </div>
              </div>
              {execSummaryOpen && (
                <>
                  <pre className="text-[11px] whitespace-pre-wrap font-sans text-foreground leading-relaxed max-h-80 overflow-y-auto mt-2">
                    {selfhealData.narrative_summary.plain_text}
                  </pre>
                  {selfhealData.narrative_summary.generated_at_utc && (
                    <p className="text-[10px] text-muted-foreground mt-2">
                      Generated {selfhealData.narrative_summary.generated_at_utc} UTC
                    </p>
                  )}
                </>
              )}
            </div>
          )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
          <div className="rounded-lg border border-border p-2.5 bg-card">
            <div className="flex items-center gap-2">
              <div className="rounded-md p-1 shrink-0 bg-primary/10">
                <StorageIcon style={{ fontSize: 16, color: "#1a73e8" }} />
              </div>
              <span className="text-xs font-semibold flex-1 text-foreground">Peak memory</span>
            </div>
            <p className="text-[11px] mt-1 pl-7 font-semibold tabular-nums text-foreground">
              {selfhealData.key_metrics.peak_memory_usage_pct.toFixed(1)}%
            </p>
          </div>
          <div className="rounded-lg border border-border p-2.5 bg-card">
            <div className="flex items-center gap-2">
              <div className="rounded-md p-1 shrink-0 bg-primary/10">
                <TrendingDownIcon style={{ fontSize: 16, color: "#e8710a" }} />
              </div>
              <span className="text-xs font-semibold flex-1 text-foreground">Min available</span>
            </div>
            <p className="text-[11px] mt-1 pl-7 font-medium tabular-nums text-muted-foreground">
              {fmtMemory(selfhealData.key_metrics.min_memory_available_kb)}
            </p>
          </div>
          <div className="rounded-lg border border-border p-2.5 bg-card">
            <div className="flex items-center gap-2">
              <div className="rounded-md p-1 shrink-0 bg-primary/10">
                <TrendingUpIcon style={{ fontSize: 16, color: "#188038" }} />
              </div>
              <span className="text-xs font-semibold flex-1 text-foreground">Avg available</span>
            </div>
            <p className="text-[11px] mt-1 pl-7 font-medium tabular-nums text-muted-foreground">
              {fmtMemory(selfhealData.key_metrics.avg_memory_available_kb)}
            </p>
          </div>
          <div className="rounded-lg border border-border p-2.5 bg-card">
            <div className="flex items-center gap-2">
              <div className="rounded-md p-1 shrink-0 bg-primary/10">
                <MemoryIcon style={{ fontSize: 16, color: "#7b1fa2" }} />
              </div>
              <span className="text-xs font-semibold flex-1 text-foreground">Peak CPU</span>
            </div>
            <p className="text-[11px] mt-1 pl-7 font-semibold tabular-nums text-foreground">
              {selfhealData.key_metrics.peak_cpu_usage_pct}%
            </p>
          </div>
      </div>

      {/* Insight sections */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {(
          [
            { id: "cpu" as const, title: "CPU usage", Icon: SpeedIcon },
            { id: "process" as const, title: "Process info", Icon: ListAltIcon },
            { id: "meminfo" as const, title: "Meminfo", Icon: StorageIcon },
          ] as const
        ).map(({ id, title, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveSection(id)}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-left text-sm font-medium transition-colors ${
              activeSection === id
                ? "border-primary bg-primary/5 ring-2 ring-primary/30"
                : "border-border bg-card hover:bg-muted/40"
            }`}
          >
            <Icon
              style={{ fontSize: 18 }}
              className={activeSection === id ? "text-primary" : "text-muted-foreground"}
            />
            <span className="text-foreground">{title}</span>
          </button>
        ))}
      </div>

      <div className="bg-card border border-border rounded-xl p-3 min-h-[120px]">
        {activeSection === "cpu" && cpuChart && cpuChart.traces.length > 0 && (
          <div className="space-y-3">
            <p className="text-[11px] text-muted-foreground">
              Peak {(km?.peak_cpu_usage_pct ?? 0).toFixed(1)}% · Avg{" "}
              {(km?.avg_cpu_usage_pct ?? 0).toFixed(1)}% across {km?.cpu_sample_count ?? 0} samples
              {cpuChart.display?.smoothed &&
                cpuChart.display.chart_points != null &&
                cpuChart.display.bucket_seconds != null && (
                  <>
                    {" "}
                    · Graph: {cpuChart.display.chart_points} points (
                    {cpuChart.display.bucket_seconds >= 3600
                      ? `${(cpuChart.display.bucket_seconds / 3600).toFixed(1)} h`
                      : `${Math.round(cpuChart.display.bucket_seconds / 60)} min`}{" "}
                    time average)
                  </>
                )}
            </p>
            <Plot
              data={cpuChart.traces.map((trace) => ({
                x: trace.times,
                y: trace.values,
                mode: "lines",
                name: trace.label,
                line: { width: 2 },
              }))}
              layout={mergePlot({
                title: { text: cpuChart.group },
                hovermode: "x unified",
                xaxis: { title: { text: "Time" }, tickformat: PLOT_XAXIS_TICKFORMAT },
                yaxis: {
                  title: { text: cpuChart.traces[0]?.unit || "%" },
                  rangemode: "tozero",
                },
                margin: { t: 40, r: 20, b: 60, l: 60 },
                height: 400,
                shapes: rebootTimestamps.map((e: any) => ({
                  type: "line",
                  x0: e.time,
                  x1: e.time,
                  y0: 0,
                  y1: 1,
                  yref: "paper",
                  line: { color: "#d93025", width: 2, dash: "dot" },
                })),
                annotations: rebootTimestamps.map((e: any) => {
                  const sourceLabel = e.label || (e.source === "boottime" ? "B" : "TR");
                  const typeLabel = e.reboot_type === "soft" ? "S" : e.reboot_type === "hard" ? "H" : "";
                  const fullLabel = typeLabel ? `${sourceLabel}-${typeLabel}` : sourceLabel;
                  let fontColor = "#1a73e8";
                  if (e.reboot_type === "soft") fontColor = "#3b82f6";
                  else if (e.reboot_type === "hard") fontColor = "#d93025";
                  return {
                    x: e.time,
                    y: 1,
                    yref: "paper",
                    text: fullLabel,
                    showarrow: false,
                    font: { size: 9, color: fontColor, family: "monospace" },
                    yanchor: "bottom",
                  };
                }),
              })}
              useResizeHandler
              style={{ width: "100%" }}
            />
          </div>
        )}

        {activeSection === "cpu" && (!cpuChart || cpuChart.traces.length === 0) && (
          <p className="text-[11px] text-muted-foreground">No CPU sample data for this log.</p>
        )}

        {activeSection === "process" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
            <div
              ref={processLeftCardRef}
              className="min-w-0 bg-card border border-border rounded-xl p-3"
            >
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                Top processes by increasing RSS trend
              </h3>
              {selfhealData.top_processes.length > 0 ? (
                <>
                  <p className="text-[10px] text-muted-foreground mb-2">
                    Per snapshot sum RSS (KiB) for every PID of the same app name (0 if absent).<br />
                    <strong>Rank trend</strong> sorts bars (OLS slope when positive, else
                    mean first→last step). <strong>OLS</strong> is the best-fit line of that ΣRSS
                    series vs index.
                  </p>
                  {(() => {
                    const tr = selfhealData.key_metrics?.overall_time_range;
                    const isoFirst = tr?.first?.trim() || "—";
                    const isoLast = tr?.last?.trim() || "—";
                    const procs = [...selfhealData.top_processes].sort(
                      (a, b) => a.rss_trend_slope_kb - b.rss_trend_slope_kb,
                    );
                    const yLabels = procs.map((p) => p.command);
                    const xSlope = procs.map((p) => p.rss_trend_slope_kb);
                    const customdata = procs.map((p) => {
                      const ols = p.rss_ols_slope_kb ?? p.rss_trend_slope_kb;
                      return [
                        p.rss_first_kb / 1024,
                        p.rss_last_kb / 1024,
                        p.peak_rss_kb / 1024,
                        p.avg_rss_kb / 1024,
                        fmtRssDeltaFirstLast(p.rss_delta_kb),
                        fmtSlopePerSnapshotKb(p.rss_trend_slope_kb),
                        fmtSlopePerSnapshotKb(ols),
                        Math.round(p.rss_first_kb),
                        Math.round(p.rss_last_kb),
                        isoFirst,
                        isoLast,
                      ];
                    });
                    const maxLabelLen = Math.max(...yLabels.map((s) => s.length), 1);
                    const barHeight = Math.min(720, Math.max(240, procs.length * 26));
                    return (
                      <>
                        <p className="text-[10px] text-muted-foreground mb-2 font-mono break-all">
                          ΣRSS window: {isoFirst} → {isoLast}
                        </p>
                        <Plot
                        data={[
                          {
                            type: "bar",
                            orientation: "h",
                            x: xSlope,
                            y: yLabels,
                            customdata,
                            hovertemplate:
                              "<b>%{y}</b><br>ΣRSS window: %{customdata[9]} → %{customdata[10]}<br>Rank trend: %{customdata[5]}<br>OLS slope: %{customdata[6]}<br>First snapshot ΣRSS: %{customdata[0]:,.2f} MiB (%{customdata[7]:,} KiB)<br>Last snapshot ΣRSS: %{customdata[1]:,.2f} MiB (%{customdata[8]:,} KiB)<br>Δ first→last: %{customdata[4]}<br>Peak ΣRSS: %{customdata[2]:,.2f} MiB<br>Avg ΣRSS/snap: %{customdata[3]:,.2f} MiB<extra></extra>",
                            marker: { color: "#2563eb" },
                          },
                        ]}
                        layout={mergePlot({
                          margin: {
                            l: Math.min(220, 8 + maxLabelLen * 6),
                            r: 16,
                            t: 4,
                            b: 40,
                          },
                          xaxis: {
                            title: { text: "RSS trend (KB / snapshot)" },
                            tickformat: ",.2f",
                            separatethousands: true,
                          },
                          yaxis: { automargin: true, title: { text: "" } },
                          height: barHeight,
                          showlegend: false,
                        })}
                        useResizeHandler
                        style={{ width: "100%" }}
                      />
                      </>
                    );
                  })()}
                </>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  {(selfhealData.key_metrics?.snapshot_count ?? 0) < 2
                    ? "At least two memory snapshots are required to compute an RSS trend."
                    : "No applications with net RSS growth or a positive fit across snapshots (memory stable or shrinking per app)."}
                </p>
              )}
            </div>

            <div className="min-w-0 w-full flex justify-center lg:justify-stretch lg:min-h-0">
              {processAppKeys.length > 0 ? (
                <div
                  className="bg-card border border-border rounded-xl overflow-hidden w-full max-w-full flex flex-col min-h-0"
                  style={
                    processRightHeightPx != null
                      ? {
                          height: processRightHeightPx,
                          minHeight: processRightHeightPx,
                        }
                      : undefined
                  }
                >
                  <div className="shrink-0 px-3 py-2 border-b border-border bg-muted/30 space-y-2">
                    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Per-application snapshots
                    </h3>
                    <Autocomplete
                      disableClearable
                      options={processAppKeys}
                      value={resolvedProcessApp}
                      onChange={(_, value) => setSelectedProcessApp(value)}
                      renderInput={(params) => (
                        <TextField
                          {...params}
                          label="Search / select application"
                          placeholder="Type to filter…"
                          size="small"
                          sx={{
                            "& .MuiInputBase-root": { fontSize: "11px" },
                            width: "100%",
                            maxWidth: "100%",
                          }}
                        />
                      )}
                    />
                    <p className="text-[10px] text-muted-foreground leading-snug">
                      PID highlighted when it changed from the prior snapshot in time. Full history: Export Excel.
                    </p>
                  </div>
                  <div className="flex-1 min-h-0 overflow-auto">
                    <table className="text-[11px] border-collapse">
                      <colgroup>
                        <col style={{ width: "160px" }} />
                        <col style={{ width: "72px" }} />
                        <col style={{ width: "88px" }} />
                        <col style={{ width: "88px" }} />
                        <col style={{ width: "88px" }} />
                        <col style={{ width: "88px" }} />
                        <col style={{ width: "88px" }} />
                      </colgroup>
                      <thead className="sticky top-0 z-10 bg-card">
                        <tr className="border-b border-border bg-muted/20">
                          <th className="px-2 py-1 font-semibold text-muted-foreground whitespace-nowrap text-left">
                            Timestamp
                          </th>
                          {(
                            [
                              ["pid", "PID", "left"] as const,
                              ["vsz_kb", "VSZ (KB)", "right"] as const,
                              ["rss_kb", "RSS (KB)", "right"] as const,
                              ["shr_kb", "SHR (KB)", "right"] as const,
                              ["dirty_kb", "Dirty (KB)", "right"] as const,
                              ["stack_kb", "Stack (KB)", "right"] as const,
                            ] satisfies ReadonlyArray<
                              readonly [ProcessSeriesTableSortKey, string, "left" | "right"]
                            >
                          ).map(([col, label, align]) => (
                            <th
                              key={col}
                              className={`px-2 py-1 font-semibold text-muted-foreground whitespace-nowrap ${
                                align === "right" ? "text-right" : "text-left"
                              }`}
                            >
                              {label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sortedProcessSeriesRows.map((row, idx) => {
                          const sk = `${row.timestamp}\0${row.wall_clock}`;
                          const pidHighlight =
                            snapshotPidChangedChronological.get(sk) ?? false;
                          return (
                            <tr
                              key={`${row.pid}-${row.timestamp}-${idx}`}
                              className="border-b border-border hover:bg-muted/30"
                            >
                              <td className="px-2 py-1.5 font-mono text-muted-foreground whitespace-nowrap">
                                {row.timestamp.slice(0, 19)}
                              </td>
                              <td
                                className={`px-2 py-1.5 font-mono tabular-nums text-foreground ${
                                  pidHighlight
                                    ? "bg-amber-100 dark:bg-amber-900/35 font-semibold"
                                    : ""
                                }`}
                              >
                                {row.pid}
                              </td>
                              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                                {row.vsz_kb.toLocaleString()}
                              </td>
                              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                                {row.rss_kb.toLocaleString()}
                              </td>
                              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                                {row.shr_kb.toLocaleString()}
                              </td>
                              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                                {row.dirty_kb.toLocaleString()}
                              </td>
                              <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                                {row.stack_kb.toLocaleString()}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="w-full rounded-xl border border-dashed border-border p-6 text-center">
                  <p className="text-[11px] text-muted-foreground">No per-application process series.</p>
                </div>
              )}
            </div>
          </div>
        )}

        {activeSection === "meminfo" && (
          <div className="space-y-4">
            {(selfhealData.memory_pressure.sunreclaim_pct !== undefined ||
              selfhealData.memory_pressure.overcommit_ratio !== undefined) && (
              <div>
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-2">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground m-0 min-w-0">
                    Memory pressure indicators
                  </h3>
                  {meminfoReferenceButton}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {selfhealData.memory_pressure.sunreclaim_pct !== undefined && (
                    <div className="rounded-lg border border-border p-2.5">
                      <div className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-1">
                        SUnreclaim (% of Slab)
                      </div>
                      <div className="text-xl font-bold tabular-nums text-foreground">
                        {selfhealData.memory_pressure.sunreclaim_pct.toFixed(1)}%
                      </div>
                      {selfhealData.memory_pressure.sunreclaim_pct > 50 && (
                        <p className="text-[10px] text-red-600 dark:text-red-400 mt-1">
                          High - potential kernel leak
                        </p>
                      )}
                    </div>
                  )}
                  {selfhealData.memory_pressure.overcommit_ratio !== undefined && (
                    <div className="rounded-lg border border-border p-2.5">
                      <div className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground mb-1">
                        Overcommit ratio
                      </div>
                      <div className="text-xl font-bold tabular-nums text-foreground">
                        {selfhealData.memory_pressure.overcommit_ratio.toFixed(2)}x
                      </div>
                      {selfhealData.memory_pressure.overcommit_ratio > 0.8 && (
                        <p className="text-[10px] text-orange-600 dark:text-orange-400 mt-1">
                          Warning zone
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {memoryChart && memoryChart.traces.length > 0 && (
              <div>
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-2">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground m-0 min-w-0">
                    {memoryChart.group}
                  </h3>
                  {!hasMeminfoPressureSection ? meminfoReferenceButton : null}
                </div>
                <Plot
                  data={memoryChart.traces.map((trace) => ({
                    x: trace.times,
                    y: trace.values.map((v) => v / 1024),
                    mode: "lines",
                    name: trace.label,
                    line: { width: 2 },
                    hovertemplate:
                      "%{fullData.name}<br>%{x}<br>%{y:,.2f} MiB<extra></extra>",
                  }))}
                  layout={mergePlot({
                    hovermode: "x unified",
                    xaxis: { title: { text: "Time" }, tickformat: PLOT_XAXIS_TICKFORMAT },
                    yaxis: {
                      title: { text: "Memory (MiB)" },
                      tickformat: ",.0f",
                      separatethousands: true,
                    },
                    margin: { t: 24, r: 20, b: 60, l: 60 },
                    height: 500,
                    legend: { x: 0, y: 1 },
                    shapes: rebootTimestamps.map((e: any) => ({
                      type: "line",
                      x0: e.time,
                      x1: e.time,
                      y0: 0,
                      y1: 1,
                      yref: "paper",
                      line: { color: "#d93025", width: 2, dash: "dot" },
                    })),
                    annotations: rebootTimestamps.map((e: any) => {
                      const sourceLabel = e.label || (e.source === "boottime" ? "B" : "TR");
                      const typeLabel = e.reboot_type === "soft" ? "S" : e.reboot_type === "hard" ? "H" : "";
                      const fullLabel = typeLabel ? `${sourceLabel}-${typeLabel}` : sourceLabel;
                      let fontColor = "#1a73e8";
                      if (e.reboot_type === "soft") fontColor = "#3b82f6";
                      else if (e.reboot_type === "hard") fontColor = "#d93025";
                      return {
                        x: e.time,
                        y: 1,
                        yref: "paper",
                        text: fullLabel,
                        showarrow: false,
                        font: { size: 9, color: fontColor, family: "monospace" },
                        yanchor: "bottom",
                      };
                    }),
                  })}
                  useResizeHandler
                  style={{ width: "100%" }}
                />
              </div>
            )}

            {pressureChart && pressureChart.traces.length > 0 && (
              <div>
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-2">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground m-0 min-w-0">
                    {pressureChart.group}
                  </h3>
                  {!hasMeminfoPressureSection && !hasMemoryChartData ? meminfoReferenceButton : null}
                </div>
                <Plot
                  data={pressureChart.traces.map((trace) => {
                    const isPct = trace.unit === "%";
                    return {
                      x: trace.times,
                      y: isPct ? trace.values : trace.values.map((v) => v / 1024),
                      mode: "lines",
                      name: trace.label,
                      line: { width: 2 },
                      yaxis: isPct ? "y2" : "y",
                      hovertemplate: isPct
                        ? "%{fullData.name}<br>%{x}<br>%{y:.2f}%<extra></extra>"
                        : "%{fullData.name}<br>%{x}<br>%{y:,.2f} MiB<extra></extra>",
                    };
                  })}
                  layout={mergePlot({
                    hovermode: "x unified",
                    xaxis: { title: { text: "Time" }, tickformat: PLOT_XAXIS_TICKFORMAT },
                    yaxis: {
                      title: { text: "Committed memory (MiB)" },
                      tickformat: ",.0f",
                      separatethousands: true,
                    },
                    yaxis2: {
                      title: { text: "SUnreclaim % of slab" },
                      overlaying: "y",
                      side: "right",
                      tickformat: ".1f",
                      showgrid: false,
                    },
                    margin: { t: 24, r: 70, b: 60, l: 60 },
                    height: 400,
                    legend: { x: 0, y: 1 },
                    shapes: rebootTimestamps.map((e: any) => ({
                      type: "line",
                      x0: e.time,
                      x1: e.time,
                      y0: 0,
                      y1: 1,
                      yref: "paper",
                      line: { color: "#d93025", width: 2, dash: "dot" },
                    })),
                    annotations: rebootTimestamps.map((e: any) => {
                      const sourceLabel = e.label || (e.source === "boottime" ? "B" : "TR");
                      const typeLabel = e.reboot_type === "soft" ? "S" : e.reboot_type === "hard" ? "H" : "";
                      const fullLabel = typeLabel ? `${sourceLabel}-${typeLabel}` : sourceLabel;
                      let fontColor = "#1a73e8";
                      if (e.reboot_type === "soft") fontColor = "#3b82f6";
                      else if (e.reboot_type === "hard") fontColor = "#d93025";
                      return {
                        x: e.time,
                        y: 1,
                        yref: "paper",
                        text: fullLabel,
                        showarrow: false,
                        font: { size: 9, color: fontColor, family: "monospace" },
                        yanchor: "bottom",
                      };
                    }),
                  })}
                  useResizeHandler
                  style={{ width: "100%" }}
                />
              </div>
            )}

            {(!memoryChart || memoryChart.traces.length === 0) &&
              (!pressureChart || pressureChart.traces.length === 0) && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <p className="text-[11px] text-muted-foreground m-0">No meminfo chart data.</p>
                  {!hasMeminfoPressureSection ? meminfoReferenceButton : null}
                </div>
              )}
          </div>
        )}
      </div>
        </>
      )}

      <Dialog
        open={meminfoInfoOpen}
        onClose={() => setMeminfoInfoOpen(false)}
        maxWidth="lg"
        fullWidth
        scroll="paper"
        aria-labelledby="meminfo-reference-title"
      >
        <DialogTitle
          id="meminfo-reference-title"
          className="flex items-center justify-between gap-2 pr-2 border-b border-border"
        >
          <span className="text-base font-semibold">
            /proc/meminfo parameters — reference
          </span>
          <IconButton
            type="button"
            aria-label="Close"
            onClick={() => setMeminfoInfoOpen(false)}
            size="small"
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers className="p-0">
          <div className="overflow-x-auto max-h-[min(85vh,720px)]">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="sticky top-0 z-10 bg-muted/90 backdrop-blur-sm border-b border-border">
                <tr>
                  <th className="px-3 py-2.5 font-semibold text-foreground w-[140px]">
                    Parameter
                  </th>
                  <th className="px-3 py-2.5 font-semibold text-foreground min-w-[200px]">
                    What it means
                  </th>
                  <th className="px-3 py-2.5 font-semibold text-foreground">
                    Corner cases / hidden contributors
                  </th>
                </tr>
              </thead>
              <tbody>
                {MEMINFO_REFERENCE_ROWS.map((row) => (
                  <tr
                    key={row.parameter}
                    className="border-b border-border align-top hover:bg-muted/20"
                  >
                    <td className="px-3 py-2 font-mono font-medium text-foreground whitespace-nowrap">
                      {row.parameter}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">{row.meaning}</td>
                    <td className="px-3 py-2 text-muted-foreground leading-snug">
                      {meminfoCornerCell(row.corners)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="px-3 py-2 text-[10px] text-muted-foreground border-t border-border">
            Press Esc or click outside to close.
          </p>
        </DialogContent>
      </Dialog>
    </div>
  );
}

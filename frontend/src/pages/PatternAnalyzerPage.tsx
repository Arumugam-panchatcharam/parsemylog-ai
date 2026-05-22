import { useState, useEffect, useRef, useMemo, memo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  patternAnalyzerApi,
  patternGovernanceApi,
  natcoApi,
  projectsApi,
  filesApi,
} from "@/api/endpoints";
import type {
  UserPattern,
  DomainPatterns,
  DomainDiff,
  NatcoInfo,
  MaintenanceWindow,
  RegexScanProgressPayload,
  PatternValueCompare,
  ValueCompareOperator,
} from "@/api/endpoints";
import { runPatternAnalyzerScan } from "@/lib/patternAnalyzerScanRunner";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import { useTheme } from "@/hooks/useTheme";
import { mergePlotlyLayout } from "@/lib/plotlyTheme";
import { cn } from "@/lib/utils";
import { eventIdChartColor, SCATTER_MARKER_LINE } from "@/lib/chartColors";
import Plot from "react-plotly.js";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import SaveIcon from "@mui/icons-material/Save";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";

import UploadFileIcon from "@mui/icons-material/UploadFile";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import ErrorIcon from "@mui/icons-material/Error";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import CreateNewFolderIcon from "@mui/icons-material/CreateNewFolder";
import SyncIcon from "@mui/icons-material/Sync";
import PublishIcon from "@mui/icons-material/Publish";
import PublicIcon from "@mui/icons-material/Public";
import CheckBoxIcon from "@mui/icons-material/CheckBox";
import CircularProgress from "@mui/material/CircularProgress";
import LinearProgress from "@mui/material/LinearProgress";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import ScienceIcon from "@mui/icons-material/Science";
import ScheduleIcon from "@mui/icons-material/Schedule";
import CloseIcon from "@mui/icons-material/Close";
import FilterListIcon from "@mui/icons-material/FilterList";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import PatternOverviewTab from "@/pages/PatternOverviewTab";
import PatternLabTab from "@/components/analytics/PatternLabTab";

// Memoized Plot component to prevent unnecessary re-renders
const MemoizedPlot = memo(Plot);

/* ================================================================ Types */
interface PatternAnalyzerRebootRow {
  timestamp: string;
  reason: string;
  reboot_type?: string;
  is_short_reboot?: boolean;
  uptime_before_reboot_sec?: number;
}

interface ScanResult {
  traces: Array<{
    name: string;
    times: string[];
    texts: string[];
    total: number;
    bucketed?: boolean;
    bucket_minutes?: number;
    counts?: number[];
    scan_time_range?: { start: string; end: string };
    scan_filename?: string | null;
    value_compare?: {
      passed: boolean;
      operator: ValueCompareOperator;
      compare_to: number;
      capture_group: number;
      numeric_kind: "int" | "float";
      regex_line_matches: number;
      values_extracted_unique_lines: number;
      aggregate_summary: number | null;
    };
  }>;
  reboots: PatternAnalyzerRebootRow[];
  total_matches: number;
  /** Present on scans after server stamp; used to reject stale results after CPE switch. */
  cpe_serial?: string | null;
}

type RebootEntry = PatternAnalyzerRebootRow;

/* ================================================================ Constants */
const BUCKET_OPTIONS = [
  { value: 0, label: "Auto" },
  { value: 5, label: "5 min" },
  { value: 10, label: "10 min" },
  { value: 15, label: "15 min" },
  { value: 30, label: "30 min" },
  { value: 60, label: "1 hour" },
  { value: 120, label: "2 hours" },
  { value: 240, label: "4 hours" },
  { value: 360, label: "6 hours" },
  { value: 1440, label: "1 day" },
];

const NO_TOOLBAR = { displayModeBar: false } as const;

const VALUE_COMPARE_OPERATORS: ReadonlyArray<{ value: ValueCompareOperator; label: string }> = [
  { value: "gt", label: "> (gt)" },
  { value: "gte", label: "≥ (gte)" },
  { value: "lt", label: "< (lt)" },
  { value: "lte", label: "≤ (lte)" },
  { value: "eq", label: "= (eq)" },
  { value: "neq", label: "≠ (neq)" },
];

function defaultPatternValueCompare(): PatternValueCompare {
  return {
    enabled: true,
    operator: "gt",
    compare_to: 0,
    capture_group: 1,
    numeric_kind: "int",
  };
}

function coerceImportedValueCompare(raw: unknown): PatternValueCompare | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const o = raw as Record<string, unknown>;
  if (!o.enabled) return undefined;
  const op = String(o.operator || "gt").toLowerCase();
  const allowed = new Set<ValueCompareOperator>(["gt", "gte", "lt", "lte", "eq", "neq"]);
  const operator = (allowed.has(op as ValueCompareOperator) ? op : "gt") as ValueCompareOperator;
  const compare_to = typeof o.compare_to === "number" && Number.isFinite(o.compare_to)
    ? o.compare_to
    : Number(o.compare_to);
  if (!Number.isFinite(compare_to)) return undefined;
  let capture_group = Number(o.capture_group ?? 1);
  if (!Number.isFinite(capture_group) || capture_group < 1) capture_group = 1;
  const nk = String(o.numeric_kind || "int").toLowerCase() === "float" ? "float" : "int";
  return {
    enabled: true,
    operator,
    compare_to,
    capture_group: Math.floor(capture_group),
    numeric_kind: nk,
  };
}

/** Strip incomplete per-pattern scan scope before API calls (save/sync/submit). */
function sanitizeDomainsForApi(domains: DomainPatterns): DomainPatterns {
  const out: DomainPatterns = {};
  for (const [domain, list] of Object.entries(domains)) {
    out[domain] = list.map((p) => sanitizePatternForApi(p));
  }
  return out;
}

function sanitizePatternForApi(p: UserPattern): UserPattern {
  const q: UserPattern = { ...p };
  const tr = q.scan_time_range;
  if (!tr?.start?.trim() || !tr?.end?.trim()) {
    delete q.scan_time_range;
  } else {
    q.scan_time_range = { start: tr.start.trim(), end: tr.end.trim() };
  }
  if (!q.scan_filename?.trim()) delete q.scan_filename;
  else q.scan_filename = q.scan_filename.trim();
  const vc = q.value_compare;
  if (!vc?.enabled) {
    delete q.value_compare;
  } else {
    const nk = vc.numeric_kind === "float" ? "float" : "int";
    let cg = vc.capture_group != null ? Math.floor(Number(vc.capture_group)) : 1;
    if (!Number.isFinite(cg) || cg < 1) cg = 1;
    let ct = Number(vc.compare_to);
    if (!Number.isFinite(ct)) ct = 0;
    const allowed = new Set<ValueCompareOperator>(["gt", "gte", "lt", "lte", "eq", "neq"]);
    const op = allowed.has(vc.operator) ? vc.operator : "gt";
    q.value_compare = {
      enabled: true,
      operator: op,
      compare_to: ct,
      capture_group: cg,
      numeric_kind: nk,
    };
  }
  return q;
}

/** Compare log/chart timestamps for filtering (ISO-ish strings or browser-parseable dates). */
function cmpPatternAnalyzerTs(a: string, b: string): number {
  const ma = Date.parse(a);
  const mb = Date.parse(b);
  if (Number.isFinite(ma) && Number.isFinite(mb)) {
    return ma - mb;
  }
  return a.localeCompare(b);
}

/** Parse naive ISO ``YYYY-MM-DDTHH:mm[:ss]`` as UTC instant (matches scan_time_range semantics). */
function utcNaiveIsoToMs(s: string): number {
  const x = s.trim();
  if (!x) return NaN;
  if (/[zZ]$|[+-]\d\d:\d\d$/.test(x)) return Date.parse(x);
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/.exec(x);
  if (m) {
    const sec = m[6] != null ? parseInt(m[6], 10) : 0;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], sec);
  }
  return Date.parse(x);
}

/**
 * Intersect reboot-driven chart window with per-pattern scan_time_range from the scan (UTC ISO bounds).
 * Empty bounds mean “no constraint” from that side.
 */
function effectivePatternAnalyzerWindow(
  chart?: { start?: string; end?: string } | null,
  perTrace?: { start?: string; end?: string } | null,
): { lo?: string; hi?: string; disjoint: boolean } {
  const cLo = chart?.start?.trim() || "";
  const cHi = chart?.end?.trim() || "";
  const pLo = perTrace?.start?.trim() || "";
  const pHi = perTrace?.end?.trim() || "";
  let lo = "";
  let hi = "";
  if (cLo && pLo) {
    lo = cmpPatternAnalyzerTs(cLo, pLo) >= 0 ? cLo : pLo;
  } else {
    lo = cLo || pLo;
  }
  if (cHi && pHi) {
    hi = cmpPatternAnalyzerTs(cHi, pHi) <= 0 ? cHi : pHi;
  } else {
    hi = cHi || pHi;
  }
  const disjoint = Boolean(lo && hi) && cmpPatternAnalyzerTs(lo, hi) > 0;
  return {
    lo: lo || undefined,
    hi: hi || undefined,
    disjoint,
  };
}

function formatUptimeBeforeReboot(sec: number | string | undefined | null): string {
  if (sec == null || sec === "") return "—";
  const n = typeof sec === "string" ? Number(sec) : sec;
  if (!Number.isFinite(n) || n < 0) return "—";
  const s = Math.floor(n);
  if (s >= 86400) return `${(s / 86400).toFixed(1)}d`;
  if (s >= 3600) return `${(s / 3600).toFixed(1)}h`;
  return `${Math.round(s / 60)}m`;
}

/** Soft vs hard (and plot colors) for reboot markers — matches telemetry conventions. */
function patternRebootBoundaryAccent(r: PatternAnalyzerRebootRow): {
  typeLabel: string;
  reasonClass: string;
  ringClass: string;
  chipClass: string;
  plotColor: string;
} {
  const t = (r.reboot_type || "").toLowerCase();
  if (t === "soft") {
    return {
      typeLabel: "Soft",
      reasonClass: "text-sky-600 dark:text-sky-300",
      ringClass: "ring-sky-500/30 dark:ring-sky-400/35",
      chipClass:
        "border border-sky-500/45 bg-sky-500/12 text-sky-800 dark:text-sky-200 dark:bg-sky-500/15",
      plotColor: "#3b82f6",
    };
  }
  if (t === "hard") {
    return {
      typeLabel: "Hard",
      reasonClass: "text-red-600 dark:text-red-300",
      ringClass: "ring-red-500/25 dark:ring-red-400/30",
      chipClass:
        "border border-red-500/45 bg-red-500/12 text-red-800 dark:text-red-200 dark:bg-red-500/15",
      plotColor: "#d93025",
    };
  }
  return {
    typeLabel: "Unknown",
    reasonClass: "text-foreground",
    ringClass: "ring-muted-foreground/25",
    chipClass: "border border-border bg-muted text-muted-foreground",
    plotColor: "#64748b",
  };
}

/**
 * Calculate optimal bucket size based on pattern time distribution.
 * Returns bucket size in minutes.
 */
function calculateAutoBucket(scanResult: ScanResult | null): number {
  if (!scanResult || scanResult.traces.length === 0) return 60; // default 1 hour
  
  // Find min and max timestamps across all traces
  let minTime = Infinity;
  let maxTime = -Infinity;
  let totalPoints = 0;
  
  scanResult.traces.forEach((trace: any) => {
    if (trace.times && trace.times.length > 0) {
      totalPoints += trace.times.length;
      trace.times.forEach((ts: string) => {
        const ms = new Date(ts).getTime();
        if (ms < minTime) minTime = ms;
        if (ms > maxTime) maxTime = ms;
      });
    }
  });
  
  if (minTime === Infinity || maxTime === -Infinity) return 60;
  
  const durationMs = maxTime - minTime;
  return calculateBucketFromDuration(durationMs);
}

/**
 * Calculate optimal bucket size based on time duration in milliseconds.
 * Returns bucket size in minutes.
 */
function calculateBucketFromDuration(durationMs: number): number {
  const durationDays = durationMs / (1000 * 60 * 60 * 24);
  const durationHours = durationMs / (1000 * 60 * 60);
  
  // If distribution spans many days (>7 days), use 1 day bucket
  if (durationDays > 7) return 1440;
  
  // If distribution spans multiple days (2-7 days), use 6 hour bucket
  if (durationDays > 2) return 360;
  
  // If distribution spans 1-2 days, use 4 hour bucket
  if (durationDays > 1) return 240;
  
  // If distribution spans 12-24 hours, use 2 hour bucket
  if (durationHours > 12) return 120;
  
  // If distribution spans 6-12 hours, use 1 hour bucket
  if (durationHours > 6) return 60;
  
  // If distribution spans 3-6 hours, use 30 min bucket
  if (durationHours > 3) return 30;
  
  // If distribution spans 1-3 hours, use 15 min bucket
  if (durationHours > 1) return 15;
  
  // If distribution spans less than 1 hour, use 10 min bucket
  if (durationHours > 0.5) return 10;
  
  // For very short durations, use 5 min bucket
  return 5;
}

/** Convert a DRAIN3 template string to a regex by replacing <*> with .* */
function drain3ToRegex(template: string): string {
  const escaped = template.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return escaped.replace(/\\<\\\\?\*\\>/g, ".*").replace(/<\*>/g, ".*");
}

/* ================================================================ NATCO Badge / Selector */
function NatcoBadgeOrSelector({
  projectId,
  natco,
  onAssigned,
}: {
  projectId: string;
  natco: NatcoInfo | null;
  onAssigned: () => void;
}) {
  const [picking, setPicking] = useState(false);
  const [selectedId, setSelectedId] = useState<number | "">("");
  const [saving, setSaving] = useState(false);

  const { data: natcoList } = useQuery({
    queryKey: ["natcoList"],
    queryFn: async () => (await natcoApi.list()).data,
    enabled: picking || !natco, // fetch when selector shown or no natco yet
  });

  const handleAssign = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      await projectsApi.update(projectId, { natco_id: Number(selectedId) });
      setPicking(false);
      setSelectedId("");
      onAssigned();
    } catch {
      // keep selector open
    }
    setSaving(false);
  };

  // Already assigned — show badge with option to change
  if (natco && !picking) {
    return (
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-1.5 px-3 py-1 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-full text-xs font-medium text-blue-700 dark:text-blue-400">
          <PublicIcon style={{ fontSize: 14 }} />
          NATCO: {natco.code} - {natco.name}
        </span>
        <button
          onClick={() => setPicking(true)}
          className="text-[10px] text-muted-foreground hover:text-foreground underline"
        >
          change
        </button>
      </div>
    );
  }

  // Not assigned or changing — show selector
  return (
    <div className="flex items-center gap-2">
      <PublicIcon style={{ fontSize: 16, color: "#9ca3af" }} />
      <select
        value={selectedId}
        onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : "")}
        className="text-xs px-2 py-1.5 border border-border rounded-lg bg-background focus:outline-none focus:ring-1 focus:ring-ring"
      >
        <option value="">-- Select NATCO --</option>
        {natcoList?.map((n) => (
          <option key={n.id} value={n.id}>{n.code} - {n.name}</option>
        ))}
      </select>
      <button
        onClick={handleAssign}
        disabled={!selectedId || saving}
        className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
      >
        {saving ? <CircularProgress size={12} sx={{ color: "white" }} /> : <PublicIcon style={{ fontSize: 13 }} />}
        Assign
      </button>
      {natco && (
        <button
          onClick={() => setPicking(false)}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      )}
    </div>
  );
}

/* ================================================================ Component */
export default function PatternAnalyzerPage() {
  const { projectId } = useProject();
  const { cpeId } = useCPE();
  const cpeIdRef = useRef<string | null>(cpeId);
  cpeIdRef.current = cpeId;
  const { resolvedTheme } = useTheme();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [activeTab, setActiveTab] = useState<"cpe" | "overview" | "pattern-lab">("cpe");

  useEffect(() => {
    const t = searchParams.get("tab");
    if (t === "overview") setActiveTab("overview");
    else if (t === "pattern-lab") setActiveTab("pattern-lab");
    else setActiveTab("cpe");
  }, [searchParams]);

  // Domain-grouped pattern state
  const [domains, setDomains] = useState<DomainPatterns>({});
  const [patternsLoaded, setPatternsLoaded] = useState(false);
  const [collapsedDomains, setCollapsedDomains] = useState<Set<string>>(new Set());
  const [newDomainName, setNewDomainName] = useState("");
  const [showNewDomain, setShowNewDomain] = useState(false);

  // Scan config
  const [bucketMinutes, setBucketMinutes] = useState(0); // 0 = Auto
  const [filterPreNtp, setFilterPreNtp] = useState(true);
  const [filterShortReboots, setFilterShortReboots] = useState(true);
  const [scanProgress, setScanProgress] = useState<RegexScanProgressPayload | null>(null);

  // Scan results
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  
  // Track current visible zoom range for dynamic bucket adjustment
  const [visibleRange, setVisibleRange] = useState<{ start: string; end: string } | null>(null);

  // NATCO governance state
  const [showSubmitDialog, setShowSubmitDialog] = useState(false);
  const [submitComment, setSubmitComment] = useState("");
  // Diff data: { domain: DomainDiff } and selection state: { "domain::regex": true }
  const [diffData, setDiffData] = useState<Record<string, DomainDiff> | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [selectedChanges, setSelectedChanges] = useState<Record<string, boolean>>({});

  // -- Load NATCO info for this project --
  const { data: globalInfo } = useQuery({
    queryKey: ["globalPatterns", projectId],
    queryFn: async () => (await patternGovernanceApi.getGlobal(projectId!)).data,
    enabled: !!projectId,
  });

  const hasNatco = !!globalInfo?.natco;

  // -- Sync from global mutation (sends current UI patterns so merge includes unsaved edits) --
  const syncMutation = useMutation({
    mutationFn: () => patternGovernanceApi.sync(projectId!, sanitizeDomainsForApi(domains)),
    onSuccess: (res) => {
      setDomains(res.data.domains);
      queryClient.invalidateQueries({ queryKey: ["regex-patterns", projectId] });
    },
  });

  // -- Open submit dialog: send current UI patterns for diff (no save round-trip) --
  const openSubmitDialog = async () => {
    if (!projectId) return;
    setDiffLoading(true);
    setShowSubmitDialog(true);
    setDiffData(null);
    setSelectedChanges({});
    setSubmitComment("");
    try {
      const res = await patternGovernanceApi.diff(projectId, sanitizeDomainsForApi(domains));
      setDiffData(res.data.domains);
      const sel: Record<string, boolean> = {};
      for (const [domain, diff] of Object.entries(res.data.domains)) {
        for (const p of diff.new) sel[`${domain}::${p.regex}`] = true;
        for (const p of diff.modified) sel[`${domain}::${p.regex}`] = true;
      }
      setSelectedChanges(sel);
    } catch {
      // handled by UI
    }
    setDiffLoading(false);
  };

  // Count selected changes
  const selectedCount = Object.values(selectedChanges).filter(Boolean).length;

  // -- Submit to global mutation (submits per-domain, one submission per domain that has selections) --
  const submitMutation = useMutation({
    mutationFn: async () => {
      if (!diffData || !projectId) throw new Error("No diff data");
      const promises: Promise<unknown>[] = [];
      for (const [domain, diff] of Object.entries(diffData)) {
        const patsToSubmit: Array<UserPattern & { change_type: string }> = [];
        for (const p of diff.new) {
          if (selectedChanges[`${domain}::${p.regex}`]) {
            patsToSubmit.push({
              ...sanitizePatternForApi(p as UserPattern),
              change_type: "new",
            });
          }
        }
        for (const p of diff.modified) {
          if (selectedChanges[`${domain}::${p.regex}`]) {
            patsToSubmit.push({
              ...sanitizePatternForApi(p as UserPattern),
              change_type: "modified",
            });
          }
        }
        if (patsToSubmit.length > 0) {
          promises.push(patternGovernanceApi.submit(projectId, domain, patsToSubmit, submitComment));
        }
      }
      if (promises.length === 0) throw new Error("No patterns selected");
      return Promise.all(promises);
    },
    onSuccess: () => {
      setShowSubmitDialog(false);
      setDiffData(null);
      setSelectedChanges({});
      setSubmitComment("");
      queryClient.invalidateQueries({ queryKey: ["mySubmissions", projectId] });
    },
  });

  // -- Load user's submission history --
  const { data: mySubmissions } = useQuery({
    queryKey: ["mySubmissions", projectId],
    queryFn: async () => (await patternGovernanceApi.mySubmissions(projectId!)).data,
    enabled: !!projectId && hasNatco,
  });

  const [submissionsCollapsed, setSubmissionsCollapsed] = useState(true);

  const resolvedCount = mySubmissions?.filter((s) => s.status === "approved" || s.status === "rejected").length ?? 0;
  const pendingCount = mySubmissions?.filter((s) => s.status === "pending").length ?? 0;

  const clearResolvedMutation = useMutation({
    mutationFn: () => patternGovernanceApi.clearResolved(projectId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mySubmissions", projectId] });
    },
  });

  // Reboot selection state (any reboot as start, any as end)
  const [startRebootIdx, setStartRebootIdx] = useState<number | null>(null);
  const [endRebootIdx, setEndRebootIdx] = useState<number | null>(null);
  const [sliderValue, setSliderValue] = useState(0);

  // -- Load saved patterns --
  const { data: savedDomains, isLoading: loadingPatterns } = useQuery({
    queryKey: ["regex-patterns", projectId],
    queryFn: async () => {
      const res = await patternAnalyzerApi.getPatterns(projectId!);
      return res.data.domains;
    },
    enabled: !!projectId,
  });

  useEffect(() => {
    if (savedDomains && !patternsLoaded) {
      setDomains(savedDomains);
      setPatternsLoaded(true);
      // Collapse all domains by default
      setCollapsedDomains(new Set(Object.keys(savedDomains)));
    }
  }, [savedDomains, patternsLoaded]);

  // -- Load reboots for the selected CPE (query key must include cpeId) --
  const { data: rebootsData } = useQuery({
    queryKey: ["reboots", projectId, cpeId ?? ""],
    queryFn: async () => {
      const res = await patternAnalyzerApi.getReboots(projectId!, cpeId);
      return res.data.reboots;
    },
    enabled: !!projectId,
  });

  // -- Derive selected reboot timestamps --
  const reboots: RebootEntry[] = rebootsData || [];
  const selectedStart = startRebootIdx !== null ? reboots[startRebootIdx]?.timestamp || "" : "";
  const selectedEnd = endRebootIdx !== null ? reboots[endRebootIdx]?.timestamp || "" : "";
  const hasSelection = startRebootIdx !== null && endRebootIdx !== null;

  // -- Compute effective time range from reboot selection + slider --
  // End is always pinned to the selected end reboot.  Slider moves the
  // start from the selected start reboot toward the end reboot.
  //
  // IMPORTANT: Timestamps are naive ISO strings (no timezone).  We must
  // NOT convert through Date.toISOString() because that emits UTC while
  // `new Date(naiveStr)` parses as local time – introducing an offset
  // that silently breaks string comparisons against the scan data.
  let effectiveRange: { start: string; end: string } | undefined;
  if (hasSelection && selectedStart && selectedEnd) {
    if (sliderValue === 0) {
      // No slider offset – use the raw strings directly (no Date conversion).
      effectiveRange = { start: selectedStart, end: selectedEnd };
    } else {
      const startMs = new Date(selectedStart).getTime();
      const endMs = new Date(selectedEnd).getTime();
      const durationMs = endMs - startMs;
      if (durationMs <= 0) {
        effectiveRange = { start: selectedStart, end: selectedEnd };
      } else {
        const skipMs = (sliderValue / 100) * durationMs;
        const d = new Date(startMs + skipMs);
        // Format as local time to match the naive timestamps in scan data
        const pad = (n: number) => n.toString().padStart(2, "0");
        const effectiveStart = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        effectiveRange = { start: effectiveStart, end: selectedEnd };
      }
    }
  }

  const chartFilterRange = effectiveRange;

  // -- Save patterns mutation --
  const saveMutation = useMutation({
    mutationFn: () => patternAnalyzerApi.savePatterns(projectId!, sanitizeDomainsForApi(domains)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["regex-patterns", projectId] });
    },
  });

  // -- Flatten all enabled patterns for scan --
  const allPatterns: UserPattern[] = Object.values(domains).flat();
  const enabledPatterns = allPatterns.filter((p) => p.enabled && p.regex.trim());
  const enabledCount = enabledPatterns.length;
  const totalCount = allPatterns.length;

  // -- Scan status --
  const [scanStatus, setScanStatus] = useState<string>("");

  // Scan/reboot UI is per CPE; avoid showing another device's chart or reboot list.
  useEffect(() => {
    setScanResult(null);
    setScanStatus("");
    setStartRebootIdx(null);
    setEndRebootIdx(null);
    setSliderValue(0);
    setVisibleRange(null);
    setScanProgress(null);
  }, [projectId, cpeId]);

  const { data: scanFilesRaw } = useQuery({
    queryKey: ["pattern-analyzer-files", projectId, cpeId ?? ""],
    queryFn: async () =>
      (await filesApi.list(projectId!, cpeId)).data as Array<{ filename: string; is_viewable?: boolean }>,
    enabled: !!projectId,
  });

  // -- Run scan (async ripgrep + progress polling) --
  const scanMutation = useMutation({
    mutationFn: async () => {
      const dbgCpe = cpeId;
      const effectiveBucket = bucketMinutes === 0 ? calculateAutoBucket(scanResult) : bucketMinutes;

      setScanStatus("Scanning log files with ripgrep...");
      setScanProgress({
        status: "running",
        current: 0,
        total: Math.max(enabledPatterns.length, 1),
        pattern_name: null,
        error: null,
      });

      const result = await runPatternAnalyzerScan("user", {
        projectId: projectId!,
        cpeId: dbgCpe,
        patterns: enabledPatterns,
        bucketMinutes: effectiveBucket,
        filterPreNtp: filterPreNtp,
        filterShortReboots: filterShortReboots,
        onProgress: setScanProgress,
      });

      return { result, dbgCpe };
    },
    onSuccess: (payload) => {
      const current = cpeIdRef.current;
      const stamped = payload.result.cpe_serial ?? null;
      const started = payload.dbgCpe ?? null;
      const expectedKey = current ?? null;
      const resultKey = stamped !== null && stamped !== "" ? stamped : started;
      const applyResult = resultKey === expectedKey;
      setScanProgress(null);
      if (!applyResult) {
        setScanStatus("Scan results ignored — CPE changed before load finished. Run scan again.");
        return;
      }
      setScanResult(payload.result);
      setScanStatus("");
    },
    onError: () => {
      setScanStatus("");
      setScanProgress(null);
    },
  });

  // -- Handle DRAIN3 template import via URL params (template= and optional domain=) --
  useEffect(() => {
    const templateParam = searchParams.get("template");
    const domainParam = searchParams.get("domain");
    if (templateParam && patternsLoaded) {
      const regex = drain3ToRegex(templateParam);
      const name = templateParam.length > 60 ? templateParam.slice(0, 57) + "..." : templateParam;
      const targetDomain = domainParam?.trim() || "Imported";
      const existing = domains[targetDomain] || [];
      const exists = existing.some((p) => p.regex === regex);
      if (!exists) {
        setDomains((prev) => ({
          ...prev,
          [targetDomain]: [...(prev[targetDomain] || []), { name, regex, enabled: true }],
        }));
      }
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, patternsLoaded, domains, setSearchParams]);

  // -- Domain-level enable/disable --
  const toggleDomainEnabled = (domain: string, enabled: boolean) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p) => ({ ...p, enabled })),
    }));
  };

  const isDomainFullyEnabled = (domain: string): boolean => {
    const pats = domains[domain] || [];
    return pats.length > 0 && pats.every((p) => p.enabled);
  };

  const isDomainPartiallyEnabled = (domain: string): boolean => {
    const pats = domains[domain] || [];
    return pats.some((p) => p.enabled) && !pats.every((p) => p.enabled);
  };

  // -- Domain CRUD helpers --
  const toggleDomainCollapse = (domain: string) => {
    setCollapsedDomains((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain);
      else next.add(domain);
      return next;
    });
  };

  const addDomain = () => {
    const name = newDomainName.trim();
    if (!name || domains[name]) return;
    setDomains((prev) => ({ ...prev, [name]: [] }));
    setNewDomainName("");
    setShowNewDomain(false);
  };

  const removeDomain = (domain: string) => {
    setDomains((prev) => {
      const next = { ...prev };
      delete next[domain];
      return next;
    });
  };

  // Track which domain just had a pattern added so we can scroll to it
  const [scrollTarget, setScrollTarget] = useState<{ domain: string; idx: number } | null>(null);
  const newPatternRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollTarget && newPatternRef.current) {
      newPatternRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
      // Focus the regex input inside the new row
      const regexInput = newPatternRef.current.querySelector<HTMLInputElement>("input[placeholder='Regular expression']");
      regexInput?.focus();
      setScrollTarget(null);
    }
  }, [scrollTarget, domains]);

  // -- Pattern CRUD helpers --
  const addPattern = (domain: string) => {
    const newIdx = (domains[domain] || []).length;
    setDomains((prev) => ({
      ...prev,
      [domain]: [...(prev[domain] || []), { name: "", regex: "", enabled: true }],
    }));
    // Expand the domain if collapsed and schedule scroll
    setCollapsedDomains((prev) => {
      const next = new Set(prev);
      next.delete(domain);
      return next;
    });
    setScrollTarget({ domain, idx: newIdx });
  };

  const removePattern = (domain: string, idx: number) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).filter((_, i) => i !== idx),
    }));
  };

  const updatePattern = (domain: string, idx: number, field: keyof UserPattern, value: string | boolean) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) => (i === idx ? { ...p, [field]: value } : p)),
    }));
  };

  const updatePatternMW = (domain: string, idx: number, mw: MaintenanceWindow | null) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) =>
        i === idx ? { ...p, maintenance_window: mw } : p
      ),
    }));
  };

  const updatePatternRP = (domain: string, idx: number, minutes: number | null) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) =>
        i === idx ? { ...p, reboot_proximity_minutes: minutes } : p
      ),
    }));
  };

  const updatePatternFT = (domain: string, idx: number, threshold: number | null) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) =>
        i === idx ? { ...p, min_frequency_threshold: threshold } : p
      ),
    }));
  };

  const updatePatternScanFilename = (domain: string, idx: number, filename: string) => {
    const v = filename.trim();
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) =>
        i === idx ? { ...p, scan_filename: v ? v : undefined } : p
      ),
    }));
  };

  const updatePatternScanTimeRange = (
    domain: string,
    idx: number,
    range: { start: string; end: string } | null,
  ) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) =>
        i === idx ? { ...p, scan_time_range: range ?? undefined } : p
      ),
    }));
  };

  const patchScanTimeField = (domain: string, idx: number, field: "start" | "end", value: string) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((pat, i) => {
        if (i !== idx) return pat;
        const cur = pat.scan_time_range ?? { start: "", end: "" };
        return {
          ...pat,
          scan_time_range: { ...cur, [field]: value },
        };
      }),
    }));
  };

  const updatePatternValueCompare = (domain: string, idx: number, vc: PatternValueCompare | null) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) => {
        if (i !== idx) return p;
        if (!vc) {
          const { value_compare: _removed, ...rest } = p;
          return rest;
        }
        return { ...p, value_compare: vc };
      }),
    }));
  };

  const patchPatternValueCompare = (
    domain: string,
    idx: number,
    patch: Partial<PatternValueCompare>,
  ) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) => {
        if (i !== idx) return p;
        const base = p.value_compare ?? defaultPatternValueCompare();
        return { ...p, value_compare: { ...base, ...patch, enabled: true } };
      }),
    }));
  };

  const [mwEditTarget, setMwEditTarget] = useState<string | null>(null);
  const mwKey = (domain: string, idx: number) => `${domain}::${idx}`;

  // -- JSON file import --
  const handleJsonImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const json = JSON.parse(ev.target?.result as string);

        // Support domain-grouped format: { domains: {...} } or { "WLAN_Issues": [...], ... }
        // or flat array: [ {name, regex}, ... ]
        // or rule_parser_config.json format: { "WLAN_Issues": [ { Title, CPELogs: [{ Regex: [...] }] } ] }

        if (json.domains && typeof json.domains === "object") {
          // Domain-grouped format
          const imported: DomainPatterns = {};
          for (const [domain, pats] of Object.entries(json.domains)) {
            if (Array.isArray(pats)) {
              imported[domain] = (pats as UserPattern[]).map((p) => {
                const pattern: UserPattern = {
                  name: String(p.name || "").slice(0, 100),
                  regex: String(p.regex || ""),
                  enabled: p.enabled !== false,
                };
                // Preserve maintenance_window if present
                if (p.maintenance_window && typeof p.maintenance_window === "object") {
                  const mw = p.maintenance_window as { start?: string; end?: string };
                  if (mw.start && mw.end) {
                    pattern.maintenance_window = { start: mw.start, end: mw.end };
                  }
                }
                // Preserve reboot_proximity_minutes if present
                if (p.reboot_proximity_minutes != null) {
                  const rp = Number(p.reboot_proximity_minutes);
                  if (!isNaN(rp) && rp >= 1 && rp <= 60) {
                    pattern.reboot_proximity_minutes = rp;
                  }
                }
                // Preserve min_frequency_threshold if present
                if (p.min_frequency_threshold != null) {
                  const ft = Number(p.min_frequency_threshold);
                  if (!isNaN(ft) && ft >= 1 && ft <= 1000) {
                    pattern.min_frequency_threshold = ft;
                  }
                }
                const iv = coerceImportedValueCompare(p.value_compare);
                if (iv) pattern.value_compare = iv;
                return pattern;
              }).filter((p) => p.regex);
            }
          }
          // Merge into existing
          setDomains((prev) => {
            const next = { ...prev };
            for (const [domain, pats] of Object.entries(imported)) {
              const existing = next[domain] || [];
              const existingRegexes = new Set(existing.map((p) => p.regex));
              const newPats = pats.filter((p) => !existingRegexes.has(p.regex));
              next[domain] = [...existing, ...newPats];
            }
            return next;
          });
          return;
        }

        if (Array.isArray(json)) {
          // Flat array → "Imported" domain
          const imported: UserPattern[] = json
            .map((item: Record<string, unknown>) => {
              const pattern: UserPattern = {
                name: String(item.name || item.template || item.regex || "").slice(0, 100),
                regex: String(item.regex || item.pattern || item.template || ""),
                enabled: item.enabled !== false,
              };
              // Preserve maintenance_window if present
              if (item.maintenance_window && typeof item.maintenance_window === "object") {
                const mw = item.maintenance_window as { start?: string; end?: string };
                if (mw.start && mw.end) {
                  pattern.maintenance_window = { start: mw.start, end: mw.end };
                }
              }
              // Preserve reboot_proximity_minutes if present
              if (item.reboot_proximity_minutes != null) {
                const rp = Number(item.reboot_proximity_minutes);
                if (!isNaN(rp) && rp >= 1 && rp <= 60) {
                  pattern.reboot_proximity_minutes = rp;
                }
              }
              // Preserve min_frequency_threshold if present
              if (item.min_frequency_threshold != null) {
                const ft = Number(item.min_frequency_threshold);
                if (!isNaN(ft) && ft >= 1 && ft <= 1000) {
                  pattern.min_frequency_threshold = ft;
                }
              }
              const iv = coerceImportedValueCompare(item.value_compare);
              if (iv) pattern.value_compare = iv;
              return pattern;
            })
            .filter((p: UserPattern) => p.regex);
          if (imported.length > 0) {
            setDomains((prev) => {
              const existing = prev["Imported"] || [];
              const existingRegexes = new Set(existing.map((p) => p.regex));
              const newPats = imported.filter((p) => !existingRegexes.has(p.regex));
              return { ...prev, Imported: [...existing, ...newPats] };
            });
          }
          return;
        }

        // Try rule_parser_config.json format
        if (typeof json === "object") {
          const imported: DomainPatterns = {};
          let found = false;
          for (const [key, issues] of Object.entries(json)) {
            if (!Array.isArray(issues)) continue;
            const patterns: UserPattern[] = [];
            for (const issue of issues as Array<Record<string, unknown>>) {
              const title = String(issue.Title || "");
              const cpeLogs = issue.CPELogs as Array<Record<string, unknown>> | undefined;
              if (!Array.isArray(cpeLogs)) continue;
              for (const cpeLog of cpeLogs) {
                const regexEntries = cpeLog.Regex as Array<Record<string, string>> | undefined;
                if (!Array.isArray(regexEntries)) continue;
                for (const rx of regexEntries) {
                  if (rx.pattern) {
                    patterns.push({
                      name: rx.description || title || rx.pattern.slice(0, 60),
                      regex: rx.pattern,
                      enabled: true,
                    });
                    found = true;
                  }
                }
              }
            }
            if (patterns.length > 0) imported[key] = patterns;
          }
          if (found) {
            setDomains((prev) => {
              const next = { ...prev };
              for (const [domain, pats] of Object.entries(imported)) {
                const existing = next[domain] || [];
                const existingRegexes = new Set(existing.map((p) => p.regex));
                const newPats = pats.filter((p) => !existingRegexes.has(p.regex));
                next[domain] = [...existing, ...newPats];
              }
              return next;
            });
            return;
          }
        }

        alert("Unrecognized JSON format. Supported: domain-grouped, flat array, or rule_parser_config format.");
      } catch {
        alert("Failed to parse JSON file.");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  // -- Export handler --
  const handleExport = (format: "yaml" | "json") => {
    if (!projectId) return;
    const url = patternAnalyzerApi.exportUrl(projectId, format);
    // Open with auth token
    const token = localStorage.getItem("access_token");
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => res.blob())
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `patterns.${format}`;
        a.click();
        URL.revokeObjectURL(a.href);
      })
      .catch(() => alert("Export failed."));
  };

  // -- Build Plotly data (time series with individual log points) --
  // Memoized to prevent recalculation on every render
  const { plotData, plotShapes, traceNames, filteredMatchCount, actualTimeRange } = useMemo(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const plotData: any[] = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const plotShapes: any[] = [];
    const traceNames: string[] = [];
    let filteredMatchCount = 0;
    let actualTimeRange: { start: string; end: string } | undefined;

    if (scanResult) {
    // Client-side time filter: reboot/slider window ∩ each trace's scan_time_range (echoed from scan).
    const chartLo = chartFilterRange?.start?.trim() || "";
    const chartHi = chartFilterRange?.end?.trim() || "";

    scanResult.traces.forEach((trace: any, idx) => {
      let filteredTimes = trace.times;
      let filteredTexts = trace.texts;
      let filteredCounts = trace.counts || trace.times.map(() => 1);

      const { lo: rangeStart, hi: rangeEnd, disjoint } = effectivePatternAnalyzerWindow(
        chartLo || chartHi ? { start: chartLo, end: chartHi } : null,
        trace.scan_time_range ?? null,
      );
      if (disjoint) {
        return;
      }

      const hasPatScanUtc = !!(
        trace.scan_time_range?.start?.trim() && trace.scan_time_range?.end?.trim()
      );
      const cmpT = (x: string, y: string) =>
        hasPatScanUtc ? utcNaiveIsoToMs(x) - utcNaiveIsoToMs(y) : cmpPatternAnalyzerTs(x, y);

      if (rangeStart || rangeEnd) {
        const indices: number[] = [];
        for (let i = 0; i < trace.times.length; i++) {
          const t = trace.times[i];
          if (rangeStart && cmpT(t, rangeStart) < 0) continue;
          if (rangeEnd && cmpT(t, rangeEnd) > 0) continue;
          indices.push(i);
        }
        filteredTimes = indices.map((i) => trace.times[i]);
        filteredTexts = indices.map((i) => trace.texts[i]);
        filteredCounts = indices.map((i) => filteredCounts[i]);
      }

      if (filteredTimes.length === 0) return;

      filteredMatchCount += filteredTimes.length;
      const bucketInfo = trace.bucketed 
        ? ` [~${filteredTimes.length} buckets]` 
        : "";
      const label = `${trace.name} (${filteredTimes.length}${bucketInfo})`;
      traceNames.push(label);

      const color = eventIdChartColor(String(trace.name ?? idx));
      
      let markerSize: number | number[];
      if (trace.bucketed) {
        markerSize = filteredCounts.map((count: number) => Math.min(15, 5 + Math.log(count) * 2));
      } else {
        markerSize = 7;
      }
      
      plotData.push({
        x: filteredTimes,
        y: filteredTimes.map(() => label),
        type: "scatter" as const,
        mode: "markers" as const,
        name: label,
        marker: {
          size: markerSize,
          color,
          symbol: "circle",
          opacity: 0.8,
          line: { width: 0.5, color: SCATTER_MARKER_LINE },
        },
        text: trace.bucketed
          ? filteredTexts.map((txt: string, i: number) => {
              const count = filteredCounts[i];
              return `${txt} (${count} matches in ${trace.bucket_minutes || 5}min window)`;
            })
          : filteredTexts,
        hovertemplate: "%{text}<extra></extra>",
      });
    });

    // Reboot vertical lines + invisible hover targets at bottom row (avoid y-axis clutter).
    const rebootsInRange: PatternAnalyzerRebootRow[] = [];
    scanResult.reboots.forEach((reboot) => {
      if (chartLo && cmpPatternAnalyzerTs(reboot.timestamp, chartLo) < 0) return;
      if (chartHi && cmpPatternAnalyzerTs(reboot.timestamp, chartHi) > 0) return;

      rebootsInRange.push(reboot);
      const accent = patternRebootBoundaryAccent(reboot);
      plotShapes.push({
        type: "line",
        x0: reboot.timestamp,
        x1: reboot.timestamp,
        y0: 0,
        y1: 1,
        yref: "paper",
        line: { color: accent.plotColor, width: 2, dash: "dash" },
      });
    });

    if (rebootsInRange.length > 0 && traceNames.length > 0) {
      const yCat = traceNames[traceNames.length - 1] ?? traceNames[0];
      plotData.push({
        x: rebootsInRange.map((r) => r.timestamp),
        y: rebootsInRange.map(() => yCat),
        type: "scatter" as const,
        mode: "markers" as const,
        marker: { size: 16, opacity: 0, line: { width: 0 } },
        text: rebootsInRange.map((reboot) => {
          const accent = patternRebootBoundaryAccent(reboot);
          const ub = formatUptimeBeforeReboot(reboot.uptime_before_reboot_sec);
          let s = `<b>${accent.typeLabel}</b>: ${reboot.reason || "unknown"}`;
          if (ub !== "—") s += `<br>Uptime before: ${ub}`;
          if (reboot.is_short_reboot) s += `<br><i>Short reboot</i>`;
          return s;
        }),
        hovertemplate: "%{text}<extra></extra>",
        showlegend: false,
        name: "Reboot",
      });
    }
    
    // Calculate actual data bounds when no reboot selection to fix timeline compression
    if (!chartFilterRange && plotData.length > 0) {
      let minTime = Infinity;
      let maxTime = -Infinity;
      
      plotData.forEach((trace) => {
        if (trace.showlegend === false && trace.marker?.opacity === 0) return;
        trace.x.forEach((ts: string) => {
          const ms = new Date(ts).getTime();
          if (ms < minTime) minTime = ms;
          if (ms > maxTime) maxTime = ms;
        });
      });
      
      if (minTime < Infinity && maxTime > -Infinity) {
        // Use the actual min/max timestamps WITHOUT padding
        // Plotly handles the visual padding automatically
        const pad = (n: number) => n.toString().padStart(2, "0");
        const startDate = new Date(minTime);
        const endDate = new Date(maxTime);
        actualTimeRange = {
          start: `${startDate.getFullYear()}-${pad(startDate.getMonth() + 1)}-${pad(startDate.getDate())}T${pad(startDate.getHours())}:${pad(startDate.getMinutes())}:${pad(startDate.getSeconds())}`,
          end: `${endDate.getFullYear()}-${pad(endDate.getMonth() + 1)}-${pad(endDate.getDate())}T${pad(endDate.getHours())}:${pad(endDate.getMinutes())}:${pad(endDate.getSeconds())}`,
        };
      }
    }
  }

    return { plotData, plotShapes, traceNames, filteredMatchCount, actualTimeRange };
  }, [scanResult, chartFilterRange]);

  // Memoize Plotly layout to prevent unnecessary re-renders
  const plotLayout = useMemo(() => {
    const range = chartFilterRange || actualTimeRange;
    
    // Calculate effective bucket based on visible range or full data
    let effectiveBucket: number;
    if (bucketMinutes === 0) {
      // Auto mode: use visible range if available, otherwise full scan data
      if (visibleRange) {
        const startMs = new Date(visibleRange.start).getTime();
        const endMs = new Date(visibleRange.end).getTime();
        const durationMs = endMs - startMs;
        effectiveBucket = calculateBucketFromDuration(durationMs);
      } else {
        effectiveBucket = calculateAutoBucket(scanResult);
      }
    } else {
      effectiveBucket = bucketMinutes;
    }
    
    return mergePlotlyLayout(resolvedTheme === "dark", {
      height: Math.max(300, traceNames.length * 60 + 100),
      showlegend: false,
      margin: { l: 200, r: 24, t: 16, b: 48 },
      xaxis: {
        title: { text: "Time", font: { size: 11 } },
        tickfont: { size: 10 },
        type: "date" as const,
        ...(range
          ? { range: [range.start, range.end], autorange: false }
          : {}),
        ...(effectiveBucket > 0
          ? { dtick: effectiveBucket * 60 * 1000 }
          : {}),
      },
      yaxis: {
        tickfont: { size: 10 },
        type: "category" as const,
        categoryorder: "array" as const,
        categoryarray: [...traceNames].reverse(),
        automargin: true,
      },
      hovermode: "closest" as const,
      shapes: plotShapes,
      annotations: [],
      font: { family: "Roboto, sans-serif", size: 11 },
    });
  }, [
    traceNames,
    chartFilterRange,
    actualTimeRange,
    bucketMinutes,
    plotShapes,
    scanResult,
    visibleRange,
    resolvedTheme,
  ]);

  const domainNames = Object.keys(domains);

  return (
    <div className="p-4 space-y-4 max-w-full min-w-0 overflow-y-auto" style={{ height: "calc(100vh - 48px)" }}>
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <ManageSearchIcon className="text-primary" style={{ fontSize: 24 }} />
          <h2 className="text-lg font-semibold">Pattern Analyzer</h2>
        </div>
        <NatcoBadgeOrSelector
          projectId={projectId!}
          natco={globalInfo?.natco ?? null}
          onAssigned={() => {
            queryClient.invalidateQueries({ queryKey: ["globalPatterns", projectId] });
          }}
        />
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-border">
        <button
          onClick={() => {
            setActiveTab("cpe");
            setSearchParams((prev) => {
              const next = new URLSearchParams(prev);
              next.delete("tab");
              return next;
            }, { replace: true });
          }}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "cpe"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
          }`}
        >
          <ManageSearchIcon style={{ fontSize: 16 }} />
          CPE Analysis
        </button>
        <button
          onClick={() => {
            setActiveTab("overview");
            setSearchParams((prev) => {
              const next = new URLSearchParams(prev);
              next.set("tab", "overview");
              return next;
            }, { replace: true });
          }}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "overview"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
          }`}
        >
          <CompareArrowsIcon style={{ fontSize: 16 }} />
          Cross-CPE Overview
        </button>
        <button
          onClick={() => {
            setActiveTab("pattern-lab");
            setSearchParams((prev) => {
              const next = new URLSearchParams(prev);
              next.set("tab", "pattern-lab");
              return next;
            }, { replace: true });
          }}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "pattern-lab"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
          }`}
        >
          <ScienceIcon style={{ fontSize: 16 }} />
          Pattern Lab
        </button>
      </div>

      {activeTab === "overview" && <PatternOverviewTab />}

      {activeTab === "pattern-lab" && <PatternLabTab />}

      {activeTab === "cpe" && <>

      {/* ====== PATTERN MANAGEMENT ====== */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/30 flex items-center justify-between flex-wrap gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <ManageSearchIcon style={{ fontSize: 14, color: "#1a73e8" }} /> Pattern Configuration
            {totalCount > 0 && (
              <span className="ml-1 text-[10px] font-normal">
                ({domainNames.length} domain{domainNames.length !== 1 ? "s" : ""}, {totalCount} pattern{totalCount !== 1 ? "s" : ""})
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-border bg-background hover:bg-muted transition-colors"
            >
              <UploadFileIcon style={{ fontSize: 14 }} /> Import JSON
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,.yaml,.yml"
              onChange={handleJsonImport}
              className="hidden"
            />
            <button
              onClick={() => setShowNewDomain(true)}
              className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100 dark:border-blue-700 dark:bg-blue-900/20 dark:text-blue-400 transition-colors"
            >
              <CreateNewFolderIcon style={{ fontSize: 14 }} /> Add Domain
            </button>
            {/* Export dropdown */}
            <div className="relative group">
              <button
                className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-border bg-background hover:bg-muted transition-colors"
              >
                <FileDownloadIcon style={{ fontSize: 14 }} /> Export
              </button>
              <div className="absolute right-0 top-full pt-1 z-10 hidden group-hover:block">
                <div className="bg-card border border-border rounded-lg shadow-lg min-w-[100px]">
                  <button
                    onClick={() => handleExport("json")}
                    className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted transition-colors"
                  >
                    As JSON
                  </button>
                  <button
                    onClick={() => handleExport("yaml")}
                    className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted transition-colors"
                  >
                    As YAML
                  </button>
                </div>
              </div>
            </div>
            {/* NATCO Governance buttons */}
            {hasNatco && (
              <>
                <button
                  onClick={() => syncMutation.mutate()}
                  disabled={syncMutation.isPending}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-purple-300 bg-purple-50 text-purple-700 hover:bg-purple-100 dark:border-purple-700 dark:bg-purple-900/20 dark:text-purple-400 transition-colors disabled:opacity-50"
                  title="Pull latest global patterns from NATCO config"
                >
                  {syncMutation.isPending ? <CircularProgress size={12} /> : <SyncIcon style={{ fontSize: 14 }} />}
                  Sync from Global
                </button>
                <button
                  onClick={openSubmitDialog}
                  className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400 transition-colors"
                  title="Compare against global and submit changes for review"
                >
                  <PublishIcon style={{ fontSize: 14 }} />
                  Submit to Global
                </button>
              </>
            )}
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-green-300 bg-green-50 text-green-700 hover:bg-green-100 dark:border-green-700 dark:bg-green-900/20 dark:text-green-400 transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? (
                <CircularProgress size={12} />
              ) : (
                <SaveIcon style={{ fontSize: 14 }} />
              )}
              Save
            </button>
          </div>
        </div>

        {/* New domain input */}
        {showNewDomain && (
          <div className="px-4 py-2 border-b border-border bg-blue-50/50 dark:bg-blue-900/10 flex items-center gap-2">
            <input
              type="text"
              value={newDomainName}
              onChange={(e) => setNewDomainName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addDomain()}
              placeholder="Domain name (e.g. WLAN_Issues)"
              className="flex-1 text-xs px-2 py-1 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              autoFocus
            />
            <button onClick={addDomain} disabled={!newDomainName.trim()} className="px-3 py-1 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">Create</button>
            <button onClick={() => { setShowNewDomain(false); setNewDomainName(""); }} className="text-xs text-muted-foreground hover:text-foreground">Cancel</button>
          </div>
        )}

        {/* Domain-grouped pattern tables */}
        <div className="divide-y divide-border">
          {loadingPatterns ? (
            <div className="flex items-center gap-2 justify-center py-6 text-muted-foreground">
              <CircularProgress size={16} />
              <span className="text-xs">Loading patterns...</span>
            </div>
          ) : domainNames.length === 0 ? (
            <div className="text-center py-6 text-muted-foreground">
              <p className="text-sm">No patterns configured yet.</p>
              <p className="text-xs mt-1">Add a domain, import from presets/JSON, or use "Add to Pattern Analyzer" from the Pattern or Semantic Search pages.</p>
            </div>
          ) : (
            domainNames.map((domain) => {
              const patterns = domains[domain] || [];
              const isCollapsed = collapsedDomains.has(domain);
              const domainEnabled = patterns.filter((p) => p.enabled && p.regex.trim()).length;

              return (
                <div key={domain}>
                  {/* Domain header */}
                  <div
                    className="flex items-center justify-between px-4 py-2 bg-muted/20 cursor-pointer hover:bg-muted/40 transition-colors"
                    onClick={() => toggleDomainCollapse(domain)}
                  >
                    <div className="flex items-center gap-2">
                      {isCollapsed ? (
                        <ExpandMoreIcon style={{ fontSize: 18 }} className="text-muted-foreground" />
                      ) : (
                        <ExpandLessIcon style={{ fontSize: 18 }} className="text-muted-foreground" />
                      )}
                      <span className="text-xs font-semibold">{domain.replace(/_/g, " ")}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {domainEnabled}/{patterns.length} enabled
                      </span>
                    </div>
                    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      {/* Domain-level enable/disable */}
                      <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer" title={isDomainFullyEnabled(domain) ? "Disable all patterns" : "Enable all patterns"}>
                        <input
                          type="checkbox"
                          checked={isDomainFullyEnabled(domain)}
                          ref={(el) => {
                            if (el) el.indeterminate = isDomainPartiallyEnabled(domain);
                          }}
                          onChange={(e) => toggleDomainEnabled(domain, e.target.checked)}
                          className="h-3.5 w-3.5 rounded accent-primary"
                        />
                        <span className="hidden sm:inline">{isDomainFullyEnabled(domain) ? "All on" : "Toggle"}</span>
                      </label>
                      <button
                        onClick={() => addPattern(domain)}
                        className="p-1 rounded hover:bg-blue-100 dark:hover:bg-blue-900/20 text-muted-foreground hover:text-blue-600 transition-colors"
                        title="Add pattern to this domain"
                      >
                        <AddIcon style={{ fontSize: 16 }} />
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Remove domain "${domain}" and all its ${patterns.length} patterns?`)) {
                            removeDomain(domain);
                          }
                        }}
                        className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                        title="Remove domain"
                      >
                        <DeleteIcon style={{ fontSize: 16 }} />
                      </button>
                    </div>
                  </div>

                  {/* Pattern rows */}
                  {!isCollapsed && (
                    <div className="px-4 py-2 space-y-1">
                      {patterns.length === 0 ? (
                        <p className="text-[11px] text-muted-foreground py-2 text-center">No patterns in this domain yet.</p>
                      ) : (
                        <>
                          <div className="grid grid-cols-[32px_1fr_2fr_auto_32px] gap-2 px-1 py-0.5">
                            <span className="text-[10px] text-muted-foreground font-semibold uppercase">On</span>
                            <span className="text-[10px] text-muted-foreground font-semibold uppercase">Name</span>
                            <span className="text-[10px] text-muted-foreground font-semibold uppercase">Regex</span>
                            <span className="text-[10px] text-muted-foreground font-semibold uppercase whitespace-nowrap">Filters</span>
                            <span />
                          </div>
                          {patterns.map((p, idx) => {
                            const key = mwKey(domain, idx);
                            const mwOpen = mwEditTarget === key;
                            const hasMW = !!(p.maintenance_window?.start && p.maintenance_window?.end);
                            const hasRP = !!(p.reboot_proximity_minutes && p.reboot_proximity_minutes > 0);
                            const hasFT = !!(p.min_frequency_threshold && p.min_frequency_threshold > 0);
                            const hasVC = !!p.value_compare?.enabled;
                            const hasScanFile = !!(p.scan_filename?.trim());
                            const hasScanTime = !!(p.scan_time_range?.start?.trim() && p.scan_time_range?.end?.trim());
                            const hasScanScope = hasScanFile || hasScanTime;
                            const hasFilters = hasMW || hasRP || hasFT || hasScanScope || hasVC;
                            return (
                              <div key={idx} ref={scrollTarget?.domain === domain && scrollTarget?.idx === idx ? newPatternRef : undefined}>
                                <div className="grid grid-cols-[32px_1fr_2fr_auto_32px] gap-2 items-center px-1 py-0.5 rounded hover:bg-muted/30">
                                  <input
                                    type="checkbox"
                                    checked={p.enabled}
                                    onChange={(e) => updatePattern(domain, idx, "enabled", e.target.checked)}
                                    className="h-3.5 w-3.5 rounded border-input accent-primary"
                                  />
                                  <input
                                    type="text"
                                    value={p.name}
                                    onChange={(e) => updatePattern(domain, idx, "name", e.target.value)}
                                    placeholder="Pattern name"
                                    className="text-xs px-2 py-1 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-ring min-w-0"
                                  />
                                  <input
                                    type="text"
                                    value={p.regex}
                                    onChange={(e) => updatePattern(domain, idx, "regex", e.target.value)}
                                    placeholder="Regular expression"
                                    className="text-xs px-2 py-1 rounded border border-border bg-background font-mono focus:outline-none focus:ring-1 focus:ring-ring min-w-0"
                                  />
                                  <button
                                    onClick={() => setMwEditTarget(mwOpen ? null : key)}
                                    className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] whitespace-nowrap transition-colors ${
                                      hasFilters
                                        ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 hover:bg-amber-200 dark:hover:bg-amber-900/50"
                                        : "text-muted-foreground hover:bg-muted/50"
                                    }`}
                                    title={
                                      hasFilters
                                        ? [
                                            hasMW ? `MW: ${p.maintenance_window!.start}–${p.maintenance_window!.end} UTC` : "",
                                            hasRP ? `Reboot: ±${p.reboot_proximity_minutes}min` : "",
                                            hasFT ? `Frequency: >${p.min_frequency_threshold}` : "",
                                            hasVC && p.value_compare
                                              ? `Numeric: ${p.value_compare.operator} ${p.value_compare.compare_to}`
                                              : "",
                                            hasScanFile ? `Scan file: ${p.scan_filename}` : "",
                                            hasScanTime
                                              ? `UTC scan window: ${p.scan_time_range!.start}–${p.scan_time_range!.end}`
                                              : "",
                                          ].filter(Boolean).join(" | ")
                                        : "Filters / scan scope for this pattern"
                                    }
                                  >
                                    <FilterListIcon style={{ fontSize: 13 }} />
                                    {hasMW && <span>{p.maintenance_window!.start}–{p.maintenance_window!.end}</span>}
                                    {hasRP && (
                                      <span className="flex items-center gap-0.5">
                                        <RestartAltIcon style={{ fontSize: 11 }} />
                                        ±{p.reboot_proximity_minutes}m
                                      </span>
                                    )}
                                    {hasFT && (
                                      <span className="flex items-center gap-0.5">
                                        <span className="text-[9px]">&gt;</span>
                                        {p.min_frequency_threshold}
                                      </span>
                                    )}
                                    {hasVC && p.value_compare && (
                                      <span
                                        className="text-[9px] font-mono text-violet-700 dark:text-violet-300"
                                        title="Numeric threshold compare"
                                      >
                                        {p.value_compare.operator}
                                        {String(p.value_compare.compare_to)}
                                      </span>
                                    )}
                                    {hasScanFile && (
                                      <span className="flex items-center gap-0.5 max-w-[72px] truncate" title={p.scan_filename ?? ""}>
                                        <InsertDriveFileIcon style={{ fontSize: 11 }} />
                                      </span>
                                    )}
                                    {hasScanTime && <span className="text-[9px] opacity-80">⏱</span>}
                                  </button>
                                  <button
                                    onClick={() => removePattern(domain, idx)}
                                    className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                                  >
                                    <DeleteIcon style={{ fontSize: 14 }} />
                                  </button>
                                </div>
                                {mwOpen && (
                                  <div className="ml-8 mr-8 mb-1 mt-0.5 space-y-1">
                                    <div className="flex items-center gap-2 px-2 py-1.5 rounded bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40 text-[11px]">
                                      <ScheduleIcon style={{ fontSize: 13 }} className="text-amber-600 dark:text-amber-400 shrink-0" />
                                      <span className="text-muted-foreground whitespace-nowrap">Maintenance window (UTC):</span>
                                      <input
                                        type="time"
                                        value={p.maintenance_window?.start || ""}
                                        onChange={(e) =>
                                          updatePatternMW(domain, idx, {
                                            start: e.target.value,
                                            end: p.maintenance_window?.end || "",
                                          })
                                        }
                                        className="text-xs px-1.5 py-0.5 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-amber-500 w-[90px]"
                                      />
                                      <span className="text-muted-foreground">to</span>
                                      <input
                                        type="time"
                                        value={p.maintenance_window?.end || ""}
                                        onChange={(e) =>
                                          updatePatternMW(domain, idx, {
                                            start: p.maintenance_window?.start || "",
                                            end: e.target.value,
                                          })
                                        }
                                        className="text-xs px-1.5 py-0.5 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-amber-500 w-[90px]"
                                      />
                                      {hasMW && (
                                        <button
                                          onClick={() => updatePatternMW(domain, idx, null)}
                                          className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                                          title="Remove maintenance window"
                                        >
                                          <CloseIcon style={{ fontSize: 13 }} />
                                        </button>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-2 px-2 py-1.5 rounded bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/40 text-[11px]">
                                      <RestartAltIcon style={{ fontSize: 13 }} className="text-blue-600 dark:text-blue-400 shrink-0" />
                                      <span className="text-muted-foreground whitespace-nowrap">Reboot proximity:</span>
                                      <span className="text-muted-foreground">±</span>
                                      <input
                                        type="number"
                                        min={1}
                                        max={60}
                                        value={p.reboot_proximity_minutes ?? ""}
                                        onChange={(e) => {
                                          const v = e.target.value;
                                          updatePatternRP(domain, idx, v === "" ? null : Math.max(1, Math.min(60, parseInt(v, 10) || 1)));
                                        }}
                                        placeholder="min"
                                        className="text-xs px-1.5 py-0.5 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-ring w-[56px] text-center"
                                      />
                                      <span className="text-muted-foreground">min of any reboot</span>
                                      {hasRP && (
                                        <button
                                          onClick={() => updatePatternRP(domain, idx, null)}
                                          className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                                          title="Remove reboot proximity filter"
                                        >
                                          <CloseIcon style={{ fontSize: 13 }} />
                                        </button>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-2 px-2 py-1.5 rounded bg-green-50 dark:bg-green-900/10 border border-green-200 dark:border-green-800/40 text-[11px]">
                                      <FilterListIcon style={{ fontSize: 13 }} className="text-green-600 dark:text-green-400 shrink-0" />
                                      <span className="text-muted-foreground whitespace-nowrap">Min frequency threshold:</span>
                                      <span className="text-muted-foreground">&gt;</span>
                                      <input
                                        type="number"
                                        min={1}
                                        max={1000}
                                        value={p.min_frequency_threshold ?? ""}
                                        onChange={(e) => {
                                          const v = e.target.value;
                                          updatePatternFT(domain, idx, v === "" ? null : Math.max(1, Math.min(1000, parseInt(v, 10) || 1)));
                                        }}
                                        placeholder="count"
                                        className="text-xs px-1.5 py-0.5 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-green-500 w-[60px] text-center"
                                      />
                                      <span className="text-muted-foreground">occurrences to include CPE</span>
                                      {hasFT && (
                                        <button
                                          onClick={() => updatePatternFT(domain, idx, null)}
                                          className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                                          title="Remove frequency threshold filter"
                                        >
                                          <CloseIcon style={{ fontSize: 13 }} />
                                        </button>
                                      )}
                                    </div>
                                    <div className="flex flex-col gap-2 px-2 py-1.5 rounded bg-violet-50 dark:bg-violet-950/25 border border-violet-200 dark:border-violet-800/50 text-[11px]">
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <CompareArrowsIcon
                                          style={{ fontSize: 13 }}
                                          className="text-violet-600 dark:text-violet-400 shrink-0"
                                        />
                                        <label className="flex items-center gap-1.5 cursor-pointer">
                                          <input
                                            type="checkbox"
                                            checked={hasVC}
                                            onChange={(e) => {
                                              if (e.target.checked) {
                                                updatePatternValueCompare(domain, idx, defaultPatternValueCompare());
                                              } else {
                                                updatePatternValueCompare(domain, idx, null);
                                              }
                                            }}
                                            className="h-3 w-3 accent-violet-600"
                                          />
                                          <span className="text-muted-foreground whitespace-nowrap">Numeric threshold (capture group)</span>
                                        </label>
                                      </div>
                                      {hasVC && p.value_compare && (
                                        <div className="flex flex-wrap items-center gap-2 ml-6">
                                          <select
                                            value={p.value_compare.operator}
                                            onChange={(e) =>
                                              patchPatternValueCompare(domain, idx, {
                                                operator: e.target.value as ValueCompareOperator,
                                              })
                                            }
                                            className="text-xs px-1.5 py-0.5 rounded border border-border bg-background"
                                          >
                                            {VALUE_COMPARE_OPERATORS.map((opt) => (
                                              <option key={opt.value} value={opt.value}>
                                                {opt.label}
                                              </option>
                                            ))}
                                          </select>
                                          <span className="text-muted-foreground">value</span>
                                          <input
                                            type="number"
                                            step={p.value_compare.numeric_kind === "float" ? "any" : 1}
                                            value={Number.isFinite(p.value_compare.compare_to) ? p.value_compare.compare_to : ""}
                                            onChange={(e) => {
                                              const v = Number(e.target.value);
                                              patchPatternValueCompare(domain, idx, {
                                                compare_to: Number.isFinite(v) ? v : 0,
                                              });
                                            }}
                                            className="text-xs px-1.5 py-0.5 rounded border border-border bg-background w-[88px]"
                                          />
                                          <span className="text-muted-foreground">group</span>
                                          <input
                                            type="number"
                                            min={1}
                                            value={p.value_compare.capture_group ?? 1}
                                            onChange={(e) => {
                                              const g = Math.max(1, Math.floor(Number(e.target.value) || 1));
                                              patchPatternValueCompare(domain, idx, { capture_group: g });
                                            }}
                                            className="text-xs px-1.5 py-0.5 rounded border border-border bg-background w-[48px] text-center"
                                          />
                                          <select
                                            value={p.value_compare.numeric_kind ?? "int"}
                                            onChange={(e) =>
                                              patchPatternValueCompare(domain, idx, {
                                                numeric_kind: e.target.value === "float" ? "float" : "int",
                                              })
                                            }
                                            className="text-xs px-1.5 py-0.5 rounded border border-border bg-background"
                                          >
                                            <option value="int">int</option>
                                            <option value="float">float</option>
                                          </select>
                                          <button
                                            type="button"
                                            onClick={() => updatePatternValueCompare(domain, idx, null)}
                                            className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600"
                                            title="Remove numeric threshold"
                                          >
                                            <CloseIcon style={{ fontSize: 13 }} />
                                          </button>
                                        </div>
                                      )}
                                      {hasVC && (
                                        <p className="text-[10px] text-muted-foreground ml-6 leading-snug">
                                          Regex must include a capturing group (e.g. <code className="text-[10px]">Waninit_start=(\\d+)</code>).
                                          Workspace Overview reports per‑CPE pass/fail (0/1).
                                        </p>
                                      )}
                                    </div>
                                    <div className="flex flex-col gap-2 px-2 py-1.5 rounded bg-slate-50 dark:bg-slate-900/25 border border-slate-200 dark:border-slate-700/50 text-[11px]">
                                      <div className="flex items-center gap-2 flex-wrap">
                                        <InsertDriveFileIcon
                                          style={{ fontSize: 13 }}
                                          className="text-slate-600 dark:text-slate-400 shrink-0"
                                        />
                                        <span className="text-muted-foreground shrink-0">Scan log file</span>
                                        <select
                                          value={p.scan_filename ?? ""}
                                          onChange={(e) => updatePatternScanFilename(domain, idx, e.target.value)}
                                          className="text-xs px-1.5 py-0.5 rounded border border-border bg-background flex-1 min-w-[120px] max-w-[260px]"
                                        >
                                          <option value="">All files</option>
                                          {(scanFilesRaw ?? []).map((f) => (
                                            <option key={f.filename} value={f.filename}>
                                              {f.filename}
                                            </option>
                                          ))}
                                        </select>
                                        {hasScanFile && (
                                          <button
                                            type="button"
                                            onClick={() => updatePatternScanFilename(domain, idx, "")}
                                            className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                                            title="Clear file scope"
                                          >
                                            <CloseIcon style={{ fontSize: 13 }} />
                                          </button>
                                        )}
                                      </div>
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span className="text-muted-foreground shrink-0">
                                          Limit matches to time (UTC)
                                        </span>
                                        <input
                                          type="text"
                                          inputMode="numeric"
                                          placeholder="2025-03-27T00:00:00"
                                          title="UTC start (ISO local to UTC, no timezone suffix)"
                                          value={p.scan_time_range?.start ?? ""}
                                          onChange={(e) => patchScanTimeField(domain, idx, "start", e.target.value)}
                                          className="text-xs px-1 py-0.5 rounded border border-border bg-background font-mono w-[148px]"
                                        />
                                        <span className="text-muted-foreground">–</span>
                                        <input
                                          type="text"
                                          inputMode="numeric"
                                          placeholder="2025-03-28T00:00:00"
                                          title="UTC end (ISO local to UTC, no timezone suffix)"
                                          value={p.scan_time_range?.end ?? ""}
                                          onChange={(e) => patchScanTimeField(domain, idx, "end", e.target.value)}
                                          className="text-xs px-1 py-0.5 rounded border border-border bg-background font-mono w-[148px]"
                                        />
                                        {(!!p.scan_time_range?.start?.trim() || !!p.scan_time_range?.end?.trim()) && (
                                          <button
                                            type="button"
                                            onClick={() => updatePatternScanTimeRange(domain, idx, null)}
                                            className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                                            title="Clear time window"
                                          >
                                            <CloseIcon style={{ fontSize: 13 }} />
                                          </button>
                                        )}
                                      </div>
                                      <p className="text-[10px] text-muted-foreground">
                                        Ripgrep searches only the chosen basename for this pattern; timestamps filter
                                        parsed log times against your UTC window (ISO{' '}
                                        <code className="text-[9px]">YYYY-MM-DDTHH:mm:ss</code>). Partial entries are
                                        omitted on Save until both start and end are set. This window stays on the
                                        project only—it is not submitted to global NATCO patterns.
                                      </p>
                                    </div>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </>
                      )}
                      {/* Inline add-pattern row at the bottom */}
                      <button
                        onClick={() => addPattern(domain)}
                        className="flex items-center gap-1.5 w-full px-1 py-1.5 mt-1 text-[11px] text-muted-foreground hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/10 rounded transition-colors border border-dashed border-transparent hover:border-blue-300 dark:hover:border-blue-700"
                      >
                        <AddIcon style={{ fontSize: 14 }} />
                        Add pattern
                      </button>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {saveMutation.isSuccess && (
          <div className="px-4 py-1.5 bg-green-50 dark:bg-green-900/10 text-green-700 dark:text-green-400 text-[11px] border-t border-border">
            Patterns saved successfully.
          </div>
        )}
        {saveMutation.isError && (
          <div className="px-4 py-1.5 bg-red-50 dark:bg-red-900/10 text-red-700 dark:text-red-400 text-[11px] border-t border-border flex items-center gap-1">
            <ErrorIcon style={{ fontSize: 13 }} />
            {(saveMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Save failed"}
          </div>
        )}
        {syncMutation.isSuccess && (
          <div className="px-4 py-1.5 bg-purple-50 dark:bg-purple-900/10 text-purple-700 dark:text-purple-400 text-[11px] border-t border-border flex items-center gap-1">
            <SyncIcon style={{ fontSize: 13 }} />
            Synced {syncMutation.data?.data.synced || 0} global patterns. Remember to Save.
          </div>
        )}
        {submitMutation.isSuccess && (
          <div className="px-4 py-1.5 bg-amber-50 dark:bg-amber-900/10 text-amber-700 dark:text-amber-400 text-[11px] border-t border-border flex items-center gap-1">
            <PublishIcon style={{ fontSize: 13 }} />
            Patterns submitted for admin review.
          </div>
        )}
      </div>

      {/* NATCO Submission History — collapsible */}
      {hasNatco && mySubmissions && mySubmissions.length > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div
            className="px-4 py-2 border-b border-border bg-muted/30 flex items-center justify-between cursor-pointer hover:bg-muted/50 transition-colors"
            onClick={() => setSubmissionsCollapsed((v) => !v)}
          >
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <PublishIcon style={{ fontSize: 14, color: "#f59e0b" }} /> My Submissions
              <span className="ml-1 text-[10px] font-normal">
                ({mySubmissions.length} total{pendingCount > 0 ? `, ${pendingCount} pending` : ""})
              </span>
            </h3>
            <div className="flex items-center gap-2">
              {resolvedCount > 0 && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm(`Clear ${resolvedCount} approved/rejected submission(s)?`)) {
                      clearResolvedMutation.mutate();
                    }
                  }}
                  disabled={clearResolvedMutation.isPending}
                  className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors disabled:opacity-50"
                  title="Remove all approved and rejected submissions from history"
                >
                  <DeleteIcon style={{ fontSize: 12 }} />
                  Clear resolved ({resolvedCount})
                </button>
              )}
              {submissionsCollapsed
                ? <ExpandMoreIcon style={{ fontSize: 18 }} className="text-muted-foreground" />
                : <ExpandLessIcon style={{ fontSize: 18 }} className="text-muted-foreground" />}
            </div>
          </div>
          {!submissionsCollapsed && (
            <div className="divide-y divide-border">
              {mySubmissions.map((s) => (
                <div key={s.id} className="px-4 py-2 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      s.status === "approved" ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400" :
                      s.status === "rejected" ? "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400" :
                      "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
                    }`}>{s.status}</span>
                    <span className="font-medium">{s.domain}</span>
                    <span className="text-muted-foreground">{s.patterns.length} pattern{s.patterns.length !== 1 ? "s" : ""}</span>
                  </div>
                  <div className="flex items-center gap-2 text-muted-foreground">
                    {s.admin_comment && <span className="italic max-w-[200px] truncate" title={s.admin_comment}>"{s.admin_comment}"</span>}
                    <span>{s.created_at?.split("T")[0] || ""}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Submit to Global Dialog (diff-based) */}
      {showSubmitDialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border rounded-2xl shadow-lg w-full max-w-2xl max-h-[85vh] flex flex-col">
            {/* Dialog Header */}
            <div className="px-6 py-4 border-b border-border shrink-0">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <PublishIcon style={{ fontSize: 20, color: "#f59e0b" }} />
                Submit Changes to Global
              </h3>
              <p className="text-xs text-muted-foreground mt-1">
                Showing only new and modified patterns compared to the global NATCO configuration. Select which changes to submit for admin review.
              </p>
            </div>

            {/* Dialog Content */}
            <div className="flex-1 overflow-y-auto p-4">
              {diffLoading ? (
                <div className="flex items-center gap-2 justify-center py-12"><CircularProgress size={20} /> <span className="text-sm text-muted-foreground">Comparing against global...</span></div>
              ) : diffData && (() => {
                const allDomains = Object.entries(diffData);
                const hasChanges = allDomains.some(([, d]) => d.new.length > 0 || d.modified.length > 0);

                if (!hasChanges) {
                  return (
                    <div className="text-center py-12 text-muted-foreground">
                      <CheckBoxIcon style={{ fontSize: 40 }} className="mx-auto mb-2 opacity-50" />
                      <p className="text-sm font-medium">No changes detected</p>
                      <p className="text-xs mt-1">Your local patterns match the global configuration.</p>
                    </div>
                  );
                }

                return (
                  <div className="space-y-4">
                    {allDomains.map(([domain, diff]) => {
                      if (diff.new.length === 0 && diff.modified.length === 0) return null;
                      return (
                        <div key={domain} className="border border-border rounded-xl overflow-hidden">
                          <div className="px-4 py-2 bg-muted/30 flex items-center justify-between">
                            <span className="text-sm font-semibold">{domain}</span>
                            <span className="text-xs text-muted-foreground">
                              {diff.new.length > 0 && <span className="text-green-600 dark:text-green-400 mr-2">{diff.new.length} new</span>}
                              {diff.modified.length > 0 && <span className="text-blue-600 dark:text-blue-400">{diff.modified.length} modified</span>}
                            </span>
                          </div>
                          <div className="divide-y divide-border/50">
                            {/* New patterns */}
                            {diff.new.map((p) => {
                              const key = `${domain}::${p.regex}`;
                              const checked = !!selectedChanges[key];
                              return (
                                <label key={key} className="flex items-start gap-3 px-4 py-2 hover:bg-muted/20 cursor-pointer">
                                  <input type="checkbox" checked={checked} onChange={(e) => setSelectedChanges((prev) => ({ ...prev, [key]: e.target.checked }))} className="h-4 w-4 mt-0.5 accent-green-600 shrink-0" />
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="px-1.5 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded text-[10px] font-bold">NEW</span>
                                      <span className="text-xs font-medium truncate">{p.name}</span>
                                      {p.maintenance_window && (
                                        <span className="text-[10px] text-purple-600 dark:text-purple-400" title="Maintenance window">MW {p.maintenance_window.start}–{p.maintenance_window.end}</span>
                                      )}
                                      {p.reboot_proximity_minutes != null && (
                                        <span className="text-[10px] text-orange-600 dark:text-orange-400" title="Reboot proximity">±{p.reboot_proximity_minutes}m</span>
                                      )}
                                      {p.min_frequency_threshold != null && (
                                        <span className="text-[10px] text-green-600 dark:text-green-400" title="Frequency threshold">&gt;{p.min_frequency_threshold}</span>
                                      )}
                                      {p.scan_filename?.trim() && (
                                        <span className="text-[10px] text-sky-600 dark:text-sky-400" title="Scan log file">
                                          file:{p.scan_filename}
                                        </span>
                                      )}
                                    </div>
                                    <code className="text-[11px] font-mono text-muted-foreground block truncate mt-0.5">{p.regex}</code>
                                  </div>
                                </label>
                              );
                            })}
                            {/* Modified patterns */}
                            {diff.modified.map((p) => {
                              const key = `${domain}::${p.regex}`;
                              const checked = !!selectedChanges[key];
                              const mwStr = p.maintenance_window ? `${p.maintenance_window.start}–${p.maintenance_window.end}` : "none";
                              const gMwStr = p.global_maintenance_window ? `${p.global_maintenance_window.start}–${p.global_maintenance_window.end}` : "none";
                              const mwChanged = mwStr !== gMwStr;
                              const rpChanged = (p.reboot_proximity_minutes ?? null) !== (p.global_reboot_proximity_minutes ?? null);
                              const ftChanged = (p.min_frequency_threshold ?? null) !== (p.global_min_frequency_threshold ?? null);
                              const scanFileStr = p.scan_filename?.trim() || "none";
                              const gScanFileStr = p.global_scan_filename?.trim() || "none";
                              const scanFileChanged = scanFileStr !== gScanFileStr;
                              return (
                                <label key={key} className="flex items-start gap-3 px-4 py-2 hover:bg-muted/20 cursor-pointer">
                                  <input type="checkbox" checked={checked} onChange={(e) => setSelectedChanges((prev) => ({ ...prev, [key]: e.target.checked }))} className="h-4 w-4 mt-0.5 accent-primary shrink-0" />
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded text-[10px] font-bold">MODIFIED</span>
                                      <span className="text-xs font-medium truncate">{p.name}</span>
                                      {p.global_name && p.global_name !== p.name && (
                                        <span className="text-[10px] text-muted-foreground line-through truncate max-w-[120px]">{p.global_name}</span>
                                      )}
                                    </div>
                                    <code className="text-[11px] font-mono text-muted-foreground block truncate mt-0.5">{p.regex}</code>
                                    <div className="flex flex-wrap gap-2 mt-0.5">
                                      {p.global_enabled !== undefined && p.global_enabled !== p.enabled && (
                                        <span className="text-[10px] text-muted-foreground">enabled: {String(p.global_enabled)} → {String(p.enabled)}</span>
                                      )}
                                      {mwChanged && (
                                        <span className="text-[10px] text-purple-600 dark:text-purple-400">MW: {gMwStr} → {mwStr}</span>
                                      )}
                                      {rpChanged && (
                                        <span className="text-[10px] text-orange-600 dark:text-orange-400">Reboot: ±{p.global_reboot_proximity_minutes ?? "none"}m → ±{p.reboot_proximity_minutes ?? "none"}m</span>
                                      )}
                                      {ftChanged && (
                                        <span className="text-[10px] text-green-600 dark:text-green-400">Freq: &gt;{p.global_min_frequency_threshold ?? "none"} → &gt;{p.min_frequency_threshold ?? "none"}</span>
                                      )}
                                      {scanFileChanged && (
                                        <span className="text-[10px] text-sky-600 dark:text-sky-400">
                                          Scan file: {gScanFileStr} → {scanFileStr}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </div>

            {/* Dialog Footer */}
            <div className="px-6 py-4 border-t border-border shrink-0 space-y-3">
              <div>
                <label className="block text-xs font-medium mb-1">Comment (optional)</label>
                <textarea
                  value={submitComment}
                  onChange={(e) => setSubmitComment(e.target.value)}
                  placeholder="Describe what you're submitting..."
                  className="w-full px-3 py-2 border border-input rounded-lg bg-background resize-none text-sm"
                  rows={2}
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => submitMutation.mutate()}
                  disabled={selectedCount === 0 || submitMutation.isPending}
                  className="flex-1 py-2.5 bg-amber-600 text-white rounded-lg font-medium hover:bg-amber-700 disabled:opacity-50 flex items-center justify-center gap-1.5"
                >
                  {submitMutation.isPending ? <CircularProgress size={14} sx={{ color: "white" }} /> : <PublishIcon style={{ fontSize: 16 }} />}
                  Submit {selectedCount} Pattern{selectedCount !== 1 ? "s" : ""} for Review
                </button>
                <button onClick={() => { setShowSubmitDialog(false); setDiffData(null); setSelectedChanges({}); setSubmitComment(""); }} className="px-6 py-2.5 border border-border rounded-lg hover:bg-muted">
                  Cancel
                </button>
              </div>
              {submitMutation.isError && (
                <div className="text-xs text-red-600 flex items-center gap-1">
                  <ErrorIcon style={{ fontSize: 13 }} />
                  {(submitMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Submission failed"}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ====== SCAN CONFIGURATION ====== */}
      <div className="bg-card border border-border rounded-xl overflow-hidden min-w-0">
        <div className="px-4 py-2 border-b border-border bg-muted/30">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <PlayArrowIcon className="text-primary" style={{ fontSize: 14 }} /> Scan Configuration
          </h3>
        </div>
        <div className="p-4 space-y-4 min-w-0">
          {/* Row 1: Bucket + Run */}
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">
                Time Bucket
              </label>
              <select
                value={bucketMinutes}
                onChange={(e) => setBucketMinutes(Number(e.target.value))}
                className="text-xs px-3 py-1.5 rounded border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              >
                {BUCKET_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              {bucketMinutes === 0 && scanResult && (
                <div className="text-[10px] text-muted-foreground mt-1">
                  Using: {(() => {
                    let effectiveBucket: number;
                    if (visibleRange) {
                      const startMs = new Date(visibleRange.start).getTime();
                      const endMs = new Date(visibleRange.end).getTime();
                      const durationMs = endMs - startMs;
                      effectiveBucket = calculateBucketFromDuration(durationMs);
                    } else {
                      effectiveBucket = calculateAutoBucket(scanResult);
                    }
                    return BUCKET_OPTIONS.find(opt => opt.value === effectiveBucket)?.label || `${effectiveBucket} min`;
                  })()}{visibleRange ? " (zoomed)" : ""}
                </div>
              )}
            </div>

            <label className="flex items-center gap-1.5 cursor-pointer select-none" title="Exclude log lines with build-time timestamps (before NTP sync corrects the clock)">
              <input
                type="checkbox"
                checked={filterPreNtp}
                onChange={(e) => setFilterPreNtp(e.target.checked)}
                className="h-3.5 w-3.5 rounded accent-primary"
              />
              <span className="text-xs text-muted-foreground">Filter pre-NTP logs</span>
            </label>

            <label className="flex items-center gap-1.5 cursor-pointer select-none" title="Show only short reboots (brief power loss)">
              <input
                type="checkbox"
                checked={filterShortReboots}
                onChange={(e) => setFilterShortReboots(e.target.checked)}
                className="h-3.5 w-3.5 rounded accent-primary"
              />
              <span className="text-xs text-muted-foreground">Short reboots only</span>
            </label>

            <button
              onClick={() => scanMutation.mutate()}
              disabled={scanMutation.isPending || enabledCount === 0}
              className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {scanMutation.isPending ? (
                <CircularProgress size={14} sx={{ color: "white" }} />
              ) : (
                <PlayArrowIcon style={{ fontSize: 16 }} />
              )}
              Run Scan ({enabledCount} pattern{enabledCount !== 1 ? "s" : ""})
            </button>
          </div>

          {/* Row 2: Reboot range selector */}
          {reboots.length > 0 && (
            <div>
              <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1.5 flex items-center gap-1">
                <RestartAltIcon style={{ fontSize: 12 }} /> Reboot Range ({reboots.length} reboots detected)
              </label>

              <div className="flex flex-wrap items-end gap-4 mb-3">
                {/* Start reboot selector */}
                <div>
                  <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">
                    From (Start)
                  </label>
                  <select
                    value={startRebootIdx ?? ""}
                    onChange={(e) => {
                      const val = e.target.value === "" ? null : Number(e.target.value);
                      setStartRebootIdx(val);
                      setSliderValue(0);
                    }}
                    className="text-xs px-3 py-1.5 rounded border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-ring min-w-[220px]"
                  >
                    <option value="">-- Select --</option>
                    {reboots.map((r, idx) => {
                      const ra = patternRebootBoundaryAccent(r);
                      const ub = formatUptimeBeforeReboot(r.uptime_before_reboot_sec);
                      const bits = [ra.typeLabel, ub !== "—" ? `up ${ub}` : "", r.reason || "unknown"].filter(
                        Boolean,
                      );
                      return (
                        <option
                          key={idx}
                          value={idx}
                          disabled={endRebootIdx !== null && idx >= endRebootIdx}
                        >
                          Reboot #{idx + 1} — {r.timestamp.replace("T", " ")} — {bits.join(" · ")}
                        </option>
                      );
                    })}
                  </select>
                </div>

                {/* End reboot selector */}
                <div>
                  <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">
                    To (End)
                  </label>
                  <select
                    value={endRebootIdx ?? ""}
                    onChange={(e) => {
                      const val = e.target.value === "" ? null : Number(e.target.value);
                      setEndRebootIdx(val);
                      setSliderValue(0);
                    }}
                    className="text-xs px-3 py-1.5 rounded border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-ring min-w-[220px]"
                  >
                    <option value="">-- Select --</option>
                    {reboots.map((r, idx) => {
                      const ra = patternRebootBoundaryAccent(r);
                      const ub = formatUptimeBeforeReboot(r.uptime_before_reboot_sec);
                      const bits = [ra.typeLabel, ub !== "—" ? `up ${ub}` : "", r.reason || "unknown"].filter(
                        Boolean,
                      );
                      return (
                        <option
                          key={idx}
                          value={idx}
                          disabled={startRebootIdx !== null && idx <= startRebootIdx}
                        >
                          Reboot #{idx + 1} — {r.timestamp.replace("T", " ")} — {bits.join(" · ")}
                        </option>
                      );
                    })}
                  </select>
                </div>

                {/* Clear button */}
                {hasSelection && (
                  <button
                    onClick={() => {
                      setStartRebootIdx(null);
                      setEndRebootIdx(null);
                      setSliderValue(0);
                    }}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-background hover:bg-muted text-muted-foreground transition-colors"
                  >
                    Clear
                  </button>
                )}
              </div>

              {/* Slider + effective range (shown when both reboots selected) */}
              {hasSelection && selectedStart && selectedEnd && (() => {
                const durationMs = new Date(selectedEnd).getTime() - new Date(selectedStart).getTime();
                const viewingMs = durationMs - (sliderValue / 100) * durationMs;
                const viewingMin = Math.round(viewingMs / 60000);
                const viewingLabel =
                  viewingMin >= 1440
                    ? `${(viewingMin / 1440).toFixed(1)} days`
                    : viewingMin >= 60
                      ? `${(viewingMin / 60).toFixed(1)} hr`
                      : `${viewingMin} min`;

                return (
                  <div className="bg-muted/30 rounded-lg p-3 space-y-3">
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                      <span className="font-mono">{selectedStart}</span>
                      <span>{"\u2192"}</span>
                      <span className="font-mono">{selectedEnd}</span>
                    </div>

                    <div className="flex items-center gap-3">
                      <label className="text-[10px] text-muted-foreground font-semibold uppercase w-28 shrink-0">
                        Skip from start
                      </label>
                      <input
                        type="range"
                        min={0}
                        max={95}
                        value={sliderValue}
                        onChange={(e) => setSliderValue(Number(e.target.value))}
                        className="flex-1 accent-primary"
                      />
                      <span className="text-xs font-medium w-20 text-right">{sliderValue}%</span>
                    </div>

                    <div className="text-[10px] text-muted-foreground">
                      Viewing last <span className="font-semibold">{viewingLabel}</span> before end reboot
                    </div>

                    {chartFilterRange && (
                      <div className="text-[10px] text-muted-foreground">
                        Effective chart window:{" "}
                        <span className="font-mono font-medium">{chartFilterRange.start}</span>
                        {" \u2192 "}
                        <span className="font-mono font-medium">{chartFilterRange.end}</span>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          )}

          {scanMutation.isPending && (
            <div className="rounded-lg border border-primary/30 bg-muted/40 dark:bg-muted/30 p-3 space-y-2 min-w-0 max-w-full overflow-hidden box-border">
              <div className="w-full min-w-0 overflow-hidden rounded-full">
                <LinearProgress
                  sx={{ width: "100%", borderRadius: 9999 }}
                  variant={scanProgress != null && scanProgress.total > 0 ? "determinate" : "indeterminate"}
                  value={
                    scanProgress != null && scanProgress.total > 0
                      ? Math.min(
                          100,
                          Math.max(0, (100 * scanProgress.current) / scanProgress.total),
                        )
                      : 0
                  }
                />
              </div>
              <div className="flex flex-col items-center gap-1 text-center text-muted-foreground min-w-0 px-1">
                <span className="text-sm break-words max-w-full">
                  {scanProgress?.pattern_name
                    ? `Scanning: ${scanProgress.pattern_name}`
                    : scanStatus || "Scanning log files with ripgrep…"}
                </span>
                {scanProgress != null && scanProgress.total > 0 ? (
                  <span className="text-[11px] font-mono tabular-nums">
                    Pattern {scanProgress.current} / {scanProgress.total}
                  </span>
                ) : null}
              </div>
            </div>
          )}
        </div>

        {scanMutation.isError && (
          <div className="px-4 py-2 bg-red-50 dark:bg-red-900/10 text-red-700 dark:text-red-400 text-xs border-t border-border flex items-center gap-1.5">
            <ErrorIcon style={{ fontSize: 14 }} />
            {(scanMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Scan failed"}
          </div>
        )}
      </div>

      {/* ====== RESULTS CHART ====== */}
      {scanResult && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-border bg-muted/30 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                Pattern Occurrences Over Time
              </h3>
              <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                Device:{" "}
                <span className="text-foreground font-medium">
                  {scanResult.cpe_serial ?? cpeId ?? "—"}
                </span>
                {!scanResult.cpe_serial && cpeId ? (
                  <span className="text-muted-foreground/80"> (legacy scan — run again to stamp)</span>
                ) : null}
              </p>
              {scanResult.traces.some((t) => t.value_compare) && (
                <ul className="mt-1 text-[10px] text-muted-foreground space-y-0.5 list-none pl-0">
                  {scanResult.traces
                    .filter((t) => t.value_compare)
                    .map((t) => {
                      const v = t.value_compare!;
                      const agg =
                        v.aggregate_summary != null
                          ? `agg ${v.aggregate_summary}`
                          : "no agg";
                      return (
                        <li key={t.name} className="font-mono">
                          <span className="text-foreground">{t.name}</span>
                          {": "}
                          <span
                            className={
                              v.passed
                                ? "text-emerald-700 dark:text-emerald-400"
                                : "text-amber-800 dark:text-amber-400"
                            }
                          >
                            {v.passed ? "pass" : "fail"}
                          </span>
                          {` (${v.operator} ${v.compare_to}, ${agg}, ${v.values_extracted_unique_lines} uniq)`}
                        </li>
                      );
                    })}
                </ul>
              )}
            </div>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="font-semibold">
                {chartFilterRange
                  ? `${filteredMatchCount.toLocaleString()} / ${scanResult.total_matches.toLocaleString()} matches (filtered)`
                  : `${scanResult.total_matches.toLocaleString()} total matches`}
              </span>
              {scanResult.reboots.length > 0 && (
                <span className="flex items-center gap-1 text-red-600 dark:text-red-400 font-semibold">
                  <RestartAltIcon style={{ fontSize: 13 }} />
                  {scanResult.reboots.length} reboot(s)
                </span>
              )}
            </div>
          </div>

          {plotData.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <p className="text-sm">No matches found{chartFilterRange ? " in selected time range" : " with timestamps"}.</p>
              <p className="text-xs mt-1">Try adjusting your patterns or time range.</p>
            </div>
          ) : (
            <div className="p-2">
              <MemoizedPlot
                key={`plot-${startRebootIdx}-${endRebootIdx}-${sliderValue}-${bucketMinutes}`}
                data={plotData}
                layout={plotLayout}
                config={NO_TOOLBAR}
                style={{ width: "100%" }}
                onRelayout={(event: any) => {
                  // Track visible range when user zooms
                  if (bucketMinutes === 0 && event["xaxis.range[0]"] && event["xaxis.range[1]"]) {
                    setVisibleRange({
                      start: event["xaxis.range[0]"],
                      end: event["xaxis.range[1]"]
                    });
                  }
                  // Reset visible range on double-click (autorange)
                  if (event["xaxis.autorange"] === true) {
                    setVisibleRange(null);
                  }
                }}
              />
            </div>
          )}

          {scanResult.reboots.length > 0 && (
            <div className="px-4 py-3 border-t border-border">
              <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
                <RestartAltIcon style={{ fontSize: 12, color: "#d93025" }} /> Reboot Boundaries
              </h4>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                {scanResult.reboots.map((r, idx) => {
                  const accent = patternRebootBoundaryAccent(r);
                  const ub = formatUptimeBeforeReboot(r.uptime_before_reboot_sec);
                  return (
                    <div
                      key={idx}
                      className={cn(
                        "border border-border rounded-lg p-2 bg-muted/30 dark:bg-muted/45 ring-1 ring-inset",
                        accent.ringClass,
                      )}
                    >
                      <div className="flex flex-wrap items-center gap-1.5">
                        <p className="text-[11px] font-semibold text-foreground">#{idx + 1}</p>
                        <span
                          className={cn(
                            "text-[9px] font-bold uppercase tracking-wide rounded px-1 py-px",
                            accent.chipClass,
                          )}
                        >
                          {accent.typeLabel}
                        </span>
                        {r.is_short_reboot ? (
                          <span className="text-[9px] font-semibold uppercase tracking-wide rounded px-1 py-px border border-violet-500/45 bg-violet-500/12 text-violet-800 dark:text-violet-200">
                            Short
                          </span>
                        ) : null}
                      </div>
                      <p className="text-[10px] text-muted-foreground font-mono mt-1">{r.timestamp}</p>
                      <p className={cn("text-[10px] mt-1 truncate font-medium", accent.reasonClass)} title={r.reason}>
                        {r.reason || "unknown"}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-1">
                        Uptime before reboot:{" "}
                        <span className="tabular-nums font-medium text-foreground">{ub}</span>
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      </>}
    </div>
  );
}

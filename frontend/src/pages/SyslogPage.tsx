import { useState, useMemo, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { syslogApi, telemetryApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import Plot from "react-plotly.js";
import SyslogOverviewTab from "@/pages/SyslogOverviewTab";
import ArticleIcon from "@mui/icons-material/Article";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import RefreshIcon from "@mui/icons-material/Refresh";
import DownloadIcon from "@mui/icons-material/Download";
import CachedIcon from "@mui/icons-material/Cached";
import FilterListIcon from "@mui/icons-material/FilterList";
import ErrorIcon from "@mui/icons-material/Error";
import CircularProgress from "@mui/material/CircularProgress";

/* ================================================================ Types */
interface SyslogEvent {
  timestamp: string;
  event_id: string;
  category: string;
  module: string;
  thread_id: string;
  message: string;
  description: string;
  severity: string;
  metadata: Record<string, string>;
  line_number?: number;
}

interface RebootCorrelation {
  events_near_reboots: Array<{
    event: SyslogEvent;
    reboot: any;
    delta_minutes: number;
    relation: string;
  }>;
  reboot_timestamps: string[];
  reboot_window_minutes: number;
  reboot_window_after_minutes?: number;
}

interface SyslogData {
  device_info: { serial: string; cpe_id: string };
  summary: {
    total_lines: number;
    parsed_events: number;
    skipped_lines: number;
    event_type_counts: Record<string, number>;
    time_range: { first: string; last: string };
  };
  events: SyslogEvent[];
  reboot_correlation: RebootCorrelation;
  cached?: boolean;
}

const EVENTS_TABLE_PAGE_SIZE = 50;

/**
 * Consecutive log entries with the same Event ID are merged into one row if
 * each is at most this many ms after the previous in that run. A larger gap
 * starts a new row (new “burst”) so you keep chronological context and can
 * see which events occurred between or after bursts.
 */
const EVENT_BURST_GAP_MS = 600_000;

interface CollapsedEventGroup {
  representative: SyslogEvent;
  members: SyslogEvent[];
  count: number;
  firstTimestamp: string;
  lastTimestamp: string;
}

/* ================================================================ Helpers */
function parseEventTime(iso: string): number {
  const n = Date.parse(iso);
  return Number.isNaN(n) ? 0 : n;
}

/**
 * Sort by time, then merge consecutive events that share the same Event ID
 * when each is within `gapMs` of the previous event in that run. Different
 * event IDs stay separate rows; a time gap longer than `gapMs` splits the
 * same ID into another row so bursts stay distinct in timeline order.
 */
function collapseByEventIdWithinGap(events: SyslogEvent[], gapMs: number): CollapsedEventGroup[] {
  if (events.length === 0) return [];
  const sorted = [...events].sort((a, b) => {
    const d = parseEventTime(a.timestamp) - parseEventTime(b.timestamp);
    if (d !== 0) return d;
    return (a.line_number ?? 0) - (b.line_number ?? 0);
  });

  const out: CollapsedEventGroup[] = [];
  let current: CollapsedEventGroup | null = null;

  for (const ev of sorted) {
    const t = parseEventTime(ev.timestamp);
    if (
      current &&
      current.representative.event_id === ev.event_id &&
      t - parseEventTime(current.lastTimestamp) <= gapMs
    ) {
      current.members.push(ev);
      current.count = current.members.length;
      current.lastTimestamp = ev.timestamp;
    } else {
      if (current) out.push(current);
      current = {
        representative: ev,
        members: [ev],
        count: 1,
        firstTimestamp: ev.timestamp,
        lastTimestamp: ev.timestamp,
      };
    }
  }
  if (current) out.push(current);
  return out;
}

/** Sticky column widths (px) for aligned horizontal scroll */
const STICKY_W = { year: 52, month: 56, day: 44, time: 92 } as const;

function formatHumanTime(d: Date): string {
  return d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

function formatShortMonth(d: Date): string {
  return d.toLocaleDateString(undefined, { month: "short" });
}

function formatDayNum(d: Date): string {
  return String(d.getDate());
}

function formatYearNum(d: Date): string {
  return String(d.getFullYear());
}

/** Calendar day key in local timezone */
function calendarDayKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

interface DateSpanFlags {
  multiYear: boolean;
  multiMonth: boolean;
  multiDay: boolean;
}

function computeDateSpanFlags(groups: CollapsedEventGroup[]): DateSpanFlags {
  if (groups.length === 0) {
    return { multiYear: false, multiMonth: false, multiDay: false };
  }
  let minT = Infinity;
  let maxT = -Infinity;
  for (const g of groups) {
    const a = parseEventTime(g.firstTimestamp);
    const b = parseEventTime(g.lastTimestamp);
    minT = Math.min(minT, a, b);
    maxT = Math.max(maxT, a, b);
  }
  const dMin = new Date(minT);
  const dMax = new Date(maxT);
  const multiYear = dMin.getFullYear() !== dMax.getFullYear();
  const multiMonth =
    dMin.getFullYear() !== dMax.getFullYear() || dMin.getMonth() !== dMax.getMonth();
  const multiDay = calendarDayKey(dMin) !== calendarDayKey(dMax);
  return { multiYear, multiMonth, multiDay };
}

function formatGroupYearCell(g: CollapsedEventGroup): string {
  const d1 = new Date(parseEventTime(g.firstTimestamp));
  const d2 = new Date(parseEventTime(g.lastTimestamp));
  const y1 = formatYearNum(d1);
  const y2 = formatYearNum(d2);
  return y1 === y2 ? y1 : `${y1}–${y2}`;
}

function formatGroupMonthCell(g: CollapsedEventGroup): string {
  const d1 = new Date(parseEventTime(g.firstTimestamp));
  const d2 = new Date(parseEventTime(g.lastTimestamp));
  const m1 = formatShortMonth(d1);
  const m2 = formatShortMonth(d2);
  if (d1.getFullYear() === d2.getFullYear() && d1.getMonth() === d2.getMonth()) return m1;
  return `${m1}–${m2}`;
}

function formatGroupDayCell(g: CollapsedEventGroup): string {
  const d1 = new Date(parseEventTime(g.firstTimestamp));
  const d2 = new Date(parseEventTime(g.lastTimestamp));
  const day1 = formatDayNum(d1);
  const day2 = formatDayNum(d2);
  if (calendarDayKey(d1) === calendarDayKey(d2)) return day1;
  return `${day1}–${day2}`;
}

function GroupTimeCell({ group }: { group: CollapsedEventGroup }) {
  const d1 = new Date(parseEventTime(group.firstTimestamp));
  const d2 = new Date(parseEventTime(group.lastTimestamp));
  const t1 = formatHumanTime(d1);
  const t2 = formatHumanTime(d2);
  if (t1 === t2) {
    return <span className="block leading-tight">{t1}</span>;
  }
  return (
    <span className="block leading-tight whitespace-normal">
      <span className="block">{t1} –</span>
      <span className="block">{t2}</span>
    </span>
  );
}

function eventIdChartColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  const hue = h % 360;
  return `hsl(${hue} 62% 42%)`;
}

function getSeverityColor(severity: string): string {
  switch (severity.toLowerCase()) {
    case 'error':
      return 'border-red-300 bg-red-50 text-red-800 dark:border-red-700 dark:bg-red-900/20 dark:text-red-400';
    case 'warning':
      return 'border-yellow-300 bg-yellow-50 text-yellow-800 dark:border-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-400';
    case 'info':
      return 'border-blue-300 bg-blue-50 text-blue-800 dark:border-blue-700 dark:bg-blue-900/20 dark:text-blue-400';
    default:
      return 'border-gray-300 bg-gray-50 text-gray-700 dark:border-gray-600 dark:bg-gray-800/50 dark:text-gray-400';
  }
}

function getCategoryColor(category: string): string {
  const colors = {
    wifi: '#10b981',      // emerald
    parodus: '#f59e0b',   // amber  
    wan: '#3b82f6',       // blue
    dns: '#8b5cf6',       // violet
    network: '#06b6d4',   // cyan
    system: '#ef4444',    // red
    error: '#dc2626',     // red-600
    warning: '#d97706',   // amber-600
    info: '#2563eb',      // blue-600
    other: '#6b7280',     // gray-500
  };
  return colors[category as keyof typeof colors] || colors.other;
}

const NO_TOOLBAR = { displayModeBar: false } as const;

/* ================================================================ Component */
export default function SyslogPage() {
  const { projectId } = useProject();
  const { cpeId } = useCPE();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"cpe" | "overview">("cpe");
  const [reparsing, setReparsing] = useState(false);
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [filterSeverity, setFilterSeverity] = useState<string>("all");
  const [filterNearReboots, setFilterNearReboots] = useState(false);
  const [showTimelineChart, setShowTimelineChart] = useState(true);
  const [eventsSearchText, setEventsSearchText] = useState("");
  const [eventsEventIdFilter, setEventsEventIdFilter] = useState<string>("all");
  const [eventsSmartDateColumns, setEventsSmartDateColumns] = useState(true);
  const [eventsTablePage, setEventsTablePage] = useState(1);

  const { data: rawData, isLoading, isError, error } = useQuery<SyslogData>({
    queryKey: ["syslog", projectId, cpeId],
    queryFn: async () => {
      const response = await syslogApi.parse(projectId!, cpeId, false);
      return response.data.data;
    },
    enabled: !!projectId,
    retry: false,
    staleTime: 5 * 60 * 1000
  });

  // Fetch reboots from telemetry (for timeline markers)
  const { data: telemetryData } = useQuery({
    queryKey: ["telemetry-reboots", projectId, cpeId],
    queryFn: async () => {
      try {
        const res = await telemetryApi.parse(projectId!, cpeId, false);
        return res.data?.reboot_timeline?.all_events ?? [];
      } catch {
        return [];
      }
    },
    enabled: !!projectId && !!cpeId,
    staleTime: 30 * 60 * 1000,
  });

  const handleReparse = async () => {
    setReparsing(true);
    try {
      const res = await syslogApi.parse(projectId!, cpeId, true);
      qc.setQueryData(["syslog", projectId, cpeId], res.data.data);
    } catch (err) {
      console.error('Reparse failed:', err);
    }
    setReparsing(false);
  };

  const handleExportCsv = async () => {
    try {
      const response = await syslogApi.exportCsv(projectId!, cpeId);
      const blob = new Blob([response.data]);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `syslog_${cpeId || projectId}_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed:', err);
      alert('Failed to export CSV. Please try again.');
    }
  };

  // Filter events based on current filters
  const filteredEvents = useMemo(() => {
    if (!rawData?.events || !Array.isArray(rawData.events)) {
      return [];
    }

    let events = rawData.events;

    if (filterCategory !== "all") {
      events = events.filter(e => e.category === filterCategory);
    }

    if (filterSeverity !== "all") {
      events = events.filter(e => e.severity === filterSeverity);
    }

    if (filterNearReboots && rawData.reboot_correlation?.events_near_reboots) {
      const nearRebootEventIds = new Set(
        rawData.reboot_correlation.events_near_reboots.map(r =>
          `${r.event.timestamp}_${r.event.event_id}_${r.event.line_number || 0}`
        )
      );
      events = events.filter(e =>
        nearRebootEventIds.has(`${e.timestamp}_${e.event_id}_${e.line_number || 0}`)
      );
    }

    return events;
  }, [rawData, filterCategory, filterSeverity, filterNearReboots]);

  const collapsedEventGroups = useMemo(
    () => collapseByEventIdWithinGap(filteredEvents, EVENT_BURST_GAP_MS),
    [filteredEvents]
  );

  const eventIdsForTableFilter = useMemo(() => {
    const s = new Set<string>();
    for (const e of filteredEvents) s.add(e.event_id);
    return Array.from(s).sort();
  }, [filteredEvents]);

  const tableFilteredCollapsedGroups = useMemo(() => {
    const q = eventsSearchText.trim().toLowerCase();
    return collapsedEventGroups.filter((g) => {
      const rep = g.representative;
      if (eventsEventIdFilter !== "all" && rep.event_id !== eventsEventIdFilter) return false;
      if (q) {
        const hay = `${rep.description} ${rep.event_id} ${rep.module} ${rep.message} ${rep.category}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [collapsedEventGroups, eventsSearchText, eventsEventIdFilter]);

  const eventsGroupCount = tableFilteredCollapsedGroups.length;
  /** Pagination is by collapsed table rows (event-ID bursts), not raw syslog lines. */
  const eventsTableTotalPages =
    eventsGroupCount === 0 ? 0 : Math.ceil(eventsGroupCount / EVENTS_TABLE_PAGE_SIZE);
  const eventsTablePageClamped =
    eventsTableTotalPages === 0
      ? 0
      : Math.min(Math.max(1, eventsTablePage), eventsTableTotalPages);
  const eventsTablePageStart =
    eventsTableTotalPages === 0 ? 0 : (eventsTablePageClamped - 1) * EVENTS_TABLE_PAGE_SIZE;
  const paginatedTableGroups = useMemo(
    () =>
      tableFilteredCollapsedGroups.slice(
        eventsTablePageStart,
        eventsTablePageStart + EVENTS_TABLE_PAGE_SIZE
      ),
    [tableFilteredCollapsedGroups, eventsTablePageStart]
  );

  useEffect(() => {
    setEventsTablePage(1);
  }, [
    filterCategory,
    filterSeverity,
    filterNearReboots,
    eventsSearchText,
    eventsEventIdFilter,
    cpeId,
    projectId,
  ]);

  useEffect(() => {
    if (eventsTableTotalPages === 0) {
      setEventsTablePage(1);
      return;
    }
    setEventsTablePage((p) => Math.min(Math.max(1, p), eventsTableTotalPages));
  }, [eventsTableTotalPages]);

  const dateSpanFlags = useMemo(
    () => computeDateSpanFlags(tableFilteredCollapsedGroups),
    [tableFilteredCollapsedGroups]
  );

  const showYearCol = eventsSmartDateColumns ? dateSpanFlags.multiYear : true;
  const showMonthCol = eventsSmartDateColumns ? dateSpanFlags.multiMonth : true;
  const showDayCol = eventsSmartDateColumns ? dateSpanFlags.multiDay : true;

  const stickyDateOffsets = useMemo(() => {
    let acc = 0;
    const year = showYearCol ? acc : null;
    if (showYearCol) acc += STICKY_W.year;
    const month = showMonthCol ? acc : null;
    if (showMonthCol) acc += STICKY_W.month;
    const day = showDayCol ? acc : null;
    if (showDayCol) acc += STICKY_W.day;
    const time = acc;
    acc += STICKY_W.time;
    return { year, month, day, time, totalWidth: acc };
  }, [showYearCol, showMonthCol, showDayCol]);

  const timelineEventIds = useMemo(
    () => [...new Set(filteredEvents.map((e) => e.event_id))].sort(),
    [filteredEvents]
  );

  const timelineChartHeight = useMemo(
    () => Math.min(1400, Math.max(360, timelineEventIds.length * 26 + 120)),
    [timelineEventIds.length]
  );

  // Build timeline chart data: one swim lane per event ID
  const timelineChartData = useMemo(() => {
    if (!filteredEvents.length || !showTimelineChart) return [];

    return timelineEventIds.map((eventId) => {
      const idEvents = filteredEvents.filter((e) => e.event_id === eventId);
      const color = eventIdChartColor(eventId);
      return {
        x: idEvents.map((e) => e.timestamp),
        y: idEvents.map(() => eventId),
        mode: "markers" as const,
        type: "scatter" as const,
        name: eventId,
        marker: {
          size: 7,
          color,
          line: { width: 0.5, color: "rgba(255,255,255,0.35)" },
        },
        text: idEvents.map(
          (e) => `${e.description} · ${e.category} · ${e.severity}`
        ),
        hovertemplate:
          "<b>%{y}</b><br>%{text}<br><b>%{x}</b><extra></extra>",
      };
    });
  }, [filteredEvents, showTimelineChart, timelineEventIds]);

  const data = rawData ?? null;

  if (!projectId || !cpeId) {
    return (
      <div className="p-4 max-w-full overflow-y-auto">
        <div className="bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
          <p className="text-blue-800 dark:text-blue-200">
            Please select a CPE from the dropdown in the sidebar to view Syslog data
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4 max-w-full overflow-y-auto">
      {/* ========== Header ========== */}
      <div className="flex items-center gap-2 flex-wrap">
        <ArticleIcon style={{ fontSize: 24, color: "#1a73e8" }} />
        <h2 className="text-lg font-semibold">Syslog Analysis</h2>
        {activeTab === "cpe" && data?.cached && (
          <span className="inline-flex items-center gap-1 text-[10px] text-blue-600 bg-blue-50 border border-blue-200 rounded px-1.5 py-0.5 dark:text-blue-400 dark:bg-blue-900/20 dark:border-blue-700">
            <CachedIcon style={{ fontSize: 12 }} /> cached
          </span>
        )}
        {activeTab === "cpe" && data?.summary && (
          <span className="text-[11px] text-muted-foreground">
            {(data.summary?.parsed_events || 0).toLocaleString()} events parsed | {data.summary?.time_range?.first?.slice(0, 19) || 'N/A'} — {data.summary?.time_range?.last?.slice(0, 19) || 'N/A'}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {activeTab === "cpe" && data && (
            <>
              <button
                onClick={handleExportCsv}
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border hover:bg-muted transition-colors"
                title="Export syslog events to CSV"
              >
                <DownloadIcon style={{ fontSize: 15 }} />
                Export CSV
              </button>
              <button
                onClick={handleReparse}
                disabled={reparsing || isLoading}
                className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border hover:bg-muted transition-colors disabled:opacity-50"
                title="Re-parse from raw syslog.txt"
              >
                {reparsing ? <CircularProgress size={14} /> : <RefreshIcon style={{ fontSize: 15 }} />}
                Re-parse
              </button>
            </>
          )}
        </div>
      </div>

      {/* ========== Tab Navigation ========== */}
      <div className="flex items-center gap-1 border-b border-border">
        <button
          onClick={() => setActiveTab("cpe")}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "cpe"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
          }`}
        >
          <ArticleIcon style={{ fontSize: 16 }} />
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

      {/* ========== Cross-CPE Overview Tab ========== */}
      {activeTab === "overview" && <SyslogOverviewTab />}

      {/* ========== CPE Analysis Tab ========== */}
      {activeTab === "cpe" && (
        <>
          {isLoading && (
            <div className="flex items-center gap-3 justify-center py-16 text-muted-foreground">
              <CircularProgress size={24} />
              <span className="text-sm">Parsing syslog data...</span>
            </div>
          )}
          
          {isError && (
            <div className="p-4 bg-destructive/10 text-destructive rounded-xl text-sm flex items-center gap-2">
              <ErrorIcon style={{ fontSize: 18 }} />
              {(error as { response?: { data?: { error?: string } } })?.response?.data?.error || 
               (error as { message?: string })?.message || 
               "Error parsing syslog"}
            </div>
          )}

          {data && (
            <>
              {/* ========== Summary Cards ========== */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="bg-card border border-border rounded-xl p-3">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Total Events</p>
                  <p className="text-xl font-bold text-foreground">{(data.summary?.parsed_events || 0).toLocaleString()}</p>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    {(data.summary?.skipped_lines || 0).toLocaleString()} lines skipped
                  </p>
                </div>
                
                <div className="bg-card border border-border rounded-xl p-3">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Categories</p>
                  <p className="text-xl font-bold text-foreground">{Object.keys(data.summary?.event_type_counts || {}).length}</p>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Top: {Object.entries(data.summary?.event_type_counts || {}).sort(([,a], [,b]) => b - a)[0]?.[0] || 'N/A'}
                  </p>
                </div>

                <div className="bg-card border border-border rounded-xl p-3">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Near Reboots</p>
                  <p className="text-xl font-bold text-foreground">{data.reboot_correlation?.events_near_reboots?.length || 0}</p>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    ≤{data.reboot_correlation?.reboot_window_minutes ?? 60} min before reboot
                  </p>
                </div>

                <div className="bg-card border border-border rounded-xl p-3">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Time Span</p>
                  <p className="text-sm font-bold text-foreground">
                    {data.summary?.time_range?.first && data.summary?.time_range?.last
                      ? Math.round((new Date(data.summary?.time_range?.last!).getTime() - new Date(data.summary?.time_range?.first!).getTime()) / (1000 * 60 * 60 * 24))
                      : 0} days
                  </p>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    {data.summary?.time_range?.first?.slice(5, 10) || 'N/A'} — {data.summary?.time_range?.last?.slice(5, 10) || 'N/A'}
                  </p>
                </div>
              </div>

              {/* ========== Filters ========== */}
              <div className="bg-card border border-border rounded-xl p-4">
                <div className="flex items-center gap-4 flex-wrap">
                  <div className="flex items-center gap-1.5">
                    <FilterListIcon style={{ fontSize: 16 }} className="text-muted-foreground" />
                    <span className="text-sm font-medium">Filters:</span>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <label className="text-sm font-medium">Category:</label>
                    <select 
                      value={filterCategory} 
                      onChange={(e) => setFilterCategory(e.target.value)} 
                      className="text-sm px-3 py-1.5 rounded border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                    >
                      <option value="all">All ({data.summary?.parsed_events || 0})</option>
                      {Object.entries(data.summary?.event_type_counts || {})
                        .sort(([,a], [,b]) => b - a)
                        .map(([cat, count]) => (
                          <option key={cat} value={cat}>{cat} ({count})</option>
                        ))}
                    </select>
                  </div>

                  <div className="flex items-center gap-2">
                    <label className="text-sm font-medium">Severity:</label>
                    <select 
                      value={filterSeverity} 
                      onChange={(e) => setFilterSeverity(e.target.value)} 
                      className="text-sm px-3 py-1.5 rounded border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                    >
                      <option value="all">All</option>
                      <option value="error">Error</option>
                      <option value="warning">Warning</option>
                      <option value="info">Info</option>
                    </select>
                  </div>
                  
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input 
                      type="checkbox" 
                      checked={filterNearReboots} 
                      onChange={(e) => setFilterNearReboots(e.target.checked)}
                      className="rounded border-border"
                    />
                    Show only events near reboots
                  </label>

                  <label className="flex items-center gap-2 text-sm cursor-pointer ml-auto">
                    <input 
                      type="checkbox" 
                      checked={showTimelineChart} 
                      onChange={(e) => setShowTimelineChart(e.target.checked)}
                      className="rounded border-border"
                    />
                    Show timeline chart
                  </label>
                </div>
              </div>

              {/* ========== Interactive Timeline Chart ========== */}
              {showTimelineChart && (filteredEvents?.length || 0) > 0 && (
                <div className="bg-card border border-border rounded-xl overflow-hidden">
                  <div className="px-4 py-2 border-b border-border bg-muted/30">
                    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Event timeline — {timelineEventIds.length} event ID
                      {timelineEventIds.length === 1 ? "" : "s"},{" "}
                      {filteredEvents?.length || 0} point{filteredEvents?.length === 1 ? "" : "s"}
                    </h3>
                  </div>
                  <div className="p-4">
                    <Plot
                      data={timelineChartData}
                      layout={{
                        height: timelineChartHeight,
                        hovermode: 'closest',
                        xaxis: { 
                          title: { text: 'Time' },
                          tickfont: { size: 10 },
                          type: 'date',
                        },
                        yaxis: { 
                          title: { text: 'Event ID' }, 
                          type: 'category',
                          tickfont: { size: 10 },
                          automargin: true,
                        },
                        margin: { l: 96, r: 15, t: 5, b: 50 },
                        paper_bgcolor: "transparent",
                        plot_bgcolor: "transparent",
                        showlegend: timelineEventIds.length <= 10,
                        legend: {
                          orientation: "h",
                          y: -0.18,
                          x: 0.5,
                          xanchor: "center",
                          font: { size: 9 },
                        },
                        shapes: telemetryData?.map((e: any) => ({
                          type: 'line',
                          x0: e.time,
                          x1: e.time,
                          y0: 0,
                          y1: 1,
                          yref: 'paper',
                          line: { color: '#d93025', width: 2, dash: 'dot' }
                        })) || [],
                        annotations: telemetryData?.map((e: any) => {
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
                        }) || []
                      }}
                      config={NO_TOOLBAR}
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>
              )}

              {/* ========== Event Table ========== */}
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border bg-muted/30">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {`Events — ${tableFilteredCollapsedGroups.length.toLocaleString()} group${tableFilteredCollapsedGroups.length === 1 ? "" : "s"} in the table · ${(filteredEvents?.length ?? 0).toLocaleString()} raw events after filters`}
                  </h3>
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    Same <span className="font-medium text-foreground">Event ID</span> is merged into one row only when occurrences follow one another within{" "}
                    <span className="font-medium text-foreground">{EVENT_BURST_GAP_MS / 60_000} minutes</span> (chronological order). A longer gap or a different ID starts a new row so you can correlate what happens between bursts.{" "}
                    {eventsSmartDateColumns
                      ? "Date columns (year / month / day) appear only when the visible rows span multiple years, months, or calendar days."
                      : "Full date columns are always shown."}
                  </p>
                </div>
                <div className="px-4 py-2 border-b border-border bg-muted/10 flex flex-wrap items-center gap-3">
                  <label className="text-xs font-medium text-muted-foreground shrink-0">Table:</label>
                  <input
                    type="search"
                    value={eventsSearchText}
                    onChange={(e) => setEventsSearchText(e.target.value)}
                    placeholder="Search description, event id, module…"
                    className="text-sm px-3 py-1.5 rounded border border-border bg-background min-w-[12rem] max-w-md flex-1 focus:outline-none focus:ring-2 focus:ring-primary/50"
                    aria-label="Filter events table by text"
                  />
                  <div className="flex items-center gap-2">
                    <label htmlFor="syslog-events-event-id" className="text-xs font-medium whitespace-nowrap">
                      Event ID:
                    </label>
                    <select
                      id="syslog-events-event-id"
                      value={eventsEventIdFilter}
                      onChange={(e) => setEventsEventIdFilter(e.target.value)}
                      className="text-sm px-3 py-1.5 rounded border border-border bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 max-w-[12rem]"
                    >
                      <option value="all">All ({eventIdsForTableFilter.length})</option>
                      {eventIdsForTableFilter.map((id) => (
                        <option key={id} value={id}>
                          {id}
                        </option>
                      ))}
                    </select>
                  </div>
                  <label className="flex items-center gap-2 text-xs cursor-pointer whitespace-nowrap">
                    <input
                      type="checkbox"
                      checked={eventsSmartDateColumns}
                      onChange={(e) => setEventsSmartDateColumns(e.target.checked)}
                      className="rounded border-border"
                    />
                    Smart date columns
                  </label>
                </div>
                <div
                  className="max-h-[min(70vh,640px)] overflow-auto max-w-full [scrollbar-width:thin]"
                  style={{ WebkitOverflowScrolling: "touch" }}
                >
                  <table className="min-w-max w-full text-sm border-separate border-spacing-0">
                    <thead className="bg-muted/20 [&_th]:top-0">
                      <tr>
                        {showYearCol && (
                          <th
                            className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-30 border-r border-border/60 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)] bg-muted/20"
                            style={{ left: stickyDateOffsets.year ?? 0, minWidth: STICKY_W.year }}
                          >
                            Year
                          </th>
                        )}
                        {showMonthCol && (
                          <th
                            className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-20 border-r border-border/60 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)] bg-muted/20"
                            style={{ left: stickyDateOffsets.month ?? 0, minWidth: STICKY_W.month }}
                          >
                            Month
                          </th>
                        )}
                        {showDayCol && (
                          <th
                            className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-20 border-r border-border/60 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)] bg-muted/20"
                            style={{ left: stickyDateOffsets.day ?? 0, minWidth: STICKY_W.day }}
                          >
                            Day
                          </th>
                        )}
                        <th
                          className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-20 border-r border-border/60 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)] bg-muted/20"
                          style={{ left: stickyDateOffsets.time, minWidth: STICKY_W.time }}
                        >
                          Time
                        </th>
                        <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-30 bg-muted/20">
                          Count
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-30 bg-muted/20">
                          Category
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-30 bg-muted/20">
                          Event ID
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-30 bg-muted/20">
                          Severity
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap min-w-[14rem] sticky top-0 z-30 bg-muted/20">
                          Description
                        </th>
                        <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap sticky top-0 z-30 bg-muted/20">
                          Near Reboot
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {paginatedTableGroups.map((group, idx) => {
                        const event = group.representative;
                        const rowIndex = eventsTablePageStart + idx;
                        let nearReboot: RebootCorrelation["events_near_reboots"][number] | undefined;
                        for (const ev of group.members) {
                          const r = data?.reboot_correlation?.events_near_reboots?.find(
                            (x) =>
                              x.event.timestamp === ev.timestamp &&
                              x.event.event_id === ev.event_id &&
                              (x.event.line_number || 0) === (ev.line_number || 0)
                          );
                          if (r) {
                            nearReboot = r;
                            break;
                          }
                        }
                        const timeTitle = `${group.firstTimestamp} → ${group.lastTimestamp}`;
                        return (
                          <tr
                            key={`${rowIndex}_${group.firstTimestamp}_${event.event_id}_${group.count}`}
                            className="group border-t border-border/50 hover:bg-muted/20"
                          >
                            {showYearCol && (
                              <td
                                className="px-3 py-2 font-mono text-xs text-muted-foreground whitespace-nowrap sticky z-[1] border-r border-border/60 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)] bg-card group-hover:bg-muted/20"
                                style={{ left: stickyDateOffsets.year ?? 0, minWidth: STICKY_W.year }}
                                title={timeTitle}
                              >
                                {formatGroupYearCell(group)}
                              </td>
                            )}
                            {showMonthCol && (
                              <td
                                className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap sticky z-[1] border-r border-border/60 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)] bg-card group-hover:bg-muted/20"
                                style={{ left: stickyDateOffsets.month ?? 0, minWidth: STICKY_W.month }}
                                title={timeTitle}
                              >
                                {formatGroupMonthCell(group)}
                              </td>
                            )}
                            {showDayCol && (
                              <td
                                className="px-3 py-2 font-mono text-xs text-muted-foreground whitespace-nowrap sticky z-[1] border-r border-border/60 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)] bg-card group-hover:bg-muted/20"
                                style={{ left: stickyDateOffsets.day ?? 0, minWidth: STICKY_W.day }}
                                title={timeTitle}
                              >
                                {formatGroupDayCell(group)}
                              </td>
                            )}
                            <td
                              className="px-3 py-2 font-mono text-xs text-muted-foreground align-top sticky z-[1] border-r border-border/60 shadow-[2px_0_4px_-2px_rgba(0,0,0,0.08)] bg-card group-hover:bg-muted/20"
                              style={{ left: stickyDateOffsets.time, minWidth: STICKY_W.time }}
                              title={timeTitle}
                            >
                              <GroupTimeCell group={group} />
                            </td>
                            <td className="px-3 py-2 text-right whitespace-nowrap">
                              {group.count > 1 ? (
                                <span
                                  className="inline-flex items-center justify-center min-w-[2rem] px-2 py-0.5 rounded-full text-xs font-semibold bg-primary/15 text-primary border border-primary/25"
                                  title={`${group.count} occurrences in this burst (same Event ID, each within ${EVENT_BURST_GAP_MS / 60_000} min of the previous)`}
                                >
                                  ×{group.count}
                                </span>
                              ) : (
                                <span className="text-muted-foreground text-xs">1</span>
                              )}
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              <span
                                className="px-2 py-0.5 rounded text-xs font-medium"
                                style={{
                                  backgroundColor: `${getCategoryColor(event.category)}15`,
                                  color: getCategoryColor(event.category),
                                  borderColor: `${getCategoryColor(event.category)}30`,
                                }}
                              >
                                {event.category}
                              </span>
                            </td>
                            <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">{event.event_id}</td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              <span
                                className={`px-2 py-0.5 rounded text-xs font-medium ${getSeverityColor(event.severity)}`}
                              >
                                {event.severity}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-xs max-w-md min-w-[12rem] whitespace-nowrap overflow-hidden text-ellipsis" title={event.description}>
                              {event.description}
                            </td>
                            <td className="px-3 py-2 text-xs whitespace-nowrap">
                              {nearReboot && (
                                <span className="text-red-600 dark:text-red-400 font-medium">
                                  {nearReboot.delta_minutes}min {nearReboot.relation}
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 border-t border-border bg-muted/10 text-xs text-muted-foreground">
                  <span className="min-w-0">
                    {eventsTableTotalPages === 0 ? (
                      <span>No event groups match the current table filters.</span>
                    ) : (
                      <>
                        Page{" "}
                        <span className="font-semibold text-foreground">{eventsTablePageClamped}</span> of{" "}
                        <span className="font-semibold text-foreground">{eventsTableTotalPages}</span>
                        {" · "}
                        <span className="font-semibold text-foreground">
                          {`${eventsTablePageStart + 1}–${Math.min(
                            eventsTablePageStart + paginatedTableGroups.length,
                            eventsGroupCount
                          )}`}
                        </span>{" "}
                        of{" "}
                        <span className="font-semibold text-foreground">
                          {eventsGroupCount.toLocaleString()}
                        </span>{" "}
                        <span className="text-muted-foreground">
                          table row{eventsGroupCount === 1 ? "" : "s"}{" "}
                          <span className="opacity-80">(collapsed bursts, {EVENTS_TABLE_PAGE_SIZE} per page)</span>
                        </span>
                        {" · "}
                        <span className="font-semibold text-foreground">
                          {(filteredEvents?.length ?? 0).toLocaleString()}
                        </span>{" "}
                        raw events after filters
                      </>
                    )}
                  </span>
                  <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                    <button
                      type="button"
                      disabled={eventsTableTotalPages === 0 || eventsTablePageClamped <= 1}
                      onClick={() => setEventsTablePage(1)}
                      className="px-2.5 py-1 rounded border border-border bg-background text-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:bg-muted/80 text-[11px] font-medium"
                    >
                      First
                    </button>
                    <button
                      type="button"
                      disabled={eventsTableTotalPages === 0 || eventsTablePageClamped <= 1}
                      onClick={() => setEventsTablePage((p) => Math.max(1, p - 1))}
                      className="px-2.5 py-1 rounded border border-border bg-background text-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:bg-muted/80 text-[11px] font-medium"
                    >
                      Prev
                    </button>
                    <button
                      type="button"
                      disabled={
                        eventsTableTotalPages === 0 ||
                        eventsTablePageClamped >= eventsTableTotalPages
                      }
                      onClick={() =>
                        setEventsTablePage((p) =>
                          eventsTableTotalPages === 0
                            ? 1
                            : Math.min(eventsTableTotalPages, p + 1)
                        )
                      }
                      className="px-2.5 py-1 rounded border border-border bg-background text-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:bg-muted/80 text-[11px] font-medium"
                    >
                      Next
                    </button>
                    <button
                      type="button"
                      disabled={
                        eventsTableTotalPages === 0 ||
                        eventsTablePageClamped >= eventsTableTotalPages
                      }
                      onClick={() => setEventsTablePage(eventsTableTotalPages)}
                      className="px-2.5 py-1 rounded border border-border bg-background text-foreground disabled:opacity-40 disabled:cursor-not-allowed hover:bg-muted/80 text-[11px] font-medium"
                    >
                      Last
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
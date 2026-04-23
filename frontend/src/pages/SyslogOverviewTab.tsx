import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { syslogApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";
import Plot from "react-plotly.js";
import ArticleIcon from "@mui/icons-material/Article";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ErrorIcon from "@mui/icons-material/Error";
import RefreshIcon from "@mui/icons-material/Refresh";
import CircularProgress from "@mui/material/CircularProgress";

/* ================================================================ Types */
interface CrossCpeSyslogData {
  summary: {
    total_cpes: number;
    cpes_with_syslog: number;
    total_events: number;
    parsing_errors_count: number;
  };
  event_category_totals: Record<string, number>;
  top_event_ids: Array<{ event_id: string; count: number }>;
  cpe_comparison: Array<{
    cpe_id: string;
    total_events: number;
    event_counts: Record<string, number>;
    time_range?: { first: string; last: string };
    events_near_reboots?: number;
    total_reboots?: number;
  }>;
  parsing_errors: string[];
}

interface ChannelChangeDistributionData {
  summary: {
    total_cpes: number;
    cpes_with_syslog: number;
    cpes_with_channel_switches: number;
    total_channel_switches: number;
    parsing_errors_count: number;
  };
  by_reason_bucket: Array<{
    bucket: string;
    count: number;
    percentage: number;
  }>;
  by_radio_interface: Array<{
    radio: string;
    count: number;
  }>;
  by_radio_and_bucket: Record<string, Record<string, number>>;
  top_channels: Array<{
    channel: number;
    count: number;
  }>;
  top_transitions: Array<{
    transition: string;
    count: number;
  }>;
  bandwidth_distribution: Array<{
    bandwidth_mhz: number;
    count: number;
  }>;
  /** Per-radio bandwidth slices; omit on older API responses. */
  bandwidth_by_radio?: Record<
    string,
    Array<{
      bandwidth_mhz: number;
      count: number;
    }>
  >;
  cpe_breakdown: Array<{
    cpe_id: string;
    total_channel_switches: number;
    by_reason_bucket: Record<string, number>;
    by_radio_interface: Record<string, number>;
    top_channels?: Array<[number, number]>;
    top_transitions?: Array<[string, number]>;
  }>;
  parsing_errors: string[];
}

/* ================================================================ Helper Functions */
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

/** W018 radar used to be labeled 5GHz; normalize for chart and legacy cache. */
function formatRadioInterfaceForChart(radio: string): string {
  if (radio === "5GHz") return "RADAR";
  return radio;
}

function getReasonBucketLabel(bucket: string): string {
  const labels: Record<string, string> = {
    airties_cloud: 'Airties Cloud',
    radar: 'Radar/DFS',
    txop: 'TXOP (Busy)',
    cs_timer: 'CS Timer (Periodic)',
    interference: 'Interference',
    acs_policy: 'ACS Policy',
    unknown: 'Unknown',
    other: 'Other',
  };
  return labels[bucket] || bucket;
}

const RADIO_STACK_COLORS: Record<string, string> = {
  wl0: '#10b981',
  wl1: '#3b82f6',
  wl2: '#8b5cf6',
  RADAR: '#ef4444',
  unknown: '#64748b',
};

function getRadioStackColor(radio: string): string {
  return RADIO_STACK_COLORS[radio] ?? '#94a3b8';
}

/** Merge raw API keys (e.g. legacy 5GHz → RADAR) for reason × radio breakdown. */
function mergeRadioAndBucket(
  byRadioAndBucket: Record<string, Record<string, number>>
): Record<string, Record<string, number>> {
  const merged: Record<string, Record<string, number>> = {};
  for (const [rawRadio, buckets] of Object.entries(byRadioAndBucket)) {
    const radio = formatRadioInterfaceForChart(rawRadio);
    if (!merged[radio]) merged[radio] = {};
    for (const [bucket, count] of Object.entries(buckets)) {
      merged[radio][bucket] = (merged[radio][bucket] ?? 0) + count;
    }
  }
  return merged;
}

const BANDWIDTH_PIE_COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#a855f7', '#06b6d4'];

/** Merge legacy radio labels (e.g. 5GHz → RADAR) for per-radio bandwidth slices. */
function mergeBandwidthByRadio(
  raw: Record<string, Array<{ bandwidth_mhz: number; count: number }>> | undefined
): Array<{ radio: string; slices: Array<{ bandwidth_mhz: number; count: number }> }> {
  if (!raw || Object.keys(raw).length === 0) return [];
  const merged: Record<string, Record<number, number>> = {};
  for (const [rawRadio, items] of Object.entries(raw)) {
    const radio = formatRadioInterfaceForChart(rawRadio);
    if (!merged[radio]) merged[radio] = {};
    for (const { bandwidth_mhz, count } of items) {
      merged[radio][bandwidth_mhz] = (merged[radio][bandwidth_mhz] ?? 0) + count;
    }
  }
  const radiosSorted = Object.keys(merged).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true })
  );
  return radiosSorted
    .filter((radio) => radio !== 'RADAR')
    .map((radio) => ({
      radio,
      slices: Object.entries(merged[radio])
        .map(([bw, cnt]) => ({ bandwidth_mhz: Number(bw), count: cnt }))
        .sort((a, b) => a.bandwidth_mhz - b.bandwidth_mhz),
    }))
    .filter((row) => row.slices.length > 0);
}

function orderReasonBuckets(
  merged: Record<string, Record<string, number>>,
  byReasonBucket: Array<{ bucket: string; count: number }>
): string[] {
  const remaining = new Set<string>();
  for (const buckets of Object.values(merged)) {
    for (const b of Object.keys(buckets)) remaining.add(b);
  }
  const ordered: string[] = [];
  for (const { bucket } of byReasonBucket) {
    if (remaining.has(bucket)) {
      ordered.push(bucket);
      remaining.delete(bucket);
    }
  }
  ordered.push(...[...remaining].sort());
  return ordered;
}

interface ReasonRadioPivotRow {
  bucket: string;
  label: string;
  total: number;
  countsByRadio: Record<string, number>;
  dominantRadio: string;
  dominantPct: number;
}

function buildReasonRadioPivot(
  merged: Record<string, Record<string, number>>,
  bucketOrder: string[],
  radiosSorted: string[]
): ReasonRadioPivotRow[] {
  const rows: ReasonRadioPivotRow[] = [];
  for (const bucket of bucketOrder) {
    let total = 0;
    const countsByRadio: Record<string, number> = {};
    for (const r of radiosSorted) {
      const c = merged[r]?.[bucket] ?? 0;
      if (c > 0) countsByRadio[r] = c;
      total += c;
    }
    if (total === 0) continue;
    let dominantRadio = radiosSorted[0] ?? 'unknown';
    let dominantCount = -1;
    for (const r of radiosSorted) {
      const c = merged[r]?.[bucket] ?? 0;
      if (c > dominantCount) {
        dominantCount = c;
        dominantRadio = r;
      }
    }
    const dominantPct = total > 0 ? (dominantCount / total) * 100 : 0;
    rows.push({
      bucket,
      label: getReasonBucketLabel(bucket),
      total,
      countsByRadio,
      dominantRadio,
      dominantPct,
    });
  }
  return rows;
}

const NO_TOOLBAR = { displayModeBar: false } as const;
/** Plotly fills its container; helps bandwidth pies grow with the card. */
const PLOT_CONFIG_FILL = { displayModeBar: false, responsive: true } as const;

/** Same pixel height for both charts in the channel section (row 1 aligns across columns). */
const CHANNEL_SECTION_CHART_HEIGHT_PX = 340;
/** Minimum body height for table cards (row 2 stretches to match the taller column). */
const CHANNEL_TABLE_BODY_MIN_HEIGHT_PX = 260;

/** Sort key for "36 → 100" style transition labels (ascending by from-channel, then to-channel). */
function compareChannelTransitionLabelsAsc(a: string, b: string): number {
  const parse = (s: string): [number, number] | null => {
    const m = s.match(/(\d+)\s*→\s*(\d+)/);
    if (!m) return null;
    return [parseInt(m[1], 10), parseInt(m[2], 10)];
  };
  const pa = parse(a);
  const pb = parse(b);
  if (pa && pb) {
    if (pa[0] !== pb[0]) return pa[0] - pb[0];
    if (pa[1] !== pb[1]) return pa[1] - pb[1];
    return 0;
  }
  if (pa && !pb) return -1;
  if (!pa && pb) return 1;
  return a.localeCompare(b);
}

/* ================================================================ Component */
export default function SyslogOverviewTab() {
  const { projectId } = useProject();
  const queryClient = useQueryClient();
  const mergePlot = usePlotlyLayoutMerge();
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const [expandedCpe, setExpandedCpe] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRefreshingChannels, setIsRefreshingChannels] = useState(false);
  const [eventCategoriesExpanded, setEventCategoriesExpanded] = useState(false);
  const [channelDistributionExpanded, setChannelDistributionExpanded] = useState(false);

  const { data, isLoading, isError, error } = useQuery<CrossCpeSyslogData>({
    queryKey: ["syslog-overview", projectId],
    queryFn: async () => {
      const response = await syslogApi.crossCpeOverview(projectId!, false);
      const payload = response.data?.data ?? response.data;
      return payload as CrossCpeSyslogData;
    },
    enabled: !!projectId,
    staleTime: 2 * 60 * 1000,
  });

  const { data: channelData, isLoading: channelLoading } = useQuery<ChannelChangeDistributionData>({
    queryKey: ["channel-change-distribution", projectId],
    queryFn: async () => {
      const response = await syslogApi.channelChangeDistribution(projectId!, false);
      const payload = response.data?.data ?? response.data;
      return payload as ChannelChangeDistributionData;
    },
    enabled: !!projectId,
    staleTime: 2 * 60 * 1000,
  });

  const reasonRadioPivot = useMemo(() => {
    if (!channelData?.by_radio_and_bucket) return null;
    const merged = mergeRadioAndBucket(channelData.by_radio_and_bucket);
    const bucketOrder = orderReasonBuckets(merged, channelData.by_reason_bucket);
    const radiosSorted = Object.keys(merged).sort((a, b) =>
      a.localeCompare(b, undefined, { numeric: true })
    );
    const pivotRows = buildReasonRadioPivot(merged, bucketOrder, radiosSorted);
    const stackTraces = radiosSorted.map((radio) => ({
      type: 'bar' as const,
      name: radio,
      x: bucketOrder.map((b) => getReasonBucketLabel(b)),
      y: bucketOrder.map((b) => merged[radio]?.[b] ?? 0),
      marker: { color: getRadioStackColor(radio) },
      hovertemplate: `<b>%{x}</b><br>${radio}: %{y:,}<extra></extra>`,
    }));
    return { merged, bucketOrder, radiosSorted, pivotRows, stackTraces };
  }, [channelData]);

  const topChannelTransitionsByCountAsc = useMemo(() => {
    if (!channelData?.top_transitions?.length) return [];
    return [...channelData.top_transitions.slice(0, 10)].sort((p, q) => {
      if (p.count !== q.count) return p.count - q.count;
      return compareChannelTransitionLabelsAsc(p.transition, q.transition);
    });
  }, [channelData]);

  const bandwidthByRadioRows = useMemo(
    () => mergeBandwidthByRadio(channelData?.bandwidth_by_radio),
    [channelData]
  );

  const handleForceRefresh = async () => {
    if (!projectId || isRefreshing) return;
    setIsRefreshing(true);
    try {
      const response = await syslogApi.crossCpeOverview(projectId, true);
      const payload = response.data?.data ?? response.data;
      queryClient.setQueryData(["syslog-overview", projectId], payload as CrossCpeSyslogData);
      await queryClient.invalidateQueries({ queryKey: ["syslog", projectId] });
    } catch (err) {
      console.error("Force refresh failed:", err);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleForceRefreshChannels = async () => {
    if (!projectId || isRefreshingChannels) return;
    setIsRefreshingChannels(true);
    try {
      const response = await syslogApi.channelChangeDistribution(projectId, true);
      const payload = response.data?.data ?? response.data;
      queryClient.setQueryData(["channel-change-distribution", projectId], payload as ChannelChangeDistributionData);
      await queryClient.invalidateQueries({ queryKey: ["syslog", projectId] });
    } catch (err) {
      console.error("Force refresh channels failed:", err);
    } finally {
      setIsRefreshingChannels(false);
    }
  };

  if (!projectId) {
    return (
      <div className="p-4">
        <div className="bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
          <p className="text-blue-800 dark:text-blue-200">
            Please select a project to view cross-CPE syslog overview
          </p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-3 justify-center py-16 text-muted-foreground">
        <CircularProgress size={24} />
        <span className="text-sm">Loading cross-CPE syslog overview...</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-4 bg-destructive/10 text-destructive rounded-xl text-sm flex items-center gap-2">
        <ErrorIcon style={{ fontSize: 18 }} />
        {(error as { response?: { data?: { error?: string } } })?.response?.data?.error || 
         (error as { message?: string })?.message || 
         "Error loading cross-CPE overview"}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-4">
        <div className="bg-yellow-50 dark:bg-yellow-900/10 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6">
          <p className="text-yellow-800 dark:text-yellow-200">
            No syslog data available for cross-CPE analysis
          </p>
        </div>
      </div>
    );
  }

  // Prepare chart data for event category distribution
  const categoryChartData = Object.entries(data.event_category_totals)
    .sort(([,a], [,b]) => b - a)
    .slice(0, 10); // Top 10 categories

  const categoryBarChart = [{
    type: 'bar' as const,
    x: categoryChartData.map(([category]) => category),
    y: categoryChartData.map(([, count]) => count),
    marker: {
      color: categoryChartData.map(([category]) => getCategoryColor(category)),
    },
    hovertemplate: '<b>%{x}</b><br>Events: %{y:,}<extra></extra>',
  }];

  // Prepare pie chart for category distribution
  const categoryPieChart = [{
    type: 'pie' as const,
    labels: categoryChartData.map(([category]) => category),
    values: categoryChartData.map(([, count]) => count),
    marker: {
      colors: categoryChartData.map(([category]) => getCategoryColor(category)),
    },
    hovertemplate: '<b>%{label}</b><br>Events: %{value:,}<br>Percentage: %{percent}<extra></extra>',
  }];

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={handleForceRefresh}
          disabled={isRefreshing || isLoading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-card hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-foreground"
          title="Force re-parse syslog for all CPEs"
        >
          {isRefreshing ? (
            <CircularProgress size={14} className="text-muted-foreground" />
          ) : (
            <RefreshIcon style={{ fontSize: 14 }} className={isRefreshing ? "animate-spin" : ""} />
          )}
          {isRefreshing ? "Re-parsing..." : "Force Refresh All"}
        </button>
      </div>

      {/* ========== Summary Cards ========== */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-card border border-border rounded-xl p-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Total CPEs</p>
          <p className="text-xl font-bold text-foreground">{data.summary.total_cpes}</p>
          <p className="text-[10px] text-muted-foreground mt-1">
            {data.summary.cpes_with_syslog} with syslog data
          </p>
        </div>

        <div className="bg-card border border-border rounded-xl p-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Total Events</p>
          <p className="text-xl font-bold text-foreground">{data.summary.total_events.toLocaleString()}</p>
          <p className="text-[10px] text-muted-foreground mt-1">
            {Math.round(data.summary.total_events / Math.max(data.summary.cpes_with_syslog, 1)).toLocaleString()} avg per CPE
          </p>
        </div>

        <div className="bg-card border border-border rounded-xl p-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Categories</p>
          <p className="text-xl font-bold text-foreground">{Object.keys(data.event_category_totals).length}</p>
          <p className="text-[10px] text-muted-foreground mt-1">
            Top: {categoryChartData[0]?.[0] || 'N/A'}
          </p>
        </div>

        <div className="bg-card border border-border rounded-xl p-3">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Coverage</p>
          <p className="text-xl font-bold text-foreground">
            {Math.round((data.summary.cpes_with_syslog / Math.max(data.summary.total_cpes, 1)) * 100)}%
          </p>
          <p className="text-[10px] text-muted-foreground mt-1">
            {data.summary.parsing_errors_count} errors
          </p>
        </div>
      </div>

      {/* ========== Parsing Errors Section ========== */}
      {data.summary.parsing_errors_count > 0 && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-border bg-muted/30">
            <button
              onClick={() => setShowErrorDetails(!showErrorDetails)}
              className="flex items-center gap-2 text-left"
            >
              {showErrorDetails ? (
                <ExpandLessIcon style={{ fontSize: 16 }} />
              ) : (
                <ExpandMoreIcon style={{ fontSize: 16 }} />
              )}
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Parsing Errors ({data.summary.parsing_errors_count})
              </h3>
            </button>
          </div>
          {showErrorDetails && (
            <div className="p-4">
              <div className="space-y-2">
                {data.parsing_errors.map((error, idx) => (
                  <div key={idx} className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/10 p-2 rounded border border-red-200 dark:border-red-800">
                    {error}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ========== Event categories (collapsible) ========== */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/30">
          <button
            type="button"
            onClick={() => setEventCategoriesExpanded(!eventCategoriesExpanded)}
            className="flex items-center gap-2 text-left w-full"
          >
            {eventCategoriesExpanded ? (
              <ExpandLessIcon style={{ fontSize: 18 }} />
            ) : (
              <ExpandMoreIcon style={{ fontSize: 18 }} />
            )}
            <div className="flex-1 min-w-0">
              <h2 className="text-sm font-semibold text-foreground">Event categories</h2>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Category charts and top event IDs — {eventCategoriesExpanded ? "click to collapse" : "collapsed; click to expand"}
              </p>
            </div>
          </button>
        </div>
        {eventCategoriesExpanded && (
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border bg-muted/30">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Event Categories (Bar Chart)
                  </h3>
                </div>
                <div className="p-4">
                  <Plot
                    data={categoryBarChart}
                    layout={mergePlot({
                      height: 300,
                      margin: { l: 60, r: 15, t: 5, b: 80 },
                      xaxis: {
                        title: { text: "Category" },
                        tickangle: -45,
                        tickfont: { size: 10 },
                      },
                      yaxis: {
                        title: { text: "Event Count" },
                        tickfont: { size: 10 },
                      },
                      font: { family: "Roboto, sans-serif", size: 11 },
                    })}
                    config={NO_TOOLBAR}
                    style={{ width: "100%" }}
                  />
                </div>
              </div>
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="px-4 py-2 border-b border-border bg-muted/30">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Event Categories (Distribution)
                  </h3>
                </div>
                <div className="p-4">
                  <Plot
                    data={categoryPieChart}
                    layout={mergePlot({
                      height: 300,
                      margin: { l: 15, r: 15, t: 5, b: 15 },
                      font: { family: "Roboto, sans-serif", size: 11 },
                      showlegend: true,
                      legend: {
                        orientation: "v",
                        x: 1.05,
                        y: 0.5,
                        font: { size: 10 },
                      },
                    })}
                    config={NO_TOOLBAR}
                    style={{ width: "100%" }}
                  />
                </div>
              </div>
            </div>
            <div className="bg-card border border-border rounded-xl overflow-hidden">
              <div className="px-4 py-2 border-b border-border bg-muted/30">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Top Event IDs (Most Frequent)
                </h3>
              </div>
              <div className="max-h-[min(40vh,22rem)] overflow-y-auto overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-[1] bg-muted/95 backdrop-blur-sm border-b border-border/60">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">#</th>
                      <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Event ID</th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Count</th>
                      <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">% of Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_event_ids.slice(0, 15).map((item, idx) => (
                      <tr key={item.event_id} className="border-t border-border/50 hover:bg-muted/20">
                        <td className="px-4 py-2 text-muted-foreground font-mono">{idx + 1}</td>
                        <td className="px-4 py-2 font-mono font-medium">{item.event_id}</td>
                        <td className="px-4 py-2 text-right font-medium">{item.count.toLocaleString()}</td>
                        <td className="px-4 py-2 text-right text-muted-foreground">
                          {((item.count / data.summary.total_events) * 100).toFixed(1)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ========== Channel change distribution (collapsible) ========== */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/30">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setChannelDistributionExpanded(!channelDistributionExpanded)}
              className="flex items-center gap-2 text-left flex-1 min-w-0"
            >
              {channelDistributionExpanded ? (
                <ExpandLessIcon style={{ fontSize: 18 }} />
              ) : (
                <ExpandMoreIcon style={{ fontSize: 18 }} />
              )}
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-foreground">Channel distribution</h2>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  W017 / W018 ACSD — {channelDistributionExpanded ? "click to collapse" : "collapsed; click to expand"}
                </p>
              </div>
            </button>
            <button
              type="button"
              onClick={handleForceRefreshChannels}
              disabled={isRefreshingChannels || channelLoading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-background hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-foreground shrink-0"
              title="Force re-parse and re-aggregate channel changes"
            >
              {isRefreshingChannels ? (
                <CircularProgress size={14} className="text-muted-foreground" />
              ) : (
                <RefreshIcon style={{ fontSize: 14 }} className={isRefreshingChannels ? "animate-spin" : ""} />
              )}
              {isRefreshingChannels ? "Re-parsing..." : "Force Refresh"}
            </button>
          </div>
        </div>
        {channelDistributionExpanded && (
          <div className="space-y-4 p-4">

        {channelLoading && (
          <div className="flex items-center gap-3 justify-center py-8 text-muted-foreground">
            <CircularProgress size={20} />
            <span className="text-sm">Loading channel change distribution...</span>
          </div>
        )}

        {!channelLoading && (!channelData || channelData.summary.total_channel_switches === 0) && (
          <div className="bg-card border border-border rounded-xl p-6">
            <p className="text-sm text-muted-foreground text-center">
              No channel changes (W017 / W018 ACSD) found in the syslog data.
              Channel switches will appear here when detected.
            </p>
          </div>
        )}

        {!channelLoading && channelData && channelData.summary.total_channel_switches > 0 && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="bg-card border border-border rounded-xl p-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Total Switches</p>
              <p className="text-xl font-bold text-foreground">{channelData.summary.total_channel_switches.toLocaleString()}</p>
              <p className="text-[10px] text-muted-foreground mt-1">
                {channelData.summary.cpes_with_channel_switches} CPEs affected
              </p>
            </div>

            <div className="bg-card border border-border rounded-xl p-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Top Reason</p>
              <p className="text-xl font-bold text-foreground">
                {channelData.by_reason_bucket[0] ? getReasonBucketLabel(channelData.by_reason_bucket[0].bucket) : 'N/A'}
              </p>
              <p className="text-[10px] text-muted-foreground mt-1">
                {channelData.by_reason_bucket[0]?.percentage.toFixed(1)}% of switches
              </p>
            </div>

            <div className="bg-card border border-border rounded-xl p-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Coverage</p>
              <p className="text-xl font-bold text-foreground">
                {Math.round((channelData.summary.cpes_with_channel_switches / Math.max(channelData.summary.total_cpes, 1)) * 100)}%
              </p>
              <p className="text-[10px] text-muted-foreground mt-1">
                CPEs with channel switches
              </p>
            </div>

            <div className="bg-card border border-border rounded-xl p-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Avg per CPE</p>
              <p className="text-xl font-bold text-foreground">
                {Math.round(channelData.summary.total_channel_switches / Math.max(channelData.summary.cpes_with_channel_switches, 1))}
              </p>
              <p className="text-[10px] text-muted-foreground mt-1">
                switches per affected CPE
              </p>
            </div>
            </div>

            {/*
              2×2 grid: row 1 = both charts (equal height), row 2 = both tables (equal height).
              DOM order: chart L, chart R, table L, table R — so lg layout matches visual rows.
            */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:items-stretch">
              {/* Row 1 left — reasons chart */}
              <div className="bg-card border border-border rounded-xl overflow-hidden h-full flex flex-col min-h-0 min-w-0">
                <div className="px-4 py-2 border-b border-border bg-muted/30 shrink-0">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Channel switch reasons by radio
                  </h3>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Stacked bars: each segment is the count for that radio (e.g. CS Timer mostly on wl0 vs wl1).
                  </p>
                </div>
                <div
                  className="p-4 flex-1 flex flex-col justify-center min-h-0"
                  style={{ minHeight: CHANNEL_SECTION_CHART_HEIGHT_PX }}
                >
                  {reasonRadioPivot && reasonRadioPivot.stackTraces.length > 0 ? (
                    <Plot
                      data={reasonRadioPivot.stackTraces}
                      layout={mergePlot({
                        height: CHANNEL_SECTION_CHART_HEIGHT_PX,
                        margin: { l: 60, r: 15, t: 5, b: 88 },
                        barmode: "stack",
                        xaxis: {
                          title: { text: "Reason" },
                          tickangle: -45,
                          tickfont: { size: 10 },
                        },
                        yaxis: {
                          title: { text: "Count" },
                          tickfont: { size: 10 },
                        },
                        legend: {
                          orientation: "h",
                          y: -0.28,
                          x: 0.5,
                          xanchor: "center",
                          font: { size: 10 },
                        },
                        font: { family: "Roboto, sans-serif", size: 11 },
                      })}
                      config={NO_TOOLBAR}
                      style={{ width: '100%', minHeight: CHANNEL_SECTION_CHART_HEIGHT_PX }}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground text-center py-8">No reason × radio breakdown available.</p>
                  )}
                </div>
              </div>

              {/* Row 1 right — transitions chart */}
              <div className="bg-card border border-border rounded-xl overflow-hidden h-full flex flex-col min-h-0 min-w-0">
                <div className="px-4 py-2 border-b border-border bg-muted/30 shrink-0">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Top channel transitions (From → To)
                  </h3>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Ordered ascending by count (smallest at top). Ties use channel order in the label.
                  </p>
                </div>
                <div
                  className="p-4 flex-1 flex flex-col justify-center min-h-0"
                  style={{ minHeight: CHANNEL_SECTION_CHART_HEIGHT_PX }}
                >
                  {topChannelTransitionsByCountAsc.length > 0 ? (
                    <Plot
                      data={[{
                        type: 'bar' as const,
                        y: topChannelTransitionsByCountAsc.map((t) => t.transition),
                        x: topChannelTransitionsByCountAsc.map((t) => t.count),
                        orientation: 'h' as const,
                        marker: {
                          color: '#8b5cf6',
                        },
                        hovertemplate: '<b>%{y}</b><br>Count: %{x:,}<extra></extra>',
                      }]}
                      layout={mergePlot({
                        height: CHANNEL_SECTION_CHART_HEIGHT_PX,
                        margin: { l: 100, r: 15, t: 5, b: 40 },
                        xaxis: {
                          title: { text: "Count" },
                          tickfont: { size: 10 },
                        },
                        yaxis: {
                          tickfont: { size: 9 },
                          automargin: true,
                        },
                        font: { family: "Roboto, sans-serif", size: 10 },
                      })}
                      config={NO_TOOLBAR}
                      style={{ width: '100%', minHeight: CHANNEL_SECTION_CHART_HEIGHT_PX }}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground text-center py-8">No transition data for chart.</p>
                  )}
                </div>
              </div>

              {/* Row 2 left — Reason × radio table */}
              {reasonRadioPivot && reasonRadioPivot.pivotRows.length > 0 && reasonRadioPivot.radiosSorted.length > 0 ? (
                <div className="bg-card border border-border rounded-xl overflow-hidden h-full flex flex-col min-h-0 min-w-0">
                  <div className="px-4 py-2 border-b border-border bg-muted/30 shrink-0">
                    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Reason × radio
                    </h3>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      Per row, percentages sum to 100% across radios. <strong>Top radio</strong> is the dominant interface.
                    </p>
                  </div>
                  <div
                    className="flex-1 overflow-auto min-h-0"
                    style={{ minHeight: CHANNEL_TABLE_BODY_MIN_HEIGHT_PX }}
                  >
                    <table className="w-full text-sm min-w-max">
                      <thead className="sticky top-0 z-[1] bg-muted/95 backdrop-blur-sm border-b border-border/60">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground sticky left-0 z-[2] bg-muted/95 min-w-[10rem]">
                            Reason
                          </th>
                          <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground">Total</th>
                          <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground min-w-[7rem]">Top radio</th>
                          {reasonRadioPivot.radiosSorted.map((r) => (
                            <th key={r} className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground whitespace-nowrap">
                              {r}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {reasonRadioPivot.pivotRows.map((row) => (
                          <tr key={row.bucket} className="border-t border-border/50 hover:bg-muted/20">
                            <td className="px-3 py-2 font-medium sticky left-0 z-[1] bg-card border-r border-border/40">
                              {row.label}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums">{row.total.toLocaleString()}</td>
                            <td className="px-3 py-2 text-xs">
                              <span className="font-medium">{row.dominantRadio}</span>
                              <span className="text-muted-foreground"> ({row.dominantPct.toFixed(1)}%)</span>
                            </td>
                            {reasonRadioPivot.radiosSorted.map((r) => {
                              const c = row.countsByRadio[r] ?? 0;
                              const pct = row.total > 0 ? (c / row.total) * 100 : 0;
                              return (
                                <td key={r} className="px-3 py-2 text-right text-xs tabular-nums whitespace-nowrap">
                                  {c > 0 ? (
                                    <>
                                      {c.toLocaleString()}
                                      <span className="text-muted-foreground"> ({pct.toFixed(1)}%)</span>
                                    </>
                                  ) : (
                                    <span className="text-muted-foreground">—</span>
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div
                  className="bg-card border border-border rounded-xl overflow-hidden flex items-center justify-center h-full min-w-0"
                  style={{ minHeight: CHANNEL_TABLE_BODY_MIN_HEIGHT_PX + 80 }}
                >
                  <p className="text-sm text-muted-foreground text-center px-4 py-8">No Reason × radio table available.</p>
                </div>
              )}

              {/* Row 2 right — Top channels table */}
              {channelData.top_channels && channelData.top_channels.length > 0 ? (
                <div className="bg-card border border-border rounded-xl overflow-hidden h-full flex flex-col min-h-0 min-w-0">
                  <div className="px-4 py-2 border-b border-border bg-muted/30 shrink-0">
                    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Top channels
                    </h3>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      Most frequent destination channels after a switch.
                    </p>
                  </div>
                  <div
                    className="flex-1 overflow-auto min-h-0"
                    style={{ minHeight: CHANNEL_TABLE_BODY_MIN_HEIGHT_PX }}
                  >
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 z-[1] bg-muted/95 backdrop-blur-sm border-b border-border/60">
                        <tr>
                          <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">#</th>
                          <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Channel</th>
                          <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Count</th>
                          <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">% of switches</th>
                        </tr>
                      </thead>
                      <tbody>
                        {channelData.top_channels.slice(0, 10).map((item, idx) => (
                          <tr key={item.channel} className="border-t border-border/50 hover:bg-muted/20">
                            <td className="px-4 py-2 text-muted-foreground font-mono">{idx + 1}</td>
                            <td className="px-4 py-2 font-mono font-medium">Channel {item.channel}</td>
                            <td className="px-4 py-2 text-right font-medium">{item.count.toLocaleString()}</td>
                            <td className="px-4 py-2 text-right text-muted-foreground">
                              {((item.count / channelData.summary.total_channel_switches) * 100).toFixed(1)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div
                  className="bg-card border border-border rounded-xl overflow-hidden flex items-center justify-center h-full min-w-0"
                  style={{ minHeight: CHANNEL_TABLE_BODY_MIN_HEIGHT_PX + 80 }}
                >
                  <p className="text-sm text-muted-foreground text-center px-4 py-8">No top channels data.</p>
                </div>
              )}
            </div>

            {/* Bandwidth distribution per radio */}
            <div className="space-y-2">
              <div className="px-1">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Bandwidth distribution by radio
                </h3>
                <p className="text-[10px] text-muted-foreground mt-1">
                  Channel switch events by nominal bandwidth (MHz), split per radio interface.
                </p>
              </div>
              {bandwidthByRadioRows.length > 0 ? (
                <div
                  className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 items-stretch"
                  style={{ gridAutoRows: 'minmax(22rem, 1fr)' }}
                >
                  {bandwidthByRadioRows.map(({ radio, slices }) => (
                    <div
                      key={radio}
                      className="bg-card border border-border rounded-xl overflow-hidden flex flex-col h-full min-h-0 min-w-0"
                    >
                      <div className="px-3 py-2 border-b border-border bg-muted/30 shrink-0">
                        <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          {radio}
                        </h4>
                        <p className="text-[10px] text-muted-foreground mt-0.5">Bandwidth distribution</p>
                      </div>
                      <div className="flex-1 min-h-[16rem] w-full min-w-0 p-2 box-border flex flex-col">
                        <Plot
                          data={[{
                            type: 'pie' as const,
                            labels: slices.map((b) => `${b.bandwidth_mhz} MHz`),
                            values: slices.map((b) => b.count),
                            marker: {
                              colors: slices.map((_, i) => BANDWIDTH_PIE_COLORS[i % BANDWIDTH_PIE_COLORS.length]),
                            },
                            hovertemplate: '<b>%{label}</b><br>Switches: %{value:,}<br>%{percent}<extra></extra>',
                          }]}
                          layout={mergePlot({
                            autosize: true,
                            margin: { l: 8, r: 8, t: 8, b: 8 },
                            font: { family: "Roboto, sans-serif", size: 10 },
                            showlegend: true,
                            legend: {
                              orientation: "h",
                              y: -0.08,
                              x: 0.5,
                              xanchor: "center",
                              font: { size: 9 },
                            },
                          })}
                          config={PLOT_CONFIG_FILL}
                          useResizeHandler
                          style={{ width: '100%', height: '100%', flex: 1, minHeight: '14rem' }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : channelData.bandwidth_distribution && channelData.bandwidth_distribution.length > 0 ? (
                <div className="bg-card border border-border rounded-xl overflow-hidden flex flex-col min-h-[24rem] h-full">
                  <div className="px-4 py-2 border-b border-border bg-muted/30 shrink-0">
                    <h4 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Fleet-wide bandwidth distribution
                    </h4>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      All radios combined. Use <strong>Force Refresh</strong> on this section so per-radio charts can repopulate from chanspec on each line.
                    </p>
                  </div>
                  <div className="flex-1 min-h-[18rem] w-full p-4 box-border flex flex-col">
                    <Plot
                      data={[{
                        type: 'pie' as const,
                        labels: channelData.bandwidth_distribution.map((b) => `${b.bandwidth_mhz} MHz`),
                        values: channelData.bandwidth_distribution.map((b) => b.count),
                        marker: {
                          colors: channelData.bandwidth_distribution.map(
                            (_, i) => BANDWIDTH_PIE_COLORS[i % BANDWIDTH_PIE_COLORS.length]
                          ),
                        },
                        hovertemplate: '<b>%{label}</b><br>Switches: %{value:,}<br>%{percent}<extra></extra>',
                      }]}
                      layout={mergePlot({
                        autosize: true,
                        margin: { l: 8, r: 8, t: 8, b: 8 },
                        font: { family: "Roboto, sans-serif", size: 11 },
                        showlegend: true,
                        legend: {
                          orientation: "h",
                          y: -0.08,
                          x: 0.5,
                          xanchor: "center",
                          font: { size: 10 },
                        },
                      })}
                      config={PLOT_CONFIG_FILL}
                      useResizeHandler
                      style={{ width: '100%', height: '100%', flex: 1, minHeight: '16rem' }}
                    />
                  </div>
                </div>
              ) : (
                <div className="bg-card border border-border rounded-xl p-6">
                  <p className="text-sm text-muted-foreground text-center">
                    No bandwidth data: lines may not include a decodable chanspec (0x… after Channel switched to).
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
          </div>
        )}
      </div>

      {/* ========== CPE Comparison Table ========== */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/30">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            CPE Comparison ({data.cpe_comparison.length} CPEs)
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/20">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">CPE ID</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Total Events</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-muted-foreground">Near Reboots</th>
                <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Time Range</th>
                <th className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground">Top Categories</th>
                <th className="px-4 py-2 text-center text-xs font-semibold text-muted-foreground">Details</th>
              </tr>
            </thead>
            <tbody>
              {data.cpe_comparison.slice(0, 50).map((cpe) => {
                const isExpanded = expandedCpe === cpe.cpe_id;
                const topCategories = Object.entries(cpe.event_counts)
                  .sort(([,a], [,b]) => b - a)
                  .slice(0, 3);

                return (
                  <>
                    <tr key={cpe.cpe_id} className="border-t border-border/50 hover:bg-muted/20">
                      <td className="px-4 py-2 font-mono text-xs font-medium">{cpe.cpe_id}</td>
                      <td className="px-4 py-2 text-right font-medium">{cpe.total_events.toLocaleString()}</td>
                      <td className="px-4 py-2 text-right">
                        {cpe.events_near_reboots !== undefined ? (
                          <span className={cpe.events_near_reboots > 0 ? "text-red-600 dark:text-red-400 font-medium" : "text-muted-foreground"}>
                            {cpe.events_near_reboots}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">
                        {cpe.time_range ? (
                          <>
                            {cpe.time_range.first?.slice(5, 10)} — {cpe.time_range.last?.slice(5, 10)}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex flex-wrap gap-1">
                          {topCategories.map(([category, count]) => (
                            <span
                              key={category}
                              className="px-1.5 py-0.5 rounded text-xs font-medium"
                              style={{ 
                                backgroundColor: `${getCategoryColor(category)}15`,
                                color: getCategoryColor(category),
                                borderColor: `${getCategoryColor(category)}30`
                              }}
                            >
                              {category} ({count})
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-center">
                        <button
                          onClick={() => setExpandedCpe(isExpanded ? null : cpe.cpe_id)}
                          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded border hover:bg-muted transition-colors"
                        >
                          {isExpanded ? <ExpandLessIcon style={{ fontSize: 14 }} /> : <ExpandMoreIcon style={{ fontSize: 14 }} />}
                          {isExpanded ? 'Hide' : 'Show'}
                        </button>
                      </td>
                    </tr>

                    {/* Expanded Details Row */}
                    {isExpanded && (
                      <tr>
                        <td colSpan={6} className="px-4 py-3 bg-muted/10 border-t border-border/30">
                          <div className="space-y-3">
                            <h4 className="text-sm font-semibold text-foreground">Event Breakdown for {cpe.cpe_id}</h4>
                            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                              {Object.entries(cpe.event_counts)
                                .sort(([,a], [,b]) => b - a)
                                .map(([category, count]) => (
                                  <div key={category} className="bg-card border border-border rounded p-2">
                                    <div className="flex items-center justify-between">
                                      <span
                                        className="text-xs font-medium"
                                        style={{ color: getCategoryColor(category) }}
                                      >
                                        {category}
                                      </span>
                                      <span className="text-xs font-bold">{count}</span>
                                    </div>
                                    <div className="mt-1">
                                      <div 
                                        className="h-1.5 rounded-full"
                                        style={{ backgroundColor: `${getCategoryColor(category)}30` }}
                                      >
                                        <div
                                          className="h-full rounded-full"
                                          style={{ 
                                            backgroundColor: getCategoryColor(category),
                                            width: `${Math.min(100, (count / Math.max(...Object.values(cpe.event_counts))) * 100)}%`
                                          }}
                                        />
                                      </div>
                                    </div>
                                  </div>
                                ))}
                            </div>
                            {cpe.total_reboots !== undefined && cpe.total_reboots > 0 && (
                              <div className="text-sm text-muted-foreground">
                                <ArticleIcon style={{ fontSize: 14 }} className="inline mr-1" />
                                Total reboots: {cpe.total_reboots}, Events near reboots: {cpe.events_near_reboots || 0}
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
          {data.cpe_comparison.length > 50 && (
            <div className="p-4 text-center text-sm text-muted-foreground bg-muted/10">
              Showing first 50 CPEs of {data.cpe_comparison.length}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { syslogApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import Plot from "react-plotly.js";
import ArticleIcon from "@mui/icons-material/Article";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ErrorIcon from "@mui/icons-material/Error";
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

const NO_TOOLBAR = { displayModeBar: false } as const;

/* ================================================================ Component */
export default function SyslogOverviewTab() {
  const { projectId } = useProject();
  const [showErrorDetails, setShowErrorDetails] = useState(false);
  const [expandedCpe, setExpandedCpe] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery<CrossCpeSyslogData>({
    queryKey: ["syslog-overview", projectId],
    queryFn: async () => {
      const response = await syslogApi.crossCpeOverview(projectId!);
      // API returns { data: payload }; axios puts that in response.data
      const payload = response.data?.data ?? response.data;
      return payload as CrossCpeSyslogData;
    },
    enabled: !!projectId,
    staleTime: 2 * 60 * 1000,
  });

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

      {/* ========== Category Distribution Charts ========== */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Bar Chart */}
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-border bg-muted/30">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Event Categories (Bar Chart)
            </h3>
          </div>
          <div className="p-4">
            <Plot
              data={categoryBarChart}
              layout={{
                height: 300,
                margin: { l: 60, r: 15, t: 5, b: 80 },
                xaxis: { 
                  title: { text: 'Category' },
                  tickangle: -45,
                  tickfont: { size: 10 }
                },
                yaxis: { 
                  title: { text: 'Event Count' },
                  tickfont: { size: 10 }
                },
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",
                font: { family: "Roboto, sans-serif", size: 11 },
              }}
              config={NO_TOOLBAR}
              style={{ width: '100%' }}
            />
          </div>
        </div>

        {/* Pie Chart */}
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-border bg-muted/30">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Event Categories (Distribution)
            </h3>
          </div>
          <div className="p-4">
            <Plot
              data={categoryPieChart}
              layout={{
                height: 300,
                margin: { l: 15, r: 15, t: 5, b: 15 },
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",
                font: { family: "Roboto, sans-serif", size: 11 },
                showlegend: true,
                legend: {
                  orientation: "v",
                  x: 1.05,
                  y: 0.5,
                  font: { size: 10 }
                }
              }}
              config={NO_TOOLBAR}
              style={{ width: '100%' }}
            />
          </div>
        </div>
      </div>

      {/* ========== Top Event IDs ========== */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/30">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Top Event IDs (Most Frequent)
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/20">
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
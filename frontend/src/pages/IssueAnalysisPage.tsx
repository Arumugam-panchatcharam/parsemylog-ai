import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useProject } from "@/hooks/useProject";
import {
  knowledgeGraphApi,
  issueAnalysisApi,
  batchJobsApi,
  type KnowledgeGraphSummary,
  type IssueAnalysisOverview,
  type IssueAnalysisCPEReport,
  type BatchJob,
} from "../api/endpoints";
import Plot from "react-plotly.js";
import CircularProgress from "@mui/material/CircularProgress";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RefreshIcon from "@mui/icons-material/Refresh";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import HubIcon from "@mui/icons-material/Hub";
import AccountTreeIcon from "@mui/icons-material/AccountTree";

export default function IssueAnalysisPage() {
  const { projectId } = useProject();
  const qc = useQueryClient();

  const [selectedJobId, setSelectedJobId] = useState<string>("");
  const [selectedGraphId, setSelectedGraphId] = useState<string>("");
  const [selectedCPE, setSelectedCPE] = useState<string | null>(null);
  const [analysisRunning, setAnalysisRunning] = useState(false);
  const [forceReparse, setForceReparse] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const justStartedPollingRef = useRef<boolean>(false);

  // Detect project type: check if batch jobs exist
  const { data: jobsData } = useQuery({
    queryKey: ["batchJobs", projectId],
    queryFn: async () => (await batchJobsApi.list(projectId!, 50)).data,
    enabled: !!projectId,
  });
  const jobs = jobsData?.jobs?.filter((j: BatchJob) => j.status === "completed") ?? [];
  const isBatchProject = jobs.length > 0;

  // Auto-select first completed batch job
  useEffect(() => {
    if (isBatchProject && !selectedJobId && jobs.length > 0) {
      setSelectedJobId(jobs[0].job_id);
    }
  }, [isBatchProject, jobs, selectedJobId]);

  // For single-CPE projects, auto-set the job ID to "__direct__" sentinel
  const effectiveJobId = isBatchProject ? selectedJobId : "__direct__";

  // Fetch knowledge graphs
  const { data: graphs } = useQuery({
    queryKey: ["knowledgeGraphs", "global"],
    queryFn: async () => (await knowledgeGraphApi.list()).data,
  });

  // Fetch analysis results
  const {
    data: overview,
    isLoading: overviewLoading,
    refetch: refetchOverview,
  } = useQuery({
    queryKey: ["issueAnalysis", projectId, effectiveJobId],
    queryFn: async () => {
      if (!isBatchProject) {
        return (await issueAnalysisApi.getDirect(projectId!)).data;
      }
      return (await issueAnalysisApi.get(projectId!, selectedJobId)).data;
    },
    enabled: !!projectId && (isBatchProject ? !!selectedJobId : true),
    retry: false,
  });

  // Fetch per-CPE detail
  const {
    data: cpeReport,
    isLoading: cpeLoading,
  } = useQuery({
    queryKey: ["issueAnalysisCPE", projectId, effectiveJobId, selectedCPE],
    queryFn: async () => {
      if (!isBatchProject) {
        return (await issueAnalysisApi.getCPEDirect(projectId!, selectedCPE!)).data;
      }
      return (await issueAnalysisApi.getCPE(projectId!, selectedJobId, selectedCPE!)).data;
    },
    enabled: !!projectId && !!selectedCPE && (isBatchProject ? !!selectedJobId : true),
    retry: false,
  });

  // Polling: stop when results become available
  useEffect(() => {
    // Only stop if we're running AND have results AND didn't just start
    if (analysisRunning && overview?.available && !justStartedPollingRef.current) {
      setAnalysisRunning(false);
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    }
    // Reset the flag after first effect run
    if (justStartedPollingRef.current) {
      justStartedPollingRef.current = false;
    }
  }, [analysisRunning, overview]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  const startPolling = useCallback(() => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    // Set flag to prevent immediate stop
    justStartedPollingRef.current = true;
    // Stop polling effect from immediately canceling by setting running first
    setAnalysisRunning(true);
    // Then flush stale results - this won't trigger immediate re-render but will update cache
    qc.setQueryData(["issueAnalysis", projectId, effectiveJobId], undefined);
    setSelectedCPE(null);
    pollTimerRef.current = setInterval(() => {
      qc.invalidateQueries({
        queryKey: ["issueAnalysis", projectId, effectiveJobId],
      });
    }, 5000);
  }, [qc, projectId, effectiveJobId]);

  // Trigger analysis mutation
  const triggerMut = useMutation({
    mutationFn: () => {
      if (!isBatchProject) {
        return issueAnalysisApi.triggerDirect(projectId!, selectedGraphId, forceReparse);
      }
      return issueAnalysisApi.trigger(projectId!, selectedJobId, selectedGraphId, forceReparse);
    },
    onSuccess: () => {
      startPolling();
    },
  });

  if (!projectId) {
    return (
      <div className="p-6 text-muted-foreground text-center">
        Select a project first.
      </div>
    );
  }

  const fleet = overview?.fleet_report;

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto">
      <div className="flex items-center gap-2 mb-6">
        <AccountTreeIcon className="text-blue-500" />
        <h1 className="text-xl font-bold">Issue Analysis</h1>
      </div>

      {/* Controls */}
      <div className="bg-card border border-border rounded-xl p-4 mb-5">
        <div className={`grid grid-cols-1 gap-3 ${isBatchProject ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
          {isBatchProject && (
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Batch Job</label>
              <select
                value={selectedJobId}
                onChange={(e) => {
                  setSelectedJobId(e.target.value);
                  setSelectedCPE(null);
                }}
                className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background"
              >
                <option value="">Select batch job...</option>
                {jobs.map((j: BatchJob) => (
                  <option key={j.job_id} value={j.job_id}>
                    {j.job_id.slice(0, 8)} - {j.total_cpes} CPEs ({j.created_at?.slice(0, 10)})
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-xs text-muted-foreground mb-1">Knowledge Graph</label>
            <select
              value={selectedGraphId}
              onChange={(e) => {
                setSelectedGraphId(e.target.value);
                setSelectedCPE(null);
              }}
              className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background"
            >
              <option value="">Select graph...</option>
              {graphs?.map((g: KnowledgeGraphSummary) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-end gap-3">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={forceReparse}
                onChange={(e) => setForceReparse(e.target.checked)}
                className="rounded border-border"
              />
              Re-parse telemetry
            </label>
            <button
              onClick={() => triggerMut.mutate()}
              disabled={
                !selectedGraphId || triggerMut.isPending || analysisRunning ||
                (isBatchProject && !selectedJobId)
              }
              className="flex items-center gap-1.5 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              <PlayArrowIcon fontSize="small" />
              {triggerMut.isPending || analysisRunning ? "Running..." : "Run Analysis"}
            </button>
            <button
              onClick={() => refetchOverview()}
              title="Refresh results"
              className="p-2 text-sm border border-border rounded-lg hover:bg-muted"
            >
              <RefreshIcon fontSize="small" />
            </button>
          </div>
        </div>
      </div>

      {/* Loading / Running state */}
      {(overviewLoading || analysisRunning) && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <CircularProgress size={32} />
          <span className="mt-3 text-sm">
            {analysisRunning
              ? "Analysis in progress\u2026 refreshing every 5 seconds."
              : "Loading analysis\u2026"}
          </span>
        </div>
      )}

      {/* No results */}
      {!overviewLoading && !analysisRunning && !overview?.available && (
        <div className="text-center py-12 text-muted-foreground">
          <HubIcon sx={{ fontSize: 48 }} className="text-muted-foreground/30 mb-3" />
          <p className="mb-2">No analysis results available yet.</p>
          <p className="text-sm">Select a knowledge graph and click "Run Analysis" to start.</p>
        </div>
      )}

      {/* Results */}
      {!analysisRunning && overview?.available && fleet && (
        <>
          <FleetOverview fleet={fleet} />

          {/* Root Cause Distribution */}
          {fleet.root_cause_distribution && Object.keys(fleet.root_cause_distribution).length > 0 && (
            <div className="bg-card border border-border rounded-xl p-5 mb-5">
              <h2 className="text-lg font-semibold mb-3">Root Cause Distribution</h2>
              <Plot
                data={[
                  {
                    labels: Object.keys(fleet.root_cause_distribution),
                    values: Object.values(fleet.root_cause_distribution),
                    type: "pie",
                    textinfo: "label+value",
                    marker: {
                      colors: ["#ef5350", "#FF9800", "#4CAF50", "#2196F3", "#9C27B0", "#607D8B", "#795548", "#00BCD4"],
                    },
                  },
                ]}
                layout={{
                  height: 280,
                  margin: { t: 10, b: 10, l: 10, r: 10 },
                  paper_bgcolor: "transparent",
                  font: { size: 11 },
                }}
                config={{ displayModeBar: false, responsive: true }}
                className="w-full"
              />
            </div>
          )}

          {/* CPE selector */}
          <div className="bg-card border border-border rounded-xl p-5 mb-5">
            <h2 className="text-lg font-semibold mb-3">
              CPE Devices ({overview.per_cpe_count ?? 0})
            </h2>
            <div className="flex flex-wrap gap-2">
              {(overview.per_cpe_serials ?? []).map((serial) => (
                <button
                  key={serial}
                  onClick={() => setSelectedCPE(selectedCPE === serial ? null : serial)}
                  className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                    selectedCPE === serial
                      ? "bg-blue-600 text-white border-blue-600"
                      : "bg-card border-border hover:bg-muted"
                  }`}
                >
                  {serial}
                </button>
              ))}
            </div>
          </div>

          {/* Per-CPE detail */}
          {selectedCPE && (
            <div className="bg-card border border-border rounded-xl p-5 mb-5">
              {cpeLoading ? (
                <div className="flex items-center justify-center py-8">
                  <CircularProgress size={24} />
                  <span className="ml-2 text-muted-foreground text-sm">Loading CPE analysis...</span>
                </div>
              ) : cpeReport ? (
                <CPEDetail report={cpeReport} />
              ) : (
                <p className="text-sm text-muted-foreground">No data for {selectedCPE}</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fleet Overview
// ---------------------------------------------------------------------------

function FleetOverview({
  fleet,
}: {
  fleet: NonNullable<IssueAnalysisOverview["fleet_report"]>;
}) {
  const ro = fleet.reboot_overview;
  const pa = fleet.problem_areas;
  const td = fleet.trigger_distribution;

  return (
    <div className="bg-card border border-border rounded-xl p-5 mb-5">
      <div className="flex items-center gap-2 mb-4">
        <h2 className="text-lg font-semibold">Fleet Overview</h2>
        {fleet.graph_name && (
          <span className="text-xs px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
            {fleet.graph_name}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <StatCard label="Total CPEs" value={fleet.total_cpes} />
        <StatCard label="Total Reboots" value={ro.total_reboots} />
        <StatCard label="CPEs with Reboots" value={ro.cpes_with_reboots} sub={`${ro.pct_with_reboots}%`} />
        <StatCard label="Avg Reboots/CPE" value={ro.avg_reboots_per_cpe} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
        <div className="bg-orange-50 dark:bg-orange-950/30 border border-orange-200 dark:border-orange-800 rounded-lg p-3">
          <div className="text-xs text-orange-600 dark:text-orange-400 font-medium uppercase">WiFi Issues</div>
          <div className="text-xl font-bold text-orange-800 dark:text-orange-200">{pa.wifi.cpes_affected} CPEs</div>
          <div className="text-xs text-orange-500">{pa.wifi.pct_affected}% affected</div>
        </div>
        <div className="bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg p-3">
          <div className="text-xs text-blue-600 dark:text-blue-400 font-medium uppercase">WAN Issues</div>
          <div className="text-xl font-bold text-blue-800 dark:text-blue-200">{pa.wan.cpes_affected} CPEs</div>
          <div className="text-xs text-blue-500">{pa.wan.pct_affected}% affected</div>
        </div>
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg p-3">
          <div className="text-xs text-red-600 dark:text-red-400 font-medium uppercase">Memory &gt;85%</div>
          <div className="text-xl font-bold text-red-800 dark:text-red-200">{pa.memory.cpes_above_85pct} CPEs</div>
          <div className="text-xs text-red-500">{pa.memory.pct_above_85pct}% affected</div>
        </div>
      </div>

      {Object.keys(td).length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-medium text-muted-foreground mb-2">Trigger Distribution</h3>
          <Plot
            data={[
              {
                labels: Object.keys(td),
                values: Object.values(td),
                type: "pie",
                textinfo: "label+value",
                marker: {
                  colors: ["#ef5350", "#FF9800", "#4CAF50", "#2196F3", "#9C27B0", "#607D8B", "#795548", "#00BCD4"],
                },
              },
            ]}
            layout={{
              height: 250,
              margin: { t: 10, b: 10, l: 10, r: 10 },
              paper_bgcolor: "transparent",
              font: { size: 11 },
            }}
            config={{ displayModeBar: false, responsive: true }}
            className="w-full"
          />
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-xs">
        {Object.entries(fleet.hardware_breakdown).map(([k, v]) => (
          <span key={k} className="px-2 py-1 bg-muted rounded-md text-muted-foreground">{k}: {v}</span>
        ))}
        {Object.entries(fleet.firmware_breakdown).map(([k, v]) => (
          <span key={k} className="px-2 py-1 bg-muted rounded-md text-muted-foreground">{k}: {v}</span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CPE Detail
// ---------------------------------------------------------------------------

function CPEDetail({ report }: { report: IssueAnalysisCPEReport }) {
  const ident = report.identity;
  const ts = report.telemetry_timeseries;
  const timestamps = ts?.timestamps ?? [];
  const rebootTs = report.reboots.map((r) => r.timestamp);

  const rebootShapes = rebootTs.map((t) => ({
    type: "line" as const,
    x0: t, x1: t, y0: 0, y1: 1,
    yref: "paper" as const,
    line: { color: "red", width: 2, dash: "dash" as const },
  }));

  const chartLayout = (title: string, yTitle: string, extra: Record<string, unknown> = {}) => ({
    height: 220,
    margin: { t: 30, b: 30, l: 55, r: 20 },
    title: { text: title, font: { size: 13 } },
    shapes: rebootShapes,
    xaxis: { type: "date" as const },
    yaxis: { title: { text: yTitle } },
    paper_bgcolor: "transparent",
    plot_bgcolor: "rgba(0,0,0,0.02)",
    font: { size: 11 },
    showlegend: true,
    legend: { orientation: "h" as const, y: -0.2 },
    ...extra,
  });

  const plotCfg = { displayModeBar: false, responsive: true };

  return (
    <div>
      {/* Identity */}
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-lg font-bold">{ident.cpe_serial}</h2>
        <span className="text-xs px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded">
          {report.telemetry_source}
        </span>
        {report.graph_name && (
          <span className="text-xs px-2 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded">
            {report.graph_name}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground mb-4">
        <span>MAC: {ident.mac || "N/A"}</span>
        <span>Model: {ident.model || "N/A"}</span>
        <span>Firmware: {ident.firmware || "N/A"}</span>
        <span>Reboots: {report.total_reboots}</span>
        {report.memory_summary.avg_pct != null && (
          <span>Memory: {report.memory_summary.avg_pct}% avg / {report.memory_summary.peak_pct}% peak</span>
        )}
      </div>

      {/* Root Causes */}
      {report.root_causes.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-semibold mb-2">Root Cause Ranking</h3>
          <div className="space-y-2">
            {report.root_causes.map((rc, i) => (
              <div key={rc.node_id} className="flex items-center gap-2 p-2 rounded-lg border border-border">
                <span className="text-xs font-bold text-muted-foreground w-5">#{i + 1}</span>
                <div className="flex-1">
                  <span className="text-sm font-medium">{rc.label}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    confidence: {(rc.confidence * 100).toFixed(0)}% | evidence: {rc.evidence_count}
                  </span>
                </div>
                <div className="w-20 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${rc.score * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Causal Chains */}
      {report.causal_chains.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-semibold mb-2">Causal Chains Detected</h3>
          <div className="space-y-1.5">
            {report.causal_chains.slice(0, 10).map((chain, i) => (
              <div key={i} className="flex items-center gap-1 text-xs flex-wrap">
                {chain.path.map((step, j) => (
                  <span key={j} className="flex items-center gap-1">
                    {j > 0 && <span className="text-muted-foreground">&rarr;</span>}
                    <span className="px-1.5 py-0.5 rounded bg-muted font-mono">{step}</span>
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Aggregate Issues */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        {Object.entries(report.aggregate_issues)
          .filter(([, v]) => v > 0)
          .sort(([, a], [, b]) => b - a)
          .map(([cat, count]) => (
            <span key={cat} className={`px-2 py-0.5 rounded text-xs font-medium ${severityClass(cat)}`}>
              {cat}: {count}
            </span>
          ))}
      </div>

      {/* Reboot Events */}
      <h3 className="text-sm font-semibold mb-2">Reboot Events</h3>
      <div className="space-y-2 mb-5">
        {report.reboots.map((rb, i) => (
          <RebootEventCard key={i} rb={rb} />
        ))}
        {report.reboots.length === 0 && (
          <p className="text-sm text-muted-foreground">No reboots detected</p>
        )}
      </div>

      {/* Telemetry Charts */}
      {timestamps.length > 0 && (
        <>
          <h3 className="text-sm font-semibold mb-2">Telemetry Charts</h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <Plot
              data={[{ x: timestamps, y: ts.cpu, type: "scatter", name: "CPU %", line: { color: "#4CAF50" } }]}
              layout={chartLayout("CPU Usage (%)", "%")}
              config={plotCfg}
              className="w-full"
            />
            <Plot
              data={[{ x: timestamps, y: ts.memory_pct, type: "scatter", name: "Memory %", fill: "tozeroy", line: { color: "#FF9800" } }]}
              layout={chartLayout("Memory Usage (%)", "%", { yaxis: { title: { text: "%" }, range: [0, 100] } })}
              config={plotCfg}
              className="w-full"
            />
            <Plot
              data={[{ x: timestamps, y: ts.temperature, type: "scatter", name: "Temperature", line: { color: "#f44336" } }]}
              layout={chartLayout("Temperature (C)", "C")}
              config={plotCfg}
              className="w-full"
            />
            <Plot
              data={[{ x: timestamps, y: ts.connected_devices, type: "scatter", name: "Connected Devices", fill: "tozeroy", line: { color: "#607D8B" } }]}
              layout={chartLayout("Connected Devices", "Count")}
              config={plotCfg}
              className="w-full"
            />
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reboot Event Card
// ---------------------------------------------------------------------------

function RebootEventCard({ rb }: { rb: IssueAnalysisCPEReport["reboots"][number] }) {
  const [expanded, setExpanded] = useState(false);
  const topIssues = Object.entries(rb.window_events)
    .filter(([, ev]) => ev.count > 0)
    .sort(([, a], [, b]) => b.count - a.count);

  return (
    <div className="border border-border rounded-lg p-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="font-mono text-sm font-semibold">{rb.timestamp}</span>
        <span className="text-xs px-2 py-0.5 bg-muted rounded text-muted-foreground">{rb.reason || "unknown"}</span>
        <span className={`text-xs px-2 py-0.5 rounded font-medium ${severityClass(rb.likely_trigger)}`}>
          {rb.trigger_description}
        </span>
        <span className="text-xs text-muted-foreground ml-auto">{rb.total_events_in_window} events</span>
        {topIssues.length > 0 && (
          <button onClick={() => setExpanded(!expanded)} className="p-0.5 rounded hover:bg-muted">
            {expanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
          </button>
        )}
      </div>
      {expanded && topIssues.length > 0 && (
        <div className="mt-3 space-y-2">
          {topIssues.map(([cat, ev]) => (
            <div key={cat}>
              <div className="text-xs font-medium text-muted-foreground mb-1">{cat} ({ev.count} events)</div>
              {ev.sample_lines.slice(0, 3).map((line, i) => (
                <pre key={i} className="text-[11px] bg-muted rounded px-2 py-1 overflow-x-auto whitespace-pre-wrap break-all mb-1">{line}</pre>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-muted/50 rounded-lg p-3">
      <div className="text-xs text-muted-foreground uppercase tracking-wider">{label}</div>
      <div className="text-xl font-bold">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

function severityClass(cat: string): string {
  const high = new Set(["kernel_crash", "memory_issues", "wifi_driver_errors", "ccsp_process_crash"]);
  const medium = new Set(["wifi_disconnect_storm", "wan_disconnections", "btm_steering"]);
  if (high.has(cat)) return "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300";
  if (medium.has(cat)) return "bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300";
  return "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300";
}

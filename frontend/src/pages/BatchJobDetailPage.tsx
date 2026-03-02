import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams, useNavigate } from "react-router-dom";
import { batchJobsApi, type CPEProcessRecord, type RebootFleetSummary } from "@/api/endpoints";
import CircularProgress from "@mui/material/CircularProgress";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import CancelIcon from "@mui/icons-material/Cancel";
import ReplayIcon from "@mui/icons-material/Replay";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import PendingIcon from "@mui/icons-material/Pending";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import DownloadIcon from "@mui/icons-material/Download";
import RefreshIcon from "@mui/icons-material/Refresh";
import AssessmentIcon from "@mui/icons-material/Assessment";

export default function BatchJobDetailPage() {
  const { projectId, jobId } = useParams<{ projectId: string; jobId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  // Fetch job details
  const { data: jobData, isLoading: jobLoading } = useQuery({
    queryKey: ["batchJob", projectId, jobId],
    queryFn: () => batchJobsApi.get(projectId!, jobId!),
    enabled: !!projectId && !!jobId,
    refetchInterval: 3000, // Poll every 3 seconds
  });

  // Fetch CPE records
  const { data: cpesData, isLoading: cpesLoading } = useQuery({
    queryKey: ["batchJobCPEs", projectId, jobId, statusFilter],
    queryFn: () => batchJobsApi.listCPEs(projectId!, jobId!, statusFilter),
    enabled: !!projectId && !!jobId,
    refetchInterval: 3000,
  });

  const job = jobData?.data;
  const cpes = cpesData?.data?.cpes || [];

  // Retry failed CPEs mutation
  const retryMutation = useMutation({
    mutationFn: () => batchJobsApi.retry(projectId!, jobId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batchJob", projectId, jobId] });
      queryClient.invalidateQueries({ queryKey: ["batchJobCPEs", projectId, jobId] });
    },
  });

  // Cancel job mutation
  const cancelMutation = useMutation({
    mutationFn: () => batchJobsApi.cancel(projectId!, jobId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batchJob", projectId, jobId] });
    },
  });

  // Reboot summary
  const { data: summaryData, isLoading: summaryLoading, refetch: refetchSummary } = useQuery({
    queryKey: ["rebootSummary", projectId, jobId],
    queryFn: () => batchJobsApi.getRebootSummary(projectId!, jobId!),
    enabled: !!projectId && !!jobId && job?.status === "completed",
    retry: false,
  });

  const regenMutation = useMutation({
    mutationFn: () => batchJobsApi.regenerateRebootSummary(projectId!, jobId!),
    onSuccess: () => {
      setTimeout(() => refetchSummary(), 5000);
    },
  });

  const handleDownload = async (type: "fleet" | "per_cpe") => {
    try {
      const resp = await batchJobsApi.downloadRebootSummary(projectId!, jobId!, type);
      const blob = new Blob([resp.data as BlobPart]);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = type === "fleet"
        ? `fleet_reboot_summary_${jobId?.slice(0, 8)}.json`
        : `reboot_summary_per_cpe_${jobId?.slice(0, 8)}.jsonl`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      // silently ignore download errors
    }
  };

  const summary = summaryData?.data?.fleet_summary as RebootFleetSummary | undefined;

  const formatDuration = (seconds?: number) => {
    if (!seconds) return "N/A";
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hours > 0) return `${hours}h ${minutes}m ${secs}s`;
    if (minutes > 0) return `${minutes}m ${secs}s`;
    return `${secs}s`;
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CheckCircleIcon className="text-green-600" style={{ fontSize: 20 }} />;
      case "failed":
        return <ErrorIcon className="text-red-600" style={{ fontSize: 20 }} />;
      case "processing":
        return <CircularProgress size={16} className="text-blue-600" />;
      case "pending":
        return <HourglassEmptyIcon className="text-yellow-600" style={{ fontSize: 20 }} />;
      case "skipped":
        return <PendingIcon className="text-gray-600" style={{ fontSize: 20 }} />;
      default:
        return null;
    }
  };

  if (jobLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <CircularProgress />
      </div>
    );
  }

  if (!job) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <p className="text-red-600">Job not found</p>
      </div>
    );
  }

  const failedCPEs = cpes.filter((c) => c.status === "failed");

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={() => navigate(`/projects/${projectId}/batch-jobs`)}
          className="p-2 hover:bg-muted rounded-lg transition-colors"
        >
          <ArrowBackIcon />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-foreground">Batch Job Details</h1>
          <p className="text-sm text-muted-foreground mt-1">Job ID: {jobId}</p>
        </div>
        {job.status === "processing" && (
          <button
            onClick={() => {
              if (confirm("Cancel this batch job?")) {
                cancelMutation.mutate();
              }
            }}
            disabled={cancelMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 border border-red-600 text-red-600 rounded-lg hover:bg-red-50 transition-colors"
          >
            <CancelIcon style={{ fontSize: 20 }} />
            Cancel Job
          </button>
        )}
        {failedCPEs.length > 0 && (
          <button
            onClick={() => retryMutation.mutate()}
            disabled={retryMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          >
            <ReplayIcon style={{ fontSize: 20 }} />
            Retry Failed ({failedCPEs.length})
          </button>
        )}
      </div>

      {/* Job Status Card */}
      <div className="bg-card border border-border rounded-xl p-6 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div>
            <div className="text-sm text-muted-foreground mb-1">Status</div>
            <div className="text-2xl font-semibold capitalize">{job.status}</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground mb-1">Progress</div>
            <div className="text-2xl font-semibold">
              {job.processed_cpes + job.failed_cpes} / {job.total_cpes}
            </div>
            <div className="w-full bg-muted rounded-full h-2 mt-2">
              <div
                className="bg-primary h-2 rounded-full transition-all duration-300"
                style={{ width: `${job.progress_percent}%` }}
              />
            </div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground mb-1">Success Rate</div>
            <div className="text-2xl font-semibold">
              {job.total_cpes > 0
                ? ((job.processed_cpes / (job.processed_cpes + job.failed_cpes || 1)) * 100).toFixed(1)
                : 0}
              %
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-6 border-t border-border">
          <div>
            <div className="text-sm text-muted-foreground">Completed</div>
            <div className="text-xl font-semibold text-green-600">{job.processed_cpes}</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">Failed</div>
            <div className="text-xl font-semibold text-red-600">{job.failed_cpes}</div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">Elapsed Time</div>
            <div className="text-xl font-semibold">{formatDuration(job.elapsed_sec)}</div>
          </div>
          {job.eta_sec && job.status === "processing" && (
            <div>
              <div className="text-sm text-muted-foreground">ETA</div>
              <div className="text-xl font-semibold">{formatDuration(job.eta_sec)}</div>
            </div>
          )}
        </div>

        {job.error_message && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
            <strong>Error:</strong> {job.error_message}
          </div>
        )}
      </div>

      {/* Reboot Summary Section */}
      {job.status === "completed" && (
        <div className="bg-card border border-border rounded-xl p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <AssessmentIcon className="text-primary" />
              <h2 className="text-lg font-semibold">Reboot Root-Cause Summary</h2>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => regenMutation.mutate()}
                disabled={regenMutation.isPending}
                className="flex items-center gap-1 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                title="Regenerate the reboot summary from scratch"
              >
                <RefreshIcon style={{ fontSize: 16 }} />
                {regenMutation.isPending ? "Generating..." : "Regenerate"}
              </button>
              {summary && (
                <>
                  <button
                    onClick={() => handleDownload("fleet")}
                    className="flex items-center gap-1 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                    title="Download fleet aggregate JSON"
                  >
                    <DownloadIcon style={{ fontSize: 16 }} />
                    Fleet JSON
                  </button>
                  <button
                    onClick={() => handleDownload("per_cpe")}
                    className="flex items-center gap-1 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted transition-colors"
                    title="Download per-CPE JSONL for LLM input"
                  >
                    <DownloadIcon style={{ fontSize: 16 }} />
                    Per-CPE JSONL
                  </button>
                </>
              )}
            </div>
          </div>

          {summaryLoading ? (
            <div className="flex items-center justify-center py-8">
              <CircularProgress size={24} />
              <span className="ml-2 text-muted-foreground text-sm">Loading summary...</span>
            </div>
          ) : !summary ? (
            <div className="text-center py-6 text-muted-foreground">
              <p className="mb-2">No reboot summary available yet.</p>
              <p className="text-xs">
                Click "Regenerate" to generate the LLM-ready reboot root-cause analysis.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Overview Stats */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-3 bg-muted/50 rounded-lg">
                  <div className="text-xs text-muted-foreground uppercase">CPEs Analyzed</div>
                  <div className="text-xl font-semibold">{summary.sample_info.total_cpes}</div>
                </div>
                <div className="p-3 bg-muted/50 rounded-lg">
                  <div className="text-xs text-muted-foreground uppercase">Total Reboots</div>
                  <div className="text-xl font-semibold text-red-600">{summary.reboot_overview.total_reboots}</div>
                  <div className="text-xs text-muted-foreground">
                    {summary.reboot_overview.pct_with_reboots}% of CPEs affected
                  </div>
                </div>
                <div className="p-3 bg-muted/50 rounded-lg">
                  <div className="text-xs text-muted-foreground uppercase">WAN Disconnections</div>
                  <div className="text-xl font-semibold text-orange-600">{summary.wan_overview.total_disconnections}</div>
                  <div className="text-xs text-muted-foreground">
                    {summary.wan_overview.pct_affected}% of CPEs affected
                  </div>
                </div>
                <div className="p-3 bg-muted/50 rounded-lg">
                  <div className="text-xs text-muted-foreground uppercase">Unknown Cause</div>
                  <div className="text-xl font-semibold text-yellow-600">{summary.unknown_cohort.length}</div>
                  <div className="text-xs text-muted-foreground">CPEs with unexplained reboots</div>
                </div>
              </div>

              {/* Problem Categories */}
              <div>
                <h3 className="text-sm font-semibold text-muted-foreground uppercase mb-2">Problem Categories</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="p-3 border border-border rounded-lg">
                    <div className="text-sm font-medium">WiFi Issues</div>
                    <div className="text-lg font-semibold">{summary.problem_categories.wifi.cpes_affected} CPEs</div>
                    <div className="text-xs text-muted-foreground">{summary.problem_categories.wifi.pct_affected}% of fleet</div>
                    {summary.client_churn_stats.cpes_with_sustained_storms > 0 && (
                      <div className="text-xs text-red-600 mt-1">
                        {summary.client_churn_stats.cpes_with_sustained_storms} with disconnect storms
                      </div>
                    )}
                  </div>
                  <div className="p-3 border border-border rounded-lg">
                    <div className="text-sm font-medium">WAN Issues</div>
                    <div className="text-lg font-semibold">{summary.problem_categories.wan.cpes_affected} CPEs</div>
                    <div className="text-xs text-muted-foreground">{summary.problem_categories.wan.pct_affected}% of fleet</div>
                    {summary.gpon_wan_health.cpes_with_signal_degrade > 0 && (
                      <div className="text-xs text-orange-600 mt-1">
                        {summary.gpon_wan_health.cpes_with_signal_degrade} with GPON signal issues
                      </div>
                    )}
                  </div>
                  <div className="p-3 border border-border rounded-lg">
                    <div className="text-sm font-medium">Memory Issues</div>
                    <div className="text-lg font-semibold">{summary.problem_categories.memory.cpes_above_85pct} CPEs</div>
                    <div className="text-xs text-muted-foreground">{summary.problem_categories.memory.pct_above_85pct}% above 85% usage</div>
                  </div>
                </div>
              </div>

              {/* Cause Distribution */}
              {Object.keys(summary.cause_distribution).length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground uppercase mb-2">Root Cause Distribution</h3>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(summary.cause_distribution)
                      .sort(([, a], [, b]) => b - a)
                      .map(([cause, count]) => (
                        <span
                          key={cause}
                          className="px-2 py-1 bg-muted rounded text-xs font-mono"
                          title={`${count} CPEs with ${cause} as primary suspected cause`}
                        >
                          {cause.replace(/_/g, " ")}: {count}
                        </span>
                      ))}
                  </div>
                </div>
              )}

              {/* Failure Chains */}
              {Object.keys(summary.failure_chain_distribution).length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-muted-foreground uppercase mb-2">Failure Chains Detected</h3>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(summary.failure_chain_distribution)
                      .sort(([, a], [, b]) => b - a)
                      .map(([chain, count]) => (
                        <span
                          key={chain}
                          className="px-2 py-1 bg-orange-100 dark:bg-orange-950 text-orange-800 dark:text-orange-200 rounded text-xs"
                        >
                          {chain.replace(/_/g, " ")}: {count} CPEs
                        </span>
                      ))}
                  </div>
                </div>
              )}

              {/* Telemetry Source & Data Quality */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs text-muted-foreground">
                <div>
                  <span className="font-medium">Telemetry Sources:</span>{" "}
                  {Object.entries(summary.telemetry_source_distribution).map(([src, cnt]) => (
                    <span key={src} className="mr-2">{src}: {cnt}</span>
                  ))}
                </div>
                <div>
                  <span className="font-medium">Data Quality:</span>{" "}
                  {summary.data_quality.pct_with_telemetry}% with telemetry |{" "}
                  Generated {new Date(summary.generated_at).toLocaleString()}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* CPE Records */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 className="text-lg font-semibold">CPE Processing Records</h2>
          <div className="flex gap-2">
            <button
              onClick={() => setStatusFilter(undefined)}
              className={`px-3 py-1 rounded text-sm ${
                !statusFilter ? "bg-primary text-primary-foreground" : "bg-muted"
              }`}
            >
              All ({cpes.length})
            </button>
            <button
              onClick={() => setStatusFilter("pending")}
              className={`px-3 py-1 rounded text-sm ${
                statusFilter === "pending" ? "bg-yellow-600 text-white" : "bg-muted"
              }`}
            >
              Pending/Queued
            </button>
            <button
              onClick={() => setStatusFilter("processing")}
              className={`px-3 py-1 rounded text-sm ${
                statusFilter === "processing" ? "bg-blue-600 text-white" : "bg-muted"
              }`}
            >
              Processing
            </button>
            <button
              onClick={() => setStatusFilter("completed")}
              className={`px-3 py-1 rounded text-sm ${
                statusFilter === "completed" ? "bg-green-600 text-white" : "bg-muted"
              }`}
            >
              Completed
            </button>
            <button
              onClick={() => setStatusFilter("failed")}
              className={`px-3 py-1 rounded text-sm ${
                statusFilter === "failed" ? "bg-red-600 text-white" : "bg-muted"
              }`}
            >
              Failed
            </button>
          </div>
        </div>

        {cpesLoading ? (
          <div className="flex items-center justify-center py-12">
            <CircularProgress />
          </div>
        ) : cpes.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            No CPE records found
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-muted/50">
                <tr>
                  <th className="text-left px-4 py-3 text-sm font-medium">Serial</th>
                  <th className="text-left px-4 py-3 text-sm font-medium">Status</th>
                  <th className="text-right px-4 py-3 text-sm font-medium">Logs</th>
                  <th className="text-right px-4 py-3 text-sm font-medium">Patterns</th>
                  <th className="text-right px-4 py-3 text-sm font-medium">Duration</th>
                  <th className="text-left px-4 py-3 text-sm font-medium">Error</th>
                </tr>
              </thead>
              <tbody>
                {cpes.map((cpe: CPEProcessRecord) => (
                  <tr key={cpe.record_id} className="border-t border-border hover:bg-muted/30">
                    <td className="px-4 py-3 font-mono text-sm">{cpe.serial}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {getStatusIcon(cpe.status)}
                        <span className="text-sm capitalize">{cpe.status}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right text-sm">{cpe.logs_extracted || 0}</td>
                    <td className="px-4 py-3 text-right text-sm">{cpe.patterns_indexed || 0}</td>
                    <td className="px-4 py-3 text-right text-sm">
                      {cpe.processing_time_sec ? `${cpe.processing_time_sec.toFixed(1)}s` : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm text-red-600 max-w-xs truncate">
                      {cpe.error_message || "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

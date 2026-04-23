import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams, useNavigate } from "react-router-dom";
import { batchJobsApi, type CPEProcessRecord } from "@/api/endpoints";
import CircularProgress from "@mui/material/CircularProgress";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import CancelIcon from "@mui/icons-material/Cancel";
import ReplayIcon from "@mui/icons-material/Replay";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import PendingIcon from "@mui/icons-material/Pending";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";

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
    refetchInterval: (query) => {
      // Only poll if job is still active (queued or processing)
      const job = query.state.data?.data;
      const isActive = job?.status === "queued" || job?.status === "processing";
      return isActive ? 3000 : false; // Poll every 3 seconds if active, stop if complete
    },
  });

  // Fetch CPE records
  const { data: cpesData, isLoading: cpesLoading } = useQuery({
    queryKey: ["batchJobCPEs", projectId, jobId, statusFilter],
    queryFn: () => batchJobsApi.listCPEs(projectId!, jobId!, statusFilter),
    enabled: !!projectId && !!jobId,
    refetchInterval: () => {
      // Only poll if parent job is still active
      const job = jobData?.data;
      const isActive = job?.status === "queued" || job?.status === "processing";
      return isActive ? 3000 : false;
    },
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
        return <CheckCircleIcon className="text-emerald-600 dark:text-emerald-400 shrink-0" style={{ fontSize: 20 }} />;
      case "failed":
        return <ErrorIcon className="text-destructive shrink-0" style={{ fontSize: 20 }} />;
      case "processing":
        return <CircularProgress size={16} className="text-sky-600 dark:text-sky-400 shrink-0" />;
      case "pending":
        return <HourglassEmptyIcon className="text-amber-600 dark:text-amber-400 shrink-0" style={{ fontSize: 20 }} />;
      case "skipped":
        return <PendingIcon className="text-muted-foreground shrink-0" style={{ fontSize: 20 }} />;
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
      <div className="w-full min-w-0 px-4 py-6 sm:px-6 lg:px-8">
        <p className="text-destructive">Job not found</p>
      </div>
    );
  }

  const failedCPEs = cpes.filter((c) => c.status === "failed");

  return (
    <div className="w-full min-w-0 max-w-full px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center mb-6">
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
            className="flex items-center gap-2 px-4 py-2 border border-destructive text-destructive rounded-lg hover:bg-destructive/10 transition-colors"
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
      <div className="bg-card border border-border rounded-xl p-6 mb-6 w-full min-w-0">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
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

        <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-6 border-t border-border">
          <div>
            <div className="text-sm text-muted-foreground">Completed</div>
            <div className="text-xl font-semibold text-emerald-600 dark:text-emerald-400">{job.processed_cpes}</div>
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
          <div className="mt-4 p-3 bg-destructive/10 border border-destructive/25 rounded-lg text-sm text-destructive">
            <strong>Error:</strong> {job.error_message}
          </div>
        )}
      </div>

      {/* CPE Records */}
      <div className="bg-card border border-border rounded-xl overflow-hidden w-full min-w-0">
        <div className="p-4 border-b border-border flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <h2 className="text-lg font-semibold">CPE Processing Records</h2>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setStatusFilter(undefined)}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                !statusFilter
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-muted border-border text-foreground hover:bg-muted/80"
              }`}
            >
              All ({cpes.length})
            </button>
            <button
              onClick={() => setStatusFilter("pending")}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                statusFilter === "pending"
                  ? "bg-amber-500/20 border-amber-500/45 text-amber-900 dark:text-amber-100"
                  : "bg-muted border-border hover:bg-muted/80"
              }`}
            >
              Pending/Queued
            </button>
            <button
              onClick={() => setStatusFilter("processing")}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                statusFilter === "processing"
                  ? "bg-sky-500/20 border-sky-500/45 text-sky-900 dark:text-sky-100"
                  : "bg-muted border-border hover:bg-muted/80"
              }`}
            >
              Processing
            </button>
            <button
              onClick={() => setStatusFilter("completed")}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                statusFilter === "completed"
                  ? "bg-emerald-500/20 border-emerald-500/45 text-emerald-900 dark:text-emerald-100"
                  : "bg-muted border-border hover:bg-muted/80"
              }`}
            >
              Completed
            </button>
            <button
              onClick={() => setStatusFilter("failed")}
              className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                statusFilter === "failed"
                  ? "bg-destructive/15 border-destructive/40 text-destructive"
                  : "bg-muted border-border hover:bg-muted/80"
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
          <div className="p-4">
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {cpes.map((cpe: CPEProcessRecord) => (
                <div
                  key={cpe.record_id}
                  className="rounded-lg border border-border bg-muted/20 p-3 min-w-0 flex flex-col gap-2 hover:bg-muted/30 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-mono text-sm text-foreground truncate" title={cpe.serial}>
                      {cpe.serial}
                    </span>
                    {getStatusIcon(cpe.status)}
                  </div>
                  <p className="text-xs capitalize text-muted-foreground">{cpe.status}</p>
                  <div className="grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
                    <div>
                      <span className="block text-[10px] uppercase tracking-wide">Logs</span>
                      <span className="font-medium text-foreground">{cpe.logs_extracted || 0}</span>
                    </div>
                    <div>
                      <span className="block text-[10px] uppercase tracking-wide">Patterns</span>
                      <span className="font-medium text-foreground">{cpe.patterns_indexed || 0}</span>
                    </div>
                    <div>
                      <span className="block text-[10px] uppercase tracking-wide">Time</span>
                      <span className="font-medium text-foreground">
                        {cpe.processing_time_sec ? `${cpe.processing_time_sec.toFixed(1)}s` : "—"}
                      </span>
                    </div>
                  </div>
                  {cpe.error_message ? (
                    <p className="text-xs text-destructive line-clamp-3" title={cpe.error_message}>
                      {cpe.error_message}
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground">—</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams, useNavigate } from "react-router-dom";
import { batchJobsApi, type BatchJob } from "@/api/endpoints";
import VisibilityIcon from "@mui/icons-material/Visibility";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import CircularProgress from "@mui/material/CircularProgress";

export default function BatchJobsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [cpeFolderPath, setCpeFolderPath] = useState("");

  // Fetch batch jobs
  const { data: jobsData, isLoading } = useQuery({
    queryKey: ["batchJobs", projectId],
    queryFn: () => batchJobsApi.list(projectId!),
    enabled: !!projectId,
    refetchInterval: 5000, // Poll every 5 seconds
  });

  const jobs = jobsData?.data?.jobs || [];

  // Create batch job mutation
  const createJobMutation = useMutation({
    mutationFn: (folderPath: string) =>
      batchJobsApi.create(projectId!, folderPath),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batchJobs", projectId] });
      setShowCreateDialog(false);
      setCpeFolderPath("");
    },
  });

  // Delete job mutation
  const deleteJobMutation = useMutation({
    mutationFn: (jobId: string) => batchJobsApi.delete(projectId!, jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["batchJobs", projectId] });
    },
  });

  const handleCreateJob = () => {
    if (!cpeFolderPath.trim()) {
      alert("Please enter a valid folder path");
      return;
    }
    createJobMutation.mutate(cpeFolderPath);
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "text-green-600 bg-green-50";
      case "processing":
        return "text-blue-600 bg-blue-50";
      case "failed":
        return "text-red-600 bg-red-50";
      case "cancelled":
        return "text-gray-600 bg-gray-50";
      default:
        return "text-yellow-600 bg-yellow-50";
    }
  };

  const getStatusIcon = (status: string) => {
    if (status === "processing") {
      return <CircularProgress size={16} className="mr-2" />;
    }
    return null;
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return "N/A";
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m`;
    return `${Math.floor(seconds)}s`;
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <CircularProgress />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Batch Jobs</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Process large batches of CPE logs asynchronously
          </p>
        </div>
        <button
          onClick={() => setShowCreateDialog(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
        >
          <AddIcon style={{ fontSize: 20 }} />
          New Batch Job
        </button>
      </div>

      {/* Create Dialog */}
      {showCreateDialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card border border-border rounded-xl p-6 max-w-md w-full mx-4">
            <h2 className="text-xl font-semibold mb-4">Create Batch Job</h2>
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2">
                CPE Folder Name
              </label>
              <input
                type="text"
                value={cpeFolderPath}
                onChange={(e) => setCpeFolderPath(e.target.value)}
                placeholder="cpe_logs_batch_01-100"
                className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Folder name inside /app/batch_cpe_logs/ containing .zip files
              </p>
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => {
                  setShowCreateDialog(false);
                  setCpeFolderPath("");
                }}
                className="px-4 py-2 border border-border rounded-lg hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateJob}
                disabled={createJobMutation.isPending}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {createJobMutation.isPending ? (
                  <CircularProgress size={16} className="mr-2" />
                ) : null}
                Create Job
              </button>
            </div>
            {createJobMutation.isError && (
              <p className="text-sm text-red-600 mt-2">
                Error: {(createJobMutation.error as any)?.response?.data?.error || "Failed to create job"}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Jobs List */}
      {jobs.length === 0 ? (
        <div className="text-center py-12 bg-card border border-border rounded-xl">
          <p className="text-muted-foreground mb-4">No batch jobs yet</p>
          <button
            onClick={() => setShowCreateDialog(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          >
            <AddIcon style={{ fontSize: 20 }} />
            Create Your First Batch Job
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {jobs.map((job: BatchJob) => (
            <div
              key={job.job_id}
              className="bg-card border border-border rounded-xl p-4 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  {/* Status Badge */}
                  <div className="flex items-center gap-3 mb-2">
                    <span
                      className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(
                        job.status
                      )}`}
                    >
                      {getStatusIcon(job.status)}
                      {job.status.toUpperCase()}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {new Date(job.created_at).toLocaleString()}
                    </span>
                  </div>

                  {/* Progress Bar */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between text-sm mb-1">
                      <span className="font-medium">
                        {job.processed_cpes + job.failed_cpes} / {job.total_cpes} CPEs
                      </span>
                      <span className="text-muted-foreground">
                        {job.progress_percent.toFixed(1)}%
                      </span>
                    </div>
                    <div className="w-full bg-muted rounded-full h-2">
                      <div
                        className="bg-primary h-2 rounded-full transition-all duration-300"
                        style={{ width: `${job.progress_percent}%` }}
                      />
                    </div>
                  </div>

                  {/* Stats */}
                  <div className="flex flex-wrap gap-4 text-sm">
                    <div>
                      <span className="text-muted-foreground">Processed:</span>{" "}
                      <span className="font-medium text-green-600">
                        {job.processed_cpes}
                      </span>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Failed:</span>{" "}
                      <span className="font-medium text-red-600">
                        {job.failed_cpes}
                      </span>
                    </div>
                    {job.elapsed_sec && (
                      <div>
                        <span className="text-muted-foreground">Elapsed:</span>{" "}
                        <span className="font-medium">
                          {formatDuration(job.elapsed_sec)}
                        </span>
                      </div>
                    )}
                    {job.eta_sec && job.status === "processing" && (
                      <div>
                        <span className="text-muted-foreground">ETA:</span>{" "}
                        <span className="font-medium">
                          {formatDuration(job.eta_sec)}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Error Message */}
                  {job.error_message && (
                    <div className="mt-2 text-sm text-red-600 bg-red-50 px-3 py-2 rounded">
                      {job.error_message}
                    </div>
                  )}
                </div>

                {/* Actions */}
                <div className="flex gap-2 ml-4">
                  <button
                    onClick={() =>
                      navigate(`/projects/${projectId}/batch-jobs/${job.job_id}`)
                    }
                    className="p-2 hover:bg-muted rounded-lg transition-colors"
                    title="View Details"
                  >
                    <VisibilityIcon style={{ fontSize: 20 }} />
                  </button>
                  {job.status === "completed" ||
                  job.status === "failed" ||
                  job.status === "cancelled" ? (
                    <button
                      onClick={() => {
                        if (
                          confirm("Delete this batch job? This cannot be undone.")
                        ) {
                          deleteJobMutation.mutate(job.job_id);
                        }
                      }}
                      className="p-2 hover:bg-red-50 text-red-600 rounded-lg transition-colors"
                      title="Delete Job"
                    >
                      <DeleteIcon style={{ fontSize: 20 }} />
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

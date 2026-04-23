import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams, useNavigate } from "react-router-dom";
import { batchJobsApi, projectsApi, type BatchJob } from "@/api/endpoints";
import { useChunkedUpload } from "@/hooks/useChunkedUpload";
import VisibilityIcon from "@mui/icons-material/Visibility";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import CancelIcon from "@mui/icons-material/Cancel";
import DownloadIcon from "@mui/icons-material/Download";
import InfoIcon from "@mui/icons-material/Info";
import CircularProgress from "@mui/material/CircularProgress";
import LinearProgress from "@mui/material/LinearProgress";

export default function BatchJobsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [cpeFolderPath, setCpeFolderPath] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadMode, setUploadMode] = useState<"folder" | "file">("folder");

  // Fetch batch jobs
  const { data: jobsData, isLoading } = useQuery({
    queryKey: ["batchJobs", projectId],
    queryFn: () => batchJobsApi.list(projectId!),
    enabled: !!projectId,
    refetchInterval: (query) => {
      // Only poll if there are active jobs (queued or processing)
      const jobs = query.state.data?.data?.jobs || [];
      const hasActiveJobs = jobs.some((job: BatchJob) => 
        job.status === "queued" || job.status === "processing"
      );
      return hasActiveJobs ? 5000 : false; // Poll every 5 seconds if active, stop if all complete
    },
  });

  // Fetch project details for displaying name in instructions
  const { data: projectData } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  });

  const jobs = jobsData?.data?.jobs || [];
  const project = projectData?.data;

  // Chunked upload hook
  const { progress, uploadFile, cancel, reset, isUploading } = useChunkedUpload(
    projectId!,
    {
      onProgress: (progress) => {
        if (progress.status === "completed" && progress.jobId) {
          // Refresh the jobs list when upload completes
          queryClient.invalidateQueries({ queryKey: ["batchJobs", projectId] });
          // Navigate to the job detail page
          navigate(`/projects/${projectId}/batch-jobs/${progress.jobId}`);
        }
      },
    }
  );

  // Create batch job mutation (for folder mode)
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

  const handleCreateJob = async () => {
    if (uploadMode === "folder") {
      if (!cpeFolderPath.trim()) {
        alert("Please enter a valid folder path");
        return;
      }
      createJobMutation.mutate(cpeFolderPath);
    } else {
      if (!selectedFile) {
        alert("Please select a file to upload");
        return;
      }
      try {
        await uploadFile(selectedFile);
        setShowCreateDialog(false);
        setSelectedFile(null);
        reset();
      } catch (error) {
        console.error("Upload failed:", error);
        // Error is already shown in progress
      }
    }
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setSelectedFile(file || null);
  };

  const handleCancel = () => {
    if (isUploading) {
      cancel();
    }
    setShowCreateDialog(false);
    setCpeFolderPath("");
    setSelectedFile(null);
    reset();
  };

  const handleDownloadScript = async () => {
    try {
      const response = await batchJobsApi.downloadScript(projectId!);
      
      // Create blob and download
      const blob = new Blob([response.data], { type: "text/x-python" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "process_cpe_logs.py";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Failed to download script:", error);
      alert("Failed to download script. Please try again.");
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "text-emerald-800 dark:text-emerald-100 bg-emerald-500/12 border border-emerald-500/35";
      case "processing":
        return "text-sky-800 dark:text-sky-100 bg-sky-500/12 border border-sky-500/35";
      case "failed":
        return "text-destructive bg-destructive/10 border border-destructive/35";
      case "cancelled":
        return "text-muted-foreground bg-muted border border-border";
      default:
        return "text-amber-900 dark:text-amber-100 bg-amber-500/12 border border-amber-500/35";
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

  // Check if there are any active jobs
  const hasActiveJobs = jobs.some(job => 
    job.status === "queued" || job.status === "processing"
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <CircularProgress />
      </div>
    );
  }

  return (
    <div className="w-full min-w-0 max-w-full px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Batch Jobs</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Process large batches of CPE logs asynchronously
          </p>
        </div>
        <button
          onClick={() => setShowCreateDialog(true)}
          disabled={hasActiveJobs || isUploading}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          title={
            hasActiveJobs 
              ? "Cannot start new job while another job is running"
              : isUploading 
              ? "Upload in progress"
              : "Create a new batch job"
          }
        >
          <AddIcon style={{ fontSize: 20 }} />
          New Batch Job
        </button>
      </div>

      {/* Create Dialog */}
      {showCreateDialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card border border-border rounded-xl p-6 max-w-lg w-full mx-4">
            <h2 className="text-xl font-semibold mb-4">Create Batch Job</h2>

            {/* Upload Mode Selection */}
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2">Upload Method</label>
              <div className="flex gap-4">
                <label className="flex items-center">
                  <input
                    type="radio"
                    name="uploadMode"
                    value="folder"
                    checked={uploadMode === "folder"}
                    onChange={(e) => setUploadMode(e.target.value as "folder" | "file")}
                    className="mr-2"
                    disabled={isUploading}
                  />
                  Server Folder
                </label>
                <label className="flex items-center">
                  <input
                    type="radio"
                    name="uploadMode"
                    value="file"
                    checked={uploadMode === "file"}
                    onChange={(e) => setUploadMode(e.target.value as "folder" | "file")}
                    className="mr-2"
                    disabled={isUploading}
                  />
                  File Upload
                </label>
              </div>
            </div>

            {uploadMode === "folder" ? (
              <div className="mb-4">
                <label className="block text-sm font-medium mb-2">
                  CPE Folder Name
                </label>
                <input
                  type="text"
                  value={cpeFolderPath}
                  onChange={(e) => setCpeFolderPath(e.target.value)}
                  placeholder="cpe_logs_batch_01-100"
                  title="Folder name under /app/batch_cpe_logs/ containing CPE .zip files"
                  className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                  disabled={isUploading}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  Folder name inside /app/batch_cpe_logs/ containing .zip files
                </p>
              </div>
            ) : (
              <div className="mb-4">
                {/* Instructions Panel */}
                <div className="mb-4 p-4 bg-sky-500/10 border border-sky-500/30 dark:bg-sky-950/30 dark:border-sky-500/25 rounded-lg">
                  <div className="flex items-start gap-2">
                    <InfoIcon className="text-sky-600 dark:text-sky-400 mt-0.5" style={{ fontSize: 16 }} />
                    <div className="flex-1">
                      <h4 className="text-sm font-medium text-foreground mb-2">
                        Prepare Your CPE Logs Locally
                      </h4>
                      <ol className="text-xs text-muted-foreground space-y-1 list-decimal list-inside">
                        <li>Download the processing script using the button below</li>
                        <li>Place the script in your folder containing CPE log subdirectories</li>
                        <li>Run: <code className="bg-muted px-1 rounded text-foreground">python process_cpe_logs.py --target-dir . --project-name {project?.name || "my_project"}</code></li>
                        <li>The script will:
                          <ul className="ml-4 mt-1 space-y-0.5 list-disc list-inside">
                            <li>Remove duplicates and create individual CPE .zip files in archive/</li>
                            <li>Create a final project archive: <strong>{project?.name || "my_project"}.zip</strong></li>
                          </ul>
                        </li>
                        <li>Upload the final <strong>{project?.name || "my_project"}.zip</strong> file using the input below</li>
                      </ol>
                    </div>
                  </div>
                  <button
                    onClick={handleDownloadScript}
                    disabled={isUploading}
                    className="mt-3 inline-flex items-center gap-2 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                  >
                    <DownloadIcon style={{ fontSize: 14 }} />
                    Download process_cpe_logs.py
                  </button>
                </div>

                <label className="block text-sm font-medium mb-2">
                  Archive File
                </label>
                <input
                  type="file"
                  accept=".zip,.tar,.tar.gz,.tgz,.tar.bz2"
                  onChange={handleFileSelect}
                  className="w-full px-3 py-2 border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                  disabled={isUploading}
                />
                {selectedFile && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Selected: {selectedFile.name} ({(selectedFile.size / (1024 * 1024)).toFixed(1)} MB)
                  </p>
                )}
                <p className="text-xs text-muted-foreground mt-2">
                  Multiple log bundles for the <strong>same</strong> CPE (same vendor/MAC prefix before the
                  timestamp or <code className="text-xs bg-muted px-1 rounded">_CPELogs_</code> marker in each file
                  name) are merged into <strong>one</strong> batch job automatically.
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  Upload a .zip archive containing processed CPE files. Supports files up to 10GB with resume capability.
                </p>
              </div>
            )}

            {/* Upload Progress */}
            {isUploading && (
              <div className="mb-4 p-4 bg-muted rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">
                    {progress.status === "uploading" ? "Uploading..." : "Processing..."}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {progress.progress}%
                  </span>
                </div>
                <LinearProgress 
                  variant="determinate" 
                  value={progress.progress} 
                  className="mb-2"
                />
                <div className="text-xs text-muted-foreground">
                  {progress.message && <p>{progress.message}</p>}
                  {progress.status === "uploading" && (
                    <p>
                      {(progress.uploadedBytes / (1024 * 1024)).toFixed(1)} MB / {(progress.totalBytes / (1024 * 1024)).toFixed(1)} MB
                    </p>
                  )}
                </div>
                {progress.error && (
                  <p className="text-sm text-red-600 mt-2">{progress.error}</p>
                )}
              </div>
            )}

            <div className="flex gap-2 justify-end">
              <button
                onClick={handleCancel}
                className="px-4 py-2 border border-border rounded-lg hover:bg-muted transition-colors"
                disabled={progress.status === "processing"}
              >
                {isUploading ? (
                  <>
                    <CancelIcon style={{ fontSize: 16 }} className="mr-2" />
                    Cancel Upload
                  </>
                ) : (
                  "Cancel"
                )}
              </button>
              <button
                onClick={handleCreateJob}
                disabled={
                  isUploading ||
                  createJobMutation.isPending ||
                  (uploadMode === "folder" ? !cpeFolderPath.trim() : !selectedFile)
                }
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {createJobMutation.isPending ? (
                  <CircularProgress size={16} className="mr-2" />
                ) : isUploading ? null : (
                  uploadMode === "file" ? (
                    <CloudUploadIcon style={{ fontSize: 16 }} className="mr-2" />
                  ) : null
                )}
                {uploadMode === "file" && !isUploading ? "Upload & Process" : "Create Job"}
              </button>
            </div>
            {createJobMutation.isError && (
              <p className="text-sm text-red-600 mt-2">
                Error: {createJobMutation.error?.message || "Failed to create job"}
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
            disabled={isUploading}
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            <AddIcon style={{ fontSize: 20 }} />
            Create Your First Batch Job
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {jobs.map((job: BatchJob) => (
            <div
              key={job.job_id}
              className="bg-card border border-border rounded-xl p-4 hover:shadow-md transition-shadow min-w-0 flex flex-col"
            >
              <div className="flex items-start justify-between gap-3 flex-1 min-h-0">
                <div className="flex-1 min-w-0">
                  {/* Status Badge */}
                  <div className="flex items-center gap-3 mb-2">
                    <span
                      className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(
                        job.status
                      )}`}
                      title={
                        job.status === "completed" ? "Job completed successfully" :
                        job.status === "processing" ? "Job is currently processing" :
                        job.status === "failed" ? "Job failed - click for details" :
                        job.status === "cancelled" ? "Job was cancelled" :
                        "Job is queued and waiting to start"
                      }
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
                    <div className="w-full bg-muted rounded-full h-2" title={`${job.processed_cpes + job.failed_cpes} of ${job.total_cpes} CPEs processed (${job.progress_percent.toFixed(1)}%)`}>
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
                      <span className="font-medium text-emerald-600 dark:text-emerald-400">
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
                    <div className="mt-2 text-sm text-destructive bg-destructive/10 border border-destructive/25 px-3 py-2 rounded-lg">
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
                      className="p-2 hover:bg-destructive/10 text-destructive rounded-lg transition-colors"
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

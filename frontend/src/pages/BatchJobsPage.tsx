import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams, useNavigate } from "react-router-dom";
import {
  batchJobsApi,
  projectsApi,
  cpeRemoteLogsApi,
  type BatchJob,
  type RemoteLogFetchJobSummary,
} from "@/api/endpoints";
import { useChunkedUpload } from "@/hooks/useChunkedUpload";
import { useAuth } from "@/hooks/useAuth";
import VisibilityIcon from "@mui/icons-material/Visibility";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import CancelIcon from "@mui/icons-material/Cancel";
import DownloadIcon from "@mui/icons-material/Download";
import InfoIcon from "@mui/icons-material/Info";
import CircularProgress from "@mui/material/CircularProgress";
import LinearProgress from "@mui/material/LinearProgress";
import { RemoteLogLastErrorInline } from "@/components/RemoteLogLastErrorInline";

export default function BatchJobsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  /** Crash-portal/CDN bulk device-list fetch — API is admin-only. */
  const allowRemoteDeviceList = Boolean(user?.is_admin);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [cpeFolderPath, setCpeFolderPath] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadMode, setUploadMode] = useState<"folder" | "file" | "deviceJson">("folder");
  /** Avoid showing remote UI or wrong primary action before state resets (non-admin). */
  const effectiveUploadMode: "folder" | "file" | "deviceJson" =
    !allowRemoteDeviceList && uploadMode === "deviceJson" ? "folder" : uploadMode;
  const [remoteDeviceJsonFile, setRemoteDeviceJsonFile] = useState<File | null>(null);
  const [bulkDefaultStart, setBulkDefaultStart] = useState("");
  const [bulkDefaultEnd, setBulkDefaultEnd] = useState("");
  const [bulkDreBearer, setBulkDreBearer] = useState("");
  const [bulkCrashBearer, setBulkCrashBearer] = useState("");
  const [remoteBulkError, setRemoteBulkError] = useState<string | null>(null);
  const [focusFetchJobId, setFocusFetchJobId] = useState<string | null>(null);
  const [restartWipeArtifacts, setRestartWipeArtifacts] = useState(false);
  const [isDownloadingProjectCpes, setIsDownloadingProjectCpes] = useState(false);

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

  const remoteJobsQuery = useQuery({
    queryKey: ["remoteLogFetchJobs", projectId],
    queryFn: async () =>
      (
        await cpeRemoteLogsApi.listJobs(projectId!)
      ).data as RemoteLogFetchJobSummary[],
    enabled: !!projectId && !!user?.is_admin,
    refetchInterval: (query) => {
      const jobsList = Array.isArray(query.state.data) ? query.state.data : [];
      const hasOpen = jobsList.some(
        (j) =>
          typeof j.status === "string" &&
          !["completed", "failed"].includes(j.status.toLowerCase()),
      );
      return hasOpen ? 5000 : false;
    },
  });

  useEffect(() => {
    const list = remoteJobsQuery.data;
    if (!list?.length || focusFetchJobId) return;
    setFocusFetchJobId(list[0].id);
  }, [remoteJobsQuery.data, focusFetchJobId]);

  useEffect(() => {
    if (!allowRemoteDeviceList && uploadMode === "deviceJson") {
      setUploadMode("folder");
    }
  }, [allowRemoteDeviceList, uploadMode]);

  const remoteJobDetailQuery = useQuery({
    queryKey: ["remoteLogFetchDetail", projectId, focusFetchJobId],
    queryFn: async () =>
      (await cpeRemoteLogsApi.getJob(projectId!, focusFetchJobId!)).data,
    enabled: !!projectId && !!user?.is_admin && !!focusFetchJobId,
    refetchInterval: (query) => {
      const st = query.state.data?.job?.status;
      if (!st || st === "completed" || st === "failed") return false;
      return 4000;
    },
  });
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

  const startRemoteBulkMutation = useMutation({
    mutationFn: async () => {
      if (!remoteDeviceJsonFile || !projectId) {
        throw new Error("Choose a JSON file");
      }
      const fd = new FormData();
      fd.append("device_registry_bearer", bulkDreBearer.trim());
      fd.append("crash_portal_bearer", bulkCrashBearer.trim());
      if (bulkDefaultStart.trim()) fd.append("default_date_start", bulkDefaultStart.trim().slice(0, 10));
      if (bulkDefaultEnd.trim()) fd.append("default_date_end", bulkDefaultEnd.trim().slice(0, 10));
      fd.append("device_list_json", remoteDeviceJsonFile);
      return cpeRemoteLogsApi.startBulk(projectId, fd);
    },
    onSuccess: (res) => {
      setRemoteBulkError(null);
      const fid = res.data.fetch_job_id;
      if (typeof fid === "string") setFocusFetchJobId(fid);
      queryClient.invalidateQueries({ queryKey: ["batchJobs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["remoteLogFetchJobs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["remoteLogFetchDetail", projectId] });
      setShowCreateDialog(false);
      setRemoteDeviceJsonFile(null);
    },
    onError: (e: unknown) => {
      let msg = "Failed to start remote fetch.";
      if (e && typeof e === "object" && "response" in e) {
        const r = (e as { response?: { data?: { error?: string } } }).response;
        if (r?.data?.error) msg = r.data.error;
      } else if (e instanceof Error) msg = e.message;
      setRemoteBulkError(msg);
    },
  });

  const retryRemoteFailedMutation = useMutation({
    mutationFn: async (fetchJobId: string) =>
      cpeRemoteLogsApi.retryFailed(projectId!, fetchJobId, {
        device_registry_bearer: bulkDreBearer.trim(),
        crash_portal_bearer: bulkCrashBearer.trim(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["remoteLogFetchJobs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["remoteLogFetchDetail", projectId] });
    },
    onError: (e: unknown) => {
      let msg = "Retry failed.";
      if (e && typeof e === "object" && "response" in e) {
        const r = (e as { response?: { data?: { error?: string } } }).response;
        if (r?.data?.error) msg = r.data.error;
      }
      alert(msg);
    },
  });

  const restartRemoteJobMutation = useMutation({
    mutationFn: async ({
      fetchJobId,
      wipe,
    }: {
      fetchJobId: string;
      wipe: boolean;
    }) =>
      cpeRemoteLogsApi.restart(projectId!, fetchJobId, {
        device_registry_bearer: bulkDreBearer.trim(),
        crash_portal_bearer: bulkCrashBearer.trim(),
        wipe_artifacts: wipe,
      }),
    onSuccess: () => {
      setRestartWipeArtifacts(false);
      queryClient.invalidateQueries({ queryKey: ["remoteLogFetchJobs", projectId] });
      queryClient.invalidateQueries({ queryKey: ["remoteLogFetchDetail", projectId] });
      queryClient.invalidateQueries({ queryKey: ["batchJobs", projectId] });
    },
    onError: (e: unknown) => {
      let msg = "Restart failed.";
      if (e && typeof e === "object" && "response" in e) {
        const r = (e as { response?: { data?: { error?: string } } }).response;
        if (r?.data?.error) msg = r.data.error;
      }
      alert(msg);
    },
  });

  const handleCreateJob = async () => {
    if (effectiveUploadMode === "folder") {
      if (!cpeFolderPath.trim()) {
        alert("Please enter a valid folder path");
        return;
      }
      createJobMutation.mutate(cpeFolderPath);
      return;
    }
    if (effectiveUploadMode === "file") {
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
      return;
    }

    if (!allowRemoteDeviceList) {
      return;
    }

    setRemoteBulkError(null);
    if (!remoteDeviceJsonFile) {
      alert("Select a device list JSON file.");
      return;
    }
    if (!bulkDreBearer.trim() || !bulkCrashBearer.trim()) {
      alert("Provide both bearer tokens.");
      return;
    }
    try {
      await startRemoteBulkMutation.mutateAsync();
    } catch {
      // surfaced via remoteBulkError
    }
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setSelectedFile(file || null);
  };

  const handleDeviceJsonSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setRemoteDeviceJsonFile(file || null);
    setRemoteBulkError(null);
  };

  const handleCancel = () => {
    if (isUploading) {
      cancel();
    }
    setShowCreateDialog(false);
    setCpeFolderPath("");
    setSelectedFile(null);
    setRemoteDeviceJsonFile(null);
    setRemoteBulkError(null);
    reset();
  };

  const handleDownloadProjectCpes = async () => {
    if (!projectId || isDownloadingProjectCpes) return;
    setIsDownloadingProjectCpes(true);
    try {
      const response = await batchJobsApi.downloadProjectCpesCsv(projectId);
      const blob = new Blob([response.data], { type: "text/csv;charset=utf-8" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const filename =
        (project?.name && `${project.name.replace(/[^\w.\-]+/g, "_")}_cpes.csv`) || "project_cpes.csv";
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Failed to download project CPE list:", error);
      alert("Failed to download CPE list. Please try again.");
    } finally {
      setIsDownloadingProjectCpes(false);
    }
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
        <div className="flex flex-col sm:flex-row gap-2 shrink-0">
          <button
            type="button"
            onClick={handleDownloadProjectCpes}
            disabled={isDownloadingProjectCpes}
            className="flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-muted transition-colors disabled:opacity-60 disabled:cursor-wait"
            title="Download all CPEs registered for this project (CSV)"
          >
            {isDownloadingProjectCpes ? (
              <CircularProgress size={20} className="text-foreground" />
            ) : (
              <DownloadIcon style={{ fontSize: 20 }} />
            )}
            Download project CPEs
          </button>
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
      </div>

      {user?.is_admin ? (
        <section
          aria-label="Remote CPE log downloads"
          className="mb-8 rounded-xl border border-border bg-card p-4 sm:p-5"
        >
          {remoteJobsQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-6">
              <CircularProgress size={20} /> Loading fetch jobs…
            </div>
          ) : (remoteJobsQuery.data?.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground py-4">
              No remote fetch jobs yet. Use <strong>New Batch Job → Device list (JSON)</strong> to start one.
            </p>
          ) : (
            <>
              <div className="mb-4">
                <label className="flex flex-col gap-1 text-xs">
                  <span className="text-muted-foreground">Fetch job</span>
                  <select
                    value={focusFetchJobId ?? ""}
                    onChange={(e) => setFocusFetchJobId(e.target.value ? e.target.value : null)}
                    className="px-3 py-2 border border-border rounded-lg bg-background text-sm font-mono"
                  >
                    {(remoteJobsQuery.data ?? []).map((j) => (
                      <option key={j.id} value={j.id}>
                        {(j.created_at ? new Date(j.created_at).toLocaleString() : j.id.slice(0, 8))} ·{" "}
                        {j.status}
                        {j.batch_job_id ? ` · batch ${j.batch_job_id.slice(0, 8)}` : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                <label className="block text-xs">
                  <span className="text-muted-foreground">Device registry bearer</span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={bulkDreBearer}
                    onChange={(e) => setBulkDreBearer(e.target.value)}
                    className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
                    placeholder="For retry / restart"
                  />
                </label>
                <label className="block text-xs">
                  <span className="text-muted-foreground">Crash portal bearer</span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={bulkCrashBearer}
                    onChange={(e) => setBulkCrashBearer(e.target.value)}
                    className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
                    placeholder="For retry / restart"
                  />
                </label>
              </div>
              <label className="flex items-center gap-2 text-xs text-muted-foreground mb-4">
                <input
                  type="checkbox"
                  checked={restartWipeArtifacts}
                  onChange={(e) => setRestartWipeArtifacts(e.target.checked)}
                  className="rounded border-border"
                />
                Wipe staged artifacts when restarting entire job
              </label>
              <div className="flex flex-wrap gap-2 mb-4">
                <button
                  type="button"
                  disabled={
                    !focusFetchJobId ||
                    !bulkDreBearer.trim() ||
                    !bulkCrashBearer.trim() ||
                    retryRemoteFailedMutation.isPending ||
                    restartRemoteJobMutation.isPending
                  }
                  onClick={() => focusFetchJobId && void retryRemoteFailedMutation.mutate(focusFetchJobId)}
                  className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-lg border border-border hover:bg-muted disabled:opacity-50"
                >
                  {retryRemoteFailedMutation.isPending && <CircularProgress size={14} />}
                  Retry failed CPEs
                </button>
                <button
                  type="button"
                  disabled={
                    !focusFetchJobId ||
                    !bulkDreBearer.trim() ||
                    !bulkCrashBearer.trim() ||
                    retryRemoteFailedMutation.isPending ||
                    restartRemoteJobMutation.isPending
                  }
                  onClick={() => {
                    if (!focusFetchJobId) return;
                    if (
                      !window.confirm(
                        restartWipeArtifacts
                          ? "Restart entire fetch job and delete staged artifact directory?"
                          : "Restart entire fetch job?",
                      )
                    )
                      return;
                    restartRemoteJobMutation.mutate({
                      fetchJobId: focusFetchJobId,
                      wipe: restartWipeArtifacts,
                    });
                  }}
                  className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {restartRemoteJobMutation.isPending && <CircularProgress size={14} />}
                  Restart entire job
                </button>
                {remoteJobDetailQuery.data?.job?.batch_job_id ? (
                  <button
                    type="button"
                    onClick={() => {
                      const bid = remoteJobDetailQuery.data?.job.batch_job_id;
                      if (!bid || !projectId) return;
                      navigate(`/projects/${projectId}/batch-jobs/${bid}`);
                    }}
                    className="inline-flex items-center gap-2 px-3 py-2 text-xs rounded-lg border border-border hover:bg-muted"
                  >
                    <VisibilityIcon style={{ fontSize: 16 }} /> Open linked batch job
                  </button>
                ) : null}
              </div>
              {remoteJobDetailQuery.data ? (
                <>
                  <div className="text-xs flex flex-wrap gap-3 mb-3 text-muted-foreground">
                    <span>
                      Overall:{" "}
                      <strong className="text-foreground">{remoteJobDetailQuery.data.job.status}</strong>
                    </span>
                    {remoteJobDetailQuery.data.job.error_message ? (
                      <span className="text-destructive max-w-full">{remoteJobDetailQuery.data.job.error_message}</span>
                    ) : null}
                  </div>
                  <div className="overflow-x-auto rounded-lg border border-border max-h-72 overflow-y-auto">
                    <table className="w-full text-left text-[11px]">
                      <thead className="bg-muted/80 sticky top-0 z-10">
                        <tr>
                          <th className="px-2 py-1.5 font-medium">#</th>
                          <th className="px-2 py-1.5 font-medium">Serial</th>
                          <th className="px-2 py-1.5 font-medium">Dates (from JSON)</th>
                          <th className="px-2 py-1.5 font-medium">Download</th>
                          <th className="px-2 py-1.5 font-medium">Process</th>
                          <th className="px-2 py-1.5 font-medium">Error</th>
                        </tr>
                      </thead>
                      <tbody>
                        {remoteJobDetailQuery.data.units.map((u) => (
                          <tr key={u.id} className="border-t border-border/60">
                            <td className="px-2 py-1">{u.ordinal}</td>
                            <td className="px-2 py-1 font-mono">{u.serial_number}</td>
                            <td className="px-2 py-1 whitespace-nowrap" title={u.ranges_json}>
                              {u.requested_date_from && u.requested_date_to
                                ? `${u.requested_date_from} – ${u.requested_date_to}`
                                : "—"}
                            </td>
                            <td className="px-2 py-1 capitalize">{u.download_status}</td>
                            <td className="px-2 py-1 capitalize">{u.process_status}</td>
                            <td className="px-2 py-1 max-w-[240px] align-top">
                              <RemoteLogLastErrorInline lastError={u.last_error} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                remoteJobDetailQuery.isLoading && (
                  <p className="text-xs text-muted-foreground flex items-center gap-2">
                    <CircularProgress size={16} /> Loading job units…
                  </p>
                )
              )}
            </>
          )}
        </section>
      ) : null}

      {/* Create Dialog */}
      {showCreateDialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card border border-border rounded-xl p-6 max-w-2xl w-full mx-4 max-h-[92vh] overflow-y-auto">
            <h2 className="text-xl font-semibold mb-4">Create Batch Job</h2>

            {/* Upload Mode Selection */}
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2">Upload Method</label>
              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-4">
                <label className="flex items-center">
                  <input
                    type="radio"
                    name="uploadMode"
                    value="folder"
                    checked={effectiveUploadMode === "folder"}
                    onChange={(e) => setUploadMode(e.target.value as "folder" | "file" | "deviceJson")}
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
                    checked={effectiveUploadMode === "file"}
                    onChange={(e) => setUploadMode(e.target.value as "folder" | "file" | "deviceJson")}
                    className="mr-2"
                    disabled={isUploading}
                  />
                  File Upload
                </label>
                {allowRemoteDeviceList ? (
                  <label className="flex items-center">
                    <input
                      type="radio"
                      name="uploadMode"
                      value="deviceJson"
                      checked={effectiveUploadMode === "deviceJson"}
                      onChange={(e) =>
                        setUploadMode(e.target.value as "folder" | "file" | "deviceJson")
                      }
                      className="mr-2"
                      disabled={isUploading}
                    />
                    Bulk Download (JSON list)
                  </label>
                ) : null}
              </div>
              {effectiveUploadMode === "deviceJson" && allowRemoteDeviceList && (
                <p className="text-[11px] text-muted-foreground mt-2">
                  Each entry uses <code className="text-xs bg-muted px-1 rounded">serialnumber</code> plus{" "}
                  <code className="text-xs bg-muted px-1 rounded">ranges</code> (start/end ISO dates).
                  Rows with empty ranges use the optional default dates below. Example:{" "}
                  <a
                    href={`${import.meta.env.BASE_URL}examples/device_list_example.json`}
                    className="text-primary underline"
                    target="_blank"
                    rel="noreferrer"
                  >
                    device_list_example.json
                  </a>
                  .
                </p>
              )}
            </div>

            {effectiveUploadMode === "folder" ? (
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
            ) : effectiveUploadMode === "file" ? (
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
            ) : (
              <div className="mb-4 space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="block text-xs">
                    <span className="text-muted-foreground">Default range start (optional)</span>
                    <input
                      type="date"
                      value={bulkDefaultStart}
                      onChange={(e) => setBulkDefaultStart(e.target.value)}
                      className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
                    />
                  </label>
                  <label className="block text-xs">
                    <span className="text-muted-foreground">Default range end (optional)</span>
                    <input
                      type="date"
                      value={bulkDefaultEnd}
                      onChange={(e) => setBulkDefaultEnd(e.target.value)}
                      className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
                    />
                  </label>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Applied only when an entry omits ranges or ranges are invalid; otherwise each row uses its own dates.
                </p>
                <label className="block text-xs">
                  <span className="text-muted-foreground">Device registry bearer token</span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={bulkDreBearer}
                    onChange={(e) => setBulkDreBearer(e.target.value)}
                    className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
                    placeholder="Not stored on server"
                  />
                </label>
                <label className="block text-xs">
                  <span className="text-muted-foreground">Crash portal bearer token</span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={bulkCrashBearer}
                    onChange={(e) => setBulkCrashBearer(e.target.value)}
                    className="mt-1 w-full px-3 py-2 border border-border rounded-lg bg-background text-sm"
                    placeholder="Not stored on server"
                  />
                </label>
                <label className="block text-sm font-medium mb-1">Device list JSON</label>
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={handleDeviceJsonSelect}
                  className="w-full px-3 py-2 border border-border rounded-lg"
                />
                {remoteDeviceJsonFile && (
                  <p className="text-xs text-muted-foreground">
                    Selected: {remoteDeviceJsonFile.name}
                  </p>
                )}
                {remoteBulkError && (
                  <p className="text-sm text-destructive">{remoteBulkError}</p>
                )}
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
                  startRemoteBulkMutation.isPending ||
                  (effectiveUploadMode === "folder" && !cpeFolderPath.trim()) ||
                  (effectiveUploadMode === "file" && !selectedFile) ||
                  (effectiveUploadMode === "deviceJson" &&
                    (!remoteDeviceJsonFile ||
                      !bulkDreBearer.trim() ||
                      !bulkCrashBearer.trim()))
                }
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {(createJobMutation.isPending || startRemoteBulkMutation.isPending) &&
                !(isUploading && effectiveUploadMode === "file") ? (
                  <CircularProgress size={16} className="mr-2" />
                ) : isUploading ? null : effectiveUploadMode === "file" ? (
                  <CloudUploadIcon style={{ fontSize: 16 }} className="mr-2" />
                ) : null}
                {effectiveUploadMode === "file" && !isUploading
                  ? "Upload & Process"
                  : effectiveUploadMode === "deviceJson"
                    ? startRemoteBulkMutation.isPending
                      ? "Starting…"
                      : "Start remote fetch"
                    : "Create Job"}
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

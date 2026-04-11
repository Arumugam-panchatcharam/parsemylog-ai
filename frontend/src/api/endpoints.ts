import api from "./client";

// ---------- Auth ----------
export const authApi = {
  login: (username: string, password: string) =>
    api.post("/auth/login", { username, password }),
  register: (username: string, password: string, email?: string) =>
    api.post("/auth/register", { username, password, email }),
  refresh: () => api.post("/auth/refresh"),
  getProfile: () => api.get("/auth/profile"),
  updateProfile: (data: { username?: string; email?: string }) =>
    api.put("/auth/profile", data),
  changePassword: (currentPassword: string, newPassword: string) =>
    api.post("/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    }),
  getLogViewerQuickSearches: () =>
    api.get<{ buttons: { id: string; name: string; pattern: string }[] }>("/auth/log-viewer-quick-searches"),
  saveLogViewerQuickSearches: (buttons: { id: string; name: string; pattern: string }[]) =>
    api.put<{ buttons: { id: string; name: string; pattern: string }[] }>("/auth/log-viewer-quick-searches", { buttons }),
};

// ---------- Projects ----------
export const projectsApi = {
  list: () => api.get("/projects/"),
  create: (
    name: string,
    description: string | undefined,
    natcoId: number,
    projectType?: "normal" | "batch",
    tags?: string[],
  ) =>
    api.post("/projects/", {
      name,
      description,
      natco_id: natcoId,
      project_type: projectType || "normal",
      ...(tags && tags.length > 0 ? { tags } : {}),
    }),
  get: (id: string) => api.get(`/projects/${id}`),
  update: (
    id: string,
    data: {
      name?: string;
      description?: string;
      natco_id?: number | null;
      project_type?: "normal" | "batch";
      tags?: string[];
    },
  ) => api.put(`/projects/${id}`, data),
  delete: (id: string) => api.delete(`/projects/${id}`),
};

// ---------- CPEs ----------
export const cpesApi = {
  list: (projectId: string) => api.get(`/projects/${projectId}/cpes`),
};

// ---------- Batch Jobs ----------
export interface BatchJob {
  job_id: string;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  job_type: string;
  total_cpes: number;
  processed_cpes: number;
  failed_cpes: number;
  progress_percent: number;
  error_message?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  elapsed_sec?: number;
  eta_sec?: number;
}

export interface CPEProcessRecord {
  record_id: string;
  serial: string;
  status: "pending" | "processing" | "completed" | "failed" | "skipped";
  celery_task_id?: string;
  logs_extracted: number;
  patterns_indexed: number;
  processing_time_sec?: number;
  error_message?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

// Event types shared by issue analysis
export interface WindowEvents {
  [category: string]: {
    count: number;
    sample_lines: string[];
    timestamps: string[];
  };
}

export interface RebootEvent {
  timestamp: string;
  reason: string;
  window?: { start: string; end: string };
  window_events: WindowEvents;
  likely_trigger: string;
  trigger_description: string;
  total_events_in_window: number;
}

export interface TelemetryTimeseries {
  timestamps: string[];
  cpu: (number | null)[];
  memory_pct: (number | null)[];
  temperature: (number | null)[];
  connected_devices: (number | null)[];
  wan_rx_bytes_rate: (number | null)[];
  wan_tx_bytes_rate: (number | null)[];
  wifi_ssid1_rx_bytes_rate: (number | null)[];
  wifi_ssid1_tx_bytes_rate: (number | null)[];
  wifi_ssid2_rx_bytes_rate: (number | null)[];
  wifi_ssid2_tx_bytes_rate: (number | null)[];
  snapshot?: {
    gpon?: Record<string, string>;
    wan?: Record<string, string>;
    wifi?: Record<string, string>;
  };
  [key: string]: unknown;
}

export interface MemorySummary {
  avg_pct?: number;
  peak_pct?: number;
  min_pct?: number;
  samples?: number;
}

export interface ChunkedUploadStatus {
  status: "uploading" | "processing" | "completed" | "error" | "not_found";
  progress: number;
  uploaded_size: number;
  total_size: number;
  error?: string;
  job_id?: string;
  message?: string;
}

export const batchJobsApi = {
  create: (projectId: string, cpeFolderPath: string, jobType = "cpe_processing") =>
    api.post<{ job_id: string; status: string; total_cpes: number; message: string; celery_task_id: string }>(
      `/projects/${projectId}/batch-jobs/create`,
      { cpe_folder_path: cpeFolderPath, job_type: jobType }
    ),
  get: (projectId: string, jobId: string) =>
    api.get<BatchJob>(`/projects/${projectId}/batch-jobs/${jobId}`),
  list: (projectId: string, limit = 50) =>
    api.get<{ jobs: BatchJob[] }>(`/projects/${projectId}/batch-jobs`, { params: { limit } }),
  listCPEs: (projectId: string, jobId: string, status?: string) =>
    api.get<{ cpes: CPEProcessRecord[] }>(`/projects/${projectId}/batch-jobs/${jobId}/cpes`, {
      params: status ? { status } : undefined,
    }),
  retry: (projectId: string, jobId: string) =>
    api.post<{ message: string; retried_count: number }>(
      `/projects/${projectId}/batch-jobs/${jobId}/retry`
    ),
  cancel: (projectId: string, jobId: string) =>
    api.post<{ message: string; status: string; revoked_tasks: number }>(
      `/projects/${projectId}/batch-jobs/${jobId}/cancel`
    ),
  delete: (projectId: string, jobId: string) =>
    api.delete<{ message: string }>(`/projects/${projectId}/batch-jobs/${jobId}`),

  // Script download
  downloadScript: (projectId: string) =>
    api.get(`/projects/${projectId}/batch-jobs/download-script`, {
      responseType: "blob",
    }),

  // Chunked upload methods
  initUpload: (projectId: string, filename: string, totalSize: number) =>
    api.post<{ upload_id: string; chunk_size: number; message: string }>(
      `/projects/${projectId}/batch-jobs/upload/init`,
      { filename, total_size: totalSize }
    ),
  uploadChunk: (projectId: string, uploadId: string, chunkData: ArrayBuffer, start: number, end: number, total: number) =>
    api.post<{ message: string; progress: number; uploaded_size: number }>(
      `/projects/${projectId}/batch-jobs/upload/${uploadId}/chunk`,
      chunkData,
      {
        headers: {
          "Content-Type": "application/octet-stream",
          "Content-Range": `bytes ${start}-${end}/${total}`,
        },
        timeout: 300_000, // 5 minutes per chunk
      }
    ),
  completeUpload: (projectId: string, uploadId: string) =>
    api.post<{ message: string; upload_id: string }>(
      `/projects/${projectId}/batch-jobs/upload/${uploadId}/complete`
    ),
  getUploadStatus: (projectId: string, uploadId: string) =>
    api.get<ChunkedUploadStatus>(`/projects/${projectId}/batch-jobs/upload/${uploadId}/status`),
};

// ---------- Knowledge Graph ----------
export interface KnowledgeGraphSummary {
  id: string;
  name: string;
  description: string;
  is_template: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeNodeData {
  [key: string]: unknown;
  id: string;
  graph_id: string;
  node_type: "EVENT" | "CONDITION" | "ISSUE" | "ROOT_CAUSE" | "SUBGRAPH";
  name: string;
  label: string;
  domain: string | null;
  detection_config: {
    method?: string;
    keywords?: string[];
    patterns?: string[];
    source_domains?: string[];
    template_patterns?: string[];
    template_keywords?: string[];
    exclusions?: string[];
    threshold?: { metric: string; operator: string; value: number };
    referenced_graph_id?: string;
    activation_mode?: "any_issue" | "all_issues";
  } | null;
  description: string | null;
  position_x: number;
  position_y: number;
}

export interface KnowledgeEdgeData {
  [key: string]: unknown;
  id: string;
  graph_id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: "COULD_CAUSE" | "LEADS_TO" | "INDICATES" | "CORRELATES_WITH";
  conditions: {
    source_min_count?: number;
    time_window_minutes?: number;
    confidence?: number;
  } | null;
  label: string | null;
  description: string | null;
}

export interface KnowledgeGraphFull extends KnowledgeGraphSummary {
  nodes: KnowledgeNodeData[];
  edges: KnowledgeEdgeData[];
}

export interface GraphTemplate {
  filename: string;
  name: string;
  description: string;
  node_count: number;
  edge_count: number;
}

/** RDK-B module graph from configs/rdkb_module_graph.yaml (Architecture tab). */
export interface RdkbArchitectureReference {
  title: string;
  url: string;
}

export interface RdkbArchitectureNode {
  id: string;
  label: string;
  domains: string[];
  description: string;
}

export interface RdkbArchitectureEdge {
  id: string;
  source: string;
  target: string;
  relationship: string;
  notes?: string | null;
  confidence?: number;
}

export interface RdkbArchitectureGraphResponse {
  version: number;
  architecture_references: RdkbArchitectureReference[];
  nodes: RdkbArchitectureNode[];
  edges: RdkbArchitectureEdge[];
  node_count?: number;
  edge_count?: number;
  warning?: string;
}

export const knowledgeGraphApi = {
  list: (params?: { is_template?: boolean }) =>
    api.get<KnowledgeGraphSummary[]>("/knowledge-graphs/", { params }),
  create: (data: { name: string; description?: string; is_template?: boolean }) =>
    api.post<KnowledgeGraphSummary>("/knowledge-graphs/", data),
  get: (graphId: string) =>
    api.get<KnowledgeGraphFull>(`/knowledge-graphs/${graphId}`),
  update: (graphId: string, data: { name?: string; description?: string; is_template?: boolean }) =>
    api.put<KnowledgeGraphSummary>(`/knowledge-graphs/${graphId}`, data),
  delete: (graphId: string) =>
    api.delete(`/knowledge-graphs/${graphId}`),

  createNode: (graphId: string, data: Partial<KnowledgeNodeData>) =>
    api.post<KnowledgeNodeData>(`/knowledge-graphs/${graphId}/nodes`, data),
  updateNode: (graphId: string, nodeId: string, data: Partial<KnowledgeNodeData>) =>
    api.put<KnowledgeNodeData>(`/knowledge-graphs/${graphId}/nodes/${nodeId}`, data),
  deleteNode: (graphId: string, nodeId: string) =>
    api.delete(`/knowledge-graphs/${graphId}/nodes/${nodeId}`),

  createEdge: (graphId: string, data: Partial<KnowledgeEdgeData>) =>
    api.post<KnowledgeEdgeData>(`/knowledge-graphs/${graphId}/edges`, data),
  updateEdge: (graphId: string, edgeId: string, data: Partial<KnowledgeEdgeData>) =>
    api.put<KnowledgeEdgeData>(`/knowledge-graphs/${graphId}/edges/${edgeId}`, data),
  deleteEdge: (graphId: string, edgeId: string) =>
    api.delete(`/knowledge-graphs/${graphId}/edges/${edgeId}`),

  importGraph: (data: { template?: string } & Record<string, unknown>) =>
    api.post<KnowledgeGraphFull>("/knowledge-graphs/import", data),
  exportGraph: (graphId: string) =>
    api.get<{ name: string; description: string; nodes: unknown[]; edges: unknown[] }>(`/knowledge-graphs/${graphId}/export`),
  listTemplates: () =>
    api.get<GraphTemplate[]>("/knowledge-graphs/templates"),

  getRdkbArchitectureGraph: () =>
    api.get<RdkbArchitectureGraphResponse>("/knowledge-graphs/architecture/rdkb"),
};

// ---------- Issue Analysis ----------
export interface IssueAnalysisOverview {
  available: boolean;
  fleet_report?: {
    project_id: string;
    job_id: string;
    graph_name: string;
    generated_at: string;
    total_cpes: number;
    hardware_breakdown: Record<string, number>;
    firmware_breakdown: Record<string, number>;
    reboot_overview: {
      total_reboots: number;
      cpes_with_reboots: number;
      pct_with_reboots: number;
      avg_reboots_per_cpe: number;
    };
    trigger_distribution: Record<string, number>;
    issue_categories: Record<string, { cpes_affected: number; pct_affected: number; total_events: number }>;
    problem_areas: {
      wifi: { cpes_affected: number; pct_affected: number; worst_case: Array<{ serial: string; total_events: number }> };
      wan: { cpes_affected: number; pct_affected: number; worst_case: Array<{ serial: string; total_events: number }> };
      memory: { cpes_above_85pct: number; pct_above_85pct: number; worst_case: Array<{ serial: string; peak_pct?: number }> };
    };
    root_cause_distribution: Record<string, number>;
    telemetry_source_distribution: Record<string, number>;
  };
  per_cpe_count?: number;
  per_cpe_serials?: string[];
}

export interface IssueAnalysisCPEReport {
  identity: {
    cpe_serial: string;
    mac?: string;
    model?: string;
    firmware?: string;
  };
  telemetry_source: string;
  total_reboots: number;
  reboots: RebootEvent[];
  telemetry_timeseries: TelemetryTimeseries;
  memory_summary: MemorySummary;
  aggregate_issues: Record<string, number>;
  causal_chains: Array<{ path: string[]; path_ids: string[]; length: number }>;
  root_causes: Array<{
    node_id: string;
    name: string;
    label: string;
    node_type: string;
    confidence: number;
    evidence_count: number;
    score: number;
    contributing_events: Array<{ node_id: string; name: string; count: number; confidence: number }>;
  }>;
  graph_name: string;
  analysis_elapsed_ms: number;
}

export const issueAnalysisApi = {
  // Batch-job scoped
  trigger: (projectId: string, jobId: string, graphId: string, forceReparse = false) =>
    api.post<{ message: string; celery_task_id: string; graph_name: string }>(
      `/projects/${projectId}/batch-jobs/${jobId}/issue-analysis`,
      { graph_id: graphId, ...(forceReparse ? { force_reparse: true } : {}) },
    ),
  get: (projectId: string, jobId: string) =>
    api.get<IssueAnalysisOverview>(
      `/projects/${projectId}/batch-jobs/${jobId}/issue-analysis`,
    ),
  getCPE: (projectId: string, jobId: string, cpeSerial: string) =>
    api.get<IssueAnalysisCPEReport>(
      `/projects/${projectId}/batch-jobs/${jobId}/issue-analysis/cpe/${encodeURIComponent(cpeSerial)}`,
    ),
  // Direct project-level (single/few CPEs, no batch job)
  triggerDirect: (projectId: string, graphId: string, forceReparse = false) =>
    api.post<{ message: string; celery_task_id: string; graph_name: string }>(
      `/projects/${projectId}/issue-analysis`,
      { graph_id: graphId, ...(forceReparse ? { force_reparse: true } : {}) },
    ),
  getDirect: (projectId: string) =>
    api.get<IssueAnalysisOverview>(
      `/projects/${projectId}/issue-analysis`,
    ),
  getCPEDirect: (projectId: string, cpeSerial: string) =>
    api.get<IssueAnalysisCPEReport>(
      `/projects/${projectId}/issue-analysis/cpe/${encodeURIComponent(cpeSerial)}`,
    ),
};

// ---------- Files ----------
export const filesApi = {
  list: (projectId: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/files`, {
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
  upload: (projectId: string, files: File[]) => {
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    return api.post(`/projects/${projectId}/files/upload`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 600_000, // 10 min for large uploads
    });
  },
  processingStatus: (projectId: string) =>
    api.get<{
      status: "idle" | "processing" | "completed" | "error";
      message: string;
      progress: number;
      total: number;
      cpes: string[];
      error: string | null;
    }>(`/projects/${projectId}/files/processing-status`),
  getContent: (
    projectId: string,
    filename: string,
    page = 1,
    linesPerPage = 1000,
    cpeId?: string | null,
    dedup?: boolean,
  ) =>
    api.get<{
      lines: string[];
      page: number;
      total_pages: number;
      total_lines: number;
      total_lines_raw?: number;
      line_numbers?: number[];
      start_line: number;
      end_line: number;
      filename?: string;
      dedup_applied?: boolean;
    }>(`/projects/${projectId}/files/${filename}/content`, {
      params: {
        page,
        lines_per_page: linesPerPage,
        ...(cpeId ? { cpe_id: cpeId } : {}),
        ...(dedup ? { dedup: 1 } : {}),
      },
    }),
  download: (projectId: string, filename: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/files/${filename}/download`, {
      responseType: "blob",
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
  downloadMergedLogs: (projectId: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/files/merged-logs/download`, {
      responseType: "blob",
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
  search: (
    projectId: string,
    filename: string,
    pattern: string,
    cpeId?: string | null,
    dedup?: boolean,
    linesPerPage?: number,
  ) =>
    api.post<{
      matches: Array<{
        line_number: number;
        text: string;
        content_page?: number;
      }>;
      total: number;
      pattern: string;
    }>(`/projects/${projectId}/files/${filename}/search`, {
      pattern,
      cpe_id: cpeId || undefined,
      lines_per_page: linesPerPage,
      ...(dedup ? { dedup: true } : {}),
    }),
  searchAllFiles: (projectId: string, pattern: string, cpeId?: string | null, dedup?: boolean, linesPerPage?: number) =>
    api.post<{
      matches: Array<{
        filename: string;
        line_number: number;
        text: string;
        content_page?: number;
      }>;
      total: number;
      pattern: string;
      truncated?: boolean;
    }>(`/projects/${projectId}/files/search-all`, {
      pattern,
      cpe_id: cpeId ?? undefined,
      lines_per_page: linesPerPage,
      ...(dedup ? { dedup: true } : {}),
    }),
  getLogViewerDedupPatterns: (projectId: string) =>
    api.get<{ dedup_active: boolean; patterns: Array<{ id: string; regex: string; enabled: boolean; filename?: string }> }>(
      `/projects/${projectId}/log-viewer-dedup-patterns`,
    ),
  saveLogViewerDedupPatterns: (
    projectId: string,
    body: { dedup_active: boolean; patterns: Array<{ id: string; regex: string; enabled: boolean; filename?: string }> },
  ) => api.put(`/projects/${projectId}/log-viewer-dedup-patterns`, body),
  dedupFromLine: (projectId: string, line: string, filePath?: string) =>
    api.post<{
      success: boolean;
      original_line: string;
      stripped_line: string;
      generated_pattern: string;
      pattern_valid: boolean;
      pattern_error: string | null;
      preview_count: number;
      preview_lines: string[];
      error: string | null;
    }>(`/projects/${projectId}/dedup-from-line`, { line, file_path: filePath }),
  getNotes: (projectId: string) => api.get(`/projects/${projectId}/notes`),
  saveNotes: (projectId: string, content: string) =>
    api.put(`/projects/${projectId}/notes`, { content }),
};

// ---------- Patterns ----------
export const patternsApi = {
  listDomains: (projectId: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/domains`, {
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
  analyze: (projectId: string, domain: string, fileFilter?: string[], cpeId?: string | null) =>
    api.post(`/projects/${projectId}/domains/${domain}/analyze`, {
      file_filter: fileFilter,
      cpe_id: cpeId || undefined,
    }),
  getAggregated: (projectId: string, domain: string, page = 1, pageSize = 50, sort = "frequency", fileFilter?: string[]) =>
    api.get(`/projects/${projectId}/domains/${domain}/aggregated`, {
      params: { 
        page, 
        page_size: pageSize, 
        sort,
        file_filter: fileFilter && fileFilter.length > 0 ? fileFilter.join(",") : undefined
      },
    }),
  getTimeseries: (projectId: string, domain: string, template: string, interval: number, fileFilter?: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/domains/${domain}/timeseries`, {
      params: { template, interval, file_filter: fileFilter, cpe_id: cpeId || undefined },
    }),
  getParameters: (projectId: string, domain: string, template: string, fileFilter?: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/domains/${domain}/parameters`, {
      params: { template, file_filter: fileFilter, cpe_id: cpeId || undefined },
    }),
  getLoglines: (projectId: string, domain: string, template: string, page = 1, pageSize = 20, fileFilter?: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/domains/${domain}/loglines`, {
      params: { template, page, page_size: pageSize, file_filter: fileFilter, cpe_id: cpeId || undefined },
    }),
  indexingStatus: (projectId: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/indexing/status`, {
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
  getAggregatedSampleLogs: (projectId: string, domain: string, template: string, limit = 10) =>
    api.get<{ template: string; samples: Array<{ cpe_serial: string; timestamp: string; logline: string }> }>(
      `/projects/${projectId}/domains/${domain}/aggregated/${encodeURIComponent(template)}/sample-logs`,
      { params: { limit } }
    ),
  exportGlobal: (projectId: string) =>
    api.get<Blob>(`/projects/${projectId}/patterns/export-global`, {
      responseType: 'blob',
    }),
};

// ---------- Telemetry ----------
export interface WifiRfChannelEvent {
  radio: number;
  from_channel: number;
  to_channel: number;
  at_time: string;
  band?: string | null;
  dfs_related?: boolean;
}

export interface WifiRfRadioRow {
  radio: number;
  band?: string | null;
  bandwidth?: string | null;
  channel_first?: number | null;
  channel_last?: number | null;
  channel_change_count: number;
  util_first?: number | null;
  util_last?: number | null;
  util_max?: number | null;
  util_avg?: number | null;
  crowded: boolean;
}

export interface WifiRfPayload {
  radios: WifiRfRadioRow[];
  channel_events: WifiRfChannelEvent[];
  util_crowded_max_pct: number;
  util_crowded_avg_pct: number;
}

export interface WifiFleetRadioChannelRow {
  channel: number;
  cpe_count: number;
  mean_util_pct: number | null;
  max_util_pct: number | null;
}

export interface WifiFleetRadioTransition {
  from: number;
  to: number;
  count: number;
  share_pct: number;
}

export interface WifiFleetRadioTable {
  radio: number;
  /** Dominant Band string from CPE radio rows (e.g. 5GHz); used for DFS/radar channel coloring. */
  band?: string | null;
  cpes_reporting: number;
  channels: WifiFleetRadioChannelRow[];
  top_transitions: WifiFleetRadioTransition[];
}

export interface WifiFleetSummary {
  cpes_with_channel_changes: number;
  cpes_with_dfs_hint_events: number;
  cpes_wifi_crowded: number;
  total_channel_events: number;
  transition_histogram: Array<{ from: number; to: number; count: number }>;
  wifi_radio_fleet?: WifiFleetRadioTable[];
}

export interface CrossCpeTelemetryEntry {
  serial: string;
  model: string;
  memory_free_first?: number;
  memory_free_last?: number;
  memory_free_min?: number;
  memory_free_avg?: number;
  memory_available_min?: number;
  memory_available_avg?: number;
  memory_total?: number;
  memory_unit?: string;
  memory_trend?: string;
  memory_usage_pct_peak?: number | null;
  low_memory?: boolean;
  status?: string;
  reboot_count: number;
  reboot_events: Array<{ 
    time: string; 
    count: number; 
    prev_uptime: number; 
    new_uptime: number;
    reboot_type?: "soft" | "hard";
  }>;
  reboot_types?: { soft: number; hard: number };
  wifi_rf?: WifiRfPayload;
}

export interface RebootAnalytics {
  time_of_day_buckets: Record<string, {
    count: number;
    label: string;
    percentage: number;
    devices: Array<{
      serial: string;
      model?: string;
      timestamp?: string;
      hour?: number;
    }>;
  }>;
  uptime_buckets: Record<string, {
    count: number;
    label: string;
    percentage: number;
    devices: Array<{
      serial: string;
      model?: string;
      timestamp?: string;
      uptime_seconds?: number;
    }>;
  }>;
  total_reboot_events: number;
  short_reboots_count?: number;
  normal_reboots_count?: number;
}

export interface CrossCpeTelemetryOverview {
  cpes: CrossCpeTelemetryEntry[];
  fleet_summary: {
    total: number;
    with_reboots: number;
    with_low_memory: number;
    with_both: number;
  };
  wifi_fleet_summary?: WifiFleetSummary;
  reboot_analytics?: RebootAnalytics;
}

export const telemetryApi = {
  parse: (projectId: string, cpeId?: string | null, force = false) =>
    api.post(`/projects/${projectId}/telemetry/parse`, null, {
      params: { ...(cpeId ? { cpe_id: cpeId } : {}), ...(force ? { force: "1" } : {}) },
    }),
  availableFields: (projectId: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/telemetry/available-fields`, {
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
  crossCpeOverview: (projectId: string, force = false, filterShortReboots = false) =>
    api.get<CrossCpeTelemetryOverview>(`/projects/${projectId}/telemetry/cross-cpe-overview`, {
      params: {
        ...(force ? { force: "1" } : {}),
        ...(filterShortReboots ? { filter_short_reboots: "true" } : {}),
      },
    }),
  exportCsv: (
    projectId: string,
    cpeId: string,
    profiles?: string[],
    format?: 'combined' | 'separate'
  ) => {
    const params = new URLSearchParams({ cpe_id: cpeId });
    if (profiles && profiles.length > 0) {
      params.append('profiles', profiles.join(','));
    }
    if (format) {
      params.append('format', format);
    }
    return api.get(`/projects/${projectId}/telemetry/export-csv?${params.toString()}`, {
      responseType: 'blob',
    });
  },
};

// ---------- SelfHeal ----------
export const selfhealApi = {
  parse: (projectId: string, cpeSerial: string, force = false) =>
    api.post(`/projects/${projectId}/selfheal/parse`, null, {
      params: { cpe_serial: cpeSerial, ...(force ? { force: "1" } : {}) },
    }),
  crossCpeOverview: (projectId: string, force = false) =>
    api.get(`/projects/${projectId}/selfheal/cross-cpe-overview`, {
      params: { ...(force ? { force: "1" } : {}) },
    }),
  exportXlsx: (projectId: string, cpeSerial: string, force = false) =>
    api.get(`/projects/${projectId}/selfheal/export-xlsx`, {
      params: { cpe_serial: cpeSerial, ...(force ? { force: "1" } : {}) },
      responseType: 'blob',
    }),
};

// ---------- Syslog ----------
export const syslogApi = {
  parse: (projectId: string, cpeId: string | null, reparse = false) =>
    api.post(`/projects/${projectId}/syslog/parse`, null, {
      params: { ...(cpeId ? { cpe_id: cpeId } : {}), ...(reparse ? { reparse: "true" } : {}) },
    }),
  crossCpeOverview: (projectId: string, force = false) =>
    api.get(`/projects/${projectId}/syslog/cross-cpe-overview`, {
      params: { ...(force ? { force: "1" } : {}) },
    }),
  channelChangeDistribution: (projectId: string, force = false) =>
    api.get(`/projects/${projectId}/syslog/channel-change-distribution`, {
      params: { ...(force ? { force: "1" } : {}) },
    }),
  exportCsv: (projectId: string, cpeId: string | null) =>
    api.get(`/projects/${projectId}/syslog/export-csv`, {
      params: cpeId ? { cpe_id: cpeId } : undefined,
      responseType: 'blob',
    }),
  eventSummary: (projectId: string, cpeId: string | null) =>
    api.get(`/projects/${projectId}/syslog/event-summary`, {
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
};

// ---------- Semantic Search ----------
export const aiApi = {
  search: (projectId: string, query: string, topK = 10, cpeId?: string | null) =>
    api.post(`/projects/${projectId}/ai/search`, {
      query, top_k: topK, cpe_id: cpeId || undefined,
    }),
  getContext: (projectId: string, data: {
    template: string;
    timestamp: string;
    window: number;
    unit: string;
    filename?: string;
    parquet_path?: string;
    cpe_id?: string | null;
  }) => api.post(`/projects/${projectId}/ai/context`, {
    ...data,
    cpe_id: data.cpe_id || undefined,
  }),
  getParameters: (projectId: string, data: {
    template: string;
    parquet_path?: string;
    domain?: string;
    cpe_id?: string | null;
  }) => api.post(`/projects/${projectId}/ai/parameters`, {
    ...data,
    cpe_id: data.cpe_id || undefined,
  }),
  getLoglines: (projectId: string, data: {
    template: string;
    parquet_path?: string;
    domain?: string;
    page?: number;
    page_size?: number;
    cpe_id?: string | null;
    load_all?: boolean;
  }) => api.post(`/projects/${projectId}/ai/loglines`, {
    ...data,
    cpe_id: data.cpe_id || undefined,
  }),
};

// ---------- Embedding ----------
export const embeddingApi = {
  pipelineStatus: (projectId: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/pipeline/status`, {
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
  fileTemplates: (projectId: string, filename: string) =>
    api.get(`/projects/${projectId}/files/${filename}/templates`),
  downloadTemplates: (projectId: string) =>
    `${api.defaults.baseURL}/projects/${projectId}/templates/download`,
};

// ---------- Pattern Analyzer ----------
export interface MaintenanceWindow {
  start: string; // HH:MM (UTC, 24h)
  end: string;   // HH:MM (UTC, 24h)
}

export interface UserPattern {
  name: string;
  regex: string;
  enabled: boolean;
  maintenance_window?: MaintenanceWindow | null;
  reboot_proximity_minutes?: number | null;
  min_frequency_threshold?: number | null;
}

/** Domain-grouped patterns: { domain_name: UserPattern[] } */
export type DomainPatterns = Record<string, UserPattern[]>;

export const patternAnalyzerApi = {
  getPatterns: (projectId: string) =>
    api.get<{ domains: DomainPatterns }>(`/projects/${projectId}/regex-patterns`),
  savePatterns: (projectId: string, domains: DomainPatterns) =>
    api.put<{ domains: DomainPatterns; saved: number }>(`/projects/${projectId}/regex-patterns`, { domains }),
  getPresets: (projectId: string) =>
    api.get<{ presets: DomainPatterns }>(`/projects/${projectId}/regex-patterns/presets`),
  exportUrl: (projectId: string, format: "yaml" | "json") =>
    `${api.defaults.baseURL}/projects/${projectId}/regex-patterns/export?format=${format}`,
  getReboots: (projectId: string, cpeId?: string | null) =>
    api.get<{ reboots: Array<{ timestamp: string; reason: string }> }>(
      `/projects/${projectId}/reboots`,
      { params: cpeId ? { cpe_id: cpeId } : undefined }
    ),
  scan: (projectId: string, data: {
    patterns: UserPattern[];
    bucket_minutes: number;
    time_range?: { start: string; end: string };
    filter_pre_ntp?: boolean;
    filter_short_reboots?: boolean;
    cpe_id?: string | null;
  }) => api.post<{
    scan_id: string;
    total_matches: number;
    trace_count: number;
    reboots_count: number;
    elapsed_ms: number;
  }>(`/projects/${projectId}/regex-scan`, {
    ...data,
    cpe_id: data.cpe_id || undefined,
  }),
  getScanResults: (projectId: string, scanId: string, cpeId?: string | null) =>
    api.get<{
      traces: Array<{ name: string; times: string[]; texts: string[]; total: number }>;
      reboots: Array<{ timestamp: string; reason: string }>;
      total_matches: number;
    }>(`/projects/${projectId}/regex-scan/${scanId}/results`, {
      params: cpeId ? { cpe_id: cpeId } : undefined,
    }),
};

// ---------- CPE Overview ----------
export interface PatternScanDomain {
  patterns: string[];
  /** Same length/order as `patterns`; absent on caches from older scans. */
  pattern_regexes?: string[];
  cpes: Array<{ serial: string; counts: number[] }>;
}
export interface PatternScanResult {
  cached: boolean;
  scanned_at?: string;
  elapsed_ms?: number;
  domains?: Record<string, PatternScanDomain>;
}

// ---------- CPE Overview ----------
export interface CPEOverviewData {
  serial: string;
  mac: string;
  model: string;
  date_from?: string;
  date_to?: string;
  device_info: Record<string, any>;
  key_metrics: Record<string, any>;
  summary: Record<string, any>;
  reboot_summary: { total: number; reasons: Record<string, number> };
  pattern_summary: Record<string, any>;
  log_stats: { file_count: number; total_size_mb: number };
  status: "parsed" | "not_parsed" | "failed";
  reboot_count: number;
  log_size_mb: number;
}

export interface CPEOverviewResponse {
  cpes: CPEOverviewData[];
  pagination: {
    page: number;
    per_page: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_prev: boolean;
  };
}

export const cpeOverviewApi = {
  getSummary: (
    projectId: string,
    params?: {
      page?: number;
      per_page?: number;
      sort_by?: "serial" | "model" | "date_from" | "reboot_count" | "log_size";
      order?: "asc" | "desc";
      model?: string;
      serial?: string;
      status?: "parsed" | "not_parsed" | "failed";
      force?: boolean;
    }
  ) => {
    const p = params ? { ...params } as Record<string, unknown> : {};
    if (p.force) { p.force = "1"; } else { delete p.force; }
    return api.get<CPEOverviewResponse>(`/projects/${projectId}/cpe-overview`, { params: p });
  },
  getPatternScan: (projectId: string) =>
    api.get<PatternScanResult>(`/projects/${projectId}/cpe-overview/pattern-scan`),
  runPatternScan: (projectId: string, params?: { reboot_window_minutes?: number; filter_short_reboots?: boolean; min_frequency_threshold?: number }) =>
    api.post<PatternScanResult>(`/projects/${projectId}/cpe-overview/pattern-scan`, params),
};

// ---------- NATCO (user-facing) ----------
export interface NatcoInfo {
  id: number;
  code: string;
  name: string;
  description?: string;
}

export const natcoApi = {
  list: () => api.get<NatcoInfo[]>("/natcos/"),
};

// ---------- Pattern Governance (user-facing) ----------
export interface DiffPattern extends UserPattern {
  change_type: "new" | "modified";
  global_name?: string;
  global_enabled?: boolean;
  global_maintenance_window?: MaintenanceWindow | null;
  global_reboot_proximity_minutes?: number | null;
  global_min_frequency_threshold?: number | null;
}

export interface DomainDiff {
  new: DiffPattern[];
  modified: DiffPattern[];
  unchanged: UserPattern[];
}

export const patternGovernanceApi = {
  getGlobal: (projectId: string) =>
    api.get<{ domains: DomainPatterns; natco: NatcoInfo | null }>(`/projects/${projectId}/patterns/global`),
  diff: (projectId: string, currentDomains?: DomainPatterns) =>
    api.post<{ domains: Record<string, DomainDiff>; natco: NatcoInfo | null }>(`/projects/${projectId}/patterns/diff`, { domains: currentDomains ?? {} }),
  sync: (projectId: string, currentDomains?: DomainPatterns) =>
    api.post<{ domains: DomainPatterns; synced: number }>(`/projects/${projectId}/patterns/sync`, { domains: currentDomains ?? {} }),
  submit: (projectId: string, domain: string, patterns: Array<UserPattern & { change_type?: string }>, comment?: string) =>
    api.post<{ id: number; message: string }>(`/projects/${projectId}/patterns/submit`, {
      domain, patterns, comment,
    }),
  mySubmissions: (projectId: string) =>
    api.get<Array<{
      id: number;
      domain: string;
      patterns: Array<UserPattern & { change_type?: string }>;
      comment: string;
      status: string;
      admin_comment: string;
      created_at: string;
      reviewed_at: string | null;
    }>>(`/projects/${projectId}/patterns/submissions`),
  clearResolved: (projectId: string) =>
    api.delete<{ deleted: number }>(`/projects/${projectId}/patterns/submissions/clear`),
};

// ---------- Chat (AI LLM) ----------
export interface ChatFileList {
  logs: Array<{ name: string; path: string; size: number }>;
  csv: Array<{ name: string; size: number }>;
  pcap: Array<{ name: string; size: number }>;
}

export const chatApi = {
  llmStatus: (projectId: string) =>
    api.get<{ enabled: boolean; available: boolean; model_info: Record<string, unknown> | null }>(
      `/projects/${projectId}/chat/llm-status`
    ),
  listConversations: (projectId: string, cpeId?: string | null) =>
    api.get<Array<{ id: number; title: string; cpe_id: string | null; created_at: string | null; updated_at: string | null }>>(
      `/projects/${projectId}/chat/conversations`,
      { params: cpeId ? { cpe_id: cpeId } : undefined }
    ),
  createConversation: (projectId: string, title?: string, cpeId?: string | null) =>
    api.post<{ id: number; title: string; cpe_id: string | null }>(
      `/projects/${projectId}/chat/conversations`,
      { title, cpe_id: cpeId || undefined }
    ),
  deleteConversation: (projectId: string, convId: number) =>
    api.delete(`/projects/${projectId}/chat/conversations/${convId}`),
  getMessages: (projectId: string, conversationId: number, limit?: number) =>
    api.get<Array<{ id: number; role: string; content: string; context_used: Record<string, unknown> | null; created_at: string | null }>>(
      `/projects/${projectId}/chat/messages`,
      { params: { conversation_id: conversationId, ...(limit ? { limit } : {}) } }
    ),
  listFiles: (projectId: string, cpeId?: string | null) =>
    api.get<ChatFileList>(
      `/projects/${projectId}/chat/list-files`,
      { params: cpeId ? { cpe_id: cpeId } : undefined }
    ),
  // Note: send is done via fetch() + SSE streaming, not Axios
};

// ---------- Admin ----------
export interface AdminNatco extends NatcoInfo {
  pattern_count: number;
  created_at: string;
}

export interface PatternSubmission {
  id: number;
  user_id: number;
  username: string;
  natco_id: number;
  natco_code: string;
  domain: string;
  patterns: Array<UserPattern & { change_type?: string }>;
  comment: string;
  status: string;
  reviewed_by: number | null;
  admin_comment: string;
  created_at: string;
  reviewed_at: string | null;
}

export const adminApi = {
  listUsers: () => api.get("/admin/users"),
  deleteUser: (userId: number) => api.delete(`/admin/users/${userId}`),
  resetPassword: (userId: number, password: string) =>
    api.put(`/admin/users/${userId}/password`, { password }),
  userProjects: (userId: number) => api.get(`/admin/users/${userId}/projects`),

  // NATCO management
  listNatcos: () => api.get<AdminNatco[]>("/admin/natcos"),
  createNatco: (code: string, name: string, description?: string) =>
    api.post("/admin/natcos", { code, name, description }),
  updateNatco: (id: number, data: { code?: string; name?: string; description?: string }) =>
    api.put(`/admin/natcos/${id}`, data),
  deleteNatco: (id: number) => api.delete(`/admin/natcos/${id}`),

  // Global patterns
  getNatcoPatterns: (natcoId: number) =>
    api.get<{ domains: DomainPatterns; natco: NatcoInfo }>(`/admin/natcos/${natcoId}/patterns`),
  setNatcoPatterns: (natcoId: number, domains: DomainPatterns) =>
    api.put(`/admin/natcos/${natcoId}/patterns`, { domains }),
  importPresets: (natcoId: number) =>
    api.post<{ imported: number }>(`/admin/natcos/${natcoId}/patterns/import-presets`),

  // LLM settings
  getLlmSettings: () =>
    api.get<{ 
      enabled: boolean; 
      available: boolean; 
      model_info: Record<string, unknown> | null;
      providers?: {
        openai?: { configured: boolean; available: boolean; model: string | null; base_url?: string | null };
        openrouter?: { configured: boolean; available: boolean; model: string | null };
      };
      active_provider?: string | null;
    }>("/admin/settings/llm"),
  setLlmSettings: (enabled: boolean) =>
    api.put<{ enabled: boolean; message: string }>("/admin/settings/llm", { enabled }),

  // Submissions
  listSubmissions: (status?: string) =>
    api.get<PatternSubmission[]>("/admin/submissions", { params: status ? { status } : undefined }),
  getSubmission: (id: number) => api.get(`/admin/submissions/${id}`),
  approveSubmission: (id: number, comment?: string) =>
    api.post(`/admin/submissions/${id}/approve`, { comment }),
  rejectSubmission: (id: number, comment?: string) =>
    api.post(`/admin/submissions/${id}/reject`, { comment }),
};

// ---------- PCAP Analyzer ----------
export interface PcapFileInfo {
  filename: string;
  size_bytes: number;
  size_mb: number;
  uploaded_at: string;
  protocol: string;
  tags: string[];
}

/* ── Fast Analysis types ─────────────────────────────────────────────── */

export interface PcapIssue {
  severity: "critical" | "warning";
  description: string;
  affected_mac: string | null;
  metric_value: number;
}

export interface PcapRecommendation {
  action: string;
  reason: string;
}

export interface PcapHealth {
  status: "CRITICAL" | "WARNING" | "HEALTHY";
  score: number;
  critical_count: number;
  warning_count: number;
  issues: PcapIssue[];
  recommendations: PcapRecommendation[];
}

export interface PcapCaptureInfo {
  total_frames: number;
  duration: number;
  frame_rate: number;
  start_time: number;
  end_time: number;
  mgmt_frames: number;
  ctrl_frames: number;
  data_frames: number;
  deauth_frames: number;
  disassoc_frames: number;
  retry_frames: number;
  retry_pct: number;
}

export interface PcapNetworkSummary {
  ap_count: number;
  client_count: number;
  ssids: string[];
  channels: number[];
}

export interface PcapActivityBucket {
  epoch: number;
  mgmt_count: number;
  ctrl_count: number;
  data_count: number;
}

export interface PcapChannelDist {
  channel: number;
  frame_count: number;
  retry_pct: number;
  client_count: number;
}

export interface PcapEapolPair {
  client: string;
  ap: string;
  steps_seen: number[];
  complete: boolean;
}

export interface PcapOverview {
  capture_info: PcapCaptureInfo;
  network_summary: PcapNetworkSummary;
  health: PcapHealth;
  eapol_handshakes: PcapEapolPair[];
  activity_timeline: PcapActivityBucket[];
  channel_distribution: PcapChannelDist[];
  protocol_detected: string;
  cache_used: boolean;
}

export interface PcapClientSummary {
  mac: string;
  is_ap: boolean;
  status: "critical" | "warning" | "healthy";
  primary_bssid: string;
  ssid: string;
  avg_rssi: number | null;
  retry_pct: number;
  frame_count: number;
  deauth_count: number;
  channels: number[];
  power_save_pct: number;
  seq_gaps_count: number;
  eapol_status: "" | "complete" | "incomplete";
}

export interface PcapApSummary {
  bssid: string;
  ssid: string;
  channel: number | null;
  client_count: number;
  avg_retry_pct: number;
  avg_rssi: number | null;
  beacon_count: number;
  status: "critical" | "warning" | "healthy";
}

export interface Pcap1905Device {
  al_mac: string;
  eth_src: string;
  message_count: number;
  last_seen: number | null;
}

export interface Pcap1905Overview {
  has_1905: boolean;
  devices: Pcap1905Device[];
  message_distribution: Record<string, number>;
  category_distribution: Record<string, number>;
  per_device_categories: Record<string, Record<string, number>>;
  unanswered_queries: Array<{ query_type: string; expected_response?: string; query_id: string; sender: string; epoch: number | null }>;
  timeline: Array<{ epoch: number; message_type: string; src: string; dst: string; message_id: string }>;
}

export interface PcapAnalysisResult {
  overview: PcapOverview;
  clients: PcapClientSummary[];
  aps: PcapApSummary[];
  mesh_1905: Pcap1905Overview;
}

/* ── Client Detail types ─────────────────────────────────────────────── */

export interface PcapClientEvent {
  epoch: number | null;
  event_type: string;
  peer: string;
  direction: "in" | "out";
  detail: string;
}

export interface PcapApConversation {
  bssid: string;
  ssid: string;
  first_seen: number;
  last_seen: number;
  frame_count: number;
  avg_rssi: number | null;
}

export interface PcapEapolHandshake {
  peer: string;
  steps_seen: number[];
  complete: boolean;
  start_epoch: number | null;
}

export interface PcapSeqGap {
  epoch: number;
  expected_seq: number;
  actual_seq: number;
  gap_size: number;
}

export interface PcapClientDetail {
  mac: string;
  rssi_timeline: Array<{ epoch: number; rssi: number }>;
  retry_timeline: Array<{ epoch: number; retry_pct: number }>;
  frame_type_dist: { mgmt: number; ctrl: number; data: number };
  events: PcapClientEvent[];
  ap_conversations: PcapApConversation[];
  roaming: Array<{ epoch: number; from_bssid: string; to_bssid: string }>;
  eapol_handshakes: PcapEapolHandshake[];
  power_mgmt_timeline: Array<{ epoch: number; state: number }>;
  sequence_analysis: {
    seq_timeline: Array<{ epoch: number; seq: number; retry: number }>;
    seq_gaps: PcapSeqGap[];
    duplicate_frames: number;
  };
  retry_vs_power: Array<{ epoch: number; retry: number; pwrmgt: number }>;
  error?: string;
}

/* ── AP Detail types ─────────────────────────────────────────────────── */

export interface PcapApClientMetric {
  mac: string;
  avg_rssi: number | null;
  retry_pct: number;
  frame_count: number;
  first_seen: number | null;
  last_seen: number | null;
}

export interface PcapApRssiDist {
  mac: string;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

export interface PcapApDetail {
  bssid: string;
  client_metrics: PcapApClientMetric[];
  rssi_distribution: PcapApRssiDist[];
  client_timeline: Array<{ epoch: number; connected_clients: number }>;
  channel_info: { channel: number | null; frequency: number | null; phy_modes: Record<string, number> };
  error?: string;
}

export const pcapApi = {
  upload: (files: File[]) => {
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    return api.post<{ uploaded: PcapFileInfo[]; errors: string[] }>("/pcap/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 600_000,
    });
  },
  listFiles: () =>
    api.get<{ files: PcapFileInfo[] }>("/pcap/files"),
  deleteFile: (filename: string) =>
    api.delete(`/pcap/files/${encodeURIComponent(filename)}`),
  updateTags: (filename: string, tags: string[]) =>
    api.put<{ filename: string; tags: string[] }>(`/pcap/files/${encodeURIComponent(filename)}/tags`, { tags }),
  redetectProtocol: (filename: string) =>
    api.post<{ filename: string; protocol: string }>(`/pcap/files/${encodeURIComponent(filename)}/detect`),
  analyze: (filename: string, force?: boolean) =>
    api.post<PcapAnalysisResult>("/pcap/analyze", { filename, force: force || false }, { timeout: 600_000 }),
  clientDetail: (filename: string, mac: string) =>
    api.get<PcapClientDetail>(`/pcap/analyze/client/${encodeURIComponent(mac)}`, { params: { filename }, timeout: 120_000 }),
  apDetail: (filename: string, bssid: string) =>
    api.get<PcapApDetail>(`/pcap/analyze/ap/${encodeURIComponent(bssid)}`, { params: { filename }, timeout: 120_000 }),
  mesh1905Detail: (filename: string, filters?: { al_mac?: string; src?: string; dst?: string; exclude_periodic?: boolean }) => {
    const params: Record<string, string> = { filename };
    if (filters?.al_mac) params.al_mac = filters.al_mac;
    if (filters?.src) params.src = filters.src;
    if (filters?.dst) params.dst = filters.dst;
    if (filters?.exclude_periodic) params.exclude_periodic = "1";
    return api.get<Pcap1905Overview>("/pcap/analyze/1905", { params, timeout: 120_000 });
  },
};

// ── Telemetry CSV Analyzer ────────────────────────────────────────────────

export interface TelemetryCsvFileInfo {
  filename: string;
  size_bytes: number;
  size_mb: number;
  uploaded_at: string;
  tags: string[];
}

export interface TelemetryCsvMetadata {
  columns: string[];
  dtypes: Record<string, string>;
  row_count: number;
  column_count: number;
  unique_values: Record<string, string[]>;
  ready: boolean;
}

export interface TelemetryCsvSeries {
  x: any[];
  series: Array<{ name: string; values: any[] }>;
  row_count: number;
  downsampled: boolean;
}

export const telemetryCsvApi = {
  upload: (files: File[]) => {
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    return api.post<{ uploaded: TelemetryCsvFileInfo[]; errors: string[] }>("/telemetry-csv/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 600_000,
    });
  },
  listFiles: () =>
    api.get<{ files: TelemetryCsvFileInfo[] }>("/telemetry-csv/files"),
  deleteFile: (filename: string) =>
    api.delete(`/telemetry-csv/files/${encodeURIComponent(filename)}`),
  updateTags: (filename: string, tags: string[]) =>
    api.put<{ filename: string; tags: string[] }>(`/telemetry-csv/files/${encodeURIComponent(filename)}/tags`, { tags }),
  getMetadata: (filename: string) =>
    api.get<TelemetryCsvMetadata>(`/telemetry-csv/files/${encodeURIComponent(filename)}/metadata`, { timeout: 120_000 }),
  getSeries: (filename: string, xColumn: string, yColumns: string[], maxPoints?: number) =>
    api.post<TelemetryCsvSeries>("/telemetry-csv/series", { 
      filename, 
      x_column: xColumn, 
      y_columns: yColumns,
      max_points: maxPoints 
    }, { timeout: 120_000 }),
};

// ── ML Anomaly Detection API ──────────────────────────────────────────────────

export interface LogAnomalyReport {
  anomalies: Array<{
    cluster_id: number;
    template: string;
    count: number;
    anomaly_score: number;
    score?: number; // Alternative field name
    method: string;
    methods?: Record<string, number>; // Method scores
    examples: string[];
    category?: string; // Domain/category
    sample_loglines?: string[]; // Sample log lines
  }>;
  total_anomalies: number;
  processing_time: number;
  summary?: string;
  domain?: string; // Domain filter
  method_stats?: Record<string, { detected: number }>; // Stats per method
}

export interface TelemetryAnomalyReport {
  anomalies: Array<{
    cpe_id: string;
    metric_name: string;
    anomaly_type: string;
    severity: string;
    description: string;
    timestamp?: string;
    value?: number;
    expected_range?: string;
  }>;
  total_anomalies: number;
  processing_time: number;
  summary?: string | { narrative?: string }; // Can be string or object with narrative
  health?: {
    overall_score: number;
  };
  plot_data?: {
    metrics: Array<{
      name: string;
      values: number[];
      timestamps: string[];
      metric_label?: string;
      has_anomalies?: boolean;
      unit?: string;
      mean?: number;
      lower_threshold?: number;
      upper_threshold?: number;
      anomaly_points?: {
        values: number[];
        timestamps: string[];
        severities?: string[];
      };
    }>;
  };
}

export interface FleetAnalysisReport {
  log_anomalies: number;
  telemetry_anomalies: number;
  total_devices: number;
  affected_devices: number;
  top_issues: Array<{
    issue_type: string;
    affected_count: number;
    description: string;
  }>;
  processing_time: number;
  details?: {
    log_anomalies: number;
    telemetry_anomalies: number;
  };
  summary?: string;
  analyzed_cpes?: number;
  total_cpes?: number;
  health_distribution?: {
    healthy: number;
    warning: number;
    critical: number;
  };
  fleet_anomaly_patterns?: Array<{
    pattern: string;
    template?: string;
    count: number;
    cpe_count?: number;
    affected_cpes: string[];
  }>;
  outlier_cpes?: Array<{
    cpe_id: string;
    score: number;
    anomalies: number;
  }>;
  per_cpe_summary?: Record<string, {
    overall_score: number;
    health_score?: number;
    log_anomaly_count: number;
    telemetry_anomaly_count: number;
    log_anomalies?: number;
    telemetry_anomalies?: number;
  }>;
  per_cpe_results?: Array<{
    cpe_id: string;
    overall_score: number;
    health_score?: number;
    log_anomaly_count: number;
    telemetry_anomaly_count: number;
    log_anomalies?: number;
    telemetry_anomalies?: number;
  }>;
}

export const mlAnomalyApi = {
  detectLogAnomalies: (
    projectId: string,
    params: {
      cpe_id?: string;
      domain?: string;
      enable_vector_similarity?: boolean;
      enable_gru?: boolean;
      enable_isolation_forest?: boolean;
      top_n?: number;
    } = {}
  ) =>
    api.post<LogAnomalyReport>(
      `/projects/${projectId}/ml/log-anomalies`,
      {},
      { params }
    ),
  detectTelemetryAnomalies: (projectId: string, cpeId?: string) =>
    api.post<TelemetryAnomalyReport>(
      `/projects/${projectId}/ml/telemetry-anomalies`,
      {},
      { params: cpeId ? { cpe_id: cpeId } : undefined }
    ),
  runFleetAnalysis: (
    projectId: string,
    body?: {
      target_cpes?: string[];
    },
    params: {
      enable_log?: boolean;
      enable_telemetry?: boolean;
      enable_vector_similarity?: boolean;
      enable_gru?: boolean;
      enable_isolation_forest?: boolean;
      max_workers?: number;
    } = {}
  ) =>
    api.post<FleetAnalysisReport>(
      `/projects/${projectId}/ml/fleet-analysis`,
      body || {},
      { params }
    ),
  
  // Feedback APIs
  submitFeedback: (
    projectId: string,
    feedback: {
      cpe_id?: string; // CPE ID field
      domain?: string; // Domain field
      anomaly_type: string;
      cluster_id?: number;
      template?: string;
      metric_name?: string;
      is_true_positive: boolean;
      confidence?: number;
      feedback_notes?: string;
    }
  ) =>
    api.post(`/projects/${projectId}/ml/feedback`, feedback),
  
  getFeedback: (projectId: string, domain?: string) =>
    api.get<{
      feedback: Array<{
        id: number;
        anomaly_type: string;
        cluster_id?: number;
        template?: string;
        metric_name?: string;
        is_true_positive: boolean;
        confidence: number;
        feedback_notes?: string;
        created_at: string;
      }>;
      count: number;
    }>(`/projects/${projectId}/ml/feedback`, {
      params: domain ? { domain } : undefined,
    }),
  
  // Admin APIs
  getActiveGlobalModels: (params?: { model_type?: string; domain?: string }) =>
    api.get<{
      models: Array<{
        id: number;
        model_type: string;
        domain: string;
        vocabulary_size: number;
        training_samples: number;
        accuracy_metrics: any;
        trained_at: string;
        version: number;
      }>;
    }>("/projects/ml/global-models/active", { params }),
};

// ── Utilities API ──────────────────────────────────────────────────────────────

export interface MacLookupResult {
  original: string;
  mac: string | null;
  oui: string | null;
  vendor: string | null;
  error: string | null;
}

export interface OuiStatus {
  entries: number;
  file_exists: boolean;
  file_size_mb: number;
  last_modified: number | null;
}

export interface OuiUpdateResult {
  status: string;
  message: string;
  entries?: number;
  size_mb?: number;
}

export const utilitiesApi = {
  macLookup: (macs: string[]) =>
    api.post<MacLookupResult[]>("/utilities/mac-lookup", { macs }, { timeout: 120_000 }),
  
  ouiStatus: () =>
    api.get<OuiStatus>("/utilities/oui-status"),
  
  ouiUpdate: () =>
    api.post<OuiUpdateResult>("/utilities/oui-update", {}, { timeout: 90_000 }),
  
  ouiReload: () =>
    api.post<OuiUpdateResult>("/utilities/oui-reload", {}),
};

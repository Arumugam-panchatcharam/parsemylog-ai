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
  create: (name: string, description?: string, natcoId?: number | null, projectType?: "normal" | "batch") =>
    api.post("/projects/", { name, description, natco_id: natcoId || undefined, project_type: projectType || "normal" }),
  get: (id: string) => api.get(`/projects/${id}`),
  update: (id: string, data: { name?: string; description?: string; natco_id?: number | null }) =>
    api.put(`/projects/${id}`, data),
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

export interface RebootFleetSummary {
  project_id: string;
  job_id: string;
  generated_at: string;
  sample_info: {
    total_cpes: number;
    hardware_breakdown: Record<string, number>;
    firmware_breakdown: Record<string, number>;
  };
  reboot_overview: {
    total_reboots: number;
    cpes_with_reboots: number;
    pct_with_reboots: number;
    avg_reboots_per_affected: number;
  };
  wan_overview: {
    total_disconnections: number;
    cpes_affected: number;
    pct_affected: number;
  };
  problem_categories: {
    wifi: { cpes_affected: number; pct_affected: number; worst_case: Array<{ serial: string; total_events: number }> };
    wan: { cpes_affected: number; pct_affected: number; worst_case: Array<{ serial: string; total_events: number }> };
    memory: { cpes_above_85pct: number; pct_above_85pct: number; worst_case: Array<{ serial: string; peak_pct?: number }> };
  };
  cause_distribution: Record<string, number>;
  failure_chain_distribution: Record<string, number>;
  top_templates: Array<{ template: string; count: number }>;
  client_churn_stats: { cpes_with_sustained_storms: number; pct_with_storms: number; avg_peak_rate: number };
  btm_steering_stats: { cpes_with_btm_events: number; total_btm_events: number };
  gpon_wan_health: { cpes_with_signal_degrade: number; cpes_with_wan_errors: number };
  telemetry_source_distribution: Record<string, number>;
  unknown_cohort: string[];
  data_quality: { pct_with_telemetry: number; domain_coverage: Record<string, number> };
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
  getRebootSummary: (projectId: string, jobId: string) =>
    api.get<{ available: boolean; per_cpe_count: number; fleet_summary: RebootFleetSummary }>(
      `/projects/${projectId}/batch-jobs/${jobId}/reboot-summary`
    ),
  regenerateRebootSummary: (projectId: string, jobId: string) =>
    api.post<{ message: string; celery_task_id: string }>(
      `/projects/${projectId}/batch-jobs/${jobId}/reboot-summary/regenerate`
    ),
  downloadRebootSummary: (projectId: string, jobId: string, type: "fleet" | "per_cpe" = "fleet") =>
    api.get(`/projects/${projectId}/batch-jobs/${jobId}/reboot-summary/download`, {
      params: { type },
      responseType: "blob",
    }),
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
  getContent: (projectId: string, filename: string, page = 1, linesPerPage = 1000, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/files/${filename}/content`, {
      params: { page, lines_per_page: linesPerPage, ...(cpeId ? { cpe_id: cpeId } : {}) },
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
  search: (projectId: string, filename: string, pattern: string, cpeId?: string | null) =>
    api.post(`/projects/${projectId}/files/${filename}/search`, { pattern, cpe_id: cpeId || undefined }),
  searchAllFiles: (projectId: string, pattern: string, cpeId?: string | null) =>
    api.post<{ matches: Array<{ filename: string; line_number: number; text: string }>; total: number; pattern: string; truncated?: boolean }>(
      `/projects/${projectId}/files/search-all`,
      { pattern, cpe_id: cpeId ?? undefined }
    ),
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
};

// ---------- Telemetry ----------
export const telemetryApi = {
  parse: (projectId: string, cpeId?: string | null, force = false) =>
    api.post(`/projects/${projectId}/telemetry/parse`, null, {
      params: { ...(cpeId ? { cpe_id: cpeId } : {}), ...(force ? { force: "1" } : {}) },
    }),
  availableFields: (projectId: string, cpeId?: string | null) =>
    api.get(`/projects/${projectId}/telemetry/available-fields`, {
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
export interface UserPattern {
  name: string;
  regex: string;
  enabled: boolean;
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
    }
  ) => api.get<CPEOverviewResponse>(`/projects/${projectId}/cpe-overview`, { params }),
  getPatternScan: (projectId: string) =>
    api.get<PatternScanResult>(`/projects/${projectId}/cpe-overview/pattern-scan`),
  runPatternScan: (projectId: string) =>
    api.post<PatternScanResult>(`/projects/${projectId}/cpe-overview/pattern-scan`),
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
    api.get<{ enabled: boolean; available: boolean; model_info: Record<string, unknown> | null }>("/admin/settings/llm"),
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

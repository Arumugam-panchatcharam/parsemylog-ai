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
};

// ---------- Projects ----------
export const projectsApi = {
  list: () => api.get("/projects/"),
  create: (name: string, description?: string, natcoId?: number | null) =>
    api.post("/projects/", { name, description, natco_id: natcoId || undefined }),
  get: (id: string) => api.get(`/projects/${id}`),
  update: (id: string, data: { name?: string; description?: string; natco_id?: number | null }) =>
    api.put(`/projects/${id}`, data),
  delete: (id: string) => api.delete(`/projects/${id}`),
};

// ---------- CPEs ----------
export const cpesApi = {
  list: (projectId: string) => api.get(`/projects/${projectId}/cpes`),
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
  search: (projectId: string, filename: string, pattern: string, cpeId?: string | null) =>
    api.post(`/projects/${projectId}/files/${filename}/search`, { pattern, cpe_id: cpeId || undefined }),
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
export const cpeOverviewApi = {
  getSummary: (projectId: string) =>
    api.get(`/projects/${projectId}/cpe-overview`),
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
  diff: (projectId: string) =>
    api.get<{ domains: Record<string, DomainDiff>; natco: NatcoInfo | null }>(`/projects/${projectId}/patterns/diff`),
  sync: (projectId: string) =>
    api.post<{ domains: DomainPatterns; synced: number }>(`/projects/${projectId}/patterns/sync`),
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

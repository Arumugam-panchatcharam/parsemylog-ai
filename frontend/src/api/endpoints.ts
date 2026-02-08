import api from "./client";

// ---------- Auth ----------
export const authApi = {
  login: (username: string, password: string) =>
    api.post("/auth/login", { username, password }),
  register: (username: string, password: string, email?: string) =>
    api.post("/auth/register", { username, password, email }),
  refresh: () => api.post("/auth/refresh"),
  getProfile: () => api.get("/auth/profile"),
  updateProfile: (data: { username?: string; email?: string; password?: string }) =>
    api.put("/auth/profile", data),
};

// ---------- Projects ----------
export const projectsApi = {
  list: () => api.get("/projects/"),
  create: (name: string, description?: string) =>
    api.post("/projects/", { name, description }),
  get: (id: string) => api.get(`/projects/${id}`),
  delete: (id: string) => api.delete(`/projects/${id}`),
};

// ---------- Files ----------
export const filesApi = {
  list: (projectId: string) => api.get(`/projects/${projectId}/files`),
  upload: (projectId: string, files: File[]) => {
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    return api.post(`/projects/${projectId}/files/upload`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  getContent: (projectId: string, filename: string, page = 1, linesPerPage = 1000) =>
    api.get(`/projects/${projectId}/files/${filename}/content`, {
      params: { page, lines_per_page: linesPerPage },
    }),
  download: (projectId: string, filename: string) =>
    api.get(`/projects/${projectId}/files/${filename}/download`, { responseType: "blob" }),
  search: (projectId: string, filename: string, pattern: string) =>
    api.post(`/projects/${projectId}/files/${filename}/search`, { pattern }),
  getNotes: (projectId: string) => api.get(`/projects/${projectId}/notes`),
  saveNotes: (projectId: string, content: string) =>
    api.put(`/projects/${projectId}/notes`, { content }),
};

// ---------- Patterns ----------
export const patternsApi = {
  listDomains: (projectId: string) =>
    api.get(`/projects/${projectId}/domains`),
  analyze: (projectId: string, domain: string, fileFilter?: string[]) =>
    api.post(`/projects/${projectId}/domains/${domain}/analyze`, { file_filter: fileFilter }),
  getTimeseries: (projectId: string, domain: string, template: string, interval: number, fileFilter?: string) =>
    api.get(`/projects/${projectId}/domains/${domain}/timeseries`, {
      params: { template, interval, file_filter: fileFilter },
    }),
  getParameters: (projectId: string, domain: string, template: string, fileFilter?: string) =>
    api.get(`/projects/${projectId}/domains/${domain}/parameters`, {
      params: { template, file_filter: fileFilter },
    }),
  getLoglines: (projectId: string, domain: string, template: string, page = 1, pageSize = 20, fileFilter?: string) =>
    api.get(`/projects/${projectId}/domains/${domain}/loglines`, {
      params: { template, page, page_size: pageSize, file_filter: fileFilter },
    }),
  indexingStatus: (projectId: string) =>
    api.get(`/projects/${projectId}/indexing/status`),
};

// ---------- Telemetry ----------
export const telemetryApi = {
  parse: (projectId: string) =>
    api.post(`/projects/${projectId}/telemetry/parse`),
};

// ---------- AI Analysis ----------
export const aiApi = {
  search: (projectId: string, query: string, topK = 10) =>
    api.post(`/projects/${projectId}/ai/search`, { query, top_k: topK }),
  getContext: (projectId: string, data: {
    template: string;
    timestamp: string;
    window: number;
    unit: string;
    filename?: string;
    parquet_path?: string;
  }) => api.post(`/projects/${projectId}/ai/context`, data),
  getParameters: (projectId: string, data: {
    template: string;
    parquet_path?: string;
    domain?: string;
  }) => api.post(`/projects/${projectId}/ai/parameters`, data),
  getLoglines: (projectId: string, data: {
    template: string;
    parquet_path?: string;
    domain?: string;
    page?: number;
    page_size?: number;
  }) => api.post(`/projects/${projectId}/ai/loglines`, data),
};

// ---------- Embedding ----------
export const embeddingApi = {
  pipelineStatus: (projectId: string) =>
    api.get(`/projects/${projectId}/pipeline/status`),
  fileTemplates: (projectId: string, filename: string) =>
    api.get(`/projects/${projectId}/files/${filename}/templates`),
  downloadTemplates: (projectId: string) =>
    `${api.defaults.baseURL}/projects/${projectId}/templates/download`,
};

// ---------- Admin ----------
export const adminApi = {
  listUsers: () => api.get("/admin/users"),
  deleteUser: (userId: number) => api.delete(`/admin/users/${userId}`),
  resetPassword: (userId: number, password: string) =>
    api.put(`/admin/users/${userId}/password`, { password }),
  userProjects: (userId: number) => api.get(`/admin/users/${userId}/projects`),
};

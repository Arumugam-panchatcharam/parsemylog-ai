import { useState, useEffect, useRef, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "@/api/endpoints";
import type { AdminNatco, PatternSubmission, UserPattern, DomainPatterns, MaintenanceWindow } from "@/api/endpoints";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import DeleteIcon from "@mui/icons-material/Delete";
import VpnKeyIcon from "@mui/icons-material/VpnKey";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import RefreshIcon from "@mui/icons-material/Refresh";
import PeopleIcon from "@mui/icons-material/People";
import FolderIcon from "@mui/icons-material/Folder";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import PublicIcon from "@mui/icons-material/Public";
import RateReviewIcon from "@mui/icons-material/RateReview";
import SettingsIcon from "@mui/icons-material/Settings";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import AddIcon from "@mui/icons-material/Add";
import EditIcon from "@mui/icons-material/Edit";
import SaveIcon from "@mui/icons-material/Save";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ScheduleIcon from "@mui/icons-material/Schedule";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import CloseIcon from "@mui/icons-material/Close";
import CircularProgress from "@mui/material/CircularProgress";
import FilterListIcon from "@mui/icons-material/FilterList";
import { formatDate } from "@/lib/utils";
import { AdminRegexScanPreview } from "@/components/admin/AdminRegexScanPreview";

/* ================================================================ Types */
interface AdminUser {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
  created_at: string;
  last_login: string;
  project_count: number;
  file_count: number;
}

type TabKey = "users" | "natcos" | "reviews" | "settings";

/* ================================================================ Main */
export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("users");

  const tabs: { key: TabKey; label: string; icon: typeof PeopleIcon }[] = [
    { key: "users", label: "Users", icon: PeopleIcon },
    { key: "natcos", label: "NATCO Management", icon: PublicIcon },
    { key: "reviews", label: "Pattern Review", icon: RateReviewIcon },
    { key: "settings", label: "Settings", icon: SettingsIcon },
  ];

  return (
    <div className="w-full max-w-none min-w-0 p-4 sm:p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <AdminPanelSettingsIcon style={{ fontSize: 28 }} /> Admin Panel
        </h1>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-6 border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
            }`}
          >
            <t.icon style={{ fontSize: 18 }} />
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === "users" && <UsersTab />}
      {activeTab === "natcos" && <NatcoTab />}
      {activeTab === "reviews" && <ReviewTab />}
      {activeTab === "settings" && <SettingsTab />}
    </div>
  );
}

/* ================================================================ Users Tab */
function UsersTab() {
  const queryClient = useQueryClient();
  const [deleteUserId, setDeleteUserId] = useState<number | null>(null);
  const [resetUserId, setResetUserId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [viewProjectsUserId, setViewProjectsUserId] = useState<number | null>(null);

  const { data: users, isLoading } = useQuery({
    queryKey: ["adminUsers"],
    queryFn: async () => (await adminApi.listUsers()).data as AdminUser[],
  });

  const { data: userProjects } = useQuery({
    queryKey: ["adminUserProjects", viewProjectsUserId],
    queryFn: async () => (await adminApi.userProjects(viewProjectsUserId!)).data,
    enabled: !!viewProjectsUserId,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminApi.deleteUser(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["adminUsers"] }); setDeleteUserId(null); },
  });

  const resetMutation = useMutation({
    mutationFn: () => adminApi.resetPassword(resetUserId!, newPassword),
    onSuccess: () => { setResetUserId(null); setNewPassword(""); },
  });

  const stats = users ? {
    total: users.length,
    admins: users.filter(u => u.is_admin).length,
    projects: users.reduce((s, u) => s + u.project_count, 0),
    files: users.reduce((s, u) => s + u.file_count, 0),
  } : null;

  const sortedUsers = useMemo(() => {
    if (!users?.length) return users;
    return [...users].sort((a, b) =>
      a.username.localeCompare(b.username, undefined, { sensitivity: "base" }),
    );
  }, [users]);

  const statItems = [
    { label: "Users", value: stats?.total, icon: PeopleIcon, color: "#1a73e8" },
    { label: "Admins", value: stats?.admins, icon: AdminPanelSettingsIcon, color: "#f9ab00" },
    { label: "Projects", value: stats?.projects, icon: FolderIcon, color: "#188038" },
    { label: "Files", value: stats?.files, icon: InsertDriveFileIcon, color: "#5f6368" },
  ];

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">User Management</h2>
        <button onClick={() => queryClient.invalidateQueries({ queryKey: ["adminUsers"] })} title="Refresh user list" className="p-2 border border-border rounded-lg hover:bg-muted">
          <RefreshIcon style={{ fontSize: 18 }} />
        </button>
      </div>

      {stats && (
        <div className="grid grid-cols-4 gap-3 mb-6">
          {statItems.map((s) => (
            <div key={s.label} className="bg-card border border-border rounded-2xl p-4 text-center">
              <s.icon style={{ fontSize: 28, color: s.color }} className="mx-auto mb-1" />
              <p className="text-2xl font-bold">{s.value}</p>
              <p className="text-xs text-muted-foreground">{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {isLoading && <p className="text-muted-foreground">Loading...</p>}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
        {sortedUsers?.map((u) => (
          <div
            key={u.id}
            className="bg-card border border-border rounded-2xl p-4 h-full flex flex-col"
          >
            <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-sm flex items-center gap-1 flex-wrap">
                  {u.username}
                  {u.is_admin && (
                    <span title="Administrator">
                      <AdminPanelSettingsIcon style={{ fontSize: 16, color: "#f9ab00" }} />
                    </span>
                  )}
                </h3>
                <p className="text-xs text-muted-foreground break-words">
                  {u.email || "No email"} — Created: {formatDate(u.created_at)}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {u.project_count} projects, {u.file_count} files
                </p>
              </div>
              <div className="flex gap-1 shrink-0 sm:self-start">
                <button onClick={() => setViewProjectsUserId(u.id)} className="p-1.5 rounded hover:bg-accent" title="View Projects">
                  <FolderOpenIcon style={{ fontSize: 18, color: "#1a73e8" }} />
                </button>
                <button onClick={() => setResetUserId(u.id)} className="p-1.5 rounded hover:bg-yellow-100 dark:hover:bg-yellow-900/30" title="Reset Password">
                  <VpnKeyIcon style={{ fontSize: 18, color: "#f9ab00" }} />
                </button>
                <button onClick={() => setDeleteUserId(u.id)} disabled={u.is_admin} className="p-1.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30 disabled:opacity-30" title="Delete User">
                  <DeleteIcon style={{ fontSize: 18, color: "#d93025" }} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Delete Confirmation */}
      {deleteUserId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border rounded-2xl shadow-lg p-6 w-full max-w-sm">
            <h3 className="text-lg font-semibold mb-2">Delete User</h3>
            <p className="text-sm text-muted-foreground mb-1">This will permanently delete the user and all their data.</p>
            <div className="flex gap-2 mt-4">
              <button onClick={() => deleteMutation.mutate(deleteUserId)} className="flex-1 py-2.5 bg-destructive text-destructive-foreground rounded-lg font-medium">Delete</button>
              <button onClick={() => setDeleteUserId(null)} className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Reset Password */}
      {resetUserId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border rounded-2xl shadow-lg p-6 w-full max-w-sm">
            <h3 className="text-lg font-semibold mb-3">Reset Password</h3>
            <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="New password" className="w-full px-3 py-2.5 border border-input rounded-lg bg-background mb-3" />
            <div className="flex gap-2">
              <button onClick={() => resetMutation.mutate()} className="flex-1 py-2.5 bg-primary text-primary-foreground rounded-lg font-medium">Reset</button>
              <button onClick={() => { setResetUserId(null); setNewPassword(""); }} className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* User Projects Modal */}
      {viewProjectsUserId && userProjects && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border rounded-2xl shadow-lg p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-3">{userProjects.username}'s Projects</h3>
            {userProjects.projects.length === 0 ? (
              <p className="text-sm text-muted-foreground">No projects</p>
            ) : (
              <div className="space-y-2">
                {userProjects.projects.map((p: { id: string; name: string; description: string; file_count: number; total_size_mb: number }) => (
                  <div key={p.id} className="border border-border rounded-xl p-3">
                    <h4 className="font-medium text-sm">{p.name}</h4>
                    <p className="text-xs text-muted-foreground">{p.description || "No description"}</p>
                    <p className="text-xs text-muted-foreground mt-1">Files: {p.file_count} - Size: {p.total_size_mb} MB</p>
                  </div>
                ))}
              </div>
            )}
            <button onClick={() => setViewProjectsUserId(null)} className="mt-4 w-full py-2.5 border border-border rounded-lg hover:bg-muted">Close</button>
          </div>
        </div>
      )}
    </>
  );
}

/* ================================================================ NATCO Tab */
function NatcoTab() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [formCode, setFormCode] = useState("");
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formTenantId, setFormTenantId] = useState("");
  const [patternEditorNatcoId, setPatternEditorNatcoId] = useState<number | null>(null);

  const { data: natcos, isLoading } = useQuery({
    queryKey: ["adminNatcos"],
    queryFn: async () => (await adminApi.listNatcos()).data,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      adminApi.createNatco(formCode, formName, formDesc, formTenantId.trim() || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adminNatcos"] });
      setShowCreate(false);
      setFormCode(""); setFormName(""); setFormDesc(""); setFormTenantId("");
    },
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      adminApi.updateNatco(editId!, {
        code: formCode,
        name: formName,
        description: formDesc,
        remote_log_tenant_id: formTenantId.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adminNatcos"] });
      setEditId(null);
      setFormCode(""); setFormName(""); setFormDesc(""); setFormTenantId("");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminApi.deleteNatco(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["adminNatcos"] }),
  });

  const startEdit = (n: AdminNatco) => {
    setEditId(n.id);
    setFormCode(n.code);
    setFormName(n.name);
    setFormDesc(n.description || "");
    setFormTenantId(n.remote_log_tenant_id || "");
  };

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <PublicIcon style={{ fontSize: 22 }} /> NATCO Management
        </h2>
        <div className="flex gap-2">
          <button onClick={() => queryClient.invalidateQueries({ queryKey: ["adminNatcos"] })} title="Refresh NATCO list" className="p-2 border border-border rounded-lg hover:bg-muted">
            <RefreshIcon style={{ fontSize: 18 }} />
          </button>
          <button onClick={() => { setShowCreate(true); setFormCode(""); setFormName(""); setFormDesc(""); setFormTenantId(""); }} className="flex items-center gap-1.5 px-3 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90">
            <AddIcon style={{ fontSize: 18 }} /> New NATCO
          </button>
        </div>
      </div>

      {isLoading && <p className="text-muted-foreground text-sm">Loading...</p>}

      {natcos?.length === 0 && !isLoading && (
        <div className="text-center py-12 bg-card border border-border rounded-2xl text-muted-foreground">
          <PublicIcon style={{ fontSize: 40 }} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No NATCOs configured yet.</p>
          <p className="text-xs mt-1">Create your first NATCO to manage global pattern configurations.</p>
        </div>
      )}

      <div className="space-y-2">
        {natcos?.map((n) => (
          <div key={n.id} className="bg-card border border-border rounded-2xl p-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-sm flex items-center gap-2">
                  <span className="px-2 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded text-xs font-bold">{n.code}</span>
                  {n.name}
                </h3>
                <p className="text-xs text-muted-foreground mt-1">{n.description || "No description"}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {n.pattern_count} global patterns · Remote log tenant: {n.remote_log_tenant_id || "—"}
                  {" · "}Created: {formatDate(n.created_at)}
                </p>
              </div>
              <div className="flex gap-1">
                <button onClick={() => setPatternEditorNatcoId(n.id)} className="p-1.5 rounded hover:bg-accent" title="Edit Patterns">
                  <InsertDriveFileIcon style={{ fontSize: 18, color: "#1a73e8" }} />
                </button>
                <button onClick={() => startEdit(n)} className="p-1.5 rounded hover:bg-accent" title="Edit NATCO">
                  <EditIcon style={{ fontSize: 18, color: "#f9ab00" }} />
                </button>
                <button onClick={() => { if (confirm(`Delete NATCO "${n.code}" and all its patterns?`)) deleteMutation.mutate(n.id); }} className="p-1.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30" title="Delete NATCO">
                  <DeleteIcon style={{ fontSize: 18, color: "#d93025" }} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Create / Edit Modal */}
      {(showCreate || editId !== null) && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border rounded-2xl shadow-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">{editId ? "Edit NATCO" : "Create NATCO"}</h3>
            <form onSubmit={(e) => { e.preventDefault(); editId ? updateMutation.mutate() : createMutation.mutate(); }} className="space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">Code</label>
                <input type="text" value={formCode} onChange={(e) => setFormCode(e.target.value.toUpperCase())} placeholder="DE" className="w-full px-3 py-2.5 border border-input rounded-lg bg-background" maxLength={16} required />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Name</label>
                <input type="text" value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="Germany" className="w-full px-3 py-2.5 border border-input rounded-lg bg-background" required />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Description</label>
                <textarea value={formDesc} onChange={(e) => setFormDesc(e.target.value)} className="w-full px-3 py-2.5 border border-input rounded-lg bg-background resize-none" rows={2} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Remote log tenant id</label>
                <input
                  type="text"
                  value={formTenantId}
                  onChange={(e) => setFormTenantId(e.target.value)}
                  placeholder="e.g. cz (optional; overrides NATCO code for API tenant header)"
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background"
                />
              </div>
              <div className="flex gap-2 pt-2">
                <button type="submit" disabled={createMutation.isPending || updateMutation.isPending} className="flex-1 py-2.5 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-50">
                  {(createMutation.isPending || updateMutation.isPending) ? "Saving..." : editId ? "Update" : "Create"}
                </button>
                <button type="button" onClick={() => { setShowCreate(false); setEditId(null); }} className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Pattern Editor Modal */}
      {patternEditorNatcoId !== null && (
        <PatternEditorModal natcoId={patternEditorNatcoId} onClose={() => { setPatternEditorNatcoId(null); queryClient.invalidateQueries({ queryKey: ["adminNatcos"] }); }} />
      )}
    </>
  );
}

/* ================================================================ Pattern Editor Modal */
function PatternEditorModal({ natcoId, onClose }: { natcoId: number; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [domains, setDomains] = useState<DomainPatterns>({});
  const [loaded, setLoaded] = useState(false);
  const [collapsedDomains, setCollapsedDomains] = useState<Set<string>>(new Set());
  const [newDomainName, setNewDomainName] = useState("");
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["adminNatcoPatterns", natcoId],
    queryFn: async () => (await adminApi.getNatcoPatterns(natcoId)).data,
  });

  useEffect(() => {
    if (data && !loaded) {
      setDomains(data.domains);
      setLoaded(true);
    }
  }, [data, loaded]);

  const saveMutation = useMutation({
    mutationFn: () => adminApi.setNatcoPatterns(natcoId, domains),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["adminNatcoPatterns", natcoId] }),
  });

  const toggleCollapse = (d: string) => {
    setCollapsedDomains((prev) => { const n = new Set(prev); n.has(d) ? n.delete(d) : n.add(d); return n; });
  };

  const addDomain = () => {
    const name = newDomainName.trim();
    if (!name || domains[name]) return;
    setDomains((prev) => ({ ...prev, [name]: [] }));
    setNewDomainName("");
  };

  const removeDomain = (d: string) => {
    setDomains((prev) => { const n = { ...prev }; delete n[d]; return n; });
  };

  const addPattern = (d: string) => {
    setDomains((prev) => ({ ...prev, [d]: [...(prev[d] || []), { name: "", regex: "", enabled: true }] }));
  };

  const removePattern = (d: string, idx: number) => {
    setDomains((prev) => ({ ...prev, [d]: (prev[d] || []).filter((_, i) => i !== idx) }));
  };

  const updatePattern = (d: string, idx: number, field: keyof UserPattern, value: string | boolean) => {
    setDomains((prev) => ({ ...prev, [d]: (prev[d] || []).map((p, i) => (i === idx ? { ...p, [field]: value } : p)) }));
  };

  const [filterEditTarget, setFilterEditTarget] = useState<string | null>(null);
  const filterKey = (d: string, idx: number) => `${d}::${idx}`;

  const updatePatternMW = (d: string, idx: number, mw: MaintenanceWindow | null) => {
    setDomains((prev) => ({
      ...prev,
      [d]: (prev[d] || []).map((p, i) => (i === idx ? { ...p, maintenance_window: mw } : p)),
    }));
  };

  const updatePatternRP = (d: string, idx: number, rp: number | null) => {
    setDomains((prev) => ({
      ...prev,
      [d]: (prev[d] || []).map((p, i) => (i === idx ? { ...p, reboot_proximity_minutes: rp } : p)),
    }));
  };

  const updatePatternFT = (d: string, idx: number, ft: number | null) => {
    setDomains((prev) => ({
      ...prev,
      [d]: (prev[d] || []).map((p, i) => (i === idx ? { ...p, min_frequency_threshold: ft } : p)),
    }));
  };

  const updatePatternScanFilename = (d: string, idx: number, raw: string) => {
    const v = raw.trim();
    setDomains((prev) => ({
      ...prev,
      [d]: (prev[d] || []).map((p, i) =>
        i === idx ? { ...p, ...(v ? { scan_filename: v } : { scan_filename: undefined }) } : p,
      ),
    }));
  };

  const handleExportJSON = () => {
    const content = JSON.stringify({ domains }, null, 2);
    const blob = new Blob([content], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `global_patterns_${data?.natco?.code || "export"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  /** Parse and merge patterns from an imported JSON or YAML file. */
  const handleFileImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportMsg(null);

    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const text = ev.target?.result as string;
        let parsed: Record<string, unknown>;

        // Detect YAML vs JSON
        if (file.name.endsWith(".yaml") || file.name.endsWith(".yml")) {
          // Simple YAML parser: use JSON.parse after converting basic YAML
          // For full YAML, we rely on the structure being JSON-compatible
          // Actually let's use a simple approach: try JSON first, otherwise
          // convert simple YAML key-value patterns
          try {
            parsed = JSON.parse(text);
          } catch {
            // Basic YAML: extract patterns using regex-based heuristics
            // This handles the standard domain-grouped format the app exports
            const lines = text.split("\n");
            const result: Record<string, Array<{ name: string; regex: string; enabled: boolean; maintenance_window?: { start: string; end: string }; reboot_proximity_minutes?: number; min_frequency_threshold?: number }>> = {};
            let currentDomain = "";

            for (const line of lines) {
              const domainMatch = line.match(/^\s{2}(\S.+?):\s*$/);
              if (domainMatch) {
                currentDomain = domainMatch[1];
                if (!result[currentDomain]) result[currentDomain] = [];
                continue;
              }
              const nameMatch = line.match(/^\s+-\s+name:\s*(.+)$/);
              if (nameMatch && currentDomain) {
                result[currentDomain].push({ name: nameMatch[1].replace(/^['"]|['"]$/g, ""), regex: "", enabled: true });
                continue;
              }
              const regexMatch = line.match(/^\s+regex:\s*(.+)$/);
              if (regexMatch && currentDomain && result[currentDomain].length > 0) {
                result[currentDomain][result[currentDomain].length - 1].regex = regexMatch[1].replace(/^['"]|['"]$/g, "");
                continue;
              }
              const enabledMatch = line.match(/^\s+enabled:\s*(true|false)$/);
              if (enabledMatch && currentDomain && result[currentDomain].length > 0) {
                result[currentDomain][result[currentDomain].length - 1].enabled = enabledMatch[1] === "true";
                continue;
              }
              // Parse maintenance_window start
              const mwStartMatch = line.match(/^\s+maintenance_window:\s*\{?\s*start:\s*['"]?([^'"}\s]+)['"]?/);
              if (mwStartMatch && currentDomain && result[currentDomain].length > 0) {
                if (!result[currentDomain][result[currentDomain].length - 1].maintenance_window) {
                  result[currentDomain][result[currentDomain].length - 1].maintenance_window = { start: "", end: "" };
                }
                result[currentDomain][result[currentDomain].length - 1].maintenance_window!.start = mwStartMatch[1];
                continue;
              }
              // Parse maintenance_window end (can be on same line or separate)
              const mwEndMatch = line.match(/end:\s*['"]?([^'"}\s]+)['"]?/);
              if (mwEndMatch && currentDomain && result[currentDomain].length > 0) {
                if (!result[currentDomain][result[currentDomain].length - 1].maintenance_window) {
                  result[currentDomain][result[currentDomain].length - 1].maintenance_window = { start: "", end: "" };
                }
                result[currentDomain][result[currentDomain].length - 1].maintenance_window!.end = mwEndMatch[1];
                continue;
              }
              // Parse reboot_proximity_minutes
              const rpMatch = line.match(/^\s+reboot_proximity_minutes:\s*(\d+)$/);
              if (rpMatch && currentDomain && result[currentDomain].length > 0) {
                const rp = Number(rpMatch[1]);
                if (!isNaN(rp) && rp >= 1 && rp <= 60) {
                  result[currentDomain][result[currentDomain].length - 1].reboot_proximity_minutes = rp;
                }
              }
              // Parse min_frequency_threshold
              const ftMatch = line.match(/^\s+min_frequency_threshold:\s*(\d+)$/);
              if (ftMatch && currentDomain && result[currentDomain].length > 0) {
                const ft = Number(ftMatch[1]);
                if (!isNaN(ft) && ft >= 1 && ft <= 1000) {
                  result[currentDomain][result[currentDomain].length - 1].min_frequency_threshold = ft;
                }
              }
            }

            // Filter out patterns with empty regex
            const cleaned: Record<string, Array<{ name: string; regex: string; enabled: boolean; maintenance_window?: { start: string; end: string }; reboot_proximity_minutes?: number; min_frequency_threshold?: number }>> = {};
            for (const [d, pats] of Object.entries(result)) {
              const valid = pats.filter((p) => p.regex);
              if (valid.length > 0) cleaned[d] = valid;
            }

            if (Object.keys(cleaned).length > 0) {
              parsed = { domains: cleaned };
            } else {
              setImportMsg("Could not parse YAML file. Ensure it uses the standard domain-grouped format.");
              return;
            }
          }
        } else {
          parsed = JSON.parse(text);
        }

        // Now merge the parsed data into domains
        let imported = 0;

        // Format 1: { domains: { domain_name: [{name, regex, enabled}] } }
        if (parsed.domains && typeof parsed.domains === "object") {
          setDomains((prev) => {
            const next = { ...prev };
            for (const [domain, pats] of Object.entries(parsed.domains as Record<string, unknown>)) {
              if (!Array.isArray(pats)) continue;
              const existing = next[domain] || [];
              const existingRegexes = new Set(existing.map((p) => p.regex));
              const newPats = (pats as Array<Record<string, unknown>>)
                .map((p) => {
                  const pattern: UserPattern = {
                    name: String(p.name || "").slice(0, 200),
                    regex: String(p.regex || p.pattern || ""),
                    enabled: p.enabled !== false,
                  };
                  // Preserve maintenance_window if present
                  if (p.maintenance_window && typeof p.maintenance_window === "object") {
                    const mw = p.maintenance_window as { start?: string; end?: string };
                    if (mw.start && mw.end) {
                      pattern.maintenance_window = { start: mw.start, end: mw.end };
                    }
                  }
                  // Preserve reboot_proximity_minutes if present
                  if (p.reboot_proximity_minutes != null) {
                    const rp = Number(p.reboot_proximity_minutes);
                    if (!isNaN(rp) && rp >= 1 && rp <= 60) {
                      pattern.reboot_proximity_minutes = rp;
                    }
                  }
                  // Preserve min_frequency_threshold if present
                  if (p.min_frequency_threshold != null) {
                    const ft = Number(p.min_frequency_threshold);
                    if (!isNaN(ft) && ft >= 1 && ft <= 1000) {
                      pattern.min_frequency_threshold = ft;
                    }
                  }
                  return pattern;
                })
                .filter((p) => p.regex && !existingRegexes.has(p.regex));
              imported += newPats.length;
              next[domain] = [...existing, ...newPats];
            }
            return next;
          });
          setImportMsg(`Imported ${imported} new patterns. Click "Save All" to persist.`);
          return;
        }

        // Format 2: flat array [{name, regex}]
        if (Array.isArray(parsed)) {
          const pats = (parsed as Array<Record<string, unknown>>)
            .map((p) => {
              const pattern: UserPattern = {
                name: String(p.name || p.template || p.regex || "").slice(0, 200),
                regex: String(p.regex || p.pattern || p.template || ""),
                enabled: p.enabled !== false,
              };
              // Preserve maintenance_window if present
              if (p.maintenance_window && typeof p.maintenance_window === "object") {
                const mw = p.maintenance_window as { start?: string; end?: string };
                if (mw.start && mw.end) {
                  pattern.maintenance_window = { start: mw.start, end: mw.end };
                }
              }
              // Preserve reboot_proximity_minutes if present
              if (p.reboot_proximity_minutes != null) {
                const rp = Number(p.reboot_proximity_minutes);
                if (!isNaN(rp) && rp >= 1 && rp <= 60) {
                  pattern.reboot_proximity_minutes = rp;
                }
              }
              // Preserve min_frequency_threshold if present
              if (p.min_frequency_threshold != null) {
                const ft = Number(p.min_frequency_threshold);
                if (!isNaN(ft) && ft >= 1 && ft <= 1000) {
                  pattern.min_frequency_threshold = ft;
                }
              }
              return pattern;
            })
            .filter((p) => p.regex);

          if (pats.length > 0) {
            setDomains((prev) => {
              const existing = prev["Imported"] || [];
              const existingRegexes = new Set(existing.map((p) => p.regex));
              const newPats = pats.filter((p) => !existingRegexes.has(p.regex));
              imported = newPats.length;
              return { ...prev, Imported: [...existing, ...newPats] };
            });
            setImportMsg(`Imported ${imported} patterns into "Imported" domain. Click "Save All" to persist.`);
            return;
          }
        }

        // Format 3: rule_parser_config.json { "Domain": [ { Title, CPELogs: [{ Regex: [...] }] } ] }
        if (typeof parsed === "object") {
          const importedDomains: DomainPatterns = {};
          let found = false;
          for (const [key, issues] of Object.entries(parsed)) {
            if (!Array.isArray(issues)) continue;
            const patterns: UserPattern[] = [];
            for (const issue of issues as Array<Record<string, unknown>>) {
              const title = String(issue.Title || "");
              const cpeLogs = issue.CPELogs as Array<Record<string, unknown>> | undefined;
              if (!Array.isArray(cpeLogs)) continue;
              for (const cpeLog of cpeLogs) {
                const regexEntries = cpeLog.Regex as Array<Record<string, unknown>> | undefined;
                if (!Array.isArray(regexEntries)) continue;
                for (const rx of regexEntries) {
                  if (rx.pattern) {
                    const pattern: UserPattern = {
                      name: String(rx.description || title || String(rx.pattern).slice(0, 60)),
                      regex: String(rx.pattern),
                      enabled: true,
                    };
                    // Preserve maintenance_window if present
                    if (rx.maintenance_window && typeof rx.maintenance_window === "object") {
                      const mw = rx.maintenance_window as { start?: string; end?: string };
                      if (mw.start && mw.end) {
                        pattern.maintenance_window = { start: mw.start, end: mw.end };
                      }
                    }
                    // Preserve reboot_proximity_minutes if present
                    if (rx.reboot_proximity_minutes != null) {
                      const rp = Number(rx.reboot_proximity_minutes);
                      if (!isNaN(rp) && rp >= 1 && rp <= 60) {
                        pattern.reboot_proximity_minutes = rp;
                      }
                    }
                    // Preserve min_frequency_threshold if present
                    if (rx.min_frequency_threshold != null) {
                      const ft = Number(rx.min_frequency_threshold);
                      if (!isNaN(ft) && ft >= 1 && ft <= 1000) {
                        pattern.min_frequency_threshold = ft;
                      }
                    }
                    patterns.push(pattern);
                    found = true;
                  }
                }
              }
            }
            if (patterns.length > 0) importedDomains[key] = patterns;
          }
          if (found) {
            setDomains((prev) => {
              const next = { ...prev };
              for (const [domain, pats] of Object.entries(importedDomains)) {
                const existing = next[domain] || [];
                const existingRegexes = new Set(existing.map((p) => p.regex));
                const newPats = pats.filter((p) => !existingRegexes.has(p.regex));
                imported += newPats.length;
                next[domain] = [...existing, ...newPats];
              }
              return next;
            });
            setImportMsg(`Imported ${imported} patterns from rule config. Click "Save All" to persist.`);
            return;
          }
        }

        setImportMsg("Unrecognized file format. Supported: domain-grouped JSON/YAML, flat array, or rule_parser_config.");
      } catch {
        setImportMsg("Failed to parse file. Please check the format.");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const totalPatterns = Object.values(domains).flat().length;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-card border rounded-2xl shadow-lg w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between shrink-0">
          <div className="min-w-0">
            <h3 className="text-lg font-semibold flex items-center gap-2 flex-wrap">
              <PublicIcon style={{ fontSize: 20 }} />
              Global Patterns {data?.natco && <span className="text-sm font-normal text-muted-foreground">- {data.natco.code}: {data.natco.name}</span>}
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">{Object.keys(domains).length} domains, {totalPatterns} patterns</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            <button onClick={() => fileInputRef.current?.click()} title="Import patterns from JSON or YAML file" className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-background hover:bg-muted">
              <UploadFileIcon style={{ fontSize: 14 }} />
              Import JSON/YAML
            </button>
            <input ref={fileInputRef} type="file" accept=".json,.yaml,.yml" onChange={handleFileImport} className="hidden" />
            <button onClick={handleExportJSON} title="Export patterns as JSON file" className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-background hover:bg-muted">
              <FileDownloadIcon style={{ fontSize: 14 }} />
              Export JSON
            </button>
            <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} title="Save all pattern changes to database" className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">
              {saveMutation.isPending ? <CircularProgress size={12} sx={{ color: "white" }} /> : <SaveIcon style={{ fontSize: 14 }} />}
              Save All
            </button>
            <button
              type="button"
              onClick={onClose}
              title="Close"
              aria-label="Close Global Patterns"
              className="ml-auto sm:ml-0 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-red-300 bg-background text-red-600 hover:bg-red-50 hover:text-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/35 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-950/50 dark:hover:text-red-300"
            >
              <CloseIcon style={{ fontSize: 20 }} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="flex items-center gap-2 justify-center py-8"><CircularProgress size={20} /> Loading...</div>
          ) : (
            <>
              {/* Add domain row */}
              <div className="flex gap-2 mb-4">
                <input type="text" value={newDomainName} onChange={(e) => setNewDomainName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addDomain()} placeholder="New domain name" className="flex-1 text-sm px-3 py-2 rounded-lg border border-border bg-background" />
                <button onClick={addDomain} disabled={!newDomainName.trim()} title="Add new domain" className="px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                  <AddIcon style={{ fontSize: 16 }} />
                </button>
              </div>

              {saveMutation.isSuccess && <div className="mb-3 px-3 py-2 bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400 text-xs rounded-lg">Patterns saved successfully.</div>}
              {importMsg && <div className="mb-3 px-3 py-2 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 text-xs rounded-lg flex items-center gap-1.5"><UploadFileIcon style={{ fontSize: 14 }} />{importMsg}</div>}

              <AdminRegexScanPreview patterns={Object.values(domains).flat()} />

              {/* Domains */}
              <div className="space-y-2">
                {Object.keys(domains).map((domain) => {
                  const pats = domains[domain] || [];
                  const collapsed = collapsedDomains.has(domain);
                  return (
                    <div key={domain} className="border border-border rounded-xl overflow-hidden">
                      <div className="flex items-center justify-between px-4 py-2 bg-muted/30 cursor-pointer hover:bg-muted/50" onClick={() => toggleCollapse(domain)}>
                        <div className="flex items-center gap-2">
                          {collapsed ? <ExpandMoreIcon style={{ fontSize: 18 }} /> : <ExpandLessIcon style={{ fontSize: 18 }} />}
                          <span className="text-sm font-semibold">{domain}</span>
                          <span className="text-xs text-muted-foreground">({pats.length})</span>
                        </div>
                        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                          <button onClick={() => addPattern(domain)} title="Add pattern to this domain" className="p-1 rounded hover:bg-blue-100 dark:hover:bg-blue-900/20"><AddIcon style={{ fontSize: 16 }} /></button>
                          <button onClick={() => { if (confirm(`Remove domain "${domain}"?`)) removeDomain(domain); }} title="Remove this domain and all its patterns" className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/20"><DeleteIcon style={{ fontSize: 16 }} /></button>
                        </div>
                      </div>
                      {!collapsed && (
                        <div className="px-4 py-2 space-y-1">
                          {pats.length === 0 ? (
                            <p className="text-xs text-muted-foreground py-2 text-center">No patterns</p>
                          ) : (
                            <>
                              <div className="grid grid-cols-[32px_1fr_2fr_36px_32px] gap-2 px-1">
                                <span className="text-[10px] text-muted-foreground font-semibold uppercase">On</span>
                                <span className="text-[10px] text-muted-foreground font-semibold uppercase">Name</span>
                                <span className="text-[10px] text-muted-foreground font-semibold uppercase">Regex</span>
                                <span className="text-[10px] text-muted-foreground font-semibold uppercase">Filters</span>
                                <span />
                              </div>
                              {pats.map((p, idx) => {
                                const fk = filterKey(domain, idx);
                                const hasMW = !!p.maintenance_window;
                                const hasRP = p.reboot_proximity_minutes != null && p.reboot_proximity_minutes > 0;
                                const hasFT = p.min_frequency_threshold != null && p.min_frequency_threshold > 0;
                                const hasScanFn = !!(p.scan_filename?.trim());
                                const hasFilter = hasMW || hasRP || hasFT || hasScanFn;
                                const filterTitleParts = [
                                  hasScanFn ? `file: ${p.scan_filename}` : null,
                                  hasMW ? `MW: ${p.maintenance_window?.start ?? "–"}–${p.maintenance_window?.end ?? "–"}` : null,
                                  hasRP ? `RP: ±${p.reboot_proximity_minutes}m` : null,
                                  hasFT ? `FT: >${p.min_frequency_threshold}` : null,
                                ].filter(Boolean);
                                const filterTitle =
                                  filterTitleParts.length > 0
                                    ? filterTitleParts.join(" | ")
                                    : "Add scan file / maintenance window / reboot proximity / frequency filters";
                                return (
                                  <div key={idx}>
                                    <div className="grid grid-cols-[32px_1fr_2fr_36px_32px] gap-2 items-center px-1 py-0.5 rounded hover:bg-muted/30">
                                      <input type="checkbox" checked={p.enabled} onChange={(e) => updatePattern(domain, idx, "enabled", e.target.checked)} className="h-3.5 w-3.5 accent-blue-600" />
                                      <input type="text" value={p.name} onChange={(e) => updatePattern(domain, idx, "name", e.target.value)} placeholder="Name" className="text-xs px-2 py-1 rounded border border-border bg-background min-w-0" />
                                      <input type="text" value={p.regex} onChange={(e) => updatePattern(domain, idx, "regex", e.target.value)} placeholder="Regex" className="text-xs px-2 py-1 rounded border border-border bg-background font-mono min-w-0" />
                                      <button
                                        onClick={() => setFilterEditTarget(filterEditTarget === fk ? null : fk)}
                                        title={filterTitle}
                                        className={`p-0.5 rounded text-xs flex items-center justify-center gap-0.5 ${hasFilter ? "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400" : "hover:bg-muted text-muted-foreground"}`}
                                      >
                                        <FilterListIcon style={{ fontSize: 14 }} />
                                      </button>
                                      <button onClick={() => removePattern(domain, idx)} title="Remove this pattern" className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20"><DeleteIcon style={{ fontSize: 14 }} /></button>
                                    </div>
                                    {filterEditTarget === fk && (
                                      <div className="ml-6 mr-2 my-2 p-3 border border-border rounded-lg bg-muted/50 dark:bg-muted/30 space-y-3 text-xs text-foreground">
                                        {/* Scan log file (basename; global NATCO default for ripgrep paths) */}
                                        <div className="flex flex-wrap items-center gap-2">
                                          <InsertDriveFileIcon style={{ fontSize: 14 }} className="text-sky-600 dark:text-sky-400 shrink-0" />
                                          <span className="text-muted-foreground shrink-0">Scan file</span>
                                          <input
                                            type="text"
                                            value={p.scan_filename ?? ""}
                                            onChange={(e) => updatePatternScanFilename(domain, idx, e.target.value)}
                                            placeholder="e.g. messages"
                                            className="flex-1 min-w-[140px] max-w-[240px] px-1.5 py-0.5 rounded border border-border bg-background text-xs font-mono"
                                          />
                                          <span className="text-[10px] text-muted-foreground">basename only; empty = all files</span>
                                          {hasScanFn && (
                                            <button
                                              type="button"
                                              onClick={() => updatePatternScanFilename(domain, idx, "")}
                                              className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground"
                                              title="Clear scan file"
                                            >
                                              <CloseIcon style={{ fontSize: 12 }} />
                                            </button>
                                          )}
                                        </div>
                                        {/* Maintenance Window */}
                                        <div className="flex items-center gap-2">
                                          <ScheduleIcon style={{ fontSize: 14 }} className="text-purple-600 dark:text-purple-400 shrink-0" />
                                          <span className="text-muted-foreground w-8 shrink-0">MW</span>
                                          <input
                                            type="time"
                                            value={p.maintenance_window?.start ?? ""}
                                            onChange={(e) => updatePatternMW(domain, idx, { start: e.target.value, end: p.maintenance_window?.end ?? "" })}
                                            className="px-1.5 py-0.5 rounded border border-border bg-background text-xs w-24"
                                          />
                                          <span className="text-muted-foreground">–</span>
                                          <input
                                            type="time"
                                            value={p.maintenance_window?.end ?? ""}
                                            onChange={(e) => updatePatternMW(domain, idx, { start: p.maintenance_window?.start ?? "", end: e.target.value })}
                                            className="px-1.5 py-0.5 rounded border border-border bg-background text-xs w-24"
                                          />
                                          <span className="text-[10px] text-muted-foreground">UTC</span>
                                          {hasMW && (
                                            <button onClick={() => updatePatternMW(domain, idx, null)} className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20" title="Clear maintenance window">
                                              <CloseIcon style={{ fontSize: 12 }} />
                                            </button>
                                          )}
                                        </div>
                                        {/* Reboot Proximity */}
                                        <div className="flex items-center gap-2">
                                          <RestartAltIcon style={{ fontSize: 14 }} className="text-orange-600 dark:text-orange-400 shrink-0" />
                                          <span className="text-muted-foreground w-8 shrink-0">±</span>
                                          <input
                                            type="number"
                                            min={1}
                                            max={60}
                                            value={p.reboot_proximity_minutes ?? ""}
                                            onChange={(e) => updatePatternRP(domain, idx, e.target.value ? Number(e.target.value) : null)}
                                            placeholder="min"
                                            className="px-1.5 py-0.5 rounded border border-border bg-background text-xs w-16"
                                          />
                                          <span className="text-[10px] text-foreground/90">minutes around reboot</span>
                                          {hasRP && (
                                            <button onClick={() => updatePatternRP(domain, idx, null)} className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20" title="Clear reboot proximity">
                                              <CloseIcon style={{ fontSize: 12 }} />
                                            </button>
                                          )}
                                        </div>
                                        <div className="flex items-center gap-2">
                                          <FilterListIcon style={{ fontSize: 14 }} className="text-blue-600 dark:text-blue-400 shrink-0" />
                                          <span className="text-muted-foreground w-8 shrink-0">&gt;</span>
                                          <input
                                            type="number"
                                            min={1}
                                            max={1000}
                                            value={p.min_frequency_threshold ?? ""}
                                            onChange={(e) => updatePatternFT(domain, idx, e.target.value ? Number(e.target.value) : null)}
                                            placeholder="count"
                                            className="px-1.5 py-0.5 rounded border border-border bg-background text-xs w-20"
                                          />
                                          <span className="text-[10px] text-foreground/90">min frequency threshold</span>
                                          {hasFT && (
                                            <button onClick={() => updatePatternFT(domain, idx, null)} className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20" title="Clear frequency threshold">
                                              <CloseIcon style={{ fontSize: 12 }} />
                                            </button>
                                          )}
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

interface SubmissionDiffData {
  diff: {
    new: Array<Record<string, unknown>>;
    modified: Array<{ submitted: Record<string, unknown>; current: Record<string, unknown> }>;
    total_current: number;
  };
}

function SubmissionPatternList({ submission }: { submission: PatternSubmission }) {
  const { data: diffData, isLoading } = useQuery({
    queryKey: ["adminSubmissionDetail", submission.id],
    queryFn: async () => (await adminApi.getSubmission(submission.id)).data as SubmissionDiffData,
  });

  // Build a map of regex -> current pattern for modified patterns
  const modifiedMap = new Map<string, Record<string, unknown>>();
  if (diffData?.diff?.modified) {
    for (const m of diffData.diff.modified) {
      const sub = m.submitted as Record<string, unknown>;
      modifiedMap.set(String(sub.regex), m.current);
    }
  }

  const fmtMw = (mw?: { start?: string; end?: string } | null) => mw?.start && mw?.end ? `${mw.start}–${mw.end}` : "none";

  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold text-muted-foreground uppercase">Submitted Patterns</p>
      {submission.patterns.map((p: UserPattern & { change_type?: string }, idx: number) => {
        const current = modifiedMap.get(p.regex);
        const changes: Array<{ label: string; from: string; to: string }> = [];
        
        const fmtScanFn = (sf: unknown) => {
          const s = sf != null && String(sf).trim() ? String(sf).trim() : "";
          return s || "none";
        };

        if (current && p.change_type === "modified") {
          if (current.name !== p.name) changes.push({ label: "name", from: String(current.name), to: String(p.name) });
          if (current.enabled !== p.enabled) changes.push({ label: "enabled", from: String(current.enabled ?? true), to: String(p.enabled ?? true) });
          const curMw = current.maintenance_window as { start?: string; end?: string } | null | undefined;
          const subMw = p.maintenance_window;
          if (fmtMw(curMw) !== fmtMw(subMw)) changes.push({ label: "MW", from: fmtMw(curMw), to: fmtMw(subMw) });
          const curRp = current.reboot_proximity_minutes as number | null | undefined;
          const subRp = p.reboot_proximity_minutes;
          if ((curRp ?? null) !== (subRp ?? null)) changes.push({ label: "reboot", from: curRp != null ? `±${curRp}m` : "none", to: subRp != null ? `±${subRp}m` : "none" });
          const curFt = current.min_frequency_threshold as number | null | undefined;
          const subFt = p.min_frequency_threshold;
          if ((curFt ?? null) !== (subFt ?? null)) changes.push({ label: "frequency", from: curFt != null ? `>${curFt}` : "none", to: subFt != null ? `>${subFt}` : "none" });
          const curSf = fmtScanFn(current.scan_filename);
          const subSf = fmtScanFn(p.scan_filename);
          if (curSf !== subSf) changes.push({ label: "scan file", from: curSf, to: subSf });
        }

        return (
          <div key={idx} className="space-y-1">
            <div className="flex items-center gap-3 px-3 py-1.5 bg-muted/40 dark:bg-muted/25 rounded-lg text-xs border border-border/60">
              <span className={`w-4 h-4 rounded-full flex items-center justify-center shrink-0 ${p.enabled ? "bg-emerald-600 dark:bg-emerald-500" : "bg-muted-foreground/35"}`}>
                {p.enabled ? <CheckCircleIcon style={{ fontSize: 12, color: "white" }} /> : null}
              </span>
              {p.change_type === "new" ? (
                <span className="px-1.5 py-0.5 rounded-md text-[10px] font-bold shrink-0 border border-emerald-500/50 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200">
                  NEW
                </span>
              ) : p.change_type === "modified" ? (
                <span className="px-1.5 py-0.5 rounded-md text-[10px] font-bold shrink-0 border border-primary/45 bg-primary/10 text-foreground">
                  MODIFIED
                </span>
              ) : null}
              <span className="font-medium min-w-[120px]">{p.name}</span>
              <code className="font-mono text-[11px] text-muted-foreground flex-1 truncate">{p.regex}</code>
              {p.maintenance_window && (
                <span
                  className="shrink-0 px-1.5 py-0.5 rounded-md text-[10px] border border-border bg-muted/50 text-foreground"
                  title="Maintenance window"
                >
                  <ScheduleIcon style={{ fontSize: 10, marginRight: 2 }} className="text-violet-600 dark:text-violet-400 inline align-middle" />
                  {p.maintenance_window.start}–{p.maintenance_window.end}
                </span>
              )}
              {p.reboot_proximity_minutes != null && p.reboot_proximity_minutes > 0 && (
                <span
                  className="shrink-0 px-1.5 py-0.5 rounded-md text-[10px] border border-border bg-muted/50 text-foreground"
                  title="Reboot proximity"
                >
                  <RestartAltIcon style={{ fontSize: 10, marginRight: 2 }} className="text-orange-600 dark:text-orange-400 inline align-middle" />
                  ±{p.reboot_proximity_minutes}m
                </span>
              )}
              {p.min_frequency_threshold != null && p.min_frequency_threshold > 0 && (
                <span
                  className="shrink-0 px-1.5 py-0.5 rounded-md text-[10px] border border-border bg-muted/50 text-foreground"
                  title="Minimum frequency threshold"
                >
                  <FilterListIcon style={{ fontSize: 10, marginRight: 2 }} className="text-sky-600 dark:text-sky-400 inline align-middle" />
                  &gt;{p.min_frequency_threshold}
                </span>
              )}
              {p.scan_filename?.trim() && (
                <span
                  className="shrink-0 px-1.5 py-0.5 rounded-md text-[10px] border border-border bg-muted/50 text-foreground max-w-[120px] truncate"
                  title={`Scan log file: ${p.scan_filename}`}
                >
                  <InsertDriveFileIcon style={{ fontSize: 10, marginRight: 2 }} className="text-sky-600 dark:text-sky-400 inline align-middle" />
                  {p.scan_filename}
                </span>
              )}
            </div>
            {changes.length > 0 && (
              <div className="ml-4 sm:ml-6 px-3 py-2 bg-muted/40 border border-border rounded-lg text-xs">
                <div className="flex flex-wrap gap-x-4 gap-y-0.5">
                  {changes.map((c) => (
                    <span key={c.label} className="text-[11px] text-foreground/95">
                      <span className="text-muted-foreground">{c.label}:</span>{" "}
                      <span className="line-through text-red-600/90 dark:text-red-400/95">{c.from}</span>{" → "}
                      <span className="text-emerald-700 dark:text-emerald-300">{c.to}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
      {isLoading && <div className="flex items-center gap-2 text-xs text-muted-foreground py-2"><CircularProgress size={12} /> Loading diff...</div>}
    </div>
  );
}

/* ================================================================ Review Tab */
function ReviewTab() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("pending");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [adminComment, setAdminComment] = useState("");

  const { data: submissions, isLoading } = useQuery({
    queryKey: ["adminSubmissions", statusFilter],
    queryFn: async () => (await adminApi.listSubmissions(statusFilter || undefined)).data,
  });

  const approveMutation = useMutation({
    mutationFn: (id: number) => adminApi.approveSubmission(id, adminComment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adminSubmissions"] });
      setExpandedId(null);
      setAdminComment("");
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: number) => adminApi.rejectSubmission(id, adminComment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adminSubmissions"] });
      setExpandedId(null);
      setAdminComment("");
    },
  });

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending:
        "border border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-100",
      approved:
        "border border-emerald-500/40 bg-emerald-500/10 text-emerald-900 dark:text-emerald-100",
      rejected: "border border-destructive/40 bg-destructive/10 text-destructive",
    };
    return (
      <span className={`px-2 py-0.5 rounded-md text-xs font-medium ${colors[status] || "border border-border bg-muted"}`}>
        {status}
      </span>
    );
  };

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <RateReviewIcon style={{ fontSize: 22 }} /> Pattern Submissions
        </h2>
        <div className="flex gap-2">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} title="Filter pattern submissions by approval status" className="text-sm px-3 py-1.5 border border-border rounded-lg bg-background">
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="">All</option>
          </select>
          <button onClick={() => queryClient.invalidateQueries({ queryKey: ["adminSubmissions"] })} title="Refresh pattern submissions" className="p-2 border border-border rounded-lg hover:bg-muted">
            <RefreshIcon style={{ fontSize: 18 }} />
          </button>
        </div>
      </div>

      {isLoading && <p className="text-muted-foreground text-sm">Loading submissions...</p>}

      {submissions?.length === 0 && !isLoading && (
        <div className="text-center py-12 bg-card border border-border rounded-2xl text-muted-foreground">
          <RateReviewIcon style={{ fontSize: 40 }} className="mx-auto mb-2 opacity-50" />
          <p className="text-sm">No {statusFilter || ""} submissions.</p>
        </div>
      )}

      <div className="space-y-2">
        {submissions?.map((s: PatternSubmission) => {
          const isExpanded = expandedId === s.id;
          return (
            <div key={s.id} className="bg-card border border-border rounded-2xl overflow-hidden">
              <div className="p-4 cursor-pointer hover:bg-muted/20" onClick={() => setExpandedId(isExpanded ? null : s.id)}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {statusBadge(s.status)}
                    <span className="text-sm font-semibold">{s.domain}</span>
                    <span className="text-xs text-muted-foreground">by {s.username}</span>
                    <span className="px-1.5 py-0.5 rounded-md text-[10px] font-bold border border-primary/35 bg-primary/10 text-foreground">
                      {s.natco_code}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">{s.patterns.length} pattern(s)</span>
                    <span className="text-xs text-muted-foreground">{formatDate(s.created_at)}</span>
                    {isExpanded ? <ExpandLessIcon style={{ fontSize: 18 }} /> : <ExpandMoreIcon style={{ fontSize: 18 }} />}
                  </div>
                </div>
                {s.comment && <p className="text-xs text-muted-foreground mt-1 italic">"{s.comment}"</p>}
              </div>

              {isExpanded && (
                <div className="border-t border-border p-4 space-y-3">
                  <SubmissionPatternList submission={s} />

                  <AdminRegexScanPreview
                    defaultUserId={s.user_id}
                    patterns={s.patterns.filter((p) => p.enabled !== false && p.regex.trim())}
                  />

                  {s.admin_comment && (
                    <div className="px-3 py-2 bg-amber-50 dark:bg-amber-900/20 rounded text-xs text-amber-800 dark:text-amber-400">
                      Admin: {s.admin_comment}
                    </div>
                  )}

                  {/* Actions for pending */}
                  {s.status === "pending" && (
                    <div className="space-y-2">
                      <textarea
                        value={adminComment}
                        onChange={(e) => setAdminComment(e.target.value)}
                        placeholder="Admin comment (optional)"
                        className="w-full text-sm px-3 py-2 rounded-lg border border-border bg-background resize-none"
                        rows={2}
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={() => approveMutation.mutate(s.id)}
                          disabled={approveMutation.isPending}
                          className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-lg text-sm font-medium border-2 border-emerald-600/80 bg-emerald-600/15 text-emerald-800 hover:bg-emerald-600/25 dark:text-emerald-200 dark:border-emerald-500/70 dark:hover:bg-emerald-500/20 disabled:opacity-50"
                        >
                          {approveMutation.isPending ? <CircularProgress size={14} /> : <CheckCircleIcon style={{ fontSize: 16 }} />}
                          Approve & Merge
                        </button>
                        <button
                          onClick={() => rejectMutation.mutate(s.id)}
                          disabled={rejectMutation.isPending}
                          className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-lg text-sm font-medium border-2 border-destructive/80 bg-destructive/10 text-destructive hover:bg-destructive/20 dark:hover:bg-destructive/25 disabled:opacity-50"
                        >
                          {rejectMutation.isPending ? <CircularProgress size={14} /> : <CancelIcon style={{ fontSize: 16 }} />}
                          Reject
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}


/* ================================================================ Settings Tab (LLM) */
function SettingsTab() {
  const queryClient = useQueryClient();

  const { data: llmSettings, isLoading } = useQuery({
    queryKey: ["adminLlmSettings"],
    queryFn: async () => (await adminApi.getLlmSettings()).data,
    refetchInterval: 15000, // poll every 15s for health changes
  });

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => adminApi.setLlmSettings(enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["adminLlmSettings"] }),
  });

  const providers = llmSettings?.providers as {
    openai?: { configured: boolean; available: boolean; model: string | null; base_url: string | null };
    openrouter?: { configured: boolean; available: boolean; model: string | null };
  };

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <SettingsIcon style={{ fontSize: 22 }} /> System Settings
        </h2>
        <button onClick={() => queryClient.invalidateQueries({ queryKey: ["adminLlmSettings"] })} title="Refresh settings" className="p-2 border border-border rounded-lg hover:bg-muted">
          <RefreshIcon style={{ fontSize: 18 }} />
        </button>
      </div>

      {/* LLM Settings Card */}
      <div className="bg-card border border-border rounded-2xl p-6 max-w-2xl">
        <div className="flex items-start gap-4">
          <div className="shrink-0 h-12 w-12 rounded-xl bg-primary/10 flex items-center justify-center">
            <SmartToyIcon style={{ fontSize: 28 }} className="text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold">AI Chat</h3>
            <p className="text-sm text-muted-foreground mt-0.5">
              Enable or disable the AI-powered log analysis chat for all users.
            </p>

            {/* Toggle */}
            <div className="flex items-center gap-3 mt-4">
              <button
                onClick={() => toggleMutation.mutate(!llmSettings?.enabled)}
                disabled={isLoading || toggleMutation.isPending}
                title="Enable or disable AI chat for all users"
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30 ${
                  llmSettings?.enabled ? "bg-primary" : "bg-gray-300 dark:bg-gray-600"
                } disabled:opacity-50`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    llmSettings?.enabled ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
              <span className="text-sm font-medium">
                {llmSettings?.enabled ? "Enabled" : "Disabled"}
              </span>
              {toggleMutation.isPending && <CircularProgress size={14} />}
            </div>

            {/* Provider Status */}
            <div className="mt-4 space-y-3">
              {/* OpenAI */}
              <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">OpenAI</span>
                    {llmSettings?.active_provider === "openai" && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-primary/20 text-primary rounded font-medium">
                        ACTIVE
                      </span>
                    )}
                  </div>
                  {providers?.openai?.model && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Model: {providers.openai.model}
                    </p>
                  )}
                  {providers?.openai?.base_url && (
                    <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-md" title={providers.openai.base_url}>
                      Endpoint: {providers.openai.base_url}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  {isLoading ? (
                    <CircularProgress size={12} />
                  ) : providers?.openai?.available ? (
                    <>
                      <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                      <span className="text-xs text-green-600 dark:text-green-400">Configured</span>
                    </>
                  ) : providers?.openai?.configured ? (
                    <>
                      <span className="h-2 w-2 rounded-full bg-yellow-500" />
                      <span className="text-xs text-yellow-600 dark:text-yellow-400">Error</span>
                    </>
                  ) : (
                    <>
                      <span className="h-2 w-2 rounded-full bg-red-500" />
                      <span className="text-xs text-red-500">Not configured</span>
                    </>
                  )}
                </div>
              </div>

              {/* OpenRouter */}
              <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">OpenRouter (Fallback)</span>
                    {llmSettings?.active_provider === "openrouter" && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-primary/20 text-primary rounded font-medium">
                        ACTIVE
                      </span>
                    )}
                  </div>
                  {providers?.openrouter?.model && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {providers.openrouter.model}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  {isLoading ? (
                    <CircularProgress size={12} />
                  ) : providers?.openrouter?.available ? (
                    <>
                      <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                      <span className="text-xs text-green-600 dark:text-green-400">Configured</span>
                    </>
                  ) : (
                    <>
                      <span className="h-2 w-2 rounded-full bg-red-500" />
                      <span className="text-xs text-red-500">Not configured</span>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Configuration Instructions */}
            {llmSettings?.enabled && !llmSettings?.available && (
              <div className="mt-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg">
                <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
                  Configuration Required
                </p>
                <p className="text-xs text-yellow-700 dark:text-yellow-300 mt-1">
                  Add at least one API key to .env:
                </p>
                <ul className="text-xs text-yellow-700 dark:text-yellow-300 mt-1 space-y-0.5 ml-4 list-disc">
                  <li><code className="bg-yellow-100 dark:bg-yellow-900/40 px-1 rounded">OPENAI_API_KEY=your-key</code></li>
                  <li><code className="bg-yellow-100 dark:bg-yellow-900/40 px-1 rounded">OPENAI_BASE_URL=https://...</code> (for Azure OpenAI)</li>
                  <li><code className="bg-yellow-100 dark:bg-yellow-900/40 px-1 rounded">OPENAI_MODEL=gpt-4.1</code></li>
                  <li>Or <code className="bg-yellow-100 dark:bg-yellow-900/40 px-1 rounded">OPENROUTER_API_KEY=sk-...</code> (fallback)</li>
                </ul>
              </div>
            )}

            {/* Active Provider Info */}
            {llmSettings?.active_provider && (
              <div className="mt-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
                <p className="text-sm font-medium text-green-800 dark:text-green-200">
                  ✓ AI Chat Ready
                </p>
                <p className="text-xs text-green-700 dark:text-green-300 mt-1">
                  Using <strong>{llmSettings.active_provider === "openai" ? "OpenAI" : "OpenRouter"}</strong>
                  {llmSettings.active_provider === "openai" && " with function calling for tool access"}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

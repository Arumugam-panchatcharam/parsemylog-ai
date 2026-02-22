import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "@/api/endpoints";
import type { AdminNatco, PatternSubmission, UserPattern, DomainPatterns } from "@/api/endpoints";
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
import DownloadIcon from "@mui/icons-material/Download";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CancelIcon from "@mui/icons-material/Cancel";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import CircularProgress from "@mui/material/CircularProgress";
import { formatDate } from "@/lib/utils";

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
    <div className="p-6 max-w-6xl mx-auto">
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
        <button onClick={() => queryClient.invalidateQueries({ queryKey: ["adminUsers"] })} className="p-2 border border-border rounded-lg hover:bg-muted">
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
      <div className="space-y-2">
        {users?.map((u) => (
          <div key={u.id} className="bg-card border border-border rounded-2xl p-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-sm flex items-center gap-1">
                  {u.username}
                  {u.is_admin && <AdminPanelSettingsIcon style={{ fontSize: 16, color: "#f9ab00" }} />}
                </h3>
                <p className="text-xs text-muted-foreground">{u.email || "No email"} - Created: {formatDate(u.created_at)}</p>
                <p className="text-xs text-muted-foreground mt-1">{u.project_count} projects, {u.file_count} files</p>
              </div>
              <div className="flex gap-1">
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
  const [patternEditorNatcoId, setPatternEditorNatcoId] = useState<number | null>(null);

  const { data: natcos, isLoading } = useQuery({
    queryKey: ["adminNatcos"],
    queryFn: async () => (await adminApi.listNatcos()).data,
  });

  const createMutation = useMutation({
    mutationFn: () => adminApi.createNatco(formCode, formName, formDesc),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adminNatcos"] });
      setShowCreate(false);
      setFormCode(""); setFormName(""); setFormDesc("");
    },
  });

  const updateMutation = useMutation({
    mutationFn: () => adminApi.updateNatco(editId!, { code: formCode, name: formName, description: formDesc }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adminNatcos"] });
      setEditId(null);
      setFormCode(""); setFormName(""); setFormDesc("");
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
  };

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <PublicIcon style={{ fontSize: 22 }} /> NATCO Management
        </h2>
        <div className="flex gap-2">
          <button onClick={() => queryClient.invalidateQueries({ queryKey: ["adminNatcos"] })} className="p-2 border border-border rounded-lg hover:bg-muted">
            <RefreshIcon style={{ fontSize: 18 }} />
          </button>
          <button onClick={() => { setShowCreate(true); setFormCode(""); setFormName(""); setFormDesc(""); }} className="flex items-center gap-1.5 px-3 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90">
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
                  {n.pattern_count} global patterns - Created: {formatDate(n.created_at)}
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

  const importMutation = useMutation({
    mutationFn: () => adminApi.importPresets(natcoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["adminNatcoPatterns", natcoId] });
      setLoaded(false); // reload
    },
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
            const result: Record<string, Array<{ name: string; regex: string; enabled: boolean }>> = {};
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
              }
            }

            // Filter out patterns with empty regex
            const cleaned: Record<string, Array<{ name: string; regex: string; enabled: boolean }>> = {};
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
                .map((p) => ({
                  name: String(p.name || "").slice(0, 200),
                  regex: String(p.regex || p.pattern || ""),
                  enabled: p.enabled !== false,
                }))
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
            .map((p) => ({
              name: String(p.name || p.template || p.regex || "").slice(0, 200),
              regex: String(p.regex || p.pattern || p.template || ""),
              enabled: p.enabled !== false,
            }))
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
                const regexEntries = cpeLog.Regex as Array<Record<string, string>> | undefined;
                if (!Array.isArray(regexEntries)) continue;
                for (const rx of regexEntries) {
                  if (rx.pattern) {
                    patterns.push({ name: rx.description || title || rx.pattern.slice(0, 60), regex: rx.pattern, enabled: true });
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
        <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
          <div>
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <PublicIcon style={{ fontSize: 20 }} />
              Global Patterns {data?.natco && <span className="text-sm font-normal text-muted-foreground">- {data.natco.code}: {data.natco.name}</span>}
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">{Object.keys(domains).length} domains, {totalPatterns} patterns</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => fileInputRef.current?.click()} className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-background hover:bg-muted">
              <UploadFileIcon style={{ fontSize: 14 }} />
              Import JSON/YAML
            </button>
            <input ref={fileInputRef} type="file" accept=".json,.yaml,.yml" onChange={handleFileImport} className="hidden" />
            <button onClick={() => importMutation.mutate()} disabled={importMutation.isPending} className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-background hover:bg-muted disabled:opacity-50">
              {importMutation.isPending ? <CircularProgress size={12} /> : <DownloadIcon style={{ fontSize: 14 }} />}
              Import Presets
            </button>
            <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">
              {saveMutation.isPending ? <CircularProgress size={12} sx={{ color: "white" }} /> : <SaveIcon style={{ fontSize: 14 }} />}
              Save All
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
                <button onClick={addDomain} disabled={!newDomainName.trim()} className="px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                  <AddIcon style={{ fontSize: 16 }} />
                </button>
              </div>

              {saveMutation.isSuccess && <div className="mb-3 px-3 py-2 bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400 text-xs rounded-lg">Patterns saved successfully.</div>}
              {importMutation.isSuccess && <div className="mb-3 px-3 py-2 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 text-xs rounded-lg">Presets imported. Click "Save All" to persist.</div>}
              {importMsg && <div className="mb-3 px-3 py-2 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 text-xs rounded-lg flex items-center gap-1.5"><UploadFileIcon style={{ fontSize: 14 }} />{importMsg}</div>}

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
                          <button onClick={() => addPattern(domain)} className="p-1 rounded hover:bg-blue-100 dark:hover:bg-blue-900/20"><AddIcon style={{ fontSize: 16 }} /></button>
                          <button onClick={() => { if (confirm(`Remove domain "${domain}"?`)) removeDomain(domain); }} className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/20"><DeleteIcon style={{ fontSize: 16 }} /></button>
                        </div>
                      </div>
                      {!collapsed && (
                        <div className="px-4 py-2 space-y-1">
                          {pats.length === 0 ? (
                            <p className="text-xs text-muted-foreground py-2 text-center">No patterns</p>
                          ) : (
                            <>
                              <div className="grid grid-cols-[32px_1fr_2fr_32px] gap-2 px-1">
                                <span className="text-[10px] text-muted-foreground font-semibold uppercase">On</span>
                                <span className="text-[10px] text-muted-foreground font-semibold uppercase">Name</span>
                                <span className="text-[10px] text-muted-foreground font-semibold uppercase">Regex</span>
                                <span />
                              </div>
                              {pats.map((p, idx) => (
                                <div key={idx} className="grid grid-cols-[32px_1fr_2fr_32px] gap-2 items-center px-1 py-0.5 rounded hover:bg-muted/30">
                                  <input type="checkbox" checked={p.enabled} onChange={(e) => updatePattern(domain, idx, "enabled", e.target.checked)} className="h-3.5 w-3.5 accent-blue-600" />
                                  <input type="text" value={p.name} onChange={(e) => updatePattern(domain, idx, "name", e.target.value)} placeholder="Name" className="text-xs px-2 py-1 rounded border border-border bg-background min-w-0" />
                                  <input type="text" value={p.regex} onChange={(e) => updatePattern(domain, idx, "regex", e.target.value)} placeholder="Regex" className="text-xs px-2 py-1 rounded border border-border bg-background font-mono min-w-0" />
                                  <button onClick={() => removePattern(domain, idx)} className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20"><DeleteIcon style={{ fontSize: 14 }} /></button>
                                </div>
                              ))}
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

        {/* Footer */}
        <div className="px-6 py-3 border-t border-border shrink-0">
          <button onClick={onClose} className="w-full py-2.5 border border-border rounded-lg hover:bg-muted text-sm font-medium">Close</button>
        </div>
      </div>
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
      pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400",
      approved: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
      rejected: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
    };
    return <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || ""}`}>{status}</span>;
  };

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <RateReviewIcon style={{ fontSize: 22 }} /> Pattern Submissions
        </h2>
        <div className="flex gap-2">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="text-sm px-3 py-1.5 border border-border rounded-lg bg-background">
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="">All</option>
          </select>
          <button onClick={() => queryClient.invalidateQueries({ queryKey: ["adminSubmissions"] })} className="p-2 border border-border rounded-lg hover:bg-muted">
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
                    <span className="px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded text-[10px] font-bold">{s.natco_code}</span>
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
                  {/* Pattern list */}
                  <div className="space-y-1">
                    <p className="text-xs font-semibold text-muted-foreground uppercase">Submitted Patterns</p>
                    {s.patterns.map((p: { name: string; regex: string; enabled: boolean; change_type?: string }, idx: number) => (
                      <div key={idx} className="flex items-center gap-3 px-3 py-1.5 bg-muted/30 rounded text-xs">
                        <span className={`w-4 h-4 rounded-full flex items-center justify-center ${p.enabled ? "bg-green-500" : "bg-gray-400"}`}>
                          {p.enabled ? <CheckCircleIcon style={{ fontSize: 12, color: "white" }} /> : null}
                        </span>
                        {p.change_type === "new" ? (
                          <span className="px-1.5 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded text-[10px] font-bold shrink-0">NEW</span>
                        ) : p.change_type === "modified" ? (
                          <span className="px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded text-[10px] font-bold shrink-0">MODIFIED</span>
                        ) : null}
                        <span className="font-medium min-w-[120px]">{p.name}</span>
                        <code className="font-mono text-[11px] text-muted-foreground flex-1 truncate">{p.regex}</code>
                      </div>
                    ))}
                  </div>

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
                        <button onClick={() => approveMutation.mutate(s.id)} disabled={approveMutation.isPending} className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50">
                          {approveMutation.isPending ? <CircularProgress size={14} sx={{ color: "white" }} /> : <CheckCircleIcon style={{ fontSize: 16 }} />}
                          Approve & Merge
                        </button>
                        <button onClick={() => rejectMutation.mutate(s.id)} disabled={rejectMutation.isPending} className="flex-1 flex items-center justify-center gap-1.5 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50">
                          {rejectMutation.isPending ? <CircularProgress size={14} sx={{ color: "white" }} /> : <CancelIcon style={{ fontSize: 16 }} />}
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

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <SettingsIcon style={{ fontSize: 22 }} /> System Settings
        </h2>
        <button onClick={() => queryClient.invalidateQueries({ queryKey: ["adminLlmSettings"] })} className="p-2 border border-border rounded-lg hover:bg-muted">
          <RefreshIcon style={{ fontSize: 18 }} />
        </button>
      </div>

      {/* LLM Settings Card */}
      <div className="bg-card border border-border rounded-2xl p-6 max-w-xl">
        <div className="flex items-start gap-4">
          <div className="shrink-0 h-12 w-12 rounded-xl bg-primary/10 flex items-center justify-center">
            <SmartToyIcon style={{ fontSize: 28 }} className="text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold">AI Chat (OpenRouter)</h3>
            <p className="text-sm text-muted-foreground mt-0.5">
              Enable or disable the AI-powered log analysis chat for all users.
            </p>

            {/* Toggle */}
            <div className="flex items-center gap-3 mt-4">
              <button
                onClick={() => toggleMutation.mutate(!llmSettings?.enabled)}
                disabled={isLoading || toggleMutation.isPending}
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

            {/* Server Health */}
            <div className="mt-4 flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">OpenRouter:</span>
              {isLoading ? (
                <CircularProgress size={12} />
              ) : llmSettings?.available ? (
                <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                  <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                  Configured
                </span>
              ) : (
                <span className="flex items-center gap-1 text-xs text-red-500">
                  <span className="h-2 w-2 rounded-full bg-red-500" />
                  {llmSettings?.enabled ? "Not configured — set OPENROUTER_API_KEY in .env" : "Not checked (disabled)"}
                </span>
              )}
            </div>

            {/* Model Info */}
            {llmSettings?.model_info && (
              <div className="mt-3 p-3 bg-muted/50 rounded-lg text-xs space-y-1">
                <p className="font-medium">Provider / model</p>
                <p className="text-muted-foreground">
                  {String((llmSettings.model_info as Record<string, unknown>).provider || "OpenRouter (free)")} — {String((llmSettings.model_info as Record<string, unknown>).id || "—")}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

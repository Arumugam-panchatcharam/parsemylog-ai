import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { projectsApi, natcoApi } from "@/api/endpoints";
import type { NatcoInfo } from "@/api/endpoints";
import { useAuth } from "@/hooks/useAuth";
import { useProject } from "@/hooks/useProject";
import { formatDate } from "@/lib/utils";
import AddIcon from "@mui/icons-material/Add";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import DeleteIcon from "@mui/icons-material/Delete";
import RefreshIcon from "@mui/icons-material/Refresh";
import CalendarTodayIcon from "@mui/icons-material/CalendarToday";
import PublicIcon from "@mui/icons-material/Public";
import WorkIcon from "@mui/icons-material/Work";

export default function DashboardPage() {
  const { user } = useAuth();
  const { setProject } = useProject();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newNatcoId, setNewNatcoId] = useState<number | null>(null);
  const [newProjectType, setNewProjectType] = useState<"normal" | "batch">("normal");
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const { data: projects, isLoading, refetch } = useQuery({
    queryKey: ["projects", user?.id],
    queryFn: async () => (await projectsApi.list()).data,
    enabled: !!user,
  });

  const { data: natcos } = useQuery({
    queryKey: ["natcosList"],
    queryFn: async () => (await natcoApi.list()).data,
  });

  // Auto-select first NATCO if only one exists
  useEffect(() => {
    if (natcos && natcos.length === 1 && newNatcoId === null) {
      setNewNatcoId(natcos[0].id);
    }
  }, [natcos, newNatcoId]);

  const createMutation = useMutation({
    mutationFn: () => {
      if (!newNatcoId) {
        throw new Error("NATCO selection is required");
      }
      return projectsApi.create(newName, newDesc, newNatcoId, newProjectType);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", user?.id] });
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
      setNewNatcoId(null);
      setNewProjectType("normal");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => projectsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", user?.id] });
      setDeleteId(null);
    },
  });

  const openProject = (id: string, name: string) => {
    setProject(id, name, user!.id);
    navigate("/workspace/viewer");
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FolderOpenIcon style={{ fontSize: 28 }} /> My Projects
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Welcome back, {user?.username}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => refetch()}
            className="p-2 border border-border rounded-lg hover:bg-muted transition-colors"
            title="Refresh"
          >
            <RefreshIcon style={{ fontSize: 18 }} />
          </button>
          <button
            onClick={() => setShowCreate(true)}
            title="Create a new project"
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 transition-opacity"
          >
            <AddIcon style={{ fontSize: 18 }} /> New Project
          </button>
        </div>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="text-center py-12 text-muted-foreground">Loading projects...</div>
      )}

      {/* Empty State */}
      {!isLoading && projects?.length === 0 && (
        <div className="text-center py-16 bg-card border border-border rounded-2xl">
          <FolderOpenIcon style={{ fontSize: 48, color: "#9aa0a6" }} className="mx-auto mb-3" />
          <h3 className="text-lg font-medium text-muted-foreground">No projects yet</h3>
          <p className="text-sm text-muted-foreground mt-1">Create your first project to get started</p>
        </div>
      )}

      {/* Project Grid */}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
        {projects?.map((p: { id: string; name: string; description: string; created_at: string; project_type?: string; natco?: { code: string; name: string } | null }) => (
          <div key={p.id} className="bg-card border border-border rounded-2xl mat-card">
            <div className="p-4">
              <div className="flex items-start justify-between mb-2">
                <h3 className="font-semibold text-sm flex items-center gap-1.5">
                  <FolderOpenIcon style={{ fontSize: 18, color: "#1a73e8" }} />
                  {p.name}
                </h3>
                <div className="flex items-center gap-1">
                  {p.project_type === "batch" && (
                    <span className="px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 rounded text-[10px] font-bold" title="Batch Processing Project">
                      BATCH
                    </span>
                  )}
                  {p.natco && (
                    <span className="px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded text-[10px] font-bold" title={p.natco.name}>
                      {p.natco.code}
                    </span>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); setDeleteId(p.id); }}
                    className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                    title="Delete"
                  >
                    <DeleteIcon style={{ fontSize: 16 }} />
                  </button>
                </div>
              </div>
              <p className="text-xs text-muted-foreground mb-3 line-clamp-2 min-h-[2rem]" title={p.description || "No description"}>
                {p.description || "No description"}
              </p>
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <CalendarTodayIcon style={{ fontSize: 13 }} />
                  {formatDate(p.created_at)}
                </span>
                <div className="flex gap-2">
                  {p.project_type === "batch" && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/projects/${p.id}/batch-jobs`);
                      }}
                      className="px-3 py-1.5 text-xs bg-muted text-foreground rounded-lg font-medium hover:bg-muted/80 transition-colors flex items-center gap-1"
                      title="Batch Jobs"
                    >
                      <WorkIcon style={{ fontSize: 14 }} />
                      Jobs
                    </button>
                  )}
                  <button
                    onClick={() => openProject(p.id, p.name)}
                    title="Open project in log viewer"
                    className="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 transition-opacity"
                  >
                    Open
                  </button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-2xl shadow-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">Create New Project</h3>
            <form onSubmit={(e) => { e.preventDefault(); createMutation.mutate(); }} className="space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">Project Name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Description (optional)</label>
                <textarea
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                  rows={3}
                />
              </div>
              {natcos && natcos.length > 0 && (
                <div>
                  <label className="block text-sm font-medium mb-1 flex items-center gap-1">
                    <PublicIcon style={{ fontSize: 16 }} /> NATCO <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={newNatcoId ?? ""}
                    onChange={(e) => setNewNatcoId(e.target.value ? Number(e.target.value) : null)}
                    title="Select a country/operator for pattern management"
                    className="w-full px-3 py-2.5 border border-input rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-ring text-sm"
                    required
                  >
                    <option value="">-- Select NATCO --</option>
                    {natcos.map((n: NatcoInfo) => (
                      <option key={n.id} value={n.id}>{n.code} - {n.name}</option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground mt-1">Required: Each project must have a NATCO for pattern management.</p>
                </div>
              )}
              {(!natcos || natcos.length === 0) && (
                <div className="px-3 py-2 bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 text-xs rounded">
                  No NATCOs available. Please contact admin to create NATCOs before creating projects.
                </div>
              )}
              <div>
                <label className="block text-sm font-medium mb-1">Project Type</label>
                <div className="space-y-2">
                  <label className="flex items-start gap-2 cursor-pointer p-2 border border-border rounded-lg hover:bg-muted/50 transition-colors" title="Standard project for log analysis">
                    <input
                      type="radio"
                      name="projectType"
                      value="normal"
                      checked={newProjectType === "normal"}
                      onChange={(e) => setNewProjectType(e.target.value as "normal" | "batch")}
                      className="mt-0.5"
                    />
                    <div className="flex-1">
                      <div className="font-medium text-sm">Normal Processing</div>
                      <div className="text-xs text-muted-foreground">Upload log files via UI for analysis</div>
                    </div>
                  </label>
                  <label className="flex items-start gap-2 cursor-pointer p-2 border border-border rounded-lg hover:bg-muted/50 transition-colors" title="Batch processing project for bulk CPE analysis">
                    <input
                      type="radio"
                      name="projectType"
                      value="batch"
                      checked={newProjectType === "batch"}
                      onChange={(e) => setNewProjectType(e.target.value as "normal" | "batch")}
                      className="mt-0.5"
                    />
                    <div className="flex-1">
                      <div className="font-medium text-sm">Batch Processing</div>
                      <div className="text-xs text-muted-foreground">Process large batches of CPE logs from server</div>
                    </div>
                  </label>
                </div>
              </div>
              <div className="flex gap-2 pt-2">
                <button type="submit" disabled={createMutation.isPending || !newName.trim() || !newNatcoId} className="flex-1 py-2.5 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-50">
                  {createMutation.isPending ? "Creating..." : "Create Project"}
                </button>
                <button type="button" onClick={() => setShowCreate(false)} className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted">
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirmation */}
      {deleteId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-card border border-border rounded-2xl shadow-lg p-6 w-full max-w-sm">
            <h3 className="text-lg font-semibold mb-2">Delete Project</h3>
            <p className="text-sm text-muted-foreground mb-1">Are you sure? This cannot be undone.</p>
            <p className="text-sm text-destructive font-medium mb-4">All files and data will be permanently lost.</p>
            <div className="flex gap-2">
              <button
                onClick={() => deleteMutation.mutate(deleteId)}
                disabled={deleteMutation.isPending}
                className="flex-1 py-2.5 bg-destructive text-destructive-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting..." : "Delete"}
              </button>
              <button onClick={() => setDeleteId(null)} className="flex-1 py-2.5 border border-border rounded-lg hover:bg-muted">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

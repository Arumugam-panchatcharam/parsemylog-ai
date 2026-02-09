import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { projectsApi } from "@/api/endpoints";
import { useAuth } from "@/hooks/useAuth";
import { useProject } from "@/hooks/useProject";
import { formatDate } from "@/lib/utils";
import AddIcon from "@mui/icons-material/Add";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import DeleteIcon from "@mui/icons-material/Delete";
import RefreshIcon from "@mui/icons-material/Refresh";
import CalendarTodayIcon from "@mui/icons-material/CalendarToday";

export default function DashboardPage() {
  const { user } = useAuth();
  const { setProject } = useProject();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [deleteId, setDeleteId] = useState<string | null>(null);

  const { data: projects, isLoading, refetch } = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await projectsApi.list()).data,
  });

  const createMutation = useMutation({
    mutationFn: () => projectsApi.create(newName, newDesc),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => projectsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
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
        {projects?.map((p: { id: string; name: string; description: string; created_at: string }) => (
          <div key={p.id} className="bg-card border border-border rounded-2xl mat-card">
            <div className="p-4">
              <div className="flex items-start justify-between mb-2">
                <h3 className="font-semibold text-sm flex items-center gap-1.5">
                  <FolderOpenIcon style={{ fontSize: 18, color: "#1a73e8" }} />
                  {p.name}
                </h3>
                <button
                  onClick={(e) => { e.stopPropagation(); setDeleteId(p.id); }}
                  className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                  title="Delete"
                >
                  <DeleteIcon style={{ fontSize: 16 }} />
                </button>
              </div>
              <p className="text-xs text-muted-foreground mb-3 line-clamp-2 min-h-[2rem]">
                {p.description || "No description"}
              </p>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <CalendarTodayIcon style={{ fontSize: 13 }} />
                  {formatDate(p.created_at)}
                </span>
                <button
                  onClick={() => openProject(p.id, p.name)}
                  className="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 transition-opacity"
                >
                  Open
                </button>
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
              <div className="flex gap-2 pt-2">
                <button type="submit" disabled={createMutation.isPending} className="flex-1 py-2.5 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-50">
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

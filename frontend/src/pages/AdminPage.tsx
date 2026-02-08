import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "@/api/endpoints";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import DeleteIcon from "@mui/icons-material/Delete";
import VpnKeyIcon from "@mui/icons-material/VpnKey";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import RefreshIcon from "@mui/icons-material/Refresh";
import PeopleIcon from "@mui/icons-material/People";
import FolderIcon from "@mui/icons-material/Folder";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import { formatDate } from "@/lib/utils";

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

export default function AdminPage() {
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
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <AdminPanelSettingsIcon style={{ fontSize: 28 }} /> Admin Panel
        </h1>
        <button
          onClick={() => queryClient.invalidateQueries({ queryKey: ["adminUsers"] })}
          className="p-2 border border-border rounded-lg hover:bg-muted"
        >
          <RefreshIcon style={{ fontSize: 18 }} />
        </button>
      </div>

      {/* Stats */}
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

      {/* Users */}
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
                <p className="text-xs text-muted-foreground mt-1">
                  {u.project_count} projects, {u.file_count} files
                </p>
              </div>
              <div className="flex gap-1">
                <button onClick={() => setViewProjectsUserId(u.id)} className="p-1.5 rounded hover:bg-accent" title="View Projects">
                  <FolderOpenIcon style={{ fontSize: 18, color: "#1a73e8" }} />
                </button>
                <button onClick={() => setResetUserId(u.id)} className="p-1.5 rounded hover:bg-yellow-100 dark:hover:bg-yellow-900/30" title="Reset Password">
                  <VpnKeyIcon style={{ fontSize: 18, color: "#f9ab00" }} />
                </button>
                <button
                  onClick={() => setDeleteUserId(u.id)}
                  disabled={u.is_admin}
                  className="p-1.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30 disabled:opacity-30"
                  title="Delete User"
                >
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
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password"
              className="w-full px-3 py-2.5 border border-input rounded-lg bg-background mb-3"
            />
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
    </div>
  );
}

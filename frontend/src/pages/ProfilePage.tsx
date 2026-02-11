import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { authApi } from "@/api/endpoints";
import PersonIcon from "@mui/icons-material/Person";
import LockIcon from "@mui/icons-material/Lock";
import EmailIcon from "@mui/icons-material/Email";
import BadgeIcon from "@mui/icons-material/Badge";
import CalendarTodayIcon from "@mui/icons-material/CalendarToday";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import LogoutIcon from "@mui/icons-material/Logout";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import VisibilityIcon from "@mui/icons-material/Visibility";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";

/* ------------------------------------------------------------------ */
/*  Profile Page                                                       */
/* ------------------------------------------------------------------ */
export default function ProfilePage() {
  const { user, refreshUser, logout } = useAuth();

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-6">
      <h1 className="text-2xl font-bold flex items-center gap-2">
        <PersonIcon /> My Profile
      </h1>

      {/* ---- Profile Info Card ---- */}
      <ProfileInfoCard />

      {/* ---- Edit Profile Card ---- */}
      <EditProfileCard onSaved={refreshUser} />

      {/* ---- Change Password Card ---- */}
      <ChangePasswordCard />

      {/* ---- Account Meta ---- */}
      {user && (
        <div className="rounded-xl border bg-card p-5 space-y-2">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <CalendarTodayIcon style={{ fontSize: 20 }} /> Account Details
          </h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">Role</span>
              <p className="font-medium flex items-center gap-1">
                {user.is_admin ? (
                  <>
                    <AdminPanelSettingsIcon style={{ fontSize: 16, color: "#f9ab00" }} />
                    Administrator
                  </>
                ) : (
                  "User"
                )}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">User ID</span>
              <p className="font-medium">{user.id}</p>
            </div>
          </div>
        </div>
      )}

      {/* ---- Sign Out ---- */}
      <div className="rounded-xl border border-red-200 bg-red-50/50 p-5 space-y-3">
        <h2 className="text-lg font-semibold flex items-center gap-2 text-red-700">
          <LogoutIcon style={{ fontSize: 20 }} /> Sign Out
        </h2>
        <p className="text-sm text-muted-foreground">
          End your current session. You will need to sign in again to access your projects.
        </p>
        <button
          onClick={logout}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
        >
          Sign Out
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Profile Info (read-only)                                           */
/* ------------------------------------------------------------------ */
function ProfileInfoCard() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <div className="rounded-xl border bg-card p-5">
      <div className="flex items-center gap-4">
        <div className="h-16 w-16 rounded-full bg-primary/10 flex items-center justify-center text-primary">
          <PersonIcon style={{ fontSize: 36 }} />
        </div>
        <div>
          <p className="text-xl font-semibold">{user.username}</p>
          <p className="text-sm text-muted-foreground">{user.email || "No email set"}</p>
          {user.is_admin && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-600 bg-amber-50 rounded px-2 py-0.5 mt-1">
              <AdminPanelSettingsIcon style={{ fontSize: 12 }} /> Admin
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Edit Profile (username + email)                                    */
/* ------------------------------------------------------------------ */
function EditProfileCard({ onSaved }: { onSaved: () => Promise<void> }) {
  const { user } = useAuth();

  const [username, setUsername] = useState(user?.username ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const handleSave = async () => {
    setMsg(null);
    setSaving(true);
    try {
      const payload: { username?: string; email?: string } = {};
      if (username !== user?.username) payload.username = username;
      if (email !== (user?.email ?? "")) payload.email = email;

      if (Object.keys(payload).length === 0) {
        setMsg({ type: "err", text: "No changes to save" });
        setSaving(false);
        return;
      }

      await authApi.updateProfile(payload);
      await onSaved();
      setMsg({ type: "ok", text: "Profile updated successfully" });
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ||
        "Failed to update profile";
      setMsg({ type: "err", text: msg });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border bg-card p-5 space-y-4">
      <h2 className="text-lg font-semibold flex items-center gap-2">
        <BadgeIcon style={{ fontSize: 20 }} /> Edit Profile
      </h2>

      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium mb-1">Username</label>
          <div className="relative">
            <PersonIcon
              style={{ fontSize: 18 }}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full pl-10 pr-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Email</label>
          <div className="relative">
            <EmailIcon
              style={{ fontSize: 18 }}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="email@example.com"
              className="w-full pl-10 pr-3 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
        </div>
      </div>

      {msg && (
        <StatusBanner type={msg.type} text={msg.text} />
      )}

      <button
        onClick={handleSave}
        disabled={saving}
        className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {saving ? "Saving..." : "Save Changes"}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Change Password                                                    */
/* ------------------------------------------------------------------ */
function ChangePasswordCard() {
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const handleChange = async () => {
    setMsg(null);

    if (!currentPw) {
      setMsg({ type: "err", text: "Current password is required" });
      return;
    }
    if (newPw.length < 4) {
      setMsg({ type: "err", text: "New password must be at least 4 characters" });
      return;
    }
    if (newPw !== confirmPw) {
      setMsg({ type: "err", text: "New passwords do not match" });
      return;
    }
    if (currentPw === newPw) {
      setMsg({ type: "err", text: "New password must be different from current password" });
      return;
    }

    setSaving(true);
    try {
      await authApi.changePassword(currentPw, newPw);
      setMsg({ type: "ok", text: "Password changed successfully" });
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ||
        "Failed to change password";
      setMsg({ type: "err", text: msg });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border bg-card p-5 space-y-4">
      <h2 className="text-lg font-semibold flex items-center gap-2">
        <LockIcon style={{ fontSize: 20 }} /> Change Password
      </h2>

      <div className="space-y-3">
        <PasswordField
          label="Current Password"
          value={currentPw}
          onChange={setCurrentPw}
          show={showCurrent}
          onToggle={() => setShowCurrent((v) => !v)}
        />
        <PasswordField
          label="New Password"
          value={newPw}
          onChange={setNewPw}
          show={showNew}
          onToggle={() => setShowNew((v) => !v)}
        />
        <PasswordField
          label="Confirm New Password"
          value={confirmPw}
          onChange={setConfirmPw}
          show={showConfirm}
          onToggle={() => setShowConfirm((v) => !v)}
        />
      </div>

      {msg && (
        <StatusBanner type={msg.type} text={msg.text} />
      )}

      <button
        onClick={handleChange}
        disabled={saving || !currentPw || !newPw || !confirmPw}
        className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
      >
        {saving ? "Changing..." : "Change Password"}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Shared Components                                                  */
/* ------------------------------------------------------------------ */
function PasswordField({
  label,
  value,
  onChange,
  show,
  onToggle,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  show: boolean;
  onToggle: () => void;
}) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      <div className="relative">
        <LockIcon
          style={{ fontSize: 18 }}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
        />
        <input
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full pl-10 pr-10 py-2 rounded-lg border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
        <button
          type="button"
          onClick={onToggle}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        >
          {show ? (
            <VisibilityOffIcon style={{ fontSize: 18 }} />
          ) : (
            <VisibilityIcon style={{ fontSize: 18 }} />
          )}
        </button>
      </div>
    </div>
  );
}

function StatusBanner({ type, text }: { type: "ok" | "err"; text: string }) {
  return (
    <div
      className={`flex items-center gap-2 text-sm rounded-lg px-3 py-2 ${
        type === "ok"
          ? "bg-green-50 text-green-700 border border-green-200"
          : "bg-red-50 text-red-700 border border-red-200"
      }`}
    >
      {type === "ok" ? (
        <CheckCircleIcon style={{ fontSize: 16 }} />
      ) : (
        <ErrorIcon style={{ fontSize: 16 }} />
      )}
      {text}
    </div>
  );
}

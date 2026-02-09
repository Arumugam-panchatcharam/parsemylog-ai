import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import AnalyticsIcon from "@mui/icons-material/Analytics";
import SearchIcon from "@mui/icons-material/Search";
import DescriptionIcon from "@mui/icons-material/Description";
import TimelineIcon from "@mui/icons-material/Timeline";
import PsychologyIcon from "@mui/icons-material/Psychology";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import LogoutIcon from "@mui/icons-material/Logout";
import PersonIcon from "@mui/icons-material/Person";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { cn } from "@/lib/utils";
import { useState } from "react";
import CPESelector from "@/components/CPESelector";

const workspaceNav = [
  { to: "/workspace/viewer", icon: SearchIcon, label: "Log Viewer" },
  { to: "/workspace/pattern", icon: AnalyticsIcon, label: "Pattern" },
  { to: "/workspace/pattern-analyzer", icon: ManageSearchIcon, label: "Pattern Analyzer" },
  { to: "/workspace/telemetry", icon: TimelineIcon, label: "Telemetry" },
  { to: "/workspace/ai", icon: PsychologyIcon, label: "AI Analysis" },
  { to: "/workspace/cpe-overview", icon: CompareArrowsIcon, label: "CPE Overview" },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const { projectName, clearProject } = useProject();
  const { clearCPE } = useCPE();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const isWorkspace = location.pathname.startsWith("/workspace");

  return (
    <aside
      className={cn(
        "flex flex-col h-screen bg-sidebar border-r border-sidebar-border transition-all duration-200",
        collapsed ? "w-16" : "w-56"
      )}
    >
      {/* Header */}
      <div className="p-3 border-b border-sidebar-border">
        <div className="flex items-center justify-between">
          {!collapsed && (
            <h1 className="text-lg font-bold text-sidebar-foreground flex items-center gap-2">
              <AnalyticsIcon style={{ fontSize: 22, color: "#1a73e8" }} />
              LogAI
            </h1>
          )}
          {collapsed && <AnalyticsIcon style={{ fontSize: 22, color: "#1a73e8" }} className="mx-auto" />}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1 rounded hover:bg-sidebar-accent text-sidebar-foreground hidden md:block"
          >
            {collapsed ? <ChevronRightIcon style={{ fontSize: 18 }} /> : <ChevronLeftIcon style={{ fontSize: 18 }} />}
          </button>
        </div>
      </div>

      {/* User info */}
      {!collapsed && user && (
        <div className="px-3 py-2 border-b border-sidebar-border">
          <p className="text-sm font-medium text-sidebar-foreground flex items-center gap-1">
            <PersonIcon style={{ fontSize: 16 }} />
            {user.username}
            {user.is_admin && <AdminPanelSettingsIcon style={{ fontSize: 14, color: "#f9ab00" }} />}
          </p>
        </div>
      )}

      {/* Project info */}
      {isWorkspace && !collapsed && projectName && (
        <div className="px-3 py-2 border-b border-sidebar-border bg-sidebar-accent">
          <p className="text-xs text-muted-foreground">Project</p>
          <p className="text-sm font-medium truncate">{projectName}</p>
        </div>
      )}

      {/* CPE Selector (multi-CPE projects) */}
      {isWorkspace && !collapsed && <CPESelector />}

      {/* Navigation */}
      <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
        {isWorkspace ? (
          <>
            <NavLink
              to="/dashboard"
              onClick={() => { clearProject(); clearCPE(); }}
              className={cn(
                "flex items-center gap-2 px-3 py-2 text-sm rounded-lg hover:bg-sidebar-accent text-muted-foreground",
                collapsed && "justify-center px-2"
              )}
            >
              <ArrowBackIcon style={{ fontSize: 18 }} />
              {!collapsed && "Dashboard"}
            </NavLink>
            <div className="my-2 border-t border-sidebar-border" />
            {workspaceNav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors",
                    isActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                      : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                    collapsed && "justify-center px-2"
                  )
                }
              >
                <item.icon style={{ fontSize: 18 }} className="shrink-0" />
                {!collapsed && item.label}
              </NavLink>
            ))}
          </>
        ) : (
          <>
            <NavLink
              to="/dashboard"
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                    : "text-muted-foreground hover:bg-sidebar-accent",
                  collapsed && "justify-center px-2"
                )
              }
            >
              <DescriptionIcon style={{ fontSize: 18 }} />
              {!collapsed && "Dashboard"}
            </NavLink>
            {user?.is_admin && (
              <NavLink
                to="/admin"
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 px-3 py-2 text-sm rounded-lg transition-colors",
                    isActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                      : "text-muted-foreground hover:bg-sidebar-accent",
                    collapsed && "justify-center px-2"
                  )
                }
              >
                <AdminPanelSettingsIcon style={{ fontSize: 18 }} />
                {!collapsed && "Admin"}
              </NavLink>
            )}
          </>
        )}
      </nav>

      {/* Logout */}
      <div className="p-2 border-t border-sidebar-border">
        <button
          onClick={logout}
          className={cn(
            "flex items-center gap-2 px-3 py-2 text-sm rounded-lg w-full text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors",
            collapsed && "justify-center px-2"
          )}
        >
          <LogoutIcon style={{ fontSize: 18 }} />
          {!collapsed && "Logout"}
        </button>
      </div>
    </aside>
  );
}

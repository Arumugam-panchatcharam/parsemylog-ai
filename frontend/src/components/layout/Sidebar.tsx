import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import AnalyticsIcon from "@mui/icons-material/Analytics";
import logoImg from "@/assets/logo.png";
import SearchIcon from "@mui/icons-material/Search";
import DescriptionIcon from "@mui/icons-material/Description";
import TimelineIcon from "@mui/icons-material/Timeline";
import PsychologyIcon from "@mui/icons-material/Psychology";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import HubIcon from "@mui/icons-material/Hub";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import ModelTrainingIcon from "@mui/icons-material/ModelTraining";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import WifiIcon from "@mui/icons-material/Wifi";
import TableChartIcon from "@mui/icons-material/TableChart";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { cn } from "@/lib/utils";
import { useState, useEffect } from "react";
import CPESelector from "@/components/CPESelector";
import { chatApi, patternsApi } from "@/api/endpoints";

const workspaceNav = [
  { to: "/workspace/viewer", icon: SearchIcon, label: "Log Viewer" },
  { to: "/workspace/pattern", icon: AnalyticsIcon, label: "Pattern" },
  { to: "/workspace/pattern-analyzer", icon: ManageSearchIcon, label: "Pattern Analyzer" },
  { to: "/workspace/telemetry", icon: TimelineIcon, label: "Telemetry" },
  { to: "/workspace/ai", icon: PsychologyIcon, label: "Semantic Search" },
  { to: "/workspace/cpe-overview", icon: CompareArrowsIcon, label: "CPE Overview" },
  { to: "/workspace/issue-analysis", icon: AccountTreeIcon, label: "Issue Analysis" },
  { to: "/workspace/ml-pipeline", icon: ModelTrainingIcon, label: "ML Pipeline" },
];

export default function Sidebar() {
  const { user } = useAuth();
  const { projectId, projectName, clearProject } = useProject();
  const { cpeId, clearCPE } = useCPE();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const isWorkspace = location.pathname.startsWith("/workspace");
  const isProfile = location.pathname === "/profile";

  // AI Chat visibility:
  // Admin: always visible when LLM server is available (ignores enabled toggle + indexing)
  // Regular users: visible when LLM is enabled + available + indexing done
  const [showAiChat, setShowAiChat] = useState(false);
  useEffect(() => {
    if (!isWorkspace || !projectId) {
      setShowAiChat(false);
      return;
    }
    let cancelled = false;
    Promise.all([
      chatApi.llmStatus(projectId).catch(() => ({ data: { enabled: false, available: false } })),
      patternsApi.indexingStatus(projectId, cpeId).catch(() => ({ data: { all_done: false } })),
    ]).then(([llmRes, idxRes]) => {
      if (cancelled) return;
      const { enabled, available } = llmRes.data;
      const indexingOk = idxRes.data.all_done ?? false;
      if (user?.is_admin) {
        setShowAiChat(available);
      } else {
        setShowAiChat(enabled && available && indexingOk);
      }
    });
    return () => { cancelled = true; };
  }, [isWorkspace, projectId, cpeId, user?.is_admin]);

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
              <img src={logoImg} alt="ParseMyLog AI" className="h-6 w-6" />
              ParseMyLog AI
            </h1>
          )}
          {collapsed && <img src={logoImg} alt="ParseMyLog AI" className="h-6 w-6 mx-auto" />}
          <button
            onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="p-1 rounded hover:bg-sidebar-accent text-sidebar-foreground hidden md:block"
          >
            {collapsed ? <ChevronRightIcon style={{ fontSize: 18 }} /> : <ChevronLeftIcon style={{ fontSize: 18 }} />}
          </button>
        </div>
      </div>

      {/* (user info moved to bottom avatar) */}

      {/* Project info */}
      {isWorkspace && !collapsed && projectName && (
        <div className="px-3 py-2 border-b border-sidebar-border bg-sidebar-accent">
          <p className="text-xs text-muted-foreground">Project</p>
          <p className="text-sm font-medium truncate" title={projectName}>{projectName}</p>
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
              title={collapsed ? "Back to Dashboard" : undefined}
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
                title={collapsed ? item.label : undefined}
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
            {/* AI Chat — only visible when LLM is enabled and indexing is complete */}
            {showAiChat && (
              <>
                <div className="my-2 border-t border-sidebar-border" />
                <NavLink
                  to="/workspace/chat"
                  title={collapsed ? "AI Chat" : undefined}
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
                  <SmartToyIcon style={{ fontSize: 18 }} className="shrink-0" />
                  {!collapsed && "AI Chat"}
                </NavLink>
              </>
            )}
          </>
        ) : (
          <>
            <NavLink
              to="/dashboard"
              title={collapsed ? "Dashboard" : undefined}
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
            <NavLink
              to="/knowledge-graph"
              title={collapsed ? "Knowledge Graph" : undefined}
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
              <HubIcon style={{ fontSize: 18 }} />
              {!collapsed && "Knowledge Graph"}
            </NavLink>
            <NavLink
              to="/pcap"
              title={collapsed ? "PCAP Analyzer" : undefined}
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
              <WifiIcon style={{ fontSize: 18 }} />
              {!collapsed && "PCAP Analyzer"}
            </NavLink>
            <NavLink
              to="/telemetry-csv"
              title={collapsed ? "Telemetry CSV" : undefined}
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
              <TableChartIcon style={{ fontSize: 18 }} />
              {!collapsed && "Telemetry CSV"}
            </NavLink>
            {user?.is_admin && (
              <NavLink
                to="/admin"
                title={collapsed ? "Admin Panel" : undefined}
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

      {/* Profile avatar */}
      {user && (
        <div className="p-3 border-t border-sidebar-border">
          <button
            onClick={() => navigate("/profile")}
            title="Profile & Settings"
            className={cn(
              "flex items-center gap-3 w-full rounded-lg transition-colors",
              collapsed ? "justify-center" : "px-2 py-1.5 hover:bg-sidebar-accent",
              isProfile && "bg-sidebar-accent"
            )}
          >
            <div
              className={cn(
                "shrink-0 rounded-full bg-primary/15 text-primary flex items-center justify-center font-semibold uppercase select-none",
                "h-8 w-8 text-sm",
                isProfile && "ring-2 ring-primary"
              )}
            >
              {user.username.charAt(0)}
            </div>
            {!collapsed && (
              <div className="text-left min-w-0">
                <p className="text-sm font-medium text-sidebar-foreground truncate flex items-center gap-1">
                  {user.username}
                  {user.is_admin && (
                    <span title="Administrator">
                      <AdminPanelSettingsIcon style={{ fontSize: 13, color: "#f9ab00" }} />
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground truncate">
                  {user.email || "Manage account"}
                </p>
              </div>
            )}
          </button>
        </div>
      )}
    </aside>
  );
}

import { memo, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import logoImg from "@/assets/logo.png";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import { cn } from "@/lib/utils";
import CPESelector from "@/components/CPESelector";
import { chatApi, patternsApi } from "@/api/endpoints";
import { AppNavLink } from "./AppNavLink";
import { mainNav, workspaceNav } from "./navConfig";
import { useSidebar } from "@/hooks/useSidebar";

function SidebarInner() {
  const { user } = useAuth();
  const { projectId, projectName, clearProject } = useProject();
  const { cpeId, clearCPE } = useCPE();
  const location = useLocation();
  const { collapsed, toggleCollapsed } = useSidebar();
  const isWorkspace = location.pathname.startsWith("/workspace");

  const [llmGate, setLlmGate] = useState({
    enabled: false,
    available: false,
    indexingOk: false,
  });

  useEffect(() => {
    if (!isWorkspace || !projectId) return;
    let cancelled = false;
    Promise.all([
      chatApi.llmStatus(projectId).catch(() => ({ data: { enabled: false, available: false } })),
      patternsApi.indexingStatus(projectId, cpeId).catch(() => ({ data: { all_done: false } })),
    ]).then(([llmRes, idxRes]) => {
      if (cancelled) return;
      const { enabled, available } = llmRes.data;
      const indexingOk = idxRes.data.all_done ?? false;
      setLlmGate({ enabled, available, indexingOk });
    });
    return () => {
      cancelled = true;
    };
  }, [isWorkspace, projectId, cpeId]);

  const showAiChat = useMemo(() => {
    if (!isWorkspace || !projectId) return false;
    const { enabled, available, indexingOk } = llmGate;
    if (user?.is_admin) return available;
    return enabled && available && indexingOk;
  }, [isWorkspace, projectId, user?.is_admin, llmGate]);

  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r border-sidebar-border bg-sidebar transition-all duration-200",
        collapsed ? "w-16" : "w-56"
      )}
    >
      <div className="border-b border-sidebar-border p-3">
        <div className="flex items-center justify-between">
          {!collapsed && (
            <h1 className="flex items-center gap-2 text-lg font-bold text-sidebar-foreground">
              <img src={logoImg} alt="ParseMyLog AI" className="h-6 w-6" />
              ParseMyLog AI
            </h1>
          )}
          {collapsed ? <img src={logoImg} alt="ParseMyLog AI" className="mx-auto h-6 w-6" /> : null}
          <button
            type="button"
            onClick={toggleCollapsed}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="hidden rounded p-1 text-sidebar-foreground hover:bg-sidebar-accent md:block"
          >
            {collapsed ? (
              <ChevronRightIcon style={{ fontSize: 18 }} />
            ) : (
              <ChevronLeftIcon style={{ fontSize: 18 }} />
            )}
          </button>
        </div>
      </div>

      {isWorkspace && !collapsed && projectName ? (
        <div className="border-b border-sidebar-border bg-sidebar-accent px-3 py-2">
          <p className="text-xs text-muted-foreground">Project</p>
          <p className="truncate text-sm font-medium" title={projectName}>
            {projectName}
          </p>
        </div>
      ) : null}

      {isWorkspace && !collapsed ? <CPESelector /> : null}

      <nav className="custom-scrollbar flex-1 space-y-1 overflow-y-auto p-2" aria-label="Primary">
        {isWorkspace ? (
          <>
            <AppNavLink
              to="/dashboard"
              collapsed={collapsed}
              subtleInactive
              onClick={() => {
                clearProject();
                clearCPE();
              }}
              title={collapsed ? "Back to Dashboard" : undefined}
            >
              <ArrowBackIcon style={{ fontSize: 18 }} />
              {!collapsed ? "Dashboard" : null}
            </AppNavLink>
            <div className="my-2 border-t border-sidebar-border" />
            {workspaceNav.map((item) => {
              const Icon = item.icon;
              return (
                <AppNavLink
                  key={item.to}
                  to={item.to}
                  collapsed={collapsed}
                  title={collapsed ? item.label : undefined}
                >
                  <Icon style={{ fontSize: 18 }} className="shrink-0" />
                  {!collapsed ? item.label : null}
                </AppNavLink>
              );
            })}
            {showAiChat ? (
              <>
                <div className="my-2 border-t border-sidebar-border" />
                <AppNavLink
                  to="/workspace/chat"
                  collapsed={collapsed}
                  title={collapsed ? "AI Chat" : undefined}
                >
                  <SmartToyIcon style={{ fontSize: 18 }} className="shrink-0" />
                  {!collapsed ? "AI Chat" : null}
                </AppNavLink>
              </>
            ) : null}
          </>
        ) : (
          <>
            {mainNav.map((item) => {
              if (item.adminOnly && !user?.is_admin) return null;
              const Icon = item.icon;
              return (
                <AppNavLink
                  key={item.to}
                  to={item.to}
                  collapsed={collapsed}
                  title={collapsed ? item.label : undefined}
                >
                  <Icon style={{ fontSize: 18 }} />
                  {!collapsed ? item.label : null}
                </AppNavLink>
              );
            })}
          </>
        )}
      </nav>
    </aside>
  );
}

export default memo(SidebarInner);

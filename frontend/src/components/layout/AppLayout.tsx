import { Outlet } from "react-router-dom";
import { memo } from "react";
import Sidebar from "./Sidebar";
import ToolsBar from "./ToolsBar";
import { SidebarProvider } from "./sidebarContext";
import { useGlobalAppShortcuts } from "@/hooks/useGlobalAppShortcuts";
import { ErrorBoundary } from "@/components/ui";
import { cn } from "@/lib/utils";

function AppLayoutInner() {
  useGlobalAppShortcuts();

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className={cn(
          "sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100]",
          "focus:rounded-lg focus:bg-card focus:px-4 focus:py-2 focus:text-sm focus:font-medium",
          "focus:shadow-lg focus:ring-2 focus:ring-ring"
        )}
      >
        Skip to main content
      </a>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
          <ToolsBar />
          <main
            id="main-content"
            tabIndex={-1}
            className="min-h-0 flex-1 overflow-y-auto outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
          >
            <ErrorBoundary fallbackTitle="This page failed to render">
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}

export default memo(AppLayoutInner);

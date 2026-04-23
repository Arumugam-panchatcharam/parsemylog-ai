import { Outlet } from "react-router-dom";
import { memo, useCallback, useEffect, useState } from "react";
import Sidebar from "./Sidebar";
import ToolsBar from "./ToolsBar";
import { SidebarProvider } from "./sidebarContext";
import { useGlobalAppShortcuts, OPEN_ABOUT_EVENT } from "@/hooks/useGlobalAppShortcuts";
import AboutDialog from "@/components/AboutDialog";
import { ErrorBoundary } from "@/components/ui";
import { cn } from "@/lib/utils";

function AppLayoutInner() {
  useGlobalAppShortcuts();
  const [aboutOpen, setAboutOpen] = useState(false);

  useEffect(() => {
    const onOpenAbout = () => setAboutOpen(true);
    window.addEventListener(OPEN_ABOUT_EVENT, onOpenAbout);
    return () => window.removeEventListener(OPEN_ABOUT_EVENT, onOpenAbout);
  }, []);

  const handleAboutClose = useCallback(() => setAboutOpen(false), []);

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
          <ToolsBar onOpenAbout={() => setAboutOpen(true)} />
          <main
            id="main-content"
            tabIndex={-1}
            className="flex min-h-0 flex-1 flex-col overflow-y-auto outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
          >
            <ErrorBoundary fallbackTitle="This page failed to render">
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </div>
      <AboutDialog open={aboutOpen} onClose={handleAboutClose} />
    </SidebarProvider>
  );
}

export default memo(AppLayoutInner);

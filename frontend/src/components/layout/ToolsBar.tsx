import { memo, useCallback, useState } from "react";
import Popover from "@mui/material/Popover";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import RouterIcon from "@mui/icons-material/Router";
import { cn } from "@/lib/utils";
import TimeZoneBar from "./TimeZoneBar";
import MacLookupBar from "./MacLookupBar";
import ThemeToggle from "./ThemeToggle";
import UserMenu from "./UserMenu";

export interface ToolsBarProps {
  onOpenAbout: () => void;
}

function ToolsBarInner({ onOpenAbout }: ToolsBarProps) {
  const [tzAnchor, setTzAnchor] = useState<HTMLElement | null>(null);
  const [macAnchor, setMacAnchor] = useState<HTMLElement | null>(null);

  const closeTz = useCallback(() => setTzAnchor(null), []);
  const closeMac = useCallback(() => setMacAnchor(null), []);

  return (
    <section
      className="shrink-0 border-b border-border bg-card"
      aria-label="Utilities: time zone, MAC lookup, appearance, account"
    >
      <div className="flex w-full items-center gap-1 px-3 py-1.5">
        <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={(e) => setTzAnchor(e.currentTarget)}
          aria-label="Open time zone converter"
          title="Time zone converter"
          className={cn(
            "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border",
            "bg-background text-foreground transition-colors",
            "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          )}
        >
          <AccessTimeIcon sx={{ fontSize: 18 }} aria-hidden />
        </button>
        <Popover
          open={Boolean(tzAnchor)}
          anchorEl={tzAnchor}
          onClose={closeTz}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          transformOrigin={{ vertical: "top", horizontal: "right" }}
          slotProps={{
            paper: {
              className: "border border-border bg-card shadow-lg",
              sx: { mt: 0.5, maxWidth: "min(560px, calc(100vw - 24px))" },
            },
          }}
        >
          <div className="p-3 max-h-[min(80vh,640px)] overflow-auto">
            <TimeZoneBar />
          </div>
        </Popover>

        <button
          type="button"
          onClick={(e) => setMacAnchor(e.currentTarget)}
          aria-label="Open MAC OUI lookup"
          title="MAC OUI lookup"
          className={cn(
            "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border",
            "bg-background text-foreground transition-colors",
            "hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          )}
        >
          <RouterIcon sx={{ fontSize: 18 }} aria-hidden />
        </button>
        <Popover
          open={Boolean(macAnchor)}
          anchorEl={macAnchor}
          onClose={closeMac}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          transformOrigin={{ vertical: "top", horizontal: "right" }}
          slotProps={{
            paper: {
              className: "border border-border bg-card shadow-lg",
              sx: { mt: 0.5, width: "min(720px, calc(100vw - 24px))" },
            },
          }}
        >
          <div className="p-3 max-h-[min(85vh,720px)] overflow-auto">
            <MacLookupBar />
          </div>
        </Popover>
        </div>

        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <UserMenu onOpenAbout={onOpenAbout} />
        </div>
      </div>
    </section>
  );
}

export const ToolsBar = memo(ToolsBarInner);
ToolsBar.displayName = "ToolsBar";

export default ToolsBar;

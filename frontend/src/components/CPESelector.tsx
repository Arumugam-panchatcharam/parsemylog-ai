import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useProject } from "@/hooks/useProject";
import { useCPE, type CPEInfo } from "@/hooks/useCPE";
import { cpesApi } from "@/api/endpoints";
import DevicesOtherIcon from "@mui/icons-material/DevicesOther";
import SearchIcon from "@mui/icons-material/Search";

/**
 * CPE Selector — shown in the sidebar when a project has multiple CPE devices.
 *
 * Auto-selects the first CPE if none is selected.
 * Hidden when there are zero or one CPEs (legacy single-device project).
 */
export default function CPESelector() {
  const { projectId } = useProject();
  const { cpeId, setCPE, clearCPE } = useCPE();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  const { data: cpes = [], isFetching: cpesFetching } = useQuery<CPEInfo[]>({
    queryKey: ["cpes", projectId],
    queryFn: async () => {
      if (!projectId) return [];
      const res = await cpesApi.list(projectId);
      const data = res.data;
      return Array.isArray(data) ? data : [];
    },
    enabled: !!projectId,
  });

  // Auto-select first CPE if not already selected
  useEffect(() => {
    if (cpes.length > 0 && !cpeId) {
      setCPE(cpes[0]);
    }
    // Clear CPE only when we're sure the project has no CPEs (don't clear during refetch after upload)
    if (cpes.length === 0 && cpeId && !cpesFetching) {
      clearCPE();
    }
  }, [cpes, cpeId, cpesFetching, setCPE, clearCPE]);

  // Click-outside to close dropdown — must run unconditionally (before any return) to satisfy Rules of Hooks
  useEffect(() => {
    if (!dropdownOpen) return;
    const onOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, [dropdownOpen]);

  // Don't render if no CPEs (legacy project)
  if (cpes.length === 0) return null;

  // Single CPE — show as a label (no dropdown)
  if (cpes.length === 1) {
    const c = cpes[0];
    return (
      <div className="px-3 py-2 border-b border-sidebar-border">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5 flex items-center gap-1">
          <DevicesOtherIcon style={{ fontSize: 12 }} />
          CPE Device
        </p>
        <p className="text-xs font-medium truncate text-sidebar-foreground" title={c.serial}>
          {c.serial}
          {c.mac ? ` (${c.mac})` : ""}
        </p>
      </div>
    );
  }

  // Multiple CPEs — searchable dropdown
  const q = searchQuery.trim().toLowerCase();
  const filteredCpes = q
    ? cpes.filter(
        (c) =>
          c.serial?.toLowerCase().includes(q) ||
          c.mac?.toLowerCase().replace(/:/g, "").includes(q.replace(/:/g, "")) ||
          c.date_from?.toLowerCase().includes(q)
      )
    : cpes;

  const selectedCpe = cpes.find((c) => c.serial === cpeId);

  return (
    <div className="px-3 py-2 border-b border-sidebar-border" ref={containerRef}>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 flex items-center gap-1">
        <DevicesOtherIcon style={{ fontSize: 12 }} />
        CPE Device ({cpes.length})
      </p>
      <div className="relative">
        <button
          type="button"
          onClick={() => setDropdownOpen((o) => !o)}
          title="Select a CPE device to view"
          className="w-full text-left text-xs bg-sidebar border border-sidebar-border rounded px-2 py-1.5 text-sidebar-foreground focus:outline-none focus:ring-1 focus:ring-primary flex items-center justify-between gap-1"
        >
          <span className="truncate" title={selectedCpe ? `${selectedCpe.serial}${selectedCpe.mac ? ` (${selectedCpe.mac})` : ""}` : "Select CPE..."}>
            {selectedCpe
              ? `${selectedCpe.serial}${selectedCpe.mac ? ` (${selectedCpe.mac})` : ""}`
              : "Select CPE..."}
          </span>
          <span className="shrink-0 text-muted-foreground">{dropdownOpen ? "▲" : "▼"}</span>
        </button>
        {dropdownOpen && (
          <div className="absolute top-full left-0 right-0 mt-0.5 bg-card border border-border rounded-lg shadow-lg z-50 overflow-hidden">
            <div className="p-1.5 border-b border-border">
              <div className="flex items-center gap-1 bg-muted/50 rounded px-2 py-1">
                <SearchIcon style={{ fontSize: 14 }} className="text-muted-foreground" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search by serial or MAC..."
                  title="Search CPEs by serial number or MAC address"
                  className="flex-1 min-w-0 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                  autoFocus
                />
              </div>
            </div>
            <div className="max-h-48 overflow-y-auto custom-scrollbar">
              {filteredCpes.length === 0 ? (
                <p className="text-[11px] text-muted-foreground px-3 py-2">No match</p>
              ) : (
                filteredCpes.map((c) => (
                  <button
                    key={c.serial}
                    type="button"
                    onClick={() => {
                      setCPE(c);
                      setDropdownOpen(false);
                      setSearchQuery("");
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-muted transition-colors ${
                      cpeId === c.serial ? "bg-primary/15 text-primary font-medium" : "text-foreground"
                    }`}
                    title={`${c.serial}${c.mac ? ` (${c.mac})` : ""}${c.date_from ? ` — ${c.date_from}` : ""}`}
                  >
                    <span className="block truncate">
                      {c.serial}
                      {c.mac ? ` (${c.mac})` : ""}
                      {c.date_from ? ` — ${c.date_from}` : ""}
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

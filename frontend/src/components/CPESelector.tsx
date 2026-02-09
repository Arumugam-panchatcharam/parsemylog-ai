import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useProject } from "@/hooks/useProject";
import { useCPE, type CPEInfo } from "@/hooks/useCPE";
import { cpesApi } from "@/api/endpoints";
import DevicesOtherIcon from "@mui/icons-material/DevicesOther";

/**
 * CPE Selector — shown in the sidebar when a project has multiple CPE devices.
 *
 * Auto-selects the first CPE if none is selected.
 * Hidden when there are zero or one CPEs (legacy single-device project).
 */
export default function CPESelector() {
  const { projectId } = useProject();
  const { cpeId, setCPE, clearCPE } = useCPE();

  const { data: cpes = [] } = useQuery<CPEInfo[]>({
    queryKey: ["cpes", projectId],
    queryFn: async () => {
      if (!projectId) return [];
      const res = await cpesApi.list(projectId);
      return res.data;
    },
    enabled: !!projectId,
  });

  // Auto-select first CPE if not already selected
  useEffect(() => {
    if (cpes.length > 0 && !cpeId) {
      setCPE(cpes[0]);
    }
    // Clear CPE if project has no CPEs (legacy project)
    if (cpes.length === 0 && cpeId) {
      clearCPE();
    }
  }, [cpes, cpeId, setCPE, clearCPE]);

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

  // Multiple CPEs — show dropdown
  return (
    <div className="px-3 py-2 border-b border-sidebar-border">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 flex items-center gap-1">
        <DevicesOtherIcon style={{ fontSize: 12 }} />
        CPE Device ({cpes.length})
      </p>
      <select
        value={cpeId || ""}
        onChange={(e) => {
          const selected = cpes.find((c) => c.serial === e.target.value);
          if (selected) setCPE(selected);
        }}
        className="w-full text-xs bg-sidebar border border-sidebar-border rounded px-2 py-1.5 text-sidebar-foreground focus:outline-none focus:ring-1 focus:ring-primary"
      >
        {cpes.map((c) => (
          <option key={c.serial} value={c.serial}>
            {c.serial}
            {c.mac ? ` (${c.mac})` : ""}
            {c.date_from ? ` — ${c.date_from}` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}

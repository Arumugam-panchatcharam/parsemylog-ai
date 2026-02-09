import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { patternAnalyzerApi } from "@/api/endpoints";
import type { UserPattern, DomainPatterns } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import Plot from "react-plotly.js";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import SaveIcon from "@mui/icons-material/Save";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import DownloadIcon from "@mui/icons-material/Download";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import ErrorIcon from "@mui/icons-material/Error";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import CreateNewFolderIcon from "@mui/icons-material/CreateNewFolder";
import CircularProgress from "@mui/material/CircularProgress";

/* ================================================================ Types */
interface ScanResult {
  traces: Array<{ name: string; times: string[]; texts: string[]; total: number }>;
  reboots: Array<{ timestamp: string; reason: string }>;
  total_matches: number;
}
interface RebootEntry {
  timestamp: string;
  reason: string;
}

/* ================================================================ Constants */
const BUCKET_OPTIONS = [
  { value: 1, label: "1 min" },
  { value: 5, label: "5 min" },
  { value: 15, label: "15 min" },
  { value: 60, label: "1 hour" },
  { value: 1440, label: "1 day" },
];

const TRACE_COLORS = [
  "#1a73e8", "#d93025", "#188038", "#e8710a", "#9334e6",
  "#00acc1", "#c2185b", "#689f38", "#ff6d00", "#5c6bc0",
];

const NO_TOOLBAR = { displayModeBar: false } as const;

/** Convert a DRAIN3 template string to a regex by replacing <*> with .* */
function drain3ToRegex(template: string): string {
  const escaped = template.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return escaped.replace(/\\<\\\\?\*\\>/g, ".*").replace(/<\*>/g, ".*");
}

/* ================================================================ Component */
export default function PatternAnalyzerPage() {
  const { projectId } = useProject();
  const [searchParams, setSearchParams] = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Domain-grouped pattern state
  const [domains, setDomains] = useState<DomainPatterns>({});
  const [patternsLoaded, setPatternsLoaded] = useState(false);
  const [collapsedDomains, setCollapsedDomains] = useState<Set<string>>(new Set());
  const [newDomainName, setNewDomainName] = useState("");
  const [showNewDomain, setShowNewDomain] = useState(false);

  // Scan config
  const [bucketMinutes, setBucketMinutes] = useState(5);
  const [filterPreNtp, setFilterPreNtp] = useState(true);

  // Scan results
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);

  // Preset import
  const [showPresets, setShowPresets] = useState(false);

  // Reboot selection state (any reboot as start, any as end)
  const [startRebootIdx, setStartRebootIdx] = useState<number | null>(null);
  const [endRebootIdx, setEndRebootIdx] = useState<number | null>(null);
  const [sliderValue, setSliderValue] = useState(0);

  // -- Load saved patterns --
  const { data: savedDomains, isLoading: loadingPatterns } = useQuery({
    queryKey: ["regex-patterns", projectId],
    queryFn: async () => {
      const res = await patternAnalyzerApi.getPatterns(projectId!);
      return res.data.domains;
    },
    enabled: !!projectId,
  });

  useEffect(() => {
    if (savedDomains && !patternsLoaded) {
      setDomains(savedDomains);
      setPatternsLoaded(true);
      // Collapse all domains by default
      setCollapsedDomains(new Set(Object.keys(savedDomains)));
    }
  }, [savedDomains, patternsLoaded]);

  // -- Load presets --
  const { data: presetsData } = useQuery({
    queryKey: ["regex-presets", projectId],
    queryFn: async () => {
      const res = await patternAnalyzerApi.getPresets(projectId!);
      return res.data.presets;
    },
    enabled: !!projectId && showPresets,
  });

  // -- Load reboots on mount --
  const { data: rebootsData } = useQuery({
    queryKey: ["reboots", projectId],
    queryFn: async () => {
      const res = await patternAnalyzerApi.getReboots(projectId!);
      return res.data.reboots;
    },
    enabled: !!projectId,
  });

  // -- Derive selected reboot timestamps --
  const reboots: RebootEntry[] = rebootsData || [];
  const selectedStart = startRebootIdx !== null ? reboots[startRebootIdx]?.timestamp || "" : "";
  const selectedEnd = endRebootIdx !== null ? reboots[endRebootIdx]?.timestamp || "" : "";
  const hasSelection = startRebootIdx !== null && endRebootIdx !== null;

  // -- Compute effective time range from reboot selection + slider --
  // End is always pinned to the selected end reboot.  Slider moves the
  // start from the selected start reboot toward the end reboot.
  //
  // IMPORTANT: Timestamps are naive ISO strings (no timezone).  We must
  // NOT convert through Date.toISOString() because that emits UTC while
  // `new Date(naiveStr)` parses as local time – introducing an offset
  // that silently breaks string comparisons against the scan data.
  let effectiveRange: { start: string; end: string } | undefined;
  if (hasSelection && selectedStart && selectedEnd) {
    if (sliderValue === 0) {
      // No slider offset – use the raw strings directly (no Date conversion).
      effectiveRange = { start: selectedStart, end: selectedEnd };
    } else {
      const startMs = new Date(selectedStart).getTime();
      const endMs = new Date(selectedEnd).getTime();
      const durationMs = endMs - startMs;
      if (durationMs <= 0) {
        effectiveRange = { start: selectedStart, end: selectedEnd };
      } else {
        const skipMs = (sliderValue / 100) * durationMs;
        const d = new Date(startMs + skipMs);
        // Format as local time to match the naive timestamps in scan data
        const pad = (n: number) => n.toString().padStart(2, "0");
        const effectiveStart = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        effectiveRange = { start: effectiveStart, end: selectedEnd };
      }
    }
  }

  // -- Save patterns mutation --
  const saveMutation = useMutation({
    mutationFn: () => patternAnalyzerApi.savePatterns(projectId!, domains),
  });

  // -- Flatten all enabled patterns for scan --
  const allPatterns: UserPattern[] = Object.values(domains).flat();
  const enabledPatterns = allPatterns.filter((p) => p.enabled && p.regex.trim());
  const enabledCount = enabledPatterns.length;
  const totalCount = allPatterns.length;

  // -- Scan status --
  const [scanStatus, setScanStatus] = useState<string>("");

  // -- Run scan mutation (two-phase: scan → fetch results) --
  const scanMutation = useMutation({
    mutationFn: async () => {
      // Phase 1: trigger scan, get lightweight metadata
      setScanStatus("Scanning log files with ripgrep...");
      const scanRes = await patternAnalyzerApi.scan(projectId!, {
        patterns: enabledPatterns,
        bucket_minutes: bucketMinutes,
        time_range: effectiveRange,
        filter_pre_ntp: filterPreNtp,
      });

      const { scan_id, total_matches, trace_count, elapsed_ms } = scanRes.data;
      setScanStatus(
        `Scan complete (${total_matches.toLocaleString()} matches, ${trace_count} patterns, ${elapsed_ms}ms). Loading results...`
      );

      // Phase 2: fetch full Plotly-ready data from cache
      const resultsRes = await patternAnalyzerApi.getScanResults(projectId!, scan_id);
      return resultsRes.data;
    },
    onSuccess: (data) => {
      setScanResult(data);
      setScanStatus("");
    },
    onError: () => {
      setScanStatus("");
    },
  });

  // -- Handle DRAIN3 template import via URL params --
  useEffect(() => {
    const templateParam = searchParams.get("template");
    if (templateParam && patternsLoaded) {
      const regex = drain3ToRegex(templateParam);
      const name = templateParam.length > 60 ? templateParam.slice(0, 57) + "..." : templateParam;
      // Add to "Imported" domain
      const importDomain = "Imported";
      const existing = domains[importDomain] || [];
      const exists = existing.some((p) => p.regex === regex);
      if (!exists) {
        setDomains((prev) => ({
          ...prev,
          [importDomain]: [...(prev[importDomain] || []), { name, regex, enabled: true }],
        }));
      }
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, patternsLoaded, domains, setSearchParams]);

  // -- Domain-level enable/disable --
  const toggleDomainEnabled = (domain: string, enabled: boolean) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p) => ({ ...p, enabled })),
    }));
  };

  const isDomainFullyEnabled = (domain: string): boolean => {
    const pats = domains[domain] || [];
    return pats.length > 0 && pats.every((p) => p.enabled);
  };

  const isDomainPartiallyEnabled = (domain: string): boolean => {
    const pats = domains[domain] || [];
    return pats.some((p) => p.enabled) && !pats.every((p) => p.enabled);
  };

  // -- Domain CRUD helpers --
  const toggleDomainCollapse = (domain: string) => {
    setCollapsedDomains((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain);
      else next.add(domain);
      return next;
    });
  };

  const addDomain = () => {
    const name = newDomainName.trim();
    if (!name || domains[name]) return;
    setDomains((prev) => ({ ...prev, [name]: [] }));
    setNewDomainName("");
    setShowNewDomain(false);
  };

  const removeDomain = (domain: string) => {
    setDomains((prev) => {
      const next = { ...prev };
      delete next[domain];
      return next;
    });
  };

  // -- Pattern CRUD helpers --
  const addPattern = (domain: string) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: [...(prev[domain] || []), { name: "", regex: "", enabled: true }],
    }));
  };

  const removePattern = (domain: string, idx: number) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).filter((_, i) => i !== idx),
    }));
  };

  const updatePattern = (domain: string, idx: number, field: keyof UserPattern, value: string | boolean) => {
    setDomains((prev) => ({
      ...prev,
      [domain]: (prev[domain] || []).map((p, i) => (i === idx ? { ...p, [field]: value } : p)),
    }));
  };

  const importPreset = (presetDomain: string) => {
    const presetPatterns = presetsData?.[presetDomain] || [];
    const existing = domains[presetDomain] || [];
    const existingRegexes = new Set(existing.map((p) => p.regex));
    const newPatterns = presetPatterns.filter((p) => !existingRegexes.has(p.regex));
    setDomains((prev) => ({
      ...prev,
      [presetDomain]: [...(prev[presetDomain] || []), ...newPatterns],
    }));
    setShowPresets(false);
  };

  // -- JSON file import --
  const handleJsonImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const json = JSON.parse(ev.target?.result as string);

        // Support domain-grouped format: { domains: {...} } or { "WLAN_Issues": [...], ... }
        // or flat array: [ {name, regex}, ... ]
        // or rule_parser_config.json format: { "WLAN_Issues": [ { Title, CPELogs: [{ Regex: [...] }] } ] }

        if (json.domains && typeof json.domains === "object") {
          // Domain-grouped format
          const imported: DomainPatterns = {};
          for (const [domain, pats] of Object.entries(json.domains)) {
            if (Array.isArray(pats)) {
              imported[domain] = (pats as UserPattern[]).map((p) => ({
                name: String(p.name || "").slice(0, 100),
                regex: String(p.regex || ""),
                enabled: p.enabled !== false,
              })).filter((p) => p.regex);
            }
          }
          // Merge into existing
          setDomains((prev) => {
            const next = { ...prev };
            for (const [domain, pats] of Object.entries(imported)) {
              const existing = next[domain] || [];
              const existingRegexes = new Set(existing.map((p) => p.regex));
              const newPats = pats.filter((p) => !existingRegexes.has(p.regex));
              next[domain] = [...existing, ...newPats];
            }
            return next;
          });
          return;
        }

        if (Array.isArray(json)) {
          // Flat array → "Imported" domain
          const imported: UserPattern[] = json
            .map((item: Record<string, unknown>) => ({
              name: String(item.name || item.template || item.regex || "").slice(0, 100),
              regex: String(item.regex || item.pattern || item.template || ""),
              enabled: item.enabled !== false,
            }))
            .filter((p: UserPattern) => p.regex);
          if (imported.length > 0) {
            setDomains((prev) => {
              const existing = prev["Imported"] || [];
              const existingRegexes = new Set(existing.map((p) => p.regex));
              const newPats = imported.filter((p) => !existingRegexes.has(p.regex));
              return { ...prev, Imported: [...existing, ...newPats] };
            });
          }
          return;
        }

        // Try rule_parser_config.json format
        if (typeof json === "object") {
          const imported: DomainPatterns = {};
          let found = false;
          for (const [key, issues] of Object.entries(json)) {
            if (!Array.isArray(issues)) continue;
            const patterns: UserPattern[] = [];
            for (const issue of issues as Array<Record<string, unknown>>) {
              const title = String(issue.Title || "");
              const cpeLogs = issue.CPELogs as Array<Record<string, unknown>> | undefined;
              if (!Array.isArray(cpeLogs)) continue;
              for (const cpeLog of cpeLogs) {
                const regexEntries = cpeLog.Regex as Array<Record<string, string>> | undefined;
                if (!Array.isArray(regexEntries)) continue;
                for (const rx of regexEntries) {
                  if (rx.pattern) {
                    patterns.push({
                      name: rx.description || title || rx.pattern.slice(0, 60),
                      regex: rx.pattern,
                      enabled: true,
                    });
                    found = true;
                  }
                }
              }
            }
            if (patterns.length > 0) imported[key] = patterns;
          }
          if (found) {
            setDomains((prev) => {
              const next = { ...prev };
              for (const [domain, pats] of Object.entries(imported)) {
                const existing = next[domain] || [];
                const existingRegexes = new Set(existing.map((p) => p.regex));
                const newPats = pats.filter((p) => !existingRegexes.has(p.regex));
                next[domain] = [...existing, ...newPats];
              }
              return next;
            });
            return;
          }
        }

        alert("Unrecognized JSON format. Supported: domain-grouped, flat array, or rule_parser_config format.");
      } catch {
        alert("Failed to parse JSON file.");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  // -- Export handler --
  const handleExport = (format: "yaml" | "json") => {
    if (!projectId) return;
    const url = patternAnalyzerApi.exportUrl(projectId, format);
    // Open with auth token
    const token = localStorage.getItem("access_token");
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => res.blob())
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `patterns.${format}`;
        a.click();
        URL.revokeObjectURL(a.href);
      })
      .catch(() => alert("Export failed."));
  };

  // -- Build Plotly data (time series with individual log points) --
  // Recomputed every render so it always reflects the latest filter.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const plotData: any[] = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const plotShapes: any[] = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const plotAnnotations: any[] = [];
  const traceNames: string[] = [];
  let filteredMatchCount = 0;

  if (scanResult) {
    // Client-side time filter so graph updates instantly when
    // reboot selection or slider changes (without re-scanning).
    const rangeStart = effectiveRange?.start || "";
    const rangeEnd = effectiveRange?.end || "";

    scanResult.traces.forEach((trace, idx) => {
      let filteredTimes = trace.times;
      let filteredTexts = trace.texts;

      if (rangeStart || rangeEnd) {
        const indices: number[] = [];
        for (let i = 0; i < trace.times.length; i++) {
          const t = trace.times[i];
          if (rangeStart && t < rangeStart) continue;
          if (rangeEnd && t > rangeEnd) continue;
          indices.push(i);
        }
        filteredTimes = indices.map((i) => trace.times[i]);
        filteredTexts = indices.map((i) => trace.texts[i]);
      }

      if (filteredTimes.length === 0) return;

      filteredMatchCount += filteredTimes.length;
      const label = `${trace.name} (${filteredTimes.length})`;
      traceNames.push(label);

      const color = TRACE_COLORS[idx % TRACE_COLORS.length];
      plotData.push({
        x: filteredTimes,
        y: filteredTimes.map(() => label),
        type: "scatter" as const,
        mode: "markers" as const,
        name: label,
        marker: {
          size: 7,
          color,
          symbol: "circle",
          opacity: 0.8,
          line: { width: 0.5, color: "white" },
        },
        text: filteredTexts,
        hovertemplate: "%{text}<extra></extra>",
      });
    });

    // Only show reboot lines within the effective range so they don't
    // stretch the x-axis beyond the filtered data.
    scanResult.reboots.forEach((reboot) => {
      if (rangeStart && reboot.timestamp < rangeStart) return;
      if (rangeEnd && reboot.timestamp > rangeEnd) return;

      plotShapes.push({
        type: "line",
        x0: reboot.timestamp,
        x1: reboot.timestamp,
        y0: 0,
        y1: 1,
        yref: "paper",
        line: { color: "#d93025", width: 2, dash: "dash" },
      });
      plotAnnotations.push({
        x: reboot.timestamp,
        y: 1,
        yref: "paper",
        text: `Reboot: ${reboot.reason || "unknown"}`,
        showarrow: true,
        arrowhead: 2,
        ax: 0,
        ay: -30,
        font: { size: 10, color: "#d93025" },
        bordercolor: "#d93025",
        borderwidth: 1,
        borderpad: 2,
        bgcolor: "rgba(255,255,255,0.9)",
      });
    });
  }

  const domainNames = Object.keys(domains);

  return (
    <div className="p-4 space-y-4 max-w-full overflow-y-auto" style={{ height: "calc(100vh - 48px)" }}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <ManageSearchIcon style={{ fontSize: 24, color: "#1a73e8" }} />
        <h2 className="text-lg font-semibold">Pattern Analyzer</h2>
      </div>

      {/* ====== PATTERN MANAGEMENT ====== */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/30 flex items-center justify-between flex-wrap gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <ManageSearchIcon style={{ fontSize: 14, color: "#1a73e8" }} /> Pattern Configuration
            {totalCount > 0 && (
              <span className="ml-1 text-[10px] font-normal">
                ({domainNames.length} domain{domainNames.length !== 1 ? "s" : ""}, {totalCount} pattern{totalCount !== 1 ? "s" : ""})
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setShowPresets(!showPresets)}
              className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-border bg-background hover:bg-muted transition-colors"
            >
              <DownloadIcon style={{ fontSize: 14 }} /> Import Preset
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-border bg-background hover:bg-muted transition-colors"
            >
              <UploadFileIcon style={{ fontSize: 14 }} /> Import JSON
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json,.yaml,.yml"
              onChange={handleJsonImport}
              className="hidden"
            />
            <button
              onClick={() => setShowNewDomain(true)}
              className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100 dark:border-blue-700 dark:bg-blue-900/20 dark:text-blue-400 transition-colors"
            >
              <CreateNewFolderIcon style={{ fontSize: 14 }} /> Add Domain
            </button>
            {/* Export dropdown */}
            <div className="relative group">
              <button
                className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-border bg-background hover:bg-muted transition-colors"
              >
                <FileDownloadIcon style={{ fontSize: 14 }} /> Export
              </button>
              <div className="absolute right-0 top-full mt-1 bg-card border border-border rounded-lg shadow-lg z-10 hidden group-hover:block min-w-[100px]">
                <button
                  onClick={() => handleExport("json")}
                  className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted transition-colors"
                >
                  As JSON
                </button>
                <button
                  onClick={() => handleExport("yaml")}
                  className="block w-full text-left px-3 py-1.5 text-xs hover:bg-muted transition-colors"
                >
                  As YAML
                </button>
              </div>
            </div>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded border border-green-300 bg-green-50 text-green-700 hover:bg-green-100 dark:border-green-700 dark:bg-green-900/20 dark:text-green-400 transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? (
                <CircularProgress size={12} />
              ) : (
                <SaveIcon style={{ fontSize: 14 }} />
              )}
              Save
            </button>
          </div>
        </div>

        {/* Preset import dropdown */}
        {showPresets && presetsData && (
          <div className="px-4 py-2 border-b border-border bg-yellow-50/50 dark:bg-yellow-900/10">
            <p className="text-[11px] text-muted-foreground mb-1.5">Import patterns from a domain preset (patterns are added to matching domain):</p>
            <div className="flex flex-wrap gap-2">
              {Object.keys(presetsData).map((domain) => (
                <button
                  key={domain}
                  onClick={() => importPreset(domain)}
                  className="px-3 py-1 text-xs font-medium rounded-full border border-border bg-background hover:bg-muted transition-colors"
                >
                  {domain.replace(/_/g, " ")} ({presetsData[domain].length})
                </button>
              ))}
            </div>
          </div>
        )}

        {/* New domain input */}
        {showNewDomain && (
          <div className="px-4 py-2 border-b border-border bg-blue-50/50 dark:bg-blue-900/10 flex items-center gap-2">
            <input
              type="text"
              value={newDomainName}
              onChange={(e) => setNewDomainName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addDomain()}
              placeholder="Domain name (e.g. WLAN_Issues)"
              className="flex-1 text-xs px-2 py-1 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-blue-500"
              autoFocus
            />
            <button onClick={addDomain} disabled={!newDomainName.trim()} className="px-3 py-1 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">Create</button>
            <button onClick={() => { setShowNewDomain(false); setNewDomainName(""); }} className="text-xs text-muted-foreground hover:text-foreground">Cancel</button>
          </div>
        )}

        {/* Domain-grouped pattern tables */}
        <div className="divide-y divide-border">
          {loadingPatterns ? (
            <div className="flex items-center gap-2 justify-center py-6 text-muted-foreground">
              <CircularProgress size={16} />
              <span className="text-xs">Loading patterns...</span>
            </div>
          ) : domainNames.length === 0 ? (
            <div className="text-center py-6 text-muted-foreground">
              <p className="text-sm">No patterns configured yet.</p>
              <p className="text-xs mt-1">Add a domain, import from presets/JSON, or use "Add to Pattern Analyzer" from the Pattern or AI Analysis pages.</p>
            </div>
          ) : (
            domainNames.map((domain) => {
              const patterns = domains[domain] || [];
              const isCollapsed = collapsedDomains.has(domain);
              const domainEnabled = patterns.filter((p) => p.enabled && p.regex.trim()).length;

              return (
                <div key={domain}>
                  {/* Domain header */}
                  <div
                    className="flex items-center justify-between px-4 py-2 bg-muted/20 cursor-pointer hover:bg-muted/40 transition-colors"
                    onClick={() => toggleDomainCollapse(domain)}
                  >
                    <div className="flex items-center gap-2">
                      {isCollapsed ? (
                        <ExpandMoreIcon style={{ fontSize: 18 }} className="text-muted-foreground" />
                      ) : (
                        <ExpandLessIcon style={{ fontSize: 18 }} className="text-muted-foreground" />
                      )}
                      <span className="text-xs font-semibold">{domain.replace(/_/g, " ")}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {domainEnabled}/{patterns.length} enabled
                      </span>
                    </div>
                    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      {/* Domain-level enable/disable */}
                      <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer" title={isDomainFullyEnabled(domain) ? "Disable all patterns" : "Enable all patterns"}>
                        <input
                          type="checkbox"
                          checked={isDomainFullyEnabled(domain)}
                          ref={(el) => {
                            if (el) el.indeterminate = isDomainPartiallyEnabled(domain);
                          }}
                          onChange={(e) => toggleDomainEnabled(domain, e.target.checked)}
                          className="h-3.5 w-3.5 rounded accent-blue-600"
                        />
                        <span className="hidden sm:inline">{isDomainFullyEnabled(domain) ? "All on" : "Toggle"}</span>
                      </label>
                      <button
                        onClick={() => addPattern(domain)}
                        className="p-1 rounded hover:bg-blue-100 dark:hover:bg-blue-900/20 text-muted-foreground hover:text-blue-600 transition-colors"
                        title="Add pattern to this domain"
                      >
                        <AddIcon style={{ fontSize: 16 }} />
                      </button>
                      <button
                        onClick={() => {
                          if (confirm(`Remove domain "${domain}" and all its ${patterns.length} patterns?`)) {
                            removeDomain(domain);
                          }
                        }}
                        className="p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                        title="Remove domain"
                      >
                        <DeleteIcon style={{ fontSize: 16 }} />
                      </button>
                    </div>
                  </div>

                  {/* Pattern rows */}
                  {!isCollapsed && (
                    <div className="px-4 py-2 space-y-1">
                      {patterns.length === 0 ? (
                        <p className="text-[11px] text-muted-foreground py-2 text-center">No patterns in this domain yet.</p>
                      ) : (
                        <>
                          <div className="grid grid-cols-[32px_1fr_2fr_32px] gap-2 px-1 py-0.5">
                            <span className="text-[10px] text-muted-foreground font-semibold uppercase">On</span>
                            <span className="text-[10px] text-muted-foreground font-semibold uppercase">Name</span>
                            <span className="text-[10px] text-muted-foreground font-semibold uppercase">Regex</span>
                            <span />
                          </div>
                          {patterns.map((p, idx) => (
                            <div
                              key={idx}
                              className="grid grid-cols-[32px_1fr_2fr_32px] gap-2 items-center px-1 py-0.5 rounded hover:bg-muted/30"
                            >
                              <input
                                type="checkbox"
                                checked={p.enabled}
                                onChange={(e) => updatePattern(domain, idx, "enabled", e.target.checked)}
                                className="h-3.5 w-3.5 rounded border-gray-300 accent-blue-600"
                              />
                              <input
                                type="text"
                                value={p.name}
                                onChange={(e) => updatePattern(domain, idx, "name", e.target.value)}
                                placeholder="Pattern name"
                                className="text-xs px-2 py-1 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-blue-500 min-w-0"
                              />
                              <input
                                type="text"
                                value={p.regex}
                                onChange={(e) => updatePattern(domain, idx, "regex", e.target.value)}
                                placeholder="Regular expression"
                                className="text-xs px-2 py-1 rounded border border-border bg-background font-mono focus:outline-none focus:ring-1 focus:ring-blue-500 min-w-0"
                              />
                              <button
                                onClick={() => removePattern(domain, idx)}
                                className="p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/20 text-muted-foreground hover:text-red-600 transition-colors"
                              >
                                <DeleteIcon style={{ fontSize: 14 }} />
                              </button>
                            </div>
                          ))}
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {saveMutation.isSuccess && (
          <div className="px-4 py-1.5 bg-green-50 dark:bg-green-900/10 text-green-700 dark:text-green-400 text-[11px] border-t border-border">
            Patterns saved successfully.
          </div>
        )}
        {saveMutation.isError && (
          <div className="px-4 py-1.5 bg-red-50 dark:bg-red-900/10 text-red-700 dark:text-red-400 text-[11px] border-t border-border flex items-center gap-1">
            <ErrorIcon style={{ fontSize: 13 }} />
            {(saveMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Save failed"}
          </div>
        )}
      </div>

      {/* ====== SCAN CONFIGURATION ====== */}
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/30">
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <PlayArrowIcon style={{ fontSize: 14, color: "#188038" }} /> Scan Configuration
          </h3>
        </div>
        <div className="p-4 space-y-4">
          {/* Row 1: Bucket + Run */}
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">
                Time Bucket
              </label>
              <select
                value={bucketMinutes}
                onChange={(e) => setBucketMinutes(Number(e.target.value))}
                className="text-xs px-3 py-1.5 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {BUCKET_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <label className="flex items-center gap-1.5 cursor-pointer select-none" title="Exclude log lines with build-time timestamps (before NTP sync corrects the clock)">
              <input
                type="checkbox"
                checked={filterPreNtp}
                onChange={(e) => setFilterPreNtp(e.target.checked)}
                className="h-3.5 w-3.5 rounded accent-blue-600"
              />
              <span className="text-xs text-muted-foreground">Filter pre-NTP logs</span>
            </label>

            <button
              onClick={() => scanMutation.mutate()}
              disabled={scanMutation.isPending || enabledCount === 0}
              className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {scanMutation.isPending ? (
                <CircularProgress size={14} sx={{ color: "white" }} />
              ) : (
                <PlayArrowIcon style={{ fontSize: 16 }} />
              )}
              Run Scan ({enabledCount} pattern{enabledCount !== 1 ? "s" : ""})
            </button>
          </div>

          {/* Row 2: Reboot range selector */}
          {reboots.length > 0 && (
            <div>
              <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1.5 flex items-center gap-1">
                <RestartAltIcon style={{ fontSize: 12 }} /> Reboot Range ({reboots.length} reboots detected)
              </label>

              <div className="flex flex-wrap items-end gap-4 mb-3">
                {/* Start reboot selector */}
                <div>
                  <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">
                    From (Start)
                  </label>
                  <select
                    value={startRebootIdx ?? ""}
                    onChange={(e) => {
                      const val = e.target.value === "" ? null : Number(e.target.value);
                      setStartRebootIdx(val);
                      setSliderValue(0);
                    }}
                    className="text-xs px-3 py-1.5 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-blue-500 min-w-[220px]"
                  >
                    <option value="">-- Select --</option>
                    {reboots.map((r, idx) => (
                      <option
                        key={idx}
                        value={idx}
                        disabled={endRebootIdx !== null && idx >= endRebootIdx}
                      >
                        Reboot #{idx + 1} — {r.timestamp.replace("T", " ")} ({r.reason || "unknown"})
                      </option>
                    ))}
                  </select>
                </div>

                {/* End reboot selector */}
                <div>
                  <label className="block text-[10px] text-muted-foreground font-semibold uppercase mb-1">
                    To (End)
                  </label>
                  <select
                    value={endRebootIdx ?? ""}
                    onChange={(e) => {
                      const val = e.target.value === "" ? null : Number(e.target.value);
                      setEndRebootIdx(val);
                      setSliderValue(0);
                    }}
                    className="text-xs px-3 py-1.5 rounded border border-border bg-background focus:outline-none focus:ring-1 focus:ring-blue-500 min-w-[220px]"
                  >
                    <option value="">-- Select --</option>
                    {reboots.map((r, idx) => (
                      <option
                        key={idx}
                        value={idx}
                        disabled={startRebootIdx !== null && idx <= startRebootIdx}
                      >
                        Reboot #{idx + 1} — {r.timestamp.replace("T", " ")} ({r.reason || "unknown"})
                      </option>
                    ))}
                  </select>
                </div>

                {/* Clear button */}
                {hasSelection && (
                  <button
                    onClick={() => {
                      setStartRebootIdx(null);
                      setEndRebootIdx(null);
                      setSliderValue(0);
                    }}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border bg-background hover:bg-muted text-muted-foreground transition-colors"
                  >
                    Clear
                  </button>
                )}
              </div>

              {/* Slider + effective range (shown when both reboots selected) */}
              {hasSelection && selectedStart && selectedEnd && (() => {
                const durationMs = new Date(selectedEnd).getTime() - new Date(selectedStart).getTime();
                const viewingMs = durationMs - (sliderValue / 100) * durationMs;
                const viewingMin = Math.round(viewingMs / 60000);
                const viewingLabel =
                  viewingMin >= 1440
                    ? `${(viewingMin / 1440).toFixed(1)} days`
                    : viewingMin >= 60
                      ? `${(viewingMin / 60).toFixed(1)} hr`
                      : `${viewingMin} min`;

                return (
                  <div className="bg-muted/30 rounded-lg p-3 space-y-3">
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                      <span className="font-mono">{selectedStart}</span>
                      <span>{"\u2192"}</span>
                      <span className="font-mono">{selectedEnd}</span>
                    </div>

                    <div className="flex items-center gap-3">
                      <label className="text-[10px] text-muted-foreground font-semibold uppercase w-28 shrink-0">
                        Skip from start
                      </label>
                      <input
                        type="range"
                        min={0}
                        max={95}
                        value={sliderValue}
                        onChange={(e) => setSliderValue(Number(e.target.value))}
                        className="flex-1 accent-blue-600"
                      />
                      <span className="text-xs font-medium w-20 text-right">{sliderValue}%</span>
                    </div>

                    <div className="text-[10px] text-muted-foreground">
                      Viewing last <span className="font-semibold">{viewingLabel}</span> before end reboot
                    </div>

                    {effectiveRange && (
                      <div className="text-[10px] text-muted-foreground">
                        Effective range:{" "}
                        <span className="font-mono font-medium">{effectiveRange.start}</span>
                        {" \u2192 "}
                        <span className="font-mono font-medium">{effectiveRange.end}</span>
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          )}
        </div>

        {scanMutation.isError && (
          <div className="px-4 py-2 bg-red-50 dark:bg-red-900/10 text-red-700 dark:text-red-400 text-xs border-t border-border flex items-center gap-1.5">
            <ErrorIcon style={{ fontSize: 14 }} />
            {(scanMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Scan failed"}
          </div>
        )}
      </div>

      {/* ====== RESULTS CHART ====== */}
      {scanResult && (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="px-4 py-2 border-b border-border bg-muted/30 flex items-center justify-between">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              Pattern Occurrences Over Time
            </h3>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="font-semibold">
                {effectiveRange
                  ? `${filteredMatchCount.toLocaleString()} / ${scanResult.total_matches.toLocaleString()} matches (filtered)`
                  : `${scanResult.total_matches.toLocaleString()} total matches`}
              </span>
              {scanResult.reboots.length > 0 && (
                <span className="flex items-center gap-1 text-red-600 dark:text-red-400 font-semibold">
                  <RestartAltIcon style={{ fontSize: 13 }} />
                  {scanResult.reboots.length} reboot(s)
                </span>
              )}
            </div>
          </div>

          {plotData.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <p className="text-sm">No matches found{effectiveRange ? " in selected time range" : " with timestamps"}.</p>
              <p className="text-xs mt-1">Try adjusting your patterns or time range.</p>
            </div>
          ) : (
            <div className="p-2">
              <Plot
                key={`plot-${startRebootIdx}-${endRebootIdx}-${sliderValue}-${bucketMinutes}`}
                data={plotData}
                layout={{
                  height: Math.max(300, traceNames.length * 60 + 100),
                  margin: { l: 180, r: 20, t: 10, b: 45 },
                  xaxis: {
                    title: { text: "Time", font: { size: 11 } },
                    tickfont: { size: 10 },
                    type: "date",
                    ...(effectiveRange
                      ? { range: [effectiveRange.start, effectiveRange.end], autorange: false }
                      : {}),
                    ...(bucketMinutes > 0
                      ? { dtick: bucketMinutes * 60 * 1000 }
                      : {}),
                  },
                  yaxis: {
                    tickfont: { size: 10 },
                    type: "category",
                    categoryorder: "array",
                    categoryarray: [...traceNames].reverse(),
                    automargin: true,
                  },
                  hovermode: "closest",
                  legend: {
                    orientation: "h",
                    y: 1.08,
                    x: 0.5,
                    xanchor: "center",
                    font: { size: 10 },
                  },
                  shapes: plotShapes,
                  annotations: plotAnnotations,
                  paper_bgcolor: "transparent",
                  plot_bgcolor: "transparent",
                  font: { family: "Roboto, sans-serif", size: 11 },
                }}
                config={NO_TOOLBAR}
                style={{ width: "100%" }}
              />
            </div>
          )}

          {scanResult.reboots.length > 0 && (
            <div className="px-4 py-3 border-t border-border">
              <h4 className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1">
                <RestartAltIcon style={{ fontSize: 12, color: "#d93025" }} /> Reboot Boundaries
              </h4>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                {scanResult.reboots.map((r, idx) => (
                  <div
                    key={idx}
                    className="border border-red-200 dark:border-red-800 rounded-lg p-2 bg-red-50/50 dark:bg-red-900/10"
                  >
                    <p className="text-[11px] font-semibold text-red-700 dark:text-red-400">
                      #{idx + 1}
                    </p>
                    <p className="text-[10px] text-muted-foreground font-mono">{r.timestamp}</p>
                    <p className="text-[10px] mt-0.5 truncate" title={r.reason}>
                      {r.reason || "unknown"}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {scanMutation.isPending && (
        <div className="flex items-center gap-3 justify-center py-8 text-muted-foreground">
          <CircularProgress size={20} />
          <span className="text-sm">{scanStatus || "Scanning log files with ripgrep..."}</span>
        </div>
      )}
    </div>
  );
}

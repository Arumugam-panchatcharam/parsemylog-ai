import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { patternsApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { cn } from "@/lib/utils";
import { labelForPosition } from "@/lib/drain3MaskLabels";
import { DynamicValuesMacRichText, plainTextWithFormattedMacs } from "@/lib/macAddressDisplay";
import { useCPE } from "@/hooks/useCPE";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";
import Plot from "react-plotly.js";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CircularProgress from "@mui/material/CircularProgress";
import FilterListIcon from "@mui/icons-material/FilterList";
import SearchIcon from "@mui/icons-material/Search";
import ScheduleIcon from "@mui/icons-material/Schedule";
import BarChartIcon from "@mui/icons-material/BarChart";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import NotesIcon from "@mui/icons-material/Notes";
import DevicesIcon from "@mui/icons-material/Devices";
import PersonIcon from "@mui/icons-material/Person";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import CloseIcon from "@mui/icons-material/Close";
import DownloadIcon from "@mui/icons-material/Download";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

const NO_TOOLBAR = { displayModeBar: false } as const;

/** Persists single-CPE pattern trend panel open/closed across templates, routes, and reloads. */
const PATTERN_TREND_EXPANDED_KEY = "parsemylog.patternPage.trendSectionExpanded";

function readStoredTrendExpanded(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return localStorage.getItem(PATTERN_TREND_EXPANDED_KEY) === "true";
  } catch {
    return false;
  }
}

function persistTrendExpanded(expanded: boolean): void {
  try {
    localStorage.setItem(PATTERN_TREND_EXPANDED_KEY, expanded ? "true" : "false");
  } catch {
    /* ignore quota / private mode */
  }
}

interface AggregatedPattern {
  template: string;
  occurrence_count: number;
  cpe_count: number;
  cpe_details: Record<string, number>;
}

interface AggregatedResponse {
  domain: string;
  total_cpes: number;
  total_unique_patterns: number;
  page: number;
  page_size: number;
  total_pages: number;
  source_files: string[];
  patterns: AggregatedPattern[];
}

export default function PatternPage() {
  const { projectId } = useProject();
  const { cpeId } = useCPE();
  const navigate = useNavigate();
  const mergePlot = usePlotlyLayoutMerge();
  const [selectedDomain, setSelectedDomain] = useState<string>("");
  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  const [timeInterval, setTimeInterval] = useState(0);
  const [activeTab, setActiveTab] = useState<"cpe" | "overview">("cpe");
  const [selectedPatternDetails, setSelectedPatternDetails] = useState<AggregatedPattern | null>(null);

  // Fetch sample logs when pattern is selected
  const { data: sampleLogs } = useQuery<{
    template: string;
    samples: Array<{
      cpe_serial: string;
      filename?: string;
      timestamp: string;
      logline: string;
    }>;
  } | null>({
    queryKey: ["aggregatedSampleLogs", projectId, selectedDomain, selectedPatternDetails?.template],
    queryFn: async () => {
      if (!selectedPatternDetails) return null;
      const response = await patternsApi.getAggregatedSampleLogs(
        projectId!,
        selectedDomain,
        selectedPatternDetails.template,
        3
      );
      return response.data;
    },
    enabled: !!projectId && !!selectedDomain && !!selectedPatternDetails,
  });

  // File filter for single CPE view
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [appliedFiles, setAppliedFiles] = useState<string[]>([]);
  const [allSourceFiles, setAllSourceFiles] = useState<string[]>([]);
  const [singleTemplateSearch, setSingleTemplateSearch] = useState("");
  const [trendSectionExpanded, setTrendSectionExpanded] = useState(() => readStoredTrendExpanded());

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== PATTERN_TREND_EXPANDED_KEY || e.newValue == null) return;
      setTrendSectionExpanded(e.newValue === "true");
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // File filter for aggregated view
  const [aggregatedSelectedFiles, setAggregatedSelectedFiles] = useState<string[]>([]);
  const [aggregatedAppliedFiles, setAggregatedAppliedFiles] = useState<string[]>([]);
  const [hiddenPatterns, setHiddenPatterns] = useState<Set<string>>(new Set());
  const [patternFilter, setPatternFilter] = useState("");
  const [searchAcrossDomains, setSearchAcrossDomains] = useState(false);
  const [allDomainsPatterns, setAllDomainsPatterns] = useState<Array<AggregatedPattern & { domain: string }>>([]);

  const { data: domains } = useQuery({ queryKey: ["domains", projectId, cpeId], queryFn: async () => (await patternsApi.listDomains(projectId!, cpeId)).data, enabled: !!projectId });
  const { data: indexStatus } = useQuery({ queryKey: ["indexingStatus", projectId, cpeId], queryFn: async () => (await patternsApi.indexingStatus(projectId!, cpeId)).data, enabled: !!projectId, refetchInterval: (query) => (query.state.data?.all_done ? false : 5000) });

  // Analysis — triggered by domain + appliedFiles (not selectedFiles)
  const { data: analysisRaw, isLoading: analysisLoading, isError: analysisError, error: analysisErr } = useQuery({
    queryKey: ["analyze", projectId, selectedDomain, appliedFiles, cpeId],
    queryFn: async () => (await patternsApi.analyze(projectId!, selectedDomain, appliedFiles.length > 0 ? appliedFiles : undefined, cpeId)).data,
    enabled: !!projectId && !!selectedDomain,
    retry: false,
  });

  const chartData = analysisRaw?.chart_data;
  const summary = analysisRaw?.summary;

  const singleTemplateTableRows = useMemo(() => {
    if (!chartData?.length) return [];
    type Row = { template: string; count: number };
    const q = singleTemplateSearch.trim().toLowerCase();
    const filtered = q
      ? (chartData as Row[]).filter((r) => r.template.toLowerCase().includes(q))
      : [...(chartData as Row[])];
    return filtered.sort((a, b) => b.count - a.count);
  }, [chartData, singleTemplateSearch]);

  // Populate allSourceFiles from UNFILTERED analysis response
  useEffect(() => {
    if (analysisRaw?.source_files && appliedFiles.length === 0) {
      setAllSourceFiles(analysisRaw.source_files);
    }
  }, [analysisRaw, appliedFiles]);

  const domainSourceFiles = allSourceFiles;
  const fileFilterStr = appliedFiles.length > 0 ? appliedFiles.join(",") : undefined;

  // Reset when domain changes
  useEffect(() => {
    setSelectedTemplate("");
    setSelectedFiles([]);
    setAppliedFiles([]);
    setAllSourceFiles([]);
    setSingleTemplateSearch("");
  }, [selectedDomain]);

  const { data: tsData } = useQuery({ queryKey: ["timeseries", projectId, selectedDomain, selectedTemplate, timeInterval, fileFilterStr, cpeId], queryFn: async () => (await patternsApi.getTimeseries(projectId!, selectedDomain, selectedTemplate, timeInterval, fileFilterStr, cpeId)).data, enabled: !!projectId && !!selectedDomain && !!selectedTemplate });
  const { data: params } = useQuery({ queryKey: ["parameters", projectId, selectedDomain, selectedTemplate, fileFilterStr, cpeId], queryFn: async () => (await patternsApi.getParameters(projectId!, selectedDomain, selectedTemplate, fileFilterStr, cpeId)).data, enabled: !!projectId && !!selectedDomain && !!selectedTemplate });
  const { data: loglines } = useQuery({ queryKey: ["loglines", projectId, selectedDomain, selectedTemplate, fileFilterStr, cpeId], queryFn: async () => (await patternsApi.getLoglines(projectId!, selectedDomain, selectedTemplate, 1, 20, fileFilterStr, cpeId)).data, enabled: !!projectId && !!selectedDomain && !!selectedTemplate });

  // Aggregated patterns query - now fetches all patterns by default (for search)
  const { data: aggregatedData, isLoading: aggregatedLoading } = useQuery<AggregatedResponse>({
    queryKey: ["aggregatedPatterns", projectId, selectedDomain, aggregatedAppliedFiles],
    queryFn: async () => {
      const response = await patternsApi.getAggregated(
        projectId!, 
        selectedDomain, 
        1, 
        10000, // Fetch all patterns by default
        "frequency",
        aggregatedAppliedFiles.length > 0 ? aggregatedAppliedFiles : undefined
      );
      return response.data;
    },
    enabled: !!projectId && !!selectedDomain && activeTab === "overview" && !searchAcrossDomains,
  });

  // Fetch patterns from ALL domains when cross-domain search is enabled
  const { data: allDomainsData, isLoading: allDomainsLoading } = useQuery<{
    domains: Array<{
      domain: string;
      label: string;
      patterns: AggregatedPattern[];
      total_cpes: number;
      total_unique_patterns: number;
    }>;
    total_patterns: number;
  }>({
    queryKey: ["allDomainsPatterns", projectId, aggregatedAppliedFiles],
    queryFn: async () => {
      // Fetch all indexed domains first
      const domainsResponse = await patternsApi.listDomains(projectId!, undefined);
      const indexedDomains = domainsResponse.data.filter((d: { indexed: boolean }) => d.indexed);
      
      // Fetch patterns from each domain
      const domainPromises = indexedDomains.map(async (d: { domain: string; label: string }) => {
        const response = await patternsApi.getAggregated(
          projectId!,
          d.domain,
          1,
          10000,
          "frequency",
          aggregatedAppliedFiles.length > 0 ? aggregatedAppliedFiles : undefined
        );
        return {
          domain: d.domain,
          label: d.label,
          patterns: response.data.patterns,
          total_cpes: response.data.total_cpes,
          total_unique_patterns: response.data.total_unique_patterns,
        };
      });
      
      const domainsData = await Promise.all(domainPromises);
      const totalPatterns = domainsData.reduce((sum, d) => sum + d.total_unique_patterns, 0);
      
      return {
        domains: domainsData,
        total_patterns: totalPatterns,
      };
    },
    enabled: !!projectId && activeTab === "overview" && searchAcrossDomains,
  });

  // Update allDomainsPatterns when data loads (flatten patterns with domain info)
  useEffect(() => {
    if (allDomainsData?.domains) {
      const flattenedPatterns = allDomainsData.domains.flatMap(d =>
        d.patterns.map(p => ({ ...p, domain: d.domain }))
      );
      setAllDomainsPatterns(flattenedPatterns);
    }
  }, [allDomainsData]);

  // Update aggregated source files when data loads (without filter)
  useEffect(() => {
    if (aggregatedData?.source_files && aggregatedAppliedFiles.length === 0) {
      // Only update if files changed to avoid infinite loops
      const newFiles = aggregatedData.source_files.sort().join(',');
      const currentFiles = aggregatedSelectedFiles.sort().join(',');
      if (newFiles !== currentFiles && aggregatedSelectedFiles.length === 0) {
        setAggregatedSelectedFiles(aggregatedData.source_files);
      }
    }
  }, [aggregatedData?.source_files, aggregatedAppliedFiles.length]);

  const intervalMarks = ["1s", "1min", "1h", "1d"];
  const toggleFile = (f: string) => setSelectedFiles((p) => p.includes(f) ? p.filter((x) => x !== f) : [...p, f]);
  const filtersChanged = JSON.stringify(selectedFiles.sort()) !== JSON.stringify(appliedFiles.sort());
  
  const toggleAggregatedFile = (f: string) => setAggregatedSelectedFiles((p) => p.includes(f) ? p.filter((x) => x !== f) : [...p, f]);
  const aggregatedFiltersChanged = JSON.stringify(aggregatedSelectedFiles.sort()) !== JSON.stringify(aggregatedAppliedFiles.sort());

  // Toggle hide pattern
  const toggleHidePattern = (template: string) => {
    setHiddenPatterns(prev => {
      const newSet = new Set(prev);
      if (newSet.has(template)) {
        newSet.delete(template);
      } else {
        newSet.add(template);
      }
      return newSet;
    });
  };

  // Export ALL patterns to CSV (fetch all pages)
  const exportPatterns = async () => {
    if ((!aggregatedData && !searchAcrossDomains) || !projectId) return;
    
    try {
      let allPatterns: (AggregatedPattern & { domain?: string })[] = [];
      
      if (searchAcrossDomains) {
        // Export from all domains
        allPatterns = allDomainsPatterns
          .filter((p) => !hiddenPatterns.has(p.template))
          .filter((p) => {
            if (!patternFilter) return true;
            return p.template.toLowerCase().includes(patternFilter.toLowerCase());
          });
      } else if (selectedDomain) {
        // Export from current domain
        allPatterns = (aggregatedData?.patterns || [])
          .filter((p: AggregatedPattern) => !hiddenPatterns.has(p.template))
          .filter((p: AggregatedPattern) => {
            if (!patternFilter) return true;
            return p.template.toLowerCase().includes(patternFilter.toLowerCase());
          });
      }
      
      // Create CSV content
      const headers = searchAcrossDomains 
        ? ['#', 'Domain', 'Pattern Template', 'Frequency', 'CPE Count']
        : ['#', 'Pattern Template', 'Frequency', 'CPE Count', 'Total CPEs'];
      
      const csvRows = [
        headers.join(','),
        ...allPatterns.map((pattern, idx: number) => {
          if (searchAcrossDomains) {
            const domainLabel = domains?.find((d: { domain: string }) => d.domain === pattern.domain)?.label || pattern.domain;
            return [
              idx + 1,
              `"${domainLabel}"`,
              `"${pattern.template.replace(/"/g, '""')}"`,
              pattern.occurrence_count,
              pattern.cpe_count
            ].join(',');
          } else {
            return [
              idx + 1,
              `"${pattern.template.replace(/"/g, '""')}"`,
              pattern.occurrence_count,
              pattern.cpe_count,
              aggregatedData?.total_cpes || 0
            ].join(',');
          }
        })
      ];
      
      const csvContent = csvRows.join('\n');
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement('a');
      const url = URL.createObjectURL(blob);
      
      const domainSuffix = searchAcrossDomains ? 'all_domains' : selectedDomain;
      const fileFilter = aggregatedAppliedFiles.length > 0 ? '_filtered' : '';
      const searchFilter = patternFilter ? '_search' : '';
      link.setAttribute('href', url);
      link.setAttribute('download', `aggregated_patterns_${domainSuffix}${fileFilter}${searchFilter}.csv`);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (error) {
      console.error('Export failed:', error);
    }
  };

  const handleGlobalExport = async () => {
    if (!projectId) return;
    
    try {
      const response = await patternsApi.exportGlobal(projectId);
      const blob = new Blob([response.data]);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      
      // Get filename from Content-Disposition header, fallback to default
      let filename = "patterns-export.zip";
      const contentDisposition = response.headers['content-disposition'];
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
        if (filenameMatch && filenameMatch[1]) {
          filename = filenameMatch[1];
        }
      }
      
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Global export failed:', error);
      alert('Failed to export. Please try again.');
    }
  };

   // Reset when switching tabs or changing domain in Cross-CPE overview
  useEffect(() => {
    if (activeTab === "overview") {
      setAggregatedSelectedFiles([]);
      setAggregatedAppliedFiles([]);
      setPatternFilter("");
      setSearchAcrossDomains(false);
    }
  }, [selectedDomain, activeTab]);

  return (
    <div className="p-4 space-y-4 max-w-full overflow-y-auto" style={{ height: "calc(100vh - 48px)" }}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <BarChartIcon style={{ fontSize: 24, color: "#1a73e8" }} />
          <h2 className="text-lg font-semibold">Pattern Analysis</h2>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {activeTab === "overview" && projectId && (
            <button
              type="button"
              onClick={handleGlobalExport}
              title="Download a .zip with the Excel workbook (all domains, by file). The server caches under your project after the first build—re-downloads are fast unless logs were re-indexed or CPEs changed."
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
            >
              <DownloadIcon style={{ fontSize: 14 }} />
              Export ALL
            </button>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1 border-b border-border">
        <button
          type="button"
          onClick={() => setActiveTab("cpe")}
          className={cn(
            "flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors",
            activeTab === "cpe"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border",
          )}
        >
          <PersonIcon style={{ fontSize: 16 }} />
          CPE Analysis
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("overview")}
          className={cn(
            "flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors",
            activeTab === "overview"
              ? "border-primary text-primary"
              : "border-transparent text-muted-foreground hover:text-foreground hover:border-border",
          )}
        >
          <CompareArrowsIcon style={{ fontSize: 16 }} />
          Cross-CPE Overview
        </button>
      </div>

      {activeTab === "cpe" && (
      <div className="space-y-4">
      {/* Same top layout as Cross-CPE Overview: Domain | Files (60%) + Summary KPIs (40%), then index status */}
      <div className="space-y-3">
        <div className="flex h-auto flex-col gap-4 md:h-[180px] md:flex-row">
          <div className="flex min-h-[160px] w-full overflow-hidden rounded-xl border border-border bg-card shadow-sm md:min-h-0 md:h-full md:w-[60%] md:flex-row">
            <div className="flex w-full min-h-0 flex-col border-border bg-muted/10 p-3 md:w-1/2 md:shrink-0 md:border-r">
              <h3 className="mb-2 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                <ManageSearchIcon style={{ fontSize: 14 }} />
                Domain
              </h3>
              <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1 custom-scrollbar">
                {domains?.map((d: { domain: string; label: string; indexed: boolean }) => (
                  <button
                    key={d.domain}
                    type="button"
                    onClick={() => (!d.indexed ? null : setSelectedDomain(d.domain))}
                    disabled={!d.indexed}
                    className={`w-full rounded-md px-2.5 py-1.5 text-left text-xs transition-all ${
                      selectedDomain === d.domain
                        ? "bg-primary font-medium text-primary-foreground shadow-sm"
                        : d.indexed
                          ? "text-foreground hover:bg-background hover:shadow-sm"
                          : "cursor-not-allowed opacity-50"
                    }`}
                  >
                    <div className="truncate">{d.label}</div>
                    {!d.indexed && <div className="text-[9px] opacity-70">(not indexed)</div>}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex min-h-0 w-full flex-col bg-card p-3 md:w-1/2 md:min-w-0">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                  <FilterListIcon style={{ fontSize: 14 }} />
                  Files{" "}
                  {selectedDomain && domainSourceFiles.length > 0 ? `(${domainSourceFiles.length})` : ""}
                </h3>
                {selectedDomain && domainSourceFiles.length > 0 && (
                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => setSelectedFiles([...domainSourceFiles])}
                      className="rounded px-1.5 py-0.5 text-[9px] text-primary hover:bg-muted transition-colors"
                    >
                      All
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedFiles([])}
                      className="rounded px-1.5 py-0.5 text-[9px] text-primary hover:bg-muted transition-colors"
                    >
                      None
                    </button>
                    {filtersChanged && (
                      <button
                        type="button"
                        onClick={() => setAppliedFiles([...selectedFiles])}
                        className="ml-1 rounded-full bg-primary px-2 py-0.5 text-[9px] font-bold text-primary-foreground shadow-sm hover:opacity-90 animate-in fade-in zoom-in duration-200"
                      >
                        Apply
                      </button>
                    )}
                  </div>
                )}
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-border/50 bg-muted/20 p-1 custom-scrollbar">
                {analysisLoading && selectedDomain && domainSourceFiles.length === 0 ? (
                  <div className="flex h-full flex-col items-center justify-center gap-2 p-2 text-muted-foreground">
                    <CircularProgress size={20} />
                    <p className="text-xs">Loading files…</p>
                  </div>
                ) : selectedDomain && domainSourceFiles.length > 0 ? (
                  <div className="space-y-0.5">
                    {domainSourceFiles.map((fname) => (
                      <label
                        key={fname}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-[11px] transition-all hover:bg-background hover:shadow-sm"
                        title={fname}
                      >
                        <input
                          type="checkbox"
                          checked={selectedFiles.includes(fname)}
                          onChange={() => toggleFile(fname)}
                          className="h-3.5 w-3.5 shrink-0 accent-primary rounded"
                        />
                        <span className="truncate opacity-90">{fname}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="flex h-full flex-col items-center justify-center p-2 text-center text-muted-foreground">
                    <p className="text-xs">{!selectedDomain ? "Select a domain first" : "No source files found"}</p>
                  </div>
                )}
              </div>
              {appliedFiles.length > 0 && (
                <div className="mt-1.5 text-right text-[10px] font-medium text-muted-foreground">
                  Showing results for <span className="text-foreground">{appliedFiles.length}</span> file(s)
                </div>
              )}
            </div>
          </div>

          <div className="relative flex w-full flex-col justify-center overflow-hidden rounded-xl border border-border bg-card p-4 shadow-sm md:h-full md:w-[40%]">
            <div className="absolute right-0 top-0 p-3 opacity-5">
              <BarChartIcon style={{ fontSize: 120 }} />
            </div>
            {summary ? (
              <div className="relative z-10 flex flex-1 flex-col items-center justify-around gap-4 sm:flex-row sm:gap-0">
                <div className="group cursor-default text-center">
                  <div className="mb-2 flex items-center justify-center gap-2">
                    <div className="rounded-full bg-blue-100 p-2 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
                      <NotesIcon style={{ fontSize: 24 }} />
                    </div>
                    <div className="text-sm font-medium text-muted-foreground">Log lines</div>
                  </div>
                  <div className="text-4xl font-extrabold tracking-tight text-foreground transition-transform duration-200 group-hover:scale-110">
                    {summary.total_loglines.toLocaleString()}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">In selected domain and files</div>
                </div>

                <div className="hidden h-24 w-px bg-border/60 sm:block" />

                <div className="group cursor-default text-center">
                  <div className="mb-2 flex items-center justify-center gap-2">
                    <div className="rounded-full bg-purple-100 p-2 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400">
                      <BarChartIcon style={{ fontSize: 24 }} />
                    </div>
                    <div className="text-sm font-medium text-muted-foreground">Unique patterns</div>
                  </div>
                  <div className="text-4xl font-extrabold tracking-tight text-foreground transition-transform duration-200 group-hover:scale-110">
                    {summary.total_patterns.toLocaleString()}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">Drain3 templates for this CPE</div>
                </div>
              </div>
            ) : (
              <div className="relative z-10 flex h-full flex-col items-center justify-center text-muted-foreground">
                <ManageSearchIcon style={{ fontSize: 32 }} className="mb-2 opacity-20" />
                <p className="text-sm">{selectedDomain ? "Loading…" : "Select a domain to view statistics"}</p>
              </div>
            )}
          </div>
        </div>

        {(analysisLoading && selectedDomain) || analysisError ? (
          <div className="flex flex-wrap items-center gap-3 text-xs">
            {analysisLoading && selectedDomain && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <CircularProgress size={14} /> Analyzing…
              </div>
            )}
            {analysisError && (
              <div className="flex items-center gap-1.5 text-destructive">
                <ErrorOutlineIcon style={{ fontSize: 15 }} />
                {(analysisErr as { response?: { data?: { error?: string } } })?.response?.data?.error ||
                  "Analysis failed"}
              </div>
            )}
          </div>
        ) : null}

        <div className="rounded-xl border border-border bg-card p-3">
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Index status</p>
          <div className="flex max-h-20 flex-wrap gap-1 overflow-y-auto custom-scrollbar pr-0.5">
            {indexStatus?.domains &&
              Object.entries(indexStatus.domains).map(([key, val]: [string, unknown]) => {
                const d = val as { indexed: boolean; label: string };
                return (
                  <span
                    key={key}
                    title={
                      d.indexed ? "Domain indexed and ready for analysis" : "Indexing in progress…"
                    }
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium border border-border ${
                      d.indexed
                        ? "bg-zinc-800 text-white dark:bg-zinc-950 dark:text-white"
                        : "bg-muted text-muted-foreground dark:bg-muted/80"
                    }`}
                  >
                    {d.indexed ? (
                      <CheckCircleIcon style={{ fontSize: 14 }} className="text-green-500 shrink-0" />
                    ) : (
                      <CircularProgress size={11} className="shrink-0" />
                    )}
                    {d.label}
                  </span>
                );
              })}
          </div>
        </div>
      </div>

      {/* Templates table (sorted by frequency descending, optional search) */}
      {chartData && chartData.length > 0 && (
        <div className="bg-card border border-border rounded-2xl p-4">
          <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="text-sm font-semibold">
              Templates
              {singleTemplateSearch.trim() ? (
                <span className="ml-1.5 font-normal text-muted-foreground">
                  ({singleTemplateTableRows.length} of {chartData.length} patterns)
                </span>
              ) : (
                <span className="ml-1.5 font-normal text-muted-foreground">({chartData.length} patterns)</span>
              )}
            </h3>
            <div className="relative w-full sm:max-w-xs">
              <SearchIcon
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
                style={{ fontSize: 18 }}
              />
              <input
                type="search"
                value={singleTemplateSearch}
                onChange={(e) => setSingleTemplateSearch(e.target.value)}
                placeholder="Search templates…"
                className="w-full rounded-lg border border-input bg-background py-2 pl-9 pr-8 text-sm outline-none ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Search templates"
              />
              {singleTemplateSearch ? (
                <button
                  type="button"
                  onClick={() => setSingleTemplateSearch("")}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  Clear
                </button>
              ) : null}
            </div>
          </div>
          <div className="max-h-[min(28rem,55vh)] overflow-y-auto custom-scrollbar rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10 border-b border-border bg-muted/95 backdrop-blur-sm">
                <tr>
                  <th className="w-10 py-2 px-3 text-left font-medium text-muted-foreground">#</th>
                  <th className="py-2 px-3 text-left font-medium text-muted-foreground">Template</th>
                  <th className="w-28 py-2 px-3 text-right font-medium text-muted-foreground">Count</th>
                  <th className="w-14 py-2 px-2 text-center font-medium text-muted-foreground" title="Pattern Analyzer">
                    <span className="sr-only">Analyzer</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {singleTemplateTableRows.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-3 py-8 text-center text-muted-foreground">
                      No templates match &quot;{singleTemplateSearch.trim()}&quot;.
                    </td>
                  </tr>
                ) : (
                  singleTemplateTableRows.map((row: { template: string; count: number }, idx: number) => (
                    <tr
                      key={row.template}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelectedTemplate(row.template)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelectedTemplate(row.template);
                        }
                      }}
                      className={cn(
                        "cursor-pointer border-b border-border transition-colors last:border-b-0",
                        selectedTemplate === row.template
                          ? "bg-primary/15 hover:bg-primary/20"
                          : "hover:bg-muted/50",
                      )}
                    >
                      <td className="py-2 px-3 align-top text-muted-foreground tabular-nums">{idx + 1}</td>
                      <td className="py-2 px-3 align-top font-mono text-[11px] break-all">{row.template}</td>
                      <td className="py-2 px-3 align-top text-right font-semibold tabular-nums">{row.count.toLocaleString()}</td>
                      <td className="py-2 px-1 align-top text-center">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(
                              `/workspace/pattern-analyzer?template=${encodeURIComponent(row.template)}&domain=${encodeURIComponent(selectedDomain)}`,
                            );
                          }}
                          title="Open in Pattern Analyzer"
                          className="inline-flex rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        >
                          <ManageSearchIcon style={{ fontSize: 16 }} />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            Sorted by count (high → low). Click a row for trend, dynamic values, and matching log lines.
          </p>
        </div>
      )}

      {selectedTemplate && (<>
        {tsData?.data && tsData.data.length > 0 && (
          <div className="overflow-hidden rounded-2xl border border-border bg-card">
            <div
              className={cn(
                "flex flex-wrap items-center justify-between gap-2 px-4 py-3",
                trendSectionExpanded && "border-b border-border",
              )}
            >
              <button
                type="button"
                onClick={() =>
                  setTrendSectionExpanded((v) => {
                    const next = !v;
                    persistTrendExpanded(next);
                    return next;
                  })
                }
                className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg py-1 pl-1 pr-2 text-left hover:bg-muted/60"
                aria-expanded={trendSectionExpanded}
                aria-controls="pattern-trend-plot-panel"
                id="pattern-trend-toggle"
              >
                <ExpandMoreIcon
                  className={cn("shrink-0 text-muted-foreground transition-transform duration-200", trendSectionExpanded && "rotate-180")}
                  style={{ fontSize: 22 }}
                />
                <h3 className="text-sm font-semibold">Trend ({tsData.freq})</h3>
              </button>
              <div className="flex flex-wrap items-center gap-2">
                <ScheduleIcon style={{ fontSize: 16 }} className="text-muted-foreground" />
                {intervalMarks.map((label, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setTimeInterval(idx)}
                    title={label === "1s" ? "1 second" : label === "1m" ? "1 minute" : label === "1h" ? "1 hour" : "1 day"}
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${timeInterval === idx ? "bg-primary text-primary-foreground" : "border border-border text-muted-foreground hover:bg-muted"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {trendSectionExpanded ? (
              <div id="pattern-trend-plot-panel" className="p-4 pt-2" role="region" aria-labelledby="pattern-trend-toggle">
                <Plot
                  data={[
                    {
                      x: tsData.data.map((d: { timestamp: string }) => d.timestamp),
                      y: tsData.data.map((d: { count: number }) => d.count),
                      type: "scattergl",
                      mode: "lines+markers",
                      marker: { size: 4, color: "#1a73e8" },
                      line: { width: 2 },
                    },
                  ]}
                  layout={mergePlot({
                    height: 300,
                    margin: { l: 40, r: 20, t: 10, b: 30 },
                    hovermode: "closest",
                    font: { family: "Roboto, sans-serif" },
                  })}
                  config={NO_TOOLBAR}
                  style={{ width: "100%" }}
                />
              </div>
            ) : null}
          </div>
        )}

        {params?.parameters && params.parameters.length > 0 && (
          <div className="bg-card border border-border rounded-2xl p-4">
            <h3 className="text-sm font-semibold mb-2">Dynamic Values</h3>
            <div className="min-w-0 overflow-x-auto">
              <table className="w-full table-fixed text-xs">
                <colgroup>
                  <col className="w-40" />
                  <col />
                </colgroup>
                <thead>
                  <tr className="border-b border-border">
                    <th className="whitespace-nowrap py-2 px-3 text-left font-medium text-muted-foreground">Placeholder</th>
                    <th className="min-w-0 py-2 px-3 text-left font-medium text-muted-foreground">Values</th>
                  </tr>
                </thead>
                <tbody>
                  {params.parameters.map((p: { position: string; values: string[] }) => {
                    const title = p.values.map((v) => plainTextWithFormattedMacs(v)).join(", ");
                    return (
                      <tr key={p.position} className="border-b border-border">
                        <td className="whitespace-nowrap py-2 px-3 align-top font-medium">{labelForPosition(p.position, selectedTemplate)}</td>
                        <td className="min-w-0 py-2 px-3 align-top whitespace-normal break-words" title={title}>
                          {p.values.map((v, i) => (
                            <span key={i}>
                              {i > 0 ? <span className="text-muted-foreground">, </span> : null}
                              <DynamicValuesMacRichText raw={v} />
                            </span>
                          ))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {loglines?.lines && loglines.lines.length > 0 && (
          <div className="bg-card border border-border rounded-2xl p-4">
            <h3 className="text-sm font-semibold mb-2">Matching Log Lines ({loglines.total})</h3>
            <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="border-b border-border"><th className="text-left py-2 px-3">Timestamp</th><th className="text-left py-2 px-3">Log Line</th></tr></thead>
              <tbody>{loglines.lines.map((l: { timestamp: string; loglines: string }, idx: number) => <tr key={idx} className="border-b border-border"><td className="py-2 px-3 whitespace-nowrap">{l.timestamp}</td><td className="py-2 px-3 font-mono whitespace-pre-wrap break-all">{l.loglines}</td></tr>)}</tbody></table></div>
          </div>
        )}
      </>)}
      </div>
      )}

      {activeTab === "overview" && (
        <div className="space-y-3">
          {/* Redesigned Header: Fixed height container for perfect alignment */}
          <div className="flex gap-4 h-[180px]">
            {/* Filter Group: Domain & Files combined - 60% */}
            <div className="w-[60%] flex bg-card border border-border rounded-xl overflow-hidden shadow-sm">
              {/* Domain Column */}
              <div className="w-1/2 border-r border-border p-3 flex flex-col bg-muted/10 shrink-0">
                <h3 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <ManageSearchIcon style={{ fontSize: 14 }} /> Domain
                </h3>
                <div className="overflow-y-auto flex-1 custom-scrollbar space-y-1 pr-1">
                  {domains?.map((d: { domain: string; label: string; indexed: boolean }) => (
                    <button
                      key={d.domain}
                      onClick={() => !d.indexed ? null : setSelectedDomain(d.domain)}
                      disabled={!d.indexed}
                      className={`w-full text-left px-2.5 py-1.5 text-xs rounded-md transition-all ${
                        selectedDomain === d.domain
                          ? "bg-primary text-primary-foreground font-medium shadow-sm"
                          : d.indexed
                          ? "hover:bg-background hover:shadow-sm text-foreground"
                          : "opacity-50 cursor-not-allowed"
                      }`}
                    >
                      <div className="truncate">{d.label}</div>
                      {!d.indexed && <div className="text-[9px] opacity-70">(not indexed)</div>}
                    </button>
                  ))}
                </div>
              </div>

              {/* Files Column */}
              <div className="w-1/2 p-3 flex flex-col bg-card min-w-0">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                    <FilterListIcon style={{ fontSize: 14 }} /> 
                    Files {selectedDomain && aggregatedData?.source_files ? `(${aggregatedData.source_files.length})` : ""}
                  </h3>
                  {selectedDomain && aggregatedData?.source_files && aggregatedData.source_files.length > 0 && (
                    <div className="flex items-center gap-1.5">
                      <button 
                        onClick={() => setAggregatedSelectedFiles([...aggregatedData.source_files])} 
                        className="text-[9px] px-1.5 py-0.5 rounded hover:bg-muted text-primary transition-colors"
                      >
                        All
                      </button>
                      <button 
                        onClick={() => setAggregatedSelectedFiles([])} 
                        className="text-[9px] px-1.5 py-0.5 rounded hover:bg-muted text-primary transition-colors"
                      >
                        None
                      </button>
                      {aggregatedFiltersChanged && (
                        <button
                          onClick={() => {
                            setAggregatedAppliedFiles([...aggregatedSelectedFiles]);
                          }}
                          className="ml-1 px-2 py-0.5 text-[9px] bg-primary text-primary-foreground rounded-full font-bold shadow-sm hover:opacity-90 animate-in fade-in zoom-in duration-200"
                        >
                          Apply
                        </button>
                      )}
                    </div>
                  )}
                </div>
                
                <div className="overflow-y-auto flex-1 custom-scrollbar border border-border/50 rounded-lg bg-muted/20 p-1">
                  {selectedDomain && aggregatedData?.source_files && aggregatedData.source_files.length > 0 ? (
                    <div className="space-y-0.5">
                      {aggregatedData.source_files.map((fname) => (
                        <label key={fname} className="flex items-center gap-2 text-[11px] cursor-pointer hover:bg-background hover:shadow-sm rounded px-2 py-1 transition-all" title={fname}>
                          <input 
                            type="checkbox" 
                            checked={aggregatedSelectedFiles.includes(fname)} 
                            onChange={() => toggleAggregatedFile(fname)} 
                            className="accent-primary rounded shrink-0 w-3.5 h-3.5" 
                          />
                          <span className="truncate opacity-90">{fname}</span>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <div className="h-full flex flex-col items-center justify-center text-muted-foreground text-center p-2">
                      <p className="text-xs">
                        {!selectedDomain ? "Select a domain first" : "No source files found"}
                      </p>
                    </div>
                  )}
                </div>
                {aggregatedAppliedFiles.length > 0 && (
                  <div className="mt-1.5 text-[10px] text-muted-foreground font-medium text-right">
                    Showing results for <span className="text-foreground">{aggregatedAppliedFiles.length}</span> file(s)
                  </div>
                )}
              </div>
            </div>

            {/* Stats Section - 40% */}
            <div className="w-[40%] bg-card border border-border rounded-xl shadow-sm p-4 flex flex-col justify-center relative overflow-hidden">
              <div className="absolute top-0 right-0 p-3 opacity-5">
                <BarChartIcon style={{ fontSize: 120 }} />
              </div>
              
              {aggregatedData ? (
                <div className="flex items-center justify-around h-full relative z-10">
                  <div className="text-center group cursor-default">
                    <div className="flex items-center justify-center gap-2 mb-2">
                       <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-full text-blue-600 dark:text-blue-400">
                         <DevicesIcon style={{ fontSize: 24 }} />
                       </div>
                       <div className="text-sm font-medium text-muted-foreground">Total CPEs</div>
                    </div>
                    <div className="text-4xl font-extrabold tracking-tight text-foreground group-hover:scale-110 transition-transform duration-200">
                      {aggregatedData.total_cpes}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">Contributing to this domain</div>
                  </div>
                  
                  <div className="w-px h-24 bg-border/60" />
                  
                  <div className="text-center group cursor-default">
                    <div className="flex items-center justify-center gap-2 mb-2">
                       <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-full text-purple-600 dark:text-purple-400">
                         <BarChartIcon style={{ fontSize: 24 }} />
                       </div>
                       <div className="text-sm font-medium text-muted-foreground">Unique Patterns</div>
                    </div>
                    <div className="text-4xl font-extrabold tracking-tight text-foreground group-hover:scale-110 transition-transform duration-200">
                      {aggregatedData.total_unique_patterns.toLocaleString()}
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">Found across all devices</div>
                  </div>
                </div>
              ) : (
                 <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
                    <ManageSearchIcon style={{ fontSize: 32 }} className="mb-2 opacity-20" />
                    <p>Select a domain to view statistics</p>
                 </div>
              )}
            </div>
          </div>

          {/* Pattern Filter - Always visible */}
          <div className="bg-card border border-border rounded-xl p-3">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <FilterListIcon style={{ fontSize: 18 }} className="text-muted-foreground" />
                <input
                  type="text"
                  value={patternFilter}
                  onChange={(e) => setPatternFilter(e.target.value)}
                  placeholder="Search patterns across all CPEs..."
                  className="flex-1 px-3 py-2 text-sm border border-border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                />
                {patternFilter && (
                  <button
                    onClick={() => {
                      setPatternFilter("");
                    }}
                    className="px-3 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Clear
                  </button>
                )}
              </div>
              <div className="flex items-center gap-2 pl-7">
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={searchAcrossDomains}
                    onChange={(e) => setSearchAcrossDomains(e.target.checked)}
                    className="accent-primary rounded"
                  />
                  <span className="text-muted-foreground">
                    Search across ALL domains
                    {searchAcrossDomains && allDomainsData && ` (${allDomainsData.total_patterns.toLocaleString()} total patterns)`}
                  </span>
                </label>
                {searchAcrossDomains && allDomainsLoading && (
                  <div className="flex items-center gap-1 text-xs text-muted-foreground">
                    <CircularProgress size={12} />
                    Loading patterns from all domains...
                  </div>
                )}
              </div>
            </div>
          </div>

          {!selectedDomain && !searchAcrossDomains ? (
            <div className="bg-card border border-border rounded-2xl p-12 text-center text-muted-foreground">
              <DevicesIcon style={{ fontSize: 48 }} className="mx-auto mb-4 opacity-50" />
              <p className="text-lg">Select a domain to view aggregated patterns across all CPEs</p>
              <p className="text-sm mt-2">Or enable "Search across ALL domains" above</p>
            </div>
          ) : (!selectedDomain && searchAcrossDomains && !patternFilter) ? (
            <div className="bg-card border border-border rounded-2xl p-12 text-center text-muted-foreground">
              <FilterListIcon style={{ fontSize: 48 }} className="mx-auto mb-4 opacity-50" />
              <p className="text-lg">Enter text in the search box to search across all domains</p>
            </div>
          ) : aggregatedLoading ? (
            <div className="bg-card border border-border rounded-2xl p-12 text-center">
              <CircularProgress />
              <p className="text-muted-foreground mt-4">Loading aggregated patterns...</p>
            </div>
          ) : null}

          {/* Always show filter - works even without domain selected if cross-domain search is enabled */}
          {((aggregatedData && selectedDomain) || (searchAcrossDomains && allDomainsPatterns.length > 0)) && (
            <>

              {/* Patterns Table */}
              {(aggregatedData || (searchAcrossDomains && allDomainsPatterns.length > 0)) && (
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <div className="p-3 border-b border-border flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <h3 className="text-sm font-semibold">
                      {searchAcrossDomains ? 'All Domains - Search Results' : 'Patterns'}
                    </h3>
                    {patternFilter && (
                      <span className="text-xs text-muted-foreground">
                        {searchAcrossDomains && allDomainsPatterns.length > 0 ? (
                          <>
                            Showing {allDomainsPatterns.filter(p => 
                              !hiddenPatterns.has(p.template) && 
                              p.template.toLowerCase().includes(patternFilter.toLowerCase())
                            ).length} of {allDomainsData?.total_patterns.toLocaleString()} patterns
                          </>
                        ) : aggregatedData ? (
                          <>
                            Showing {aggregatedData.patterns?.filter(p => 
                              !hiddenPatterns.has(p.template) && 
                              p.template.toLowerCase().includes(patternFilter.toLowerCase())
                            ).length} of {aggregatedData.total_unique_patterns.toLocaleString()} patterns
                          </>
                        ) : null}
                      </span>
                    )}
                    {hiddenPatterns.size > 0 && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">
                          {hiddenPatterns.size} hidden
                        </span>
                        <button
                          onClick={() => setHiddenPatterns(new Set())}
                          className="text-xs text-primary hover:underline"
                        >
                          Show all
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={exportPatterns}
                      title="Export all patterns to CSV (excluding hidden)"
                      className="flex items-center gap-1 px-3 py-1 text-xs bg-primary text-primary-foreground rounded hover:opacity-90"
                    >
                      <DownloadIcon style={{ fontSize: 14 }} />
                      Export CSV
                    </button>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="text-left px-3 py-2 text-xs font-medium w-12">#</th>
                        {searchAcrossDomains && <th className="text-left px-3 py-2 text-xs font-medium">Domain</th>}
                        <th className="text-left px-3 py-2 text-xs font-medium">Pattern Template</th>
                        <th className="text-right px-3 py-2 text-xs font-medium">Frequency</th>
                        <th className="text-right px-3 py-2 text-xs font-medium">CPEs</th>
                        <th className="text-center px-3 py-2 text-xs font-medium w-16">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(() => {
                        // Use cross-domain patterns if enabled, otherwise use current domain patterns
                        const patternsToFilter = searchAcrossDomains && allDomainsPatterns.length > 0
                          ? allDomainsPatterns
                          : aggregatedData?.patterns || [];
                        
                        const filteredPatterns = patternsToFilter
                          .filter(p => !hiddenPatterns.has(p.template))
                          .filter(p => {
                            if (!patternFilter) return true;
                            return p.template.toLowerCase().includes(patternFilter.toLowerCase());
                          });
                        
                        if (filteredPatterns.length === 0 && patternFilter) {
                          return (
                            <tr>
                              <td colSpan={searchAcrossDomains ? 6 : 5} className="px-3 py-8 text-center text-sm text-muted-foreground">
                                <FilterListIcon style={{ fontSize: 24 }} className="mx-auto mb-2 opacity-50" />
                                <div>No patterns match your filter "{patternFilter}"</div>
                                <button
                                  onClick={() => {
                                    setPatternFilter("");
                                  }}
                                  className="mt-2 text-xs text-primary hover:underline"
                                >
                                  Clear filter
                                </button>
                              </td>
                            </tr>
                          );
                        }
                        
                        return filteredPatterns.map((pattern: AggregatedPattern | (AggregatedPattern & { domain: string }), idx: number) => {
                          const patternWithDomain = pattern as AggregatedPattern & { domain?: string };
                          const displayDomain = patternWithDomain.domain || selectedDomain;
                          const totalCpes = searchAcrossDomains 
                            ? allDomainsData?.domains.find(d => d.domain === displayDomain)?.total_cpes || 0
                            : aggregatedData?.total_cpes || 0;
                          
                          return (
                            <tr
                              key={`${displayDomain}-${pattern.template}`}
                              className="border-t border-border hover:bg-muted/30"
                            >
                              <td className="px-3 py-2 text-xs text-muted-foreground">{idx + 1}</td>
                              {searchAcrossDomains && (
                                <td className="px-3 py-2 text-xs">
                                  <span className="px-2 py-0.5 bg-muted rounded text-[10px] font-medium">
                                    {domains?.find((d: { domain: string }) => d.domain === displayDomain)?.label || displayDomain}
                                  </span>
                                </td>
                              )}
                              <td 
                                className="px-3 py-2 font-mono text-[11px] cursor-pointer"
                                onClick={() => setSelectedPatternDetails(pattern)}
                              >
                                {pattern.template}
                              </td>
                              <td className="px-3 py-2 text-right text-xs font-semibold">
                                {pattern.occurrence_count.toLocaleString()}
                              </td>
                              <td className="px-3 py-2 text-right text-xs">
                                {pattern.cpe_count} / {totalCpes}
                              </td>
                              <td className="px-3 py-2 text-center">
                                <div className="flex items-center justify-center gap-1">
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      navigate(`/workspace/pattern-analyzer?template=${encodeURIComponent(pattern.template)}&domain=${encodeURIComponent(displayDomain)}`);
                                    }}
                                    className="p-1 hover:bg-muted rounded"
                                    title="Add to Pattern Analyzer"
                                  >
                                    <ManageSearchIcon style={{ fontSize: 14 }} className="text-muted-foreground" />
                                  </button>
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      toggleHidePattern(pattern.template);
                                    }}
                                    className="p-1 hover:bg-muted rounded"
                                    title="Hide pattern"
                                  >
                                    <VisibilityOffIcon style={{ fontSize: 14 }} className="text-muted-foreground" />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        });
                      })()}
                    </tbody>
                  </table>
                </div>
              </div>
              )}

              {/* CPE Details Modal */}
              {selectedPatternDetails && (
                <div 
                  className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
                  onClick={() => setSelectedPatternDetails(null)}
                >
                  <div 
                    className="bg-card border border-border rounded-xl max-w-4xl w-full max-h-[80vh] overflow-hidden flex flex-col"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="p-4 border-b border-border flex items-start justify-between">
                      <div className="flex-1 mr-4">
                        <h3 className="text-sm font-semibold mb-2">Pattern Details</h3>
                        <p className="font-mono text-[11px] bg-muted p-2 rounded break-all">
                          {selectedPatternDetails.template}
                        </p>
                        <div className="flex flex-wrap items-center gap-3 mt-3">
                          <div className="flex gap-4 text-xs">
                            <div>
                              <span className="text-muted-foreground">Total Occurrences:</span>{" "}
                              <strong>{selectedPatternDetails.occurrence_count.toLocaleString()}</strong>
                            </div>
                            <div>
                              <span className="text-muted-foreground">CPEs with pattern:</span>{" "}
                              <strong>{selectedPatternDetails.cpe_count}</strong>
                            </div>
                          </div>
                          <button
                            onClick={() => {
                              const domain = searchAcrossDomains 
                                ? (selectedPatternDetails as any).domain || selectedDomain
                                : selectedDomain;
                              navigate(`/workspace/pattern-analyzer?template=${encodeURIComponent(selectedPatternDetails.template)}&domain=${encodeURIComponent(domain)}`);
                            }}
                            className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg border border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100 dark:border-blue-700 dark:bg-blue-900/20 dark:text-blue-400 transition-colors"
                          >
                            <ManageSearchIcon style={{ fontSize: 14 }} /> Add to Pattern Analyzer
                          </button>
                        </div>
                      </div>
                      <button
                        onClick={() => setSelectedPatternDetails(null)}
                        title="Close"
                        className="text-muted-foreground hover:text-foreground p-1"
                      >
                        <CloseIcon style={{ fontSize: 20 }} />
                      </button>
                    </div>
                    
                    <div className="flex-1 overflow-auto p-4">
                      {/* Sample Logs Section - Moved above CPE table */}
                      {sampleLogs && sampleLogs.samples.length > 0 && (
                        <div className="mb-6">
                          <h4 className="text-xs font-semibold mb-2 text-muted-foreground uppercase">
                            Sample Log Lines ({sampleLogs.samples[0].cpe_serial}
                            {sampleLogs.samples[0].filename && ` - ${sampleLogs.samples[0].filename}`})
                          </h4>
                          <div className="bg-slate-900 text-slate-200 rounded-lg p-3 space-y-1">
                            {sampleLogs.samples.map((sample, idx) => (
                              <div key={idx} className="border-b border-slate-800 last:border-b-0 pb-1 last:pb-0 mb-1 last:mb-0">
                                <div className="text-[10px] text-slate-500 mb-0.5">{sample.timestamp}</div>
                                <div className="font-mono text-[11px] whitespace-pre-wrap break-all">{sample.logline}</div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <h4 className="text-xs font-semibold mb-3 text-muted-foreground uppercase">
                        CPEs with this Pattern
                      </h4>
                      <div className="overflow-x-auto">
                        <table className="w-full">
                          <thead className="bg-muted/50">
                            <tr>
                              <th className="text-left px-3 py-2 text-xs font-medium w-12">#</th>
                              <th className="text-left px-3 py-2 text-xs font-medium">CPE Serial</th>
                              <th className="text-right px-3 py-2 text-xs font-medium">Occurrences</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(selectedPatternDetails.cpe_details)
                              .sort(([, a], [, b]) => b - a)
                              .map(([serial, count], idx) => (
                                <tr key={serial} className="border-t border-border hover:bg-muted/30">
                                  <td className="px-3 py-2 text-xs text-muted-foreground">{idx + 1}</td>
                                  <td className="px-3 py-2 font-mono text-xs">{serial}</td>
                                  <td className="px-3 py-2 text-right text-xs font-semibold">
                                    {count.toLocaleString()}
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

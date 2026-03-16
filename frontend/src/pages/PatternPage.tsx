import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { patternsApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import Plot from "react-plotly.js";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CircularProgress from "@mui/material/CircularProgress";
import FilterListIcon from "@mui/icons-material/FilterList";
import ScheduleIcon from "@mui/icons-material/Schedule";
import BarChartIcon from "@mui/icons-material/BarChart";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import SelectAllIcon from "@mui/icons-material/SelectAll";
import DeselectIcon from "@mui/icons-material/Deselect";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import DevicesIcon from "@mui/icons-material/Devices";
import PersonIcon from "@mui/icons-material/Person";
import CloseIcon from "@mui/icons-material/Close";
import DownloadIcon from "@mui/icons-material/Download";
import VisibilityOffIcon from "@mui/icons-material/VisibilityOff";

const NO_TOOLBAR = { displayModeBar: false } as const;

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
  const [selectedDomain, setSelectedDomain] = useState<string>("");
  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  const [timeInterval, setTimeInterval] = useState(0);
  const [viewMode, setViewMode] = useState<"single" | "aggregated">("single");
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
  const [showFileFilter, setShowFileFilter] = useState(false);
  const [allSourceFiles, setAllSourceFiles] = useState<string[]>([]);

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
    setShowFileFilter(false);
    setAllSourceFiles([]);
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
    enabled: !!projectId && !!selectedDomain && viewMode === "aggregated" && !searchAcrossDomains,
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
    enabled: !!projectId && viewMode === "aggregated" && searchAcrossDomains,
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
      let filename = 'patterns-export.xlsx';
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

  // Reset when switching view modes or changing domain in aggregated view
  useEffect(() => {
    if (viewMode === "aggregated") {
      setAggregatedSelectedFiles([]);
      setAggregatedAppliedFiles([]);
      setPatternFilter("");
      setSearchAcrossDomains(false);
    }
  }, [selectedDomain, viewMode]);

  return (
    <div className="p-4 space-y-3 max-w-full">
      {/* View Mode Toggle - Modernized and Compact */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold">Pattern Analysis</h2>
          {viewMode === "aggregated" && projectId && (
            <button
              onClick={handleGlobalExport}
              title="Export all domains to Excel with index (grouped by file)"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
            >
              <DownloadIcon style={{ fontSize: 14 }} />
              Export ALL
            </button>
          )}
        </div>
        <div className="inline-flex items-center bg-muted rounded-lg p-0.5 gap-0.5">
          <button
            onClick={() => setViewMode("single")}
            title="Analyze patterns for a single CPE"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              viewMode === "single"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <PersonIcon style={{ fontSize: 16 }} />
            Single CPE
          </button>
          <button
            onClick={() => setViewMode("aggregated")}
            title="Aggregate patterns across all CPEs in this project"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              viewMode === "aggregated"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <DevicesIcon style={{ fontSize: 16 }} />
            All CPEs
          </button>
        </div>
      </div>

      {viewMode === "single" ? (
        // SINGLE CPE VIEW (existing code)
      <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Domain + File filter */}
        <div className="bg-card border border-border rounded-2xl p-4 space-y-3">
          <h3 className="text-sm font-semibold flex items-center gap-1.5"><BarChartIcon style={{ fontSize: 18, color: "#1a73e8" }} /> Domain</h3>
          <select value={selectedDomain} onChange={(e) => setSelectedDomain(e.target.value)} title="Choose log domain to analyze" className="w-full px-3 py-2 text-sm border border-input rounded-lg bg-background">
            <option value="">Select a domain...</option>
            {domains?.map((d: { domain: string; label: string; indexed: boolean }) => (
              <option key={d.domain} value={d.domain} disabled={!d.indexed}>{d.label}{d.indexed ? "" : " (not indexed)"}</option>
            ))}
          </select>

          {/* File filter */}
          {selectedDomain && domainSourceFiles.length > 0 && (
            <div className="space-y-1">
              <button onClick={() => setShowFileFilter(!showFileFilter)} title="Filter pattern analysis by selected log files" className="flex items-center gap-1.5 text-xs text-primary hover:underline">
                <FilterListIcon style={{ fontSize: 16 }} />
                {showFileFilter ? "Hide" : "Filter"} Files
                {appliedFiles.length > 0 && <span className="ml-1 bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full text-[10px] font-bold">{appliedFiles.length}/{domainSourceFiles.length}</span>}
              </button>
              {showFileFilter && (
                <div className="border border-border rounded-lg p-2 max-h-48 overflow-y-auto custom-scrollbar bg-muted/30 space-y-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">Files ({domainSourceFiles.length})</span>
                    <div className="flex items-center gap-2">
                      <button onClick={() => setSelectedFiles([...domainSourceFiles])} title="Select all files" className="flex items-center gap-0.5 text-[10px] text-primary hover:underline"><SelectAllIcon style={{ fontSize: 12 }} /> All</button>
                      <button onClick={() => setSelectedFiles([])} title="Deselect all files" className="flex items-center gap-0.5 text-[10px] text-primary hover:underline"><DeselectIcon style={{ fontSize: 12 }} /> None</button>
                    </div>
                  </div>
                  {domainSourceFiles.map((fname) => (
                    <label key={fname} className="flex items-center gap-2 text-xs cursor-pointer hover:bg-muted rounded px-1 py-0.5" title={fname}>
                      <input type="checkbox" checked={selectedFiles.includes(fname)} onChange={() => toggleFile(fname)} className="accent-primary rounded" />
                      <span className="truncate">{fname}</span>
                    </label>
                  ))}
                  {/* Apply button */}
                  <button
                    onClick={() => setAppliedFiles([...selectedFiles])}
                    disabled={!filtersChanged}
                    title="Apply file filter"
                    className={`mt-1.5 w-full flex items-center justify-center gap-1 px-2 py-1.5 text-xs rounded-lg font-medium transition-colors ${filtersChanged ? "bg-primary text-primary-foreground hover:opacity-90" : "bg-muted text-muted-foreground cursor-default"}`}>
                    <PlayArrowIcon style={{ fontSize: 14 }} /> Apply Filter
                  </button>
                </div>
              )}
            </div>
          )}

          {analysisLoading && selectedDomain && <div className="flex items-center gap-2 text-xs text-muted-foreground"><CircularProgress size={14} /> Analyzing {selectedDomain}...</div>}
          {analysisError && <div className="flex items-center gap-1.5 text-xs text-destructive"><ErrorOutlineIcon style={{ fontSize: 15 }} />{(analysisErr as { response?: { data?: { error?: string } } })?.response?.data?.error || "Analysis failed"}</div>}
        </div>

        {/* Summary + Index Status */}
        <div className="bg-card border border-border rounded-2xl p-4">
          <h3 className="text-sm font-semibold mb-2">Summary</h3>
          {summary ? (
            <div className="text-sm space-y-1">
              <p>Total Log Lines: <strong>{summary.total_loglines.toLocaleString()}</strong></p>
              <p>Unique Patterns: <strong>{summary.total_patterns.toLocaleString()}</strong></p>
              {appliedFiles.length > 0 && <p className="text-xs text-muted-foreground">Filtered to {appliedFiles.length} file(s)</p>}
            </div>
          ) : <p className="text-sm text-muted-foreground">{selectedDomain ? "Loading..." : "Select a domain to analyze"}</p>}
          <div className="mt-4">
            <h4 className="text-xs font-medium mb-2">Indexed Domains</h4>
            <div className="flex flex-wrap gap-1.5">
              {indexStatus?.domains && Object.entries(indexStatus.domains).map(([key, val]: [string, unknown]) => {
                const d = val as { indexed: boolean; label: string };
                return <span key={key} title={d.indexed ? "Domain indexed and ready for analysis" : "Indexing in progress..."} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${d.indexed ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400" : "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"}`}>{d.indexed ? <CheckCircleIcon style={{ fontSize: 14 }} /> : <CircularProgress size={12} />}{d.label}</span>;
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Frequency Chart */}
      {chartData && chartData.length > 0 && (
        <div className="bg-card border border-border rounded-2xl p-4">
          <h3 className="text-sm font-semibold mb-2">Template Frequency ({chartData.length} patterns)</h3>
          <Plot
            data={[{ x: chartData.map((_: unknown, i: number) => i), y: chartData.map((d: { count: number }) => d.count), type: "bar", hovertext: chartData.map((d: { template: string }) => d.template), marker: { color: "#1a73e8" } }]}
            layout={{ height: 350, margin: { l: 50, r: 20, t: 10, b: 40 }, xaxis: { title: { text: "Log Pattern" } }, yaxis: { title: { text: "Occurrence (Log Scale)" }, type: "log" }, hovermode: "closest", paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { family: "Roboto, sans-serif" } }}
            config={NO_TOOLBAR} style={{ width: "100%" }}
            onClick={(data) => { setSelectedTemplate(chartData[data.points[0].pointIndex].template); }}
          />
          <p className="text-[11px] text-muted-foreground mt-1">Click a bar to inspect the pattern</p>
        </div>
      )}

      {selectedTemplate && (<>
        <div className="bg-card border border-border rounded-2xl p-4">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-semibold">Selected Template</h3>
            <button
              onClick={() => navigate(`/workspace/pattern-analyzer?template=${encodeURIComponent(selectedTemplate)}&domain=${encodeURIComponent(selectedDomain)}`)}
              title="Open in Pattern Analyzer for detailed analysis"
              className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg border border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100 dark:border-blue-700 dark:bg-blue-900/20 dark:text-blue-400 transition-colors"
            >
              <ManageSearchIcon style={{ fontSize: 14 }} /> Add to Pattern Analyzer
            </button>
          </div>
          <p className="text-xs font-mono bg-muted p-2 rounded-lg break-all">{selectedTemplate}</p>
        </div>

        {tsData?.data && tsData.data.length > 0 && (
          <div className="bg-card border border-border rounded-2xl p-4">
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <h3 className="text-sm font-semibold">Trend ({tsData.freq})</h3>
              <div className="flex items-center gap-2">
                <ScheduleIcon style={{ fontSize: 16 }} className="text-muted-foreground" />
                {intervalMarks.map((label, idx) => <button key={idx} onClick={() => setTimeInterval(idx)} title={label === "1s" ? "1 second" : label === "1m" ? "1 minute" : label === "1h" ? "1 hour" : "1 day"} className={`px-2.5 py-1 text-xs rounded-lg font-medium transition-colors ${timeInterval === idx ? "bg-primary text-primary-foreground" : "border border-border hover:bg-muted text-muted-foreground"}`}>{label}</button>)}
              </div>
            </div>
            <Plot data={[{ x: tsData.data.map((d: { timestamp: string }) => d.timestamp), y: tsData.data.map((d: { count: number }) => d.count), type: "scattergl", mode: "lines+markers", marker: { size: 4, color: "#1a73e8" }, line: { width: 2 } }]}
              layout={{ height: 300, margin: { l: 40, r: 20, t: 10, b: 30 }, hovermode: "closest", paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: { family: "Roboto, sans-serif" } }}
              config={NO_TOOLBAR} style={{ width: "100%" }} />
          </div>
        )}

        {params?.parameters && params.parameters.length > 0 && (
          <div className="bg-card border border-border rounded-2xl p-4">
            <h3 className="text-sm font-semibold mb-2">Dynamic Values</h3>
            <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="border-b border-border"><th className="text-left py-2 px-3">Position</th><th className="text-left py-2 px-3">Count</th><th className="text-left py-2 px-3">Values</th></tr></thead>
              <tbody>{params.parameters.map((p: { position: string; count: number; values: string[] }) => <tr key={p.position} className="border-b border-border"><td className="py-2 px-3 font-medium">{p.position}</td><td className="py-2 px-3">{p.count}</td><td className="py-2 px-3 max-w-md truncate" title={p.values.join(", ")}>{p.values.join(", ")}</td></tr>)}</tbody></table></div>
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
      ) : (
        // AGGREGATED VIEW (All CPEs)
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

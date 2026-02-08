import { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { patternsApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
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

const NO_TOOLBAR = { displayModeBar: false } as const;

export default function PatternPage() {
  const { projectId } = useProject();
  const [selectedDomain, setSelectedDomain] = useState<string>("");
  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  const [timeInterval, setTimeInterval] = useState(0);

  // File filter: user picks files, then clicks "Apply" to trigger re-analysis
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [appliedFiles, setAppliedFiles] = useState<string[]>([]);
  const [showFileFilter, setShowFileFilter] = useState(false);
  // Keep a stable copy of domain source files from the INITIAL (unfiltered) analysis
  const allSourceFilesRef = useRef<string[]>([]);

  const { data: domains } = useQuery({ queryKey: ["domains", projectId], queryFn: async () => (await patternsApi.listDomains(projectId!)).data, enabled: !!projectId });
  const { data: indexStatus } = useQuery({ queryKey: ["indexingStatus", projectId], queryFn: async () => (await patternsApi.indexingStatus(projectId!)).data, enabled: !!projectId, refetchInterval: (query) => (query.state.data?.all_done ? false : 5000) });

  // Analysis — triggered by domain + appliedFiles (not selectedFiles)
  const { data: analysisRaw, isLoading: analysisLoading, isError: analysisError, error: analysisErr } = useQuery({
    queryKey: ["analyze", projectId, selectedDomain, appliedFiles],
    queryFn: async () => (await patternsApi.analyze(projectId!, selectedDomain, appliedFiles.length > 0 ? appliedFiles : undefined)).data,
    enabled: !!projectId && !!selectedDomain,
    retry: false,
  });

  const chartData = analysisRaw?.chart_data;
  const summary = analysisRaw?.summary;

  // Populate allSourceFilesRef from UNFILTERED analysis response
  useEffect(() => {
    if (analysisRaw?.source_files && appliedFiles.length === 0) {
      allSourceFilesRef.current = analysisRaw.source_files;
    }
  }, [analysisRaw, appliedFiles]);

  const domainSourceFiles = allSourceFilesRef.current;
  const fileFilterStr = appliedFiles.length > 0 ? appliedFiles.join(",") : undefined;

  // Reset when domain changes
  useEffect(() => {
    setSelectedTemplate("");
    setSelectedFiles([]);
    setAppliedFiles([]);
    setShowFileFilter(false);
    allSourceFilesRef.current = [];
  }, [selectedDomain]);

  const { data: tsData } = useQuery({ queryKey: ["timeseries", projectId, selectedDomain, selectedTemplate, timeInterval, fileFilterStr], queryFn: async () => (await patternsApi.getTimeseries(projectId!, selectedDomain, selectedTemplate, timeInterval, fileFilterStr)).data, enabled: !!projectId && !!selectedDomain && !!selectedTemplate });
  const { data: params } = useQuery({ queryKey: ["parameters", projectId, selectedDomain, selectedTemplate, fileFilterStr], queryFn: async () => (await patternsApi.getParameters(projectId!, selectedDomain, selectedTemplate, fileFilterStr)).data, enabled: !!projectId && !!selectedDomain && !!selectedTemplate });
  const { data: loglines } = useQuery({ queryKey: ["loglines", projectId, selectedDomain, selectedTemplate, fileFilterStr], queryFn: async () => (await patternsApi.getLoglines(projectId!, selectedDomain, selectedTemplate, 1, 20, fileFilterStr)).data, enabled: !!projectId && !!selectedDomain && !!selectedTemplate });

  const intervalMarks = ["1s", "1min", "1h", "1d"];
  const toggleFile = (f: string) => setSelectedFiles((p) => p.includes(f) ? p.filter((x) => x !== f) : [...p, f]);
  const filtersChanged = JSON.stringify(selectedFiles.sort()) !== JSON.stringify(appliedFiles.sort());

  return (
    <div className="p-4 space-y-4 max-w-full">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Domain + File filter */}
        <div className="bg-card border border-border rounded-2xl p-4 space-y-3">
          <h3 className="text-sm font-semibold flex items-center gap-1.5"><BarChartIcon style={{ fontSize: 18, color: "#1a73e8" }} /> Domain</h3>
          <select value={selectedDomain} onChange={(e) => setSelectedDomain(e.target.value)} className="w-full px-3 py-2 text-sm border border-input rounded-lg bg-background">
            <option value="">Select a domain...</option>
            {domains?.map((d: { domain: string; label: string; indexed: boolean }) => (
              <option key={d.domain} value={d.domain} disabled={!d.indexed}>{d.label}{d.indexed ? "" : " (not indexed)"}</option>
            ))}
          </select>

          {/* File filter */}
          {selectedDomain && domainSourceFiles.length > 0 && (
            <div className="space-y-1">
              <button onClick={() => setShowFileFilter(!showFileFilter)} className="flex items-center gap-1.5 text-xs text-primary hover:underline">
                <FilterListIcon style={{ fontSize: 16 }} />
                {showFileFilter ? "Hide" : "Filter"} Files
                {appliedFiles.length > 0 && <span className="ml-1 bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full text-[10px] font-bold">{appliedFiles.length}/{domainSourceFiles.length}</span>}
              </button>
              {showFileFilter && (
                <div className="border border-border rounded-lg p-2 max-h-48 overflow-y-auto custom-scrollbar bg-muted/30 space-y-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">Files ({domainSourceFiles.length})</span>
                    <div className="flex items-center gap-2">
                      <button onClick={() => setSelectedFiles([...domainSourceFiles])} className="flex items-center gap-0.5 text-[10px] text-primary hover:underline"><SelectAllIcon style={{ fontSize: 12 }} /> All</button>
                      <button onClick={() => setSelectedFiles([])} className="flex items-center gap-0.5 text-[10px] text-primary hover:underline"><DeselectIcon style={{ fontSize: 12 }} /> None</button>
                    </div>
                  </div>
                  {domainSourceFiles.map((fname) => (
                    <label key={fname} className="flex items-center gap-2 text-xs cursor-pointer hover:bg-muted rounded px-1 py-0.5">
                      <input type="checkbox" checked={selectedFiles.includes(fname)} onChange={() => toggleFile(fname)} className="accent-primary rounded" />
                      <span className="truncate">{fname}</span>
                    </label>
                  ))}
                  {/* Apply button */}
                  <button
                    onClick={() => setAppliedFiles([...selectedFiles])}
                    disabled={!filtersChanged}
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
                return <span key={key} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${d.indexed ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400" : "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"}`}>{d.indexed ? <CheckCircleIcon style={{ fontSize: 14 }} /> : <CircularProgress size={12} />}{d.label}</span>;
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
          <h3 className="text-sm font-semibold mb-1">Selected Template</h3>
          <p className="text-xs font-mono bg-muted p-2 rounded-lg break-all">{selectedTemplate}</p>
        </div>

        {tsData?.data && tsData.data.length > 0 && (
          <div className="bg-card border border-border rounded-2xl p-4">
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <h3 className="text-sm font-semibold">Trend ({tsData.freq})</h3>
              <div className="flex items-center gap-2">
                <ScheduleIcon style={{ fontSize: 16 }} className="text-muted-foreground" />
                {intervalMarks.map((label, idx) => <button key={idx} onClick={() => setTimeInterval(idx)} className={`px-2.5 py-1 text-xs rounded-lg font-medium transition-colors ${timeInterval === idx ? "bg-primary text-primary-foreground" : "border border-border hover:bg-muted text-muted-foreground"}`}>{label}</button>)}
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
              <tbody>{params.parameters.map((p: { position: string; count: number; values: string[] }) => <tr key={p.position} className="border-b border-border"><td className="py-2 px-3 font-medium">{p.position}</td><td className="py-2 px-3">{p.count}</td><td className="py-2 px-3 max-w-md truncate">{p.values.join(", ")}</td></tr>)}</tbody></table></div>
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
  );
}

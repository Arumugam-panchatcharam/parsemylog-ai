import { useState, useRef, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { aiApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import { highlightLogLine } from "@/lib/logHighlighter";
import SearchIcon from "@mui/icons-material/Search";
import TextIncreaseIcon from "@mui/icons-material/TextIncrease";
import TextDecreaseIcon from "@mui/icons-material/TextDecrease";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import PsychologyIcon from "@mui/icons-material/Psychology";
import CircularProgress from "@mui/material/CircularProgress";
import FormatColorTextIcon from "@mui/icons-material/FormatColorText";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";

interface SearchResult { filename: string; template: string; frequency: number; similarity: number; domain: string; parquet_path: string; }

export default function AIAnalysisPage() {
  const { projectId } = useProject();
  const { cpeId } = useCPE();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [timeWindow, setTimeWindow] = useState(5);
  const [timeUnit, setTimeUnit] = useState<"seconds" | "minutes">("seconds");
  const [syntaxHL, setSyntaxHL] = useState(true);
  const [fontSize, setFontSize] = useState(12);
  const contextRef = useRef<HTMLDivElement>(null);

  const [searchMsg, setSearchMsg] = useState<string | null>(null);
  const searchMutation = useMutation({
    mutationFn: () => aiApi.search(projectId!, query, 10, cpeId),
    onSuccess: (res) => {
      setResults(res.data.results || []);
      setSelectedIdx(null);
      setSearchMsg(res.data.error || null);
    },
  });
  const selected = selectedIdx !== null ? results[selectedIdx] : null;
  const { data: params } = useQuery({ queryKey: ["aiParams", projectId, selected?.template, selected?.parquet_path, cpeId], queryFn: async () => (await aiApi.getParameters(projectId!, { template: selected!.template, parquet_path: selected!.parquet_path, domain: selected!.domain, cpe_id: cpeId })).data, enabled: !!projectId && !!selected });
  const { data: loglines } = useQuery({ queryKey: ["aiLoglines", projectId, selected?.template, selected?.parquet_path, cpeId], queryFn: async () => (await aiApi.getLoglines(projectId!, { template: selected!.template, parquet_path: selected!.parquet_path, domain: selected!.domain, cpe_id: cpeId })).data, enabled: !!projectId && !!selected });
  const [selectedLogIdx, setSelectedLogIdx] = useState<number | null>(null);
  const selectedLog = selectedLogIdx !== null && loglines?.lines ? loglines.lines[selectedLogIdx] : null;
  const { data: context } = useQuery({ queryKey: ["aiContext", projectId, selected?.template, selectedLog?.timestamp, timeWindow, timeUnit, cpeId], queryFn: async () => (await aiApi.getContext(projectId!, { template: selected!.template, timestamp: selectedLog!.timestamp, window: timeWindow, unit: timeUnit, filename: selected!.filename, parquet_path: selected!.parquet_path, cpe_id: cpeId })).data, enabled: !!projectId && !!selected && !!selectedLog });
  useEffect(() => { if (contextRef.current) contextRef.current.scrollTop = contextRef.current.scrollHeight; }, [context]);

  const handleSearch = () => { if (query.trim()) searchMutation.mutate(); };
  const hl = (text: string, search?: string) => syntaxHL ? highlightLogLine(text, search) : (search ? highlightLogLine(text, search) : text);

  return (
    <div className="p-4 space-y-4 max-w-full flex flex-col" style={{ minHeight: "calc(100vh - 2rem)" }}>
      {/* Search Bar */}
      <div className="bg-card border border-border rounded-2xl p-4">
        <div className="flex items-center gap-3">
          <PsychologyIcon style={{ fontSize: 22, color: "#1a73e8" }} />
          <h2 className="text-sm font-semibold shrink-0">Semantic Search</h2>
          <div className="flex-1 flex items-center gap-2 border border-input rounded-lg px-3 py-1.5 bg-background focus-within:ring-2 focus-within:ring-ring">
            <SearchIcon style={{ fontSize: 18 }} className="text-muted-foreground shrink-0" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleSearch()} placeholder="Describe the log pattern you're looking for..." className="flex-1 bg-transparent outline-none text-sm min-w-0" />
            {searchMutation.isPending && <CircularProgress size={16} />}
          </div>
          <button onClick={handleSearch} disabled={searchMutation.isPending || !query.trim()} className="px-4 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 disabled:opacity-40 shrink-0">Search</button>
        </div>
      </div>

      {searchMutation.isError && <div className="p-3 bg-destructive/10 text-destructive rounded-lg text-sm">{(searchMutation.error as { response?: { data?: { error?: string } } })?.response?.data?.error || "Search failed"}</div>}
      {searchMsg && <div className="p-3 bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800 rounded-lg text-sm">{searchMsg}</div>}

      {/* Results */}
      {results.length > 0 && (
        <div className="bg-card border border-border rounded-2xl p-4">
          <h3 className="text-sm font-semibold mb-2">Results ({results.length} patterns)</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-border text-left"><th className="py-2 px-3">Filename</th><th className="py-2 px-3">Template</th><th className="py-2 px-3 text-center">Freq</th><th className="py-2 px-3 text-center">Score</th><th className="py-2 px-3 text-center w-10"></th></tr></thead>
              <tbody>{results.map((r, idx) => (
                <tr key={idx} onClick={() => { setSelectedIdx(idx); setSelectedLogIdx(null); }} className={`border-b border-border cursor-pointer transition-colors ${selectedIdx === idx ? "bg-accent" : "hover:bg-muted"}`}>
                  <td className="py-2 px-3">{r.filename}</td><td className="py-2 px-3 font-mono max-w-md truncate">{r.template}</td>
                  <td className="py-2 px-3 text-center">{r.frequency}</td><td className={`py-2 px-3 text-center font-medium ${r.similarity >= 0.8 ? "text-green-600" : r.similarity < 0.5 ? "text-muted-foreground" : ""}`}>{r.similarity}</td>
                  <td className="py-2 px-3 text-center"><button onClick={(e) => { e.stopPropagation(); const domain = r.domain?.trim(); navigate(`/workspace/pattern-analyzer?template=${encodeURIComponent(r.template)}${domain ? `&domain=${encodeURIComponent(domain)}` : ""}`); }} title="Add to Pattern Analyzer" className="p-1 rounded hover:bg-blue-100 dark:hover:bg-blue-900/20 text-muted-foreground hover:text-blue-600 transition-colors"><ManageSearchIcon style={{ fontSize: 16 }} /></button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      )}

      {/* Parameters */}
      {params?.parameters && params.parameters.length > 0 && (
        <div className="bg-card border border-border rounded-2xl p-4">
          <h3 className="text-sm font-semibold mb-2">Parameters</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs"><thead><tr className="border-b border-border"><th className="text-left py-2 px-3">Position</th><th className="text-left py-2 px-3">Count</th><th className="text-left py-2 px-3">Values</th></tr></thead>
              <tbody>{params.parameters.map((p: { position: string; count: number; values: string[] }) => (<tr key={p.position} className="border-b border-border"><td className="py-2 px-3 font-medium">{p.position}</td><td className="py-2 px-3">{p.count}</td><td className="py-2 px-3 max-w-md truncate">{p.values.join(", ")}</td></tr>))}</tbody>
            </table>
          </div>
        </div>
      )}

      {/* Matching Log Lines */}
      {loglines?.lines && loglines.lines.length > 0 && (
        <div className="bg-card border border-border rounded-2xl p-4">
          <h3 className="text-sm font-semibold mb-2">Matching Log Lines ({loglines.total})</h3>
          <div className="overflow-x-auto bg-slate-900 rounded-lg">
            <table className="w-full text-xs text-slate-200">
              <thead><tr className="border-b border-slate-700"><th className="text-left py-2 px-3 text-slate-400">Timestamp</th><th className="text-left py-2 px-3 text-slate-400">Log Line</th></tr></thead>
              <tbody>{loglines.lines.map((l: { timestamp: string; loglines: string }, idx: number) => (
                <tr key={idx} onClick={() => setSelectedLogIdx(idx)} className={`border-b border-slate-800 cursor-pointer ${selectedLogIdx === idx ? "bg-slate-700/50" : "hover:bg-slate-800/50"}`}>
                  <td className="py-2 px-3 whitespace-nowrap font-mono text-slate-400">{l.timestamp}</td>
                  <td className="py-2 px-3 font-mono whitespace-pre-wrap break-all">{hl(l.loglines, query)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      )}

      <div className="flex-1" />

      {/* Log Context */}
      {selectedLog && (
        <div className="bg-card border border-border rounded-2xl p-4">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h3 className="text-sm font-semibold">Log Context</h3>
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-1.5">
                <AccessTimeIcon style={{ fontSize: 15 }} className="text-muted-foreground" />
                {(["seconds", "minutes"] as const).map((u) => (
                  <button key={u} onClick={() => setTimeUnit(u)} className={`px-2 py-1 text-xs rounded-lg font-medium ${timeUnit === u ? "bg-primary text-primary-foreground" : "border border-border hover:bg-muted"}`}>{u}</button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <input type="range" min={timeUnit === "seconds" ? 5 : 1} max={timeUnit === "seconds" ? 60 : 10} step={timeUnit === "seconds" ? 5 : 1} value={timeWindow} onChange={(e) => setTimeWindow(Number(e.target.value))} className="w-20 accent-primary" />
                <span className="text-xs font-medium w-10">{timeWindow}{timeUnit === "seconds" ? "s" : "min"}</span>
              </div>
              <button onClick={() => setSyntaxHL(!syntaxHL)} className={`flex items-center gap-1 px-2 py-1 text-xs rounded-lg font-medium ${syntaxHL ? "bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-300" : "border border-border hover:bg-muted text-muted-foreground"}`}>
                <FormatColorTextIcon style={{ fontSize: 13 }} /> Syntax
              </button>
              <div className="flex items-center gap-1">
                <button onClick={() => setFontSize((s) => Math.max(8, s - 1))} className="p-1 rounded hover:bg-muted"><TextDecreaseIcon style={{ fontSize: 15 }} /></button>
                <span className="text-[10px] text-muted-foreground w-5 text-center">{fontSize}</span>
                <button onClick={() => setFontSize((s) => Math.min(20, s + 1))} className="p-1 rounded hover:bg-muted"><TextIncreaseIcon style={{ fontSize: 15 }} /></button>
              </div>
            </div>
          </div>
          <div ref={contextRef} className="bg-slate-900 text-slate-200 rounded-lg p-3 log-viewer overflow-auto max-h-[500px] log-scroll" style={{ fontSize: `${fontSize}px` }}>
            {context?.lines?.map((l: { timestamp: string; loglines: string; is_match: boolean }, idx: number) => (
              <div key={idx} className={`whitespace-pre-wrap ${l.is_match ? "bg-amber-700/20 rounded px-1" : ""}`}>
                <span className="text-slate-500 mr-2">{l.timestamp}</span>
                {hl(l.loglines, query)}
              </div>
            ))}
            {!context?.lines?.length && <p className="text-slate-400">Select a log line above to view context</p>}
          </div>
        </div>
      )}
    </div>
  );
}

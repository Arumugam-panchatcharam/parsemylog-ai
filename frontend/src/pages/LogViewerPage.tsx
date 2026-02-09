import { useState, useCallback, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import { filesApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { cn } from "@/lib/utils";
import { highlightLogLine } from "@/lib/logHighlighter";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import DescriptionIcon from "@mui/icons-material/Description";
import DownloadIcon from "@mui/icons-material/Download";
import SearchIcon from "@mui/icons-material/Search";
import RefreshIcon from "@mui/icons-material/Refresh";
import FirstPageIcon from "@mui/icons-material/FirstPage";
import LastPageIcon from "@mui/icons-material/LastPage";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import SaveIcon from "@mui/icons-material/Save";
import TextIncreaseIcon from "@mui/icons-material/TextIncrease";
import TextDecreaseIcon from "@mui/icons-material/TextDecrease";
import NoteAltIcon from "@mui/icons-material/NoteAlt";
import CloseIcon from "@mui/icons-material/Close";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
import FormatColorTextIcon from "@mui/icons-material/FormatColorText";

const LINES_OPTIONS = [100, 500, 1000, 2000, 5000];

async function downloadFile(projectId: string, filename: string) {
  try {
    const res = await filesApi.download(projectId, filename);
    const blob = new Blob([res.data]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  } catch (err) { console.error("Download failed:", err); }
}

export default function LogViewerPage() {
  const { projectId } = useProject();
  const qc = useQueryClient();

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [linesPerPage, setLinesPerPage] = useState(1000);
  const [searchPattern, setSearchPattern] = useState("");
  const [activeHighlight, setActiveHighlight] = useState("");
  const [syntaxHL, setSyntaxHL] = useState(true);
  const [notes, setNotes] = useState("");
  const [saveStatus, setSaveStatus] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [fontSize, setFontSize] = useState(12);
  const [showNotes, setShowNotes] = useState(false);
  const [showSearch, setShowSearch] = useState(true);
  const [scrollToLine, setScrollToLine] = useState<number | null>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);

  const { data: files, isLoading: filesLoading } = useQuery({ queryKey: ["files", projectId], queryFn: async () => (await filesApi.list(projectId!)).data, enabled: !!projectId });
  const { data: fileContent, isLoading: contentLoading } = useQuery({ queryKey: ["fileContent", projectId, selectedFile, currentPage, linesPerPage], queryFn: async () => (await filesApi.getContent(projectId!, selectedFile!, currentPage, linesPerPage)).data, enabled: !!projectId && !!selectedFile });
  const searchMutation = useMutation({ mutationFn: (pattern: string) => filesApi.search(projectId!, selectedFile!, pattern) });
  const { data: notesData } = useQuery({ queryKey: ["notes", projectId], queryFn: async () => (await filesApi.getNotes(projectId!)).data, enabled: !!projectId });

  // After content loads, scroll to the target line
  useEffect(() => {
    if (scrollToLine !== null && fileContent && logContainerRef.current) {
      const lineIdx = scrollToLine - (fileContent.start_line || 1);
      if (lineIdx >= 0) {
        requestAnimationFrame(() => {
          const el = logContainerRef.current?.querySelector(`[data-line="${scrollToLine}"]`);
          if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            el.classList.add("bg-amber-700/40");
            setTimeout(() => el.classList.remove("bg-amber-700/40"), 2000);
          }
          setScrollToLine(null);
        });
      }
    }
  }, [scrollToLine, fileContent]);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (!projectId || !acceptedFiles.length) return;
    setIsUploading(true);
    try { await filesApi.upload(projectId, acceptedFiles); qc.invalidateQueries({ queryKey: ["files", projectId] }); }
    finally { setIsUploading(false); }
  }, [projectId, qc]);
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  const doSearch = (p?: string) => { const pat = p || searchPattern; if (pat && selectedFile) { setActiveHighlight(pat); searchMutation.mutate(pat); } };
  const quickPats: Record<string, string> = { ERROR: "(ERROR|FATAL|CRITICAL|FAIL)", WARN: "(WARNING|WARN|ALERT)", IP: "\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}", Time: "\\d{2}:\\d{2}:\\d{2}" };
  const saveNotes = async () => { if (!projectId) return; await filesApi.saveNotes(projectId, notes); setSaveStatus(`Saved ${new Date().toLocaleTimeString()}`); };
  if (notesData?.content && notes === "" && notesData.content !== notes) setNotes(notesData.content);

  const hasFiles = files && files.length > 0;
  const searchResults = searchMutation.data?.data;

  /** Render a log line with syntax + optional search highlighting */
  const renderLine = (text: string) => {
    if (syntaxHL) return highlightLogLine(text, activeHighlight || undefined);
    if (activeHighlight) return highlightLogLine(text, activeHighlight);
    return text;
  };

  return (
    <div className="flex flex-col h-[calc(100vh-3rem)] overflow-hidden">
      {/* ===== TOOLBAR ===== */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border bg-card shrink-0 flex-wrap">
        <div className="flex items-center gap-1 border border-input rounded-lg bg-background px-2 py-1 flex-1 min-w-[200px] max-w-md focus-within:ring-1 focus-within:ring-ring">
          <SearchIcon style={{ fontSize: 16 }} className="text-muted-foreground shrink-0" />
          <input value={searchPattern} onChange={(e) => setSearchPattern(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doSearch()} placeholder="Search (regex)..." className="flex-1 bg-transparent outline-none text-xs min-w-0" />
          <button onClick={() => doSearch()} className="text-[10px] bg-primary text-primary-foreground px-2 py-0.5 rounded font-medium shrink-0">Go</button>
        </div>
        <div className="flex items-center gap-1">
          {Object.entries(quickPats).map(([l, p]) => <button key={l} onClick={() => { setSearchPattern(p); doSearch(p); }} className="px-1.5 py-0.5 text-[10px] border border-border rounded hover:bg-muted">{l}</button>)}
        </div>
        <div className="w-px h-5 bg-border mx-1" />
        {/* Syntax highlight toggle */}
        <button onClick={() => setSyntaxHL(!syntaxHL)} title="Syntax highlighting"
          className={`flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded font-medium ${syntaxHL ? "bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-300" : "text-muted-foreground hover:bg-muted"}`}>
          <FormatColorTextIcon style={{ fontSize: 13 }} /> Syntax
        </button>
        <div className="flex items-center gap-0.5">
          <button onClick={() => setFontSize((s) => Math.max(8, s - 1))} className="p-0.5 rounded hover:bg-muted"><TextDecreaseIcon style={{ fontSize: 14 }} /></button>
          <span className="text-[10px] text-muted-foreground w-4 text-center">{fontSize}</span>
          <button onClick={() => setFontSize((s) => Math.min(20, s + 1))} className="p-0.5 rounded hover:bg-muted"><TextIncreaseIcon style={{ fontSize: 14 }} /></button>
        </div>
        <select value={linesPerPage} onChange={(e) => { setLinesPerPage(Number(e.target.value)); setCurrentPage(1); }} className="text-[10px] border border-input rounded bg-background px-1 py-0.5">
          {LINES_OPTIONS.map((n) => <option key={n} value={n}>{n} lines</option>)}
        </select>
        <div className="w-px h-5 bg-border mx-1" />
        <button onClick={() => setShowNotes(!showNotes)} title="Toggle notes" className={`flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded font-medium ${showNotes ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}><NoteAltIcon style={{ fontSize: 13 }} /> Notes</button>
        {!hasFiles && (
          <div {...getRootProps()} className="cursor-pointer"><input {...getInputProps()} />
            <button className="flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded text-muted-foreground hover:bg-muted font-medium"><CloudUploadIcon style={{ fontSize: 13 }} /> {isUploading ? "Uploading..." : "Upload"}</button>
          </div>
        )}
      </div>

      {/* ===== BODY ===== */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* LEFT: Files */}
        <div className="w-52 shrink-0 border-r border-border bg-card flex flex-col">
          <div className="flex items-center justify-between px-2 py-1.5 border-b border-border">
            <h3 className="text-[11px] font-semibold flex items-center gap-1 text-muted-foreground uppercase tracking-wider"><DescriptionIcon style={{ fontSize: 14 }} /> Files</h3>
            <button onClick={() => qc.invalidateQueries({ queryKey: ["files", projectId] })} className="p-0.5 rounded hover:bg-muted"><RefreshIcon style={{ fontSize: 14 }} className="text-muted-foreground" /></button>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-1 space-y-0.5">
            {filesLoading && <p className="text-[10px] text-muted-foreground p-2">Loading...</p>}
            {!hasFiles && !filesLoading && (
              <div {...getRootProps()} className={cn("border border-dashed rounded-lg p-3 text-center cursor-pointer text-[10px] text-muted-foreground", isDragActive && "border-primary bg-accent")}>
                <input {...getInputProps()} /><CloudUploadIcon style={{ fontSize: 20 }} className="mx-auto mb-1 opacity-50" /><p>Drop files here</p>
              </div>
            )}
            {files?.map((f: { filename: string; file_size: number; is_viewable: boolean; file_size_mb: number }) => (
              <div key={f.filename} className={cn("flex items-center gap-1 px-1.5 py-1 rounded text-[11px] cursor-pointer group", selectedFile === f.filename ? "bg-accent text-accent-foreground" : "hover:bg-muted")}
                onClick={() => { if (f.is_viewable) { setSelectedFile(f.filename); setCurrentPage(1); } }}>
                <DescriptionIcon style={{ fontSize: 13 }} className="text-muted-foreground shrink-0" />
                <span className="truncate flex-1" title={f.filename}>{f.filename}</span>
                <span className="text-[9px] text-muted-foreground shrink-0">{f.file_size_mb}M</span>
                <button onClick={(e) => { e.stopPropagation(); if (projectId) downloadFile(projectId, f.filename); }} className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-muted shrink-0" title="Download"><DownloadIcon style={{ fontSize: 12 }} /></button>
              </div>
            ))}
          </div>
        </div>

        {/* CENTER: Log Content */}
        <div className="flex-1 flex flex-col min-w-0">
          {selectedFile && (
            <div className="flex items-center justify-between px-3 py-1 border-b border-border bg-muted/30 shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs font-medium truncate">{selectedFile}</span>
                {fileContent && <span className="text-[10px] text-muted-foreground shrink-0">L{fileContent.start_line}–{fileContent.end_line} of {fileContent.total_lines}</span>}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button onClick={() => { if (projectId && selectedFile) downloadFile(projectId, selectedFile); }} className="p-0.5 rounded hover:bg-muted" title="Download"><DownloadIcon style={{ fontSize: 16 }} className="text-muted-foreground" /></button>
                {fileContent && fileContent.total_pages > 1 && (<>
                  <div className="w-px h-4 bg-border mx-1" />
                  <button onClick={() => setCurrentPage(1)} disabled={currentPage <= 1} className="p-0.5 rounded hover:bg-muted disabled:opacity-30"><FirstPageIcon style={{ fontSize: 16 }} /></button>
                  <button onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} disabled={currentPage <= 1} className="p-0.5 rounded hover:bg-muted disabled:opacity-30"><ChevronLeftIcon style={{ fontSize: 16 }} /></button>
                  <span className="text-[10px] px-1">{currentPage}/{fileContent.total_pages}</span>
                  <button onClick={() => setCurrentPage((p) => Math.min(fileContent.total_pages, p + 1))} disabled={currentPage >= fileContent.total_pages} className="p-0.5 rounded hover:bg-muted disabled:opacity-30"><ChevronRightIcon style={{ fontSize: 16 }} /></button>
                  <button onClick={() => setCurrentPage(fileContent.total_pages)} disabled={currentPage >= fileContent.total_pages} className="p-0.5 rounded hover:bg-muted disabled:opacity-30"><LastPageIcon style={{ fontSize: 16 }} /></button>
                </>)}
              </div>
            </div>
          )}

          <div ref={logContainerRef} className="flex-1 overflow-auto bg-slate-900 text-slate-200 log-viewer log-scroll" style={{ fontSize: `${fontSize}px` }}>
            {!selectedFile && <div className="flex items-center justify-center h-full text-slate-500 text-sm">Select a file from the sidebar to view its contents</div>}
            {contentLoading && <div className="p-4 text-slate-400 text-xs">Loading...</div>}
            {fileContent?.lines?.map((line: string, idx: number) => {
              const lineNum = (fileContent.start_line || 1) + idx;
              return (
                <div key={idx} data-line={lineNum} className="hover:bg-slate-800/50 whitespace-pre-wrap px-3 leading-relaxed transition-colors duration-500">
                  <span className="text-slate-600 select-none mr-3 inline-block w-12 text-right tabular-nums">{lineNum}</span>
                  {renderLine(line)}
                </div>
              );
            })}
          </div>

          {searchResults && (
            <div className="border-t border-border bg-card shrink-0">
              <button onClick={() => setShowSearch(!showSearch)} className="w-full flex items-center justify-between px-3 py-1 text-xs font-medium hover:bg-muted">
                <span>Search Results — {searchResults.total} match(es)</span>
                {showSearch ? <KeyboardArrowDownIcon style={{ fontSize: 16 }} /> : <KeyboardArrowUpIcon style={{ fontSize: 16 }} />}
              </button>
              {showSearch && (
                <div className="overflow-auto max-h-52 bg-slate-900 text-slate-200 log-viewer log-scroll" style={{ fontSize: `${fontSize}px` }}>
                  {searchResults.matches.map((m: { line_number: number; text: string; page: number }, idx: number) => (
                    <div key={idx}
                      onDoubleClick={() => { setCurrentPage(m.page); setScrollToLine(m.line_number); }}
                      title="Double-click to jump to this line"
                      className="hover:bg-slate-800/50 cursor-pointer whitespace-pre-wrap px-3 leading-relaxed select-none">
                      <span className="text-slate-600 select-none mr-3 inline-block w-12 text-right tabular-nums">{m.line_number}</span>
                      {renderLine(m.text)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* RIGHT: Notes */}
        {showNotes && (
          <div className="w-72 shrink-0 border-l border-border bg-card flex flex-col">
            <div className="flex items-center justify-between px-2 py-1.5 border-b border-border">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1"><NoteAltIcon style={{ fontSize: 14 }} /> Notes</h3>
              <button onClick={() => setShowNotes(false)} className="p-0.5 rounded hover:bg-muted"><CloseIcon style={{ fontSize: 14 }} /></button>
            </div>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="flex-1 p-2 text-xs bg-transparent resize-none outline-none" placeholder="Write analysis notes..." />
            <div className="flex items-center gap-2 px-2 py-1.5 border-t border-border">
              <button onClick={saveNotes} className="flex items-center gap-1 px-2 py-1 text-[10px] bg-primary text-primary-foreground rounded font-medium"><SaveIcon style={{ fontSize: 12 }} /> Save</button>
              {saveStatus && <span className="text-[10px] text-green-600">{saveStatus}</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

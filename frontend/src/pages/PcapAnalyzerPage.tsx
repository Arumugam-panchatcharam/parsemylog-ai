import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import { pcapApi } from "@/api/endpoints";
import type { PcapFileInfo, PcapAnalysisResult } from "@/api/endpoints";
import { cn } from "@/lib/utils";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RefreshIcon from "@mui/icons-material/Refresh";
import LocalOfferIcon from "@mui/icons-material/LocalOffer";
import SortIcon from "@mui/icons-material/Sort";
import DescriptionIcon from "@mui/icons-material/Description";
import AddIcon from "@mui/icons-material/Add";
import CloseIcon from "@mui/icons-material/Close";
import HubIcon from "@mui/icons-material/Hub";
import WifiIcon from "@mui/icons-material/Wifi";
import DashboardIcon from "@mui/icons-material/Dashboard";
import DevicesIcon from "@mui/icons-material/Devices";
import RouterIcon from "@mui/icons-material/Router";
import CircularProgress from "@mui/material/CircularProgress";

import OverviewTab from "@/components/pcap/OverviewTab";
import ClientsTab from "@/components/pcap/ClientsTab";
import APsTab from "@/components/pcap/APsTab";
import Mesh1905Tab from "@/components/pcap/Mesh1905Tab";

type AnalysisTab = "overview" | "clients" | "aps" | "mesh";
type SortMode = "date" | "protocol" | "tag";

// ── Protocol badge ──────────────────────────────────────────────────────

function ProtocolBadge({ protocol }: { protocol: string }) {
  if (protocol === "easymesh" || protocol === "1905.1") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300" title="IEEE 1905.1 EasyMesh">
        <HubIcon style={{ fontSize: 10 }} /> 1905
      </span>
    );
  }
  if (protocol === "802.11") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300" title="802.11 Wi-Fi">
        <WifiIcon style={{ fontSize: 10 }} /> 802.11
      </span>
    );
  }
  if (protocol === "mixed") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" title="Mixed protocols">
        Mixed
      </span>
    );
  }
  if (protocol === "detecting...") {
    return (
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium text-muted-foreground bg-muted">
        <CircularProgress size={8} thickness={5} /> ...
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-medium text-muted-foreground bg-muted">?</span>
  );
}

// ── Tag editor ──────────────────────────────────────────────────────────

function TagEditor({ tags, onSave }: { tags: string[]; onSave: (tags: string[]) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const addTag = () => {
    const t = draft.trim();
    if (t && !tags.includes(t)) onSave([...tags, t]);
    setDraft("");
    setEditing(false);
  };

  return (
    <div className="flex flex-wrap items-center gap-1 mt-0.5">
      {tags.map((tag) => (
        <span key={tag} className="inline-flex items-center gap-0.5 px-1.5 py-0 rounded text-[9px] font-medium bg-primary/10 text-primary">
          {tag}
          <button onClick={(e) => { e.stopPropagation(); onSave(tags.filter((t) => t !== tag)); }} className="hover:text-destructive">
            <CloseIcon style={{ fontSize: 9 }} />
          </button>
        </span>
      ))}
      {editing ? (
        <input
          autoFocus value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") addTag(); if (e.key === "Escape") { setEditing(false); setDraft(""); } }}
          onBlur={addTag}
          onClick={(e) => e.stopPropagation()}
          className="w-16 px-1 py-0 text-[9px] border border-input rounded bg-background outline-none focus:ring-1 focus:ring-ring"
          placeholder="tag..."
        />
      ) : (
        <button onClick={(e) => { e.stopPropagation(); setEditing(true); }} className="p-0 text-muted-foreground hover:text-primary" title="Add tag">
          <AddIcon style={{ fontSize: 12 }} />
        </button>
      )}
    </div>
  );
}

// ── Tab button ──────────────────────────────────────────────────────────

function TabBtn({ active, onClick, icon, label, count }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string; count?: number }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 px-2.5 py-1 text-[10px] rounded font-medium transition-colors",
        active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
      )}
    >
      {icon} {label}
      {count != null && count > 0 && (
        <span className={cn("ml-0.5 text-[9px] px-1 rounded-full tabular-nums", active ? "bg-primary-foreground/20" : "bg-muted-foreground/20")}>{count}</span>
      )}
    </button>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// Main Page
// ═════════════════════════════════════════════════════════════════════════

export default function PcapAnalyzerPage() {
  const qc = useQueryClient();

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AnalysisTab>("overview");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<SortMode>("date");
  const [filterTag, setFilterTag] = useState<string>("");

  const prevFileRef = useRef<string | null>(null);

  // File list (poll while detecting)
  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ["pcap-files"],
    queryFn: async () => (await pcapApi.listFiles()).data,
    refetchInterval: (query) => {
      const files: PcapFileInfo[] = query.state.data?.files ?? [];
      return files.some((f) => f.protocol === "detecting...") ? 2000 : false;
    },
  });
  const rawFiles: PcapFileInfo[] = filesData?.files ?? [];

  const allTags = useMemo(() => {
    const s = new Set<string>();
    rawFiles.forEach((f) => f.tags?.forEach((t) => s.add(t)));
    return Array.from(s).sort();
  }, [rawFiles]);

  const files = useMemo(() => {
    let list = [...rawFiles];
    if (filterTag) list = list.filter((f) => f.tags?.includes(filterTag));
    if (sortMode === "protocol") {
      const order: Record<string, number> = { easymesh: 0, "1905.1": 0, "802.11": 1, mixed: 2, unknown: 3, "detecting...": 4 };
      list.sort((a, b) => (order[a.protocol] ?? 9) - (order[b.protocol] ?? 9));
    } else if (sortMode === "tag") {
      list.sort((a, b) => ((a.tags?.[0] || "zzz")).localeCompare(b.tags?.[0] || "zzz"));
    }
    return list;
  }, [rawFiles, sortMode, filterTag]);

  useEffect(() => {
    if (!selectedFile && files.length > 0) setSelectedFile(files[0].filename);
  }, [files, selectedFile]);

  const selectedMeta = files.find((f) => f.filename === selectedFile);

  // Upload
  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (!acceptedFiles.length) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      const res = await pcapApi.upload(acceptedFiles);
      if (res.data.errors?.length) setUploadError(res.data.errors.join("; "));
      if (res.data.uploaded?.length) setSelectedFile(res.data.uploaded[0].filename);
      qc.invalidateQueries({ queryKey: ["pcap-files"] });
    } catch {
      setUploadError("Upload failed. Please try again.");
    } finally {
      setIsUploading(false);
    }
  }, [qc]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/octet-stream": [".pcap", ".pcapng"], "application/vnd.tcpdump.pcap": [".pcap", ".pcapng"] },
    multiple: true,
  });

  // Delete
  const deleteMutation = useMutation({
    mutationFn: (filename: string) => pcapApi.deleteFile(filename),
    onSuccess: (_, filename) => {
      if (selectedFile === filename) { setSelectedFile(null); analyzeMutation.reset(); }
      qc.invalidateQueries({ queryKey: ["pcap-files"] });
    },
  });

  // Tags
  const tagMutation = useMutation({
    mutationFn: ({ filename, tags }: { filename: string; tags: string[] }) => pcapApi.updateTags(filename, tags),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pcap-files"] }),
  });

  // Analysis
  const analyzeMutation = useMutation({
    mutationFn: ({ filename, force }: { filename: string; force?: boolean }) => pcapApi.analyze(filename, force),
  });

  // Clear when file changes
  useEffect(() => {
    if (selectedFile !== prevFileRef.current) {
      prevFileRef.current = selectedFile;
      analyzeMutation.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFile]);

  const runAnalysis = (force?: boolean) => {
    if (!selectedFile) return;
    analyzeMutation.mutate({ filename: selectedFile, force });
  };

  const result: PcapAnalysisResult | undefined = analyzeMutation.data?.data;
  const hasMesh = result?.mesh_1905?.has_1905 ?? false;

  return (
    <div className="relative flex flex-col h-[calc(100vh-3rem)] overflow-hidden">
      {/* ═══ TOOLBAR ═══ */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border bg-card shrink-0 flex-wrap">
        {/* Upload */}
        <div {...getRootProps()} className="cursor-pointer">
          <input {...getInputProps()} />
          <button className={cn(
            "flex items-center gap-1 px-2 py-1 text-[10px] rounded font-medium border transition-colors",
            isDragActive ? "border-primary bg-accent text-primary" : "border-border text-muted-foreground hover:bg-muted"
          )}>
            <CloudUploadIcon style={{ fontSize: 14 }} />
            {isUploading ? "Uploading..." : "Upload PCAP"}
          </button>
        </div>
        {uploadError && <span className="text-[10px] text-destructive">{uploadError}</span>}

        <div className="w-px h-5 bg-border mx-1" />

        {/* Sort */}
        <div className="flex items-center gap-1">
          <SortIcon style={{ fontSize: 13 }} className="text-muted-foreground" />
          <select value={sortMode} onChange={(e) => setSortMode(e.target.value as SortMode)} className="text-[10px] border border-input rounded bg-background px-1 py-0.5">
            <option value="date">Date</option>
            <option value="protocol">Protocol</option>
            <option value="tag">Tag</option>
          </select>
        </div>

        {allTags.length > 0 && (
          <div className="flex items-center gap-1">
            <LocalOfferIcon style={{ fontSize: 13 }} className="text-muted-foreground" />
            <select value={filterTag} onChange={(e) => setFilterTag(e.target.value)} className="text-[10px] border border-input rounded bg-background px-1 py-0.5">
              <option value="">All Tags</option>
              {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        )}

        <div className="flex-1" />

        {/* Tab buttons (shown when results exist) */}
        {result && (
          <div className="flex items-center gap-1">
            <TabBtn active={activeTab === "overview"} onClick={() => setActiveTab("overview")} icon={<DashboardIcon style={{ fontSize: 13 }} />} label="Overview" />
            <TabBtn active={activeTab === "clients"} onClick={() => setActiveTab("clients")} icon={<DevicesIcon style={{ fontSize: 13 }} />} label="Clients" count={result.clients.filter((c) => !c.is_ap).length} />
            <TabBtn active={activeTab === "aps"} onClick={() => setActiveTab("aps")} icon={<RouterIcon style={{ fontSize: 13 }} />} label="APs" count={result.aps.length} />
            {hasMesh && (
              <TabBtn active={activeTab === "mesh"} onClick={() => setActiveTab("mesh")} icon={<HubIcon style={{ fontSize: 13 }} />} label="1905.1" count={result.mesh_1905.devices.length} />
            )}
          </div>
        )}

        {result && <div className="w-px h-5 bg-border mx-1" />}

        {/* Run / Re-parse buttons */}
        {result && (
          <button
            onClick={() => runAnalysis(true)}
            disabled={analyzeMutation.isPending}
            className="flex items-center gap-1 px-2 py-1 text-[10px] rounded font-medium border border-border text-muted-foreground hover:bg-muted transition-colors disabled:opacity-50"
            title="Force re-parse (ignores cache)"
          >
            <RefreshIcon style={{ fontSize: 12 }} /> Re-parse
          </button>
        )}

        <button
          onClick={() => runAnalysis()}
          disabled={!selectedFile || analyzeMutation.isPending}
          className="flex items-center gap-1 px-3 py-1 rounded bg-primary text-primary-foreground text-[10px] font-medium disabled:opacity-50 hover:bg-primary/90 transition-colors"
        >
          {analyzeMutation.isPending ? <CircularProgress size={10} sx={{ color: "inherit" }} /> : <PlayArrowIcon style={{ fontSize: 14 }} />}
          {analyzeMutation.isPending ? "Analyzing..." : "Analyze"}
        </button>
      </div>

      {/* ═══ BODY ═══ */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* LEFT SIDEBAR: Files */}
        <div className="w-56 shrink-0 border-r border-border bg-card flex flex-col">
          <div className="flex items-center justify-between px-2 py-1.5 border-b border-border">
            <h3 className="text-[11px] font-semibold flex items-center gap-1 text-muted-foreground uppercase tracking-wider">
              <DescriptionIcon style={{ fontSize: 14 }} /> PCAP Files
            </h3>
            <button onClick={() => qc.invalidateQueries({ queryKey: ["pcap-files"] })} className="p-0.5 rounded hover:bg-muted" title="Refresh">
              <RefreshIcon style={{ fontSize: 14 }} className="text-muted-foreground" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto custom-scrollbar p-1 space-y-0.5">
            {filesLoading && <p className="text-[10px] text-muted-foreground p-2">Loading...</p>}
            {!files.length && !filesLoading && (
              <div {...getRootProps()} className={cn("border border-dashed rounded-lg p-3 text-center cursor-pointer text-[10px] text-muted-foreground", isDragActive && "border-primary bg-accent")}>
                <input {...getInputProps()} />
                <CloudUploadIcon style={{ fontSize: 20 }} className="mx-auto mb-1 opacity-50" />
                <p>Drop PCAP files here</p>
              </div>
            )}
            {files.map((f) => (
              <div
                key={f.filename}
                onClick={() => setSelectedFile(f.filename)}
                className={cn("px-1.5 py-1.5 rounded cursor-pointer group transition-colors", selectedFile === f.filename ? "bg-accent text-accent-foreground" : "hover:bg-muted")}
              >
                <div className="flex items-center gap-1">
                  <DescriptionIcon style={{ fontSize: 12 }} className="text-muted-foreground shrink-0" />
                  <span className="truncate flex-1 text-[11px] font-mono" title={f.filename}>{f.filename}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(f.filename); }}
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-destructive/10 text-destructive shrink-0"
                    title="Delete"
                  >
                    <DeleteOutlineIcon style={{ fontSize: 12 }} />
                  </button>
                </div>
                <div className="flex items-center gap-1.5 mt-1 pl-4">
                  <ProtocolBadge protocol={f.protocol} />
                  <span className="text-[9px] text-muted-foreground">{f.size_mb} MB</span>
                </div>
                <div className="pl-4">
                  <TagEditor tags={f.tags || []} onSave={(tags) => tagMutation.mutate({ filename: f.filename, tags })} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* CENTER: Analysis */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* File info bar */}
          {selectedFile && selectedMeta && (
            <div className="flex items-center gap-2 px-3 py-1 border-b border-border bg-muted/30 shrink-0">
              <span className="text-xs font-medium font-mono truncate">{selectedFile}</span>
              <ProtocolBadge protocol={selectedMeta.protocol} />
              {selectedMeta.tags?.map((t) => (
                <span key={t} className="px-1.5 py-0 rounded text-[9px] font-medium bg-primary/10 text-primary">{t}</span>
              ))}
              <span className="text-[10px] text-muted-foreground">{selectedMeta.size_mb} MB</span>
              {result?.overview.cache_used && <span className="text-[9px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">cached</span>}
            </div>
          )}

          {/* Results area */}
          <div className="flex-1 overflow-y-auto">
            {!selectedFile && (
              <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                Select a PCAP file from the sidebar
              </div>
            )}

            {selectedFile && analyzeMutation.isPending && (
              <div className="flex items-center justify-center gap-3 py-16">
                <CircularProgress size={24} />
                <span className="text-sm text-muted-foreground">Analyzing PCAP...</span>
              </div>
            )}

            {selectedFile && analyzeMutation.isError && (
              <p className="text-destructive text-sm p-4">
                Analysis failed: {(analyzeMutation.error as Error)?.message || "Unknown error"}
              </p>
            )}

            {selectedFile && analyzeMutation.isIdle && (
              <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2">
                <WifiIcon style={{ fontSize: 40 }} className="opacity-30" />
                <p className="text-sm">Click &quot;Analyze&quot; to run PCAP analysis</p>
              </div>
            )}

            {result && (
              <>
                {activeTab === "overview" && (
                  <OverviewTab
                    data={result.overview}
                    onNavigateToClient={() => setActiveTab("clients")}
                  />
                )}
                {activeTab === "clients" && selectedFile && (
                  <ClientsTab clients={result.clients} filename={selectedFile} />
                )}
                {activeTab === "aps" && selectedFile && (
                  <APsTab aps={result.aps} filename={selectedFile} />
                )}
                {activeTab === "mesh" && selectedFile && (
                  <Mesh1905Tab data={result.mesh_1905} filename={selectedFile} />
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

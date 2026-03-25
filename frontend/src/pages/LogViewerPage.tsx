import { useState, useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import { authApi, filesApi, patternsApi } from "@/api/endpoints";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import { useAuth } from "@/hooks/useAuth";
import { cn, convertLogTimestamp, TZ_OPTIONS } from "@/lib/utils";
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
import LanguageIcon from "@mui/icons-material/Language";
import CircularProgress from "@mui/material/CircularProgress";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import AddIcon from "@mui/icons-material/Add";
import SettingsIcon from "@mui/icons-material/Settings";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
const LINES_OPTIONS = [100, 500, 1000, 2000, 5000];

export interface QuickSearchButton {
  id: string;
  name: string;
  pattern: string;
}

export interface LogViewerDedupPattern {
  id: string;
  name: string;
  regex: string;
  enabled: boolean;
}

// UUID polyfill for browsers that don't support crypto.randomUUID (Safari < 15.4)
function generateUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback: generate UUID v4 manually
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function downloadFile(projectId: string, filename: string, cpeId?: string | null) {
  try {
    const res = await filesApi.download(projectId, filename, cpeId);
    const blob = new Blob([res.data]);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
  } catch (err) { console.error("Download failed:", err); }
}

async function downloadMergedLogs(projectId: string, cpeId?: string | null) {
  try {
    const res = await filesApi.downloadMergedLogs(projectId, cpeId);
    const blob = new Blob([res.data]);
    const disposition = (res.headers as Record<string, string>)?.["content-disposition"];
    const match = disposition?.match(/filename="?([^"]+)"?/);
    const downloadName = match ? match[1].trim() : "merged_logs.zip";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = downloadName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error("Download merged logs failed:", err);
  }
}

export default function LogViewerPage() {
  const { projectId } = useProject();
  const { user } = useAuth();
  const { cpeId, setCPE } = useCPE();
  const qc = useQueryClient();

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [linesPerPage, setLinesPerPage] = useState(1000);
  const [searchPattern, setSearchPattern] = useState("");
  const [searchInputValid, setSearchInputValid] = useState(false);
  const searchInputRef = useRef<string>("");
  const [activeHighlight, setActiveHighlight] = useState("");
  const [syntaxHL, setSyntaxHL] = useState(true);
  const [notes, setNotes] = useState("");
  const [saveStatus, setSaveStatus] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [processingStatus, setProcessingStatus] = useState<string | null>(null);
  const [fontSize, setFontSize] = useState(12);
  const [showNotes, setShowNotes] = useState(false);
  const [showSearch, setShowSearch] = useState(true);
  const [scrollToLine, setScrollToLine] = useState<number | null>(null);
  const [logTimezone, setLogTimezone] = useState("Original");
  const [fileSearchQuery, setFileSearchQuery] = useState("");
  const [searchAllFiles, setSearchAllFiles] = useState(false);
  const [quickSearchConfigOpen, setQuickSearchConfigOpen] = useState(false);
  const [quickSearchPanelPosition, setQuickSearchPanelPosition] = useState<{ top: number; left: number } | null>(null);
  const [quickSearchSaveError, setQuickSearchSaveError] = useState<string | null>(null);
  const [quickSearchEdit, setQuickSearchEdit] = useState<QuickSearchButton | null>(null);
  const [quickSearchName, setQuickSearchName] = useState("");
  const [quickSearchPattern, setQuickSearchPattern] = useState("");
  const [dedupPanelOpen, setDedupPanelOpen] = useState(false);
  const [dedupPanelPosition, setDedupPanelPosition] = useState<{ top: number; left: number } | null>(null);
  const dedupDropdownShownRef = useRef(false);
  const [dedupSaveError, setDedupSaveError] = useState<string | null>(null);
  const [dedupEdit, setDedupEdit] = useState<LogViewerDedupPattern | null>(null);
  const [dedupFormValidation, setDedupFormValidation] = useState(false);
  const dedupFormNameRef = useRef<string>("");
  const dedupFormRegexRef = useRef<string>("");
  const [dedupFormEnabled, setDedupFormEnabled] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const quickSearchConfigRef = useRef<HTMLDivElement>(null);
  const dedupConfigRef = useRef<HTMLDivElement>(null);
  const dedupPersistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevCpeId = useRef(cpeId);
  const [searchPanelHeight, setSearchPanelHeight] = useState(220);
  const resizingRef = useRef(false);
  const resizeStartRef = useRef({ y: 0, h: 0 });

  const { data: filesRaw, isLoading: filesLoading } = useQuery({ queryKey: ["files", projectId, cpeId], queryFn: async () => (await filesApi.list(projectId!, cpeId)).data, enabled: !!projectId });
  const files = Array.isArray(filesRaw) ? filesRaw : [];
  const { data: dedupData } = useQuery({
    queryKey: ["logViewerDedupPatterns", projectId],
    queryFn: async () => (await filesApi.getLogViewerDedupPatterns(projectId!)).data,
    enabled: !!projectId,
    staleTime: 60_000,
  });
  const dedupPatterns: LogViewerDedupPattern[] = dedupData?.patterns ?? [];
  const dedupActive = dedupData?.dedup_active ?? false;
  const dedupApply = dedupActive && dedupPatterns.some((p) => p.enabled);

  const { data: fileContent, isLoading: contentLoading, isPlaceholderData: contentIsPlaceholder } = useQuery({
    queryKey: ["fileContent", projectId, cpeId, selectedFile, currentPage, linesPerPage, dedupApply],
    queryFn: async () =>
      (await filesApi.getContent(projectId!, selectedFile!, currentPage, linesPerPage, cpeId, dedupApply)).data,
    enabled: !!projectId && !!selectedFile,
    placeholderData: keepPreviousData,
  });
  const searchMutation = useMutation({
    mutationFn: (args: { pattern: string; dedup: boolean }) =>
      filesApi.search(projectId!, selectedFile!, args.pattern, cpeId, args.dedup, linesPerPage),
  });
  const searchAllMutation = useMutation({
    mutationFn: (args: { pattern: string; dedup: boolean }) =>
      filesApi.searchAllFiles(projectId!, args.pattern, cpeId, args.dedup, linesPerPage),
  });
  const { data: notesData } = useQuery({ queryKey: ["notes", projectId], queryFn: async () => (await filesApi.getNotes(projectId!)).data, enabled: !!projectId });
  const { data: quickSearchData } = useQuery({
    queryKey: ["logViewerQuickSearches"],
    queryFn: async () => (await authApi.getLogViewerQuickSearches()).data,
    enabled: !!user,
  });
  const quickSearchButtons: QuickSearchButton[] = quickSearchData?.buttons ?? [];

  // One-time migration: if server has no buttons but localStorage has (old key), upload and clear
  const quickSearchMigrated = useRef(false);
  useEffect(() => {
    if (!user?.id || quickSearchMigrated.current || quickSearchButtons.length > 0) return;
    if (quickSearchData === undefined) return; // still loading
    quickSearchMigrated.current = true;
    const key = "parsemylog_log_viewer_quick_searches_user_" + String(user.id);
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return;
      const parsed = JSON.parse(raw) as unknown;
      const list = Array.isArray(parsed) ? parsed : (parsed && typeof parsed === "object" && "buttons" in parsed ? (parsed as { buttons: unknown }).buttons : null);
      if (!Array.isArray(list) || list.length === 0) return;
      const buttons = list.filter(
        (b): b is QuickSearchButton =>
          typeof b === "object" && b !== null && "id" in b && "name" in b && "pattern" in b
      ) as QuickSearchButton[];
      if (buttons.length > 0) {
        authApi.saveLogViewerQuickSearches(buttons).then(() => {
          localStorage.removeItem(key);
          qc.invalidateQueries({ queryKey: ["logViewerQuickSearches"] });
        });
      }
    } catch {
      // ignore
    }
  }, [user?.id, quickSearchData, quickSearchButtons.length, qc]);

  const hasFiles = files.length > 0;

  // Reset selected file when CPE changes
  useEffect(() => {
    if (prevCpeId.current !== cpeId) {
      setSelectedFile(null);
      setCurrentPage(1);
      setActiveHighlight("");
      searchMutation.reset();
      searchAllMutation.reset();
      prevCpeId.current = cpeId;
    }
  }, [cpeId, searchMutation, searchAllMutation]);

  // Indexing status — poll while indexing is active
  const { data: indexStatus } = useQuery({
    queryKey: ["indexingStatus", projectId, cpeId],
    queryFn: async () => (await patternsApi.indexingStatus(projectId!, cpeId)).data,
    enabled: !!projectId && !!hasFiles,
    refetchInterval: (query) => (query.state.data?.is_indexing ? 3000 : false),
  });
  const isIndexing = indexStatus?.is_indexing ?? false;

  // After content loads, scroll to the target line
  useEffect(() => {
    if (scrollToLine === null || !fileContent || !logContainerRef.current) return;

    const nums = fileContent.line_numbers;
    let onPage = false;
    if (nums?.length) {
      onPage = nums.includes(scrollToLine);
    } else {
      const startLine = fileContent.start_line || 1;
      const endLine = startLine + (fileContent.lines?.length || 0) - 1;
      onPage = scrollToLine >= startLine && scrollToLine <= endLine;
    }

    if (onPage) {
      requestAnimationFrame(() => {
        const el = logContainerRef.current?.querySelector(`[data-line="${scrollToLine}"]`);
        if (el) {
          el.scrollIntoView({ behavior: "auto", block: "center" });
          el.classList.add("bg-amber-700/40");
          setTimeout(() => el.classList.remove("bg-amber-700/40"), 2000);
        }
        setScrollToLine(null);
      });
    }
  }, [scrollToLine, fileContent]);

  const pollProcessingStatus = useCallback(async (pid: string) => {
    // Poll every 2s until processing completes or errors
    const poll = async (): Promise<void> => {
      try {
        const res = await filesApi.processingStatus(pid);
        const { status, message, progress, total, cpes } = res.data;
        setProcessingStatus(
          total > 0 ? `${message}  (${progress}/${total})` : message
        );
        if (status === "completed") {
          const cpeList = cpes ?? [];
          if (cpeList.length > 0) {
            setCPE({ serial: cpeList[0], mac: null, date_from: null, date_to: null });
            qc.invalidateQueries({ queryKey: ["cpes", pid] });
          }
          qc.invalidateQueries({ queryKey: ["files", pid] });
          qc.invalidateQueries({ queryKey: ["indexingStatus", pid] });
          setProcessingStatus(`Done! ${cpeList.length} CPE(s) processed, indexing in background...`);
          setTimeout(() => { setProcessingStatus(null); setIsUploading(false); }, 3000);
          return;
        }
        if (status === "error") {
          setProcessingStatus(`Processing failed: ${res.data?.error ?? "Unknown error"}`);
          setTimeout(() => { setProcessingStatus(null); setIsUploading(false); }, 5000);
          return;
        }
        // Still processing — poll again
        await new Promise((r) => setTimeout(r, 2000));
        return poll();
      } catch {
        // Network blip — retry
        await new Promise((r) => setTimeout(r, 3000));
        return poll();
      }
    };
    // Initial delay to let the backend start processing
    await new Promise((r) => setTimeout(r, 1000));
    return poll();
  }, [qc, setCPE]);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (!projectId || !acceptedFiles.length) return;
    setIsUploading(true);
    setProcessingStatus("Uploading files...");
    try {
      const res = await filesApi.upload(projectId, acceptedFiles);

      if (res.status === 202 && res.data.processing) {
        // Background processing — switch to polling
        setProcessingStatus("Files uploaded. Extracting and merging CPE logs...");
        pollProcessingStatus(projectId);
      } else {
        // Sync (legacy) path — done immediately
        qc.invalidateQueries({ queryKey: ["files", projectId] });
        qc.invalidateQueries({ queryKey: ["indexingStatus", projectId] });
        setProcessingStatus("Done! Indexing logs in background...");
        setTimeout(() => { setProcessingStatus(null); setIsUploading(false); }, 2500);
      }
    } catch {
      setProcessingStatus("Upload failed. Please try again.");
      setTimeout(() => { setProcessingStatus(null); setIsUploading(false); }, 3000);
    }
  }, [projectId, qc, setCPE, cpeId, pollProcessingStatus]);
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop });

  const doSearch = (p?: string) => {
    const pat = p || searchPattern;
    if (!pat) return;
    setActiveHighlight(pat);
    const ded = dedupApply;
    if (searchAllFiles) {
      searchMutation.reset();
      searchAllMutation.mutate({ pattern: pat, dedup: ded });
    } else {
      if (!selectedFile) return;
      searchAllMutation.reset();
      searchMutation.mutate({ pattern: pat, dedup: ded });
    }
  };
  const saveNotes = async () => { if (!projectId) return; await filesApi.saveNotes(projectId, notes); setSaveStatus(`Saved ${new Date().toLocaleTimeString()}`); qc.invalidateQueries({ queryKey: ["notes", projectId] }); };

  const openQuickSearchForm = (edit?: QuickSearchButton) => {
    setQuickSearchSaveError(null);
    setQuickSearchEdit(edit ?? null);
    setQuickSearchName(edit?.name ?? "");
    setQuickSearchPattern(edit?.pattern ?? "");
    setQuickSearchConfigOpen(true);
  };
  const closeQuickSearchForm = () => {
    setQuickSearchConfigOpen(false);
    setQuickSearchPanelPosition(null);
    setQuickSearchSaveError(null);
    setQuickSearchEdit(null);
    setQuickSearchName("");
    setQuickSearchPattern("");
  };
  const saveQuickSearchButton = async () => {
    const name = quickSearchName.trim();
    const pattern = quickSearchPattern.trim();
    if (!name || !pattern) return;
    setQuickSearchSaveError(null);
    const next = quickSearchEdit
      ? quickSearchButtons.map((b) => (b.id === quickSearchEdit.id ? { ...b, name, pattern } : b))
      : [...quickSearchButtons, { id: generateUUID(), name, pattern }];
    try {
      await authApi.saveLogViewerQuickSearches(next);
      qc.invalidateQueries({ queryKey: ["logViewerQuickSearches"] });
      closeQuickSearchForm();
    } catch (e: unknown) {
      let msg = "Save failed. Check network and try again.";
      if (e && typeof e === "object" && "response" in e) {
        const res = (e as { response?: { data?: unknown } }).response;
        if (res?.data && typeof res.data === "object" && "error" in res.data) msg = String((res.data as { error?: string }).error);
        else if (res?.data) msg = String(res.data);
      }
      setQuickSearchSaveError(msg);
      console.warn("Failed to save quick search buttons", e);
    }
  };
  const removeQuickSearchButton = async (id: string) => {
    const next = quickSearchButtons.filter((b) => b.id !== id);
    try {
      await authApi.saveLogViewerQuickSearches(next);
      qc.invalidateQueries({ queryKey: ["logViewerQuickSearches"] });
    } catch (e) {
      console.warn("Failed to save quick search buttons", e);
    }
  };

  const saveDedupFull = async (next: { dedup_active: boolean; patterns: LogViewerDedupPattern[] }): Promise<boolean> => {
    if (!projectId) return false;
    try {
      setDedupSaveError(null);
      const res = await filesApi.saveLogViewerDedupPatterns(projectId, next);
      const saved = res.data as { dedup_active: boolean; patterns: LogViewerDedupPattern[] };
      qc.setQueryData(["logViewerDedupPatterns", projectId], saved);
      await qc.invalidateQueries({ queryKey: ["fileContent", projectId] });
      return true;
    } catch (e: unknown) {
      let msg = "Save failed. Check network and try again.";
      if (e && typeof e === "object" && "response" in e) {
        const res = (e as { response?: { data?: unknown } }).response;
        if (res?.data && typeof res.data === "object" && "error" in res.data) msg = String((res.data as { error?: string }).error);
        else if (res?.data) msg = String(res.data);
      }
      setDedupSaveError(msg);
      console.warn("Failed to save dedup patterns", e);
      void qc.invalidateQueries({ queryKey: ["logViewerDedupPatterns", projectId] });
      return false;
    }
  };

  const persistDedupFromCache = useCallback(async () => {
    if (!projectId) return;
    const latest = qc.getQueryData<{ dedup_active: boolean; patterns: LogViewerDedupPattern[] }>([
      "logViewerDedupPatterns",
      projectId,
    ]);
    if (!latest) return;
    try {
      setDedupSaveError(null);
      const res = await filesApi.saveLogViewerDedupPatterns(projectId, latest);
      const saved = res.data as { dedup_active: boolean; patterns: LogViewerDedupPattern[] };
      qc.setQueryData(["logViewerDedupPatterns", projectId], saved);
      await qc.invalidateQueries({ queryKey: ["fileContent", projectId] });
    } catch (e: unknown) {
      let msg = "Save failed. Check network and try again.";
      if (e && typeof e === "object" && "response" in e) {
        const resErr = (e as { response?: { data?: unknown } }).response;
        if (resErr?.data && typeof resErr.data === "object" && "error" in resErr.data)
          msg = String((resErr.data as { error?: string }).error);
        else if (resErr?.data) msg = String(resErr.data);
      }
      setDedupSaveError(msg);
      console.warn("Failed to save dedup patterns", e);
      void qc.invalidateQueries({ queryKey: ["logViewerDedupPatterns", projectId] });
    }
  }, [projectId, qc]);

  const schedulePersistDedupFromCache = useCallback(() => {
    if (dedupPersistTimerRef.current) clearTimeout(dedupPersistTimerRef.current);
    dedupPersistTimerRef.current = setTimeout(() => {
      dedupPersistTimerRef.current = null;
      void persistDedupFromCache();
    }, 400);
  }, [persistDedupFromCache]);

  const openDedupForm = (edit?: LogViewerDedupPattern) => {
    setDedupSaveError(null);
    setDedupEdit(edit ?? null);
    const name = edit?.name ?? "";
    const regex = edit?.regex ?? "";
    dedupFormNameRef.current = name;
    dedupFormRegexRef.current = regex;
    setDedupFormValidation(!!(name.trim() && regex.trim()));
    setDedupFormEnabled(edit?.enabled ?? true);
    setDedupPanelOpen(true);
  };
  const closeDedupForm = () => {
    setDedupPanelOpen(false);
    setDedupPanelPosition(null);
    setDedupSaveError(null);
    setDedupEdit(null);
    dedupFormNameRef.current = "";
    dedupFormRegexRef.current = "";
    setDedupFormValidation(false);
    setDedupFormEnabled(true);
  };
  const saveDedupPattern = async () => {
    const name = dedupFormNameRef.current.trim();
    const regex = dedupFormRegexRef.current.trim();
    if (!name || !regex) return;
    if (dedupPersistTimerRef.current) {
      clearTimeout(dedupPersistTimerRef.current);
      dedupPersistTimerRef.current = null;
    }
    const nextPatterns = dedupEdit
      ? dedupPatterns.map((p) => (p.id === dedupEdit.id ? { ...p, name, regex, enabled: dedupFormEnabled } : p))
      : [...dedupPatterns, { id: generateUUID(), name, regex, enabled: dedupFormEnabled }];
    const ok = await saveDedupFull({ dedup_active: dedupActive, patterns: nextPatterns });
    if (ok) closeDedupForm();
  };
  const removeDedupPattern = async (id: string) => {
    if (dedupPersistTimerRef.current) {
      clearTimeout(dedupPersistTimerRef.current);
      dedupPersistTimerRef.current = null;
    }
    await saveDedupFull({ dedup_active: dedupActive, patterns: dedupPatterns.filter((p) => p.id !== id) });
  };
  const toggleDedupPatternEnabled = (id: string, enabled: boolean) => {
    if (!projectId) return;
    const nextPatterns = dedupPatterns.map((p) => (p.id === id ? { ...p, enabled } : p));
    qc.setQueryData(["logViewerDedupPatterns", projectId], { dedup_active: dedupActive, patterns: nextPatterns });
    schedulePersistDedupFromCache();
  };

  useEffect(() => {
    if (!quickSearchConfigOpen) return;
    const el = quickSearchConfigRef.current;
    if (el) {
      const rect = el.getBoundingClientRect();
      setQuickSearchPanelPosition({ left: rect.left, top: rect.bottom + 4 });
    }
  }, [quickSearchConfigOpen]);

  useEffect(() => {
    if (!quickSearchConfigOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeQuickSearchForm(); };
    const onMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (quickSearchConfigRef.current?.contains(t)) return;
      if (t && "closest" in (t as Element) && (t as Element).closest?.("[data-quick-search-panel]")) return;
      closeQuickSearchForm();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onMouseDown);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("mousedown", onMouseDown); };
  }, [quickSearchConfigOpen]);

  useEffect(() => {
    if (!dedupPanelOpen) {
      dedupDropdownShownRef.current = false;
      return;
    }
    // Calculate position only after portal is mounted in DOM
    const timer = requestAnimationFrame(() => {
      const el = dedupConfigRef.current;
      if (el) {
        const rect = el.getBoundingClientRect();
        setDedupPanelPosition({ left: rect.left, top: rect.bottom + 4 });
        dedupDropdownShownRef.current = true;
      }
    });
    return () => cancelAnimationFrame(timer);
  }, [dedupPanelOpen]);

  useEffect(() => {
    if (!dedupPanelOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDedupForm();
    };
    const onMouseDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (dedupConfigRef.current?.contains(t)) return;
      if (t && "closest" in (t as Element) && (t as Element).closest?.("[data-dedup-dropdown]")) return;
      closeDedupForm();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onMouseDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onMouseDown);
    };
  }, [dedupPanelOpen]);

  // Sync notes from API when loaded (avoid setState during render)
  useEffect(() => {
    if (notesData?.content != null && notes === "") setNotes(notesData.content);
  }, [notesData?.content]);

  const hasNotes = ((notesData?.content ?? "") as string).trim().length > 0;
  const hasUnsavedChanges = notesData && notes !== (notesData.content ?? "");

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    resizingRef.current = true;
    resizeStartRef.current = { y: e.clientY, h: searchPanelHeight };
    const onMove = (ev: MouseEvent) => {
      if (!resizingRef.current) return;
      const delta = resizeStartRef.current.y - ev.clientY;
      setSearchPanelHeight(Math.max(80, Math.min(window.innerHeight * 0.7, resizeStartRef.current.h + delta)));
    };
    const onUp = () => {
      resizingRef.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [searchPanelHeight]);

  const searchResults = searchAllFiles ? searchAllMutation.data?.data : searchMutation.data?.data;
  const searchAllResult = searchAllMutation.data?.data;
  const isAllFilesSearch = searchAllFiles && searchAllResult && searchAllResult.matches?.length !== undefined;

  /** Render a log line with optional TZ conversion + syntax + optional search highlighting */
  const renderLine = (text: string) => {
    const converted = convertLogTimestamp(text, logTimezone);
    if (syntaxHL) return highlightLogLine(converted, activeHighlight || undefined);
    if (activeHighlight) return highlightLogLine(converted, activeHighlight);
    return converted;
  };

  return (
    <div className="relative flex flex-col h-[calc(100vh-3rem)] overflow-hidden">
      {/* ===== PROCESSING OVERLAY ===== */}
      {processingStatus && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-4 p-8 bg-card rounded-2xl border border-border shadow-xl max-w-sm text-center">
            {isUploading ? (
              <CircularProgress size={48} thickness={4} />
            ) : (
              <CheckCircleIcon style={{ fontSize: 48, color: "#188038" }} />
            )}
            <p className="text-sm font-medium">{processingStatus}</p>
            {isUploading && (
              <p className="text-[11px] text-muted-foreground">
                Extracting archives, merging logs, and preparing files...
                <br />This may take a moment for large uploads.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ===== TOOLBAR ===== */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border bg-card shrink-0 flex-wrap">
        <div className="flex items-center gap-1 border border-input rounded-lg bg-background px-2 py-1 flex-1 min-w-[200px] max-w-md focus-within:ring-1 focus-within:ring-ring">
          <SearchIcon style={{ fontSize: 16 }} className="text-muted-foreground shrink-0" />
          <input
            data-command-search
            defaultValue={searchPattern}
            onChange={(e) => {
              searchInputRef.current = e.target.value;
              setSearchInputValid(e.target.value.trim().length > 0);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                setSearchPattern(searchInputRef.current);
                doSearch(searchInputRef.current);
              }
            }}
            placeholder="Search (regex)..."
            title="Search logs with regex pattern (press Enter to search)"
            className="min-w-0 flex-1 bg-transparent text-xs outline-none"
          />
          <button onClick={() => {
            setSearchPattern(searchInputRef.current);
            doSearch(searchInputRef.current);
          }} disabled={!searchInputValid || (!searchAllFiles && !selectedFile)} title="Execute search" className="text-[10px] bg-primary text-primary-foreground px-2 py-0.5 rounded font-medium shrink-0 disabled:opacity-50">Go</button>
        </div>
        <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground cursor-pointer whitespace-nowrap" title="Search across all log files in the current CPE">
          <input type="checkbox" checked={searchAllFiles} onChange={(e) => setSearchAllFiles(e.target.checked)} className="rounded border-border" />
          All files
        </label>
        <div className="flex items-center gap-1 flex-wrap">
          {quickSearchButtons.map((b) => (
            <button
              key={b.id}
              onClick={() => {
                searchInputRef.current = b.pattern;
                setSearchPattern(b.pattern);
                doSearch(b.pattern);
              }}
              className="px-1.5 py-0.5 text-[10px] border border-border rounded hover:bg-muted"
              title={b.pattern}
            >
              {b.name}
            </button>
          ))}
          <div className="relative inline-block" ref={quickSearchConfigRef}>
            <button
              type="button"
              onClick={() => openQuickSearchForm()}
              className="flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] border border-dashed border-border rounded hover:bg-muted text-muted-foreground"
              title="Add or manage regex search buttons"
            >
              <AddIcon style={{ fontSize: 12 }} /> Add
            </button>
            {quickSearchConfigOpen &&
              quickSearchPanelPosition &&
              createPortal(
                <div
                  data-quick-search-panel
                  className="min-w-[280px] p-3 bg-card border border-border rounded-lg shadow-lg"
                  style={{ position: "fixed", left: quickSearchPanelPosition.left, top: quickSearchPanelPosition.top, zIndex: 9999 }}
                >
                  <div className="text-[11px] font-medium text-muted-foreground mb-2">
                    {quickSearchEdit ? "Edit search button" : "Add search button (name → regex)"}
                  </div>
                  {quickSearchSaveError && (
                    <p className="text-[10px] text-destructive mb-2" role="alert">{quickSearchSaveError}</p>
                  )}
                  <input
                    value={quickSearchName}
                    onChange={(e) => setQuickSearchName(e.target.value)}
                    placeholder="Button name"
                    className="w-full mb-2 px-2 py-1 text-xs border border-input rounded bg-background"
                  />
                  <input
                    value={quickSearchPattern}
                    onChange={(e) => setQuickSearchPattern(e.target.value)}
                    placeholder="Regex pattern"
                    className="w-full mb-2 px-2 py-1 text-xs border border-input rounded bg-background font-mono"
                  />
                  <div className="flex items-center gap-1 mb-2">
                    <button type="button" onClick={saveQuickSearchButton} disabled={!quickSearchName.trim() || !quickSearchPattern.trim()} className="px-2 py-0.5 text-[10px] bg-primary text-primary-foreground rounded font-medium disabled:opacity-50">
                      {quickSearchEdit ? "Save" : "Add"}
                    </button>
                    {quickSearchEdit && (
                      <button type="button" onClick={closeQuickSearchForm} className="px-2 py-0.5 text-[10px] border border-border rounded font-medium">Cancel</button>
                    )}
                  </div>
                  {quickSearchButtons.length > 0 && (
                    <div className="border-t border-border pt-2 mt-2">
                      <div className="text-[10px] text-muted-foreground mb-1">Configured buttons</div>
                      <ul className="space-y-0.5 max-h-32 overflow-y-auto">
                        {quickSearchButtons.map((b) => (
                          <li key={b.id} className="flex items-center gap-1 text-[10px]">
                            <span className="truncate flex-1" title={b.pattern}>{b.name}</span>
                            <button type="button" onClick={() => openQuickSearchForm(b)} className="p-0.5 rounded hover:bg-muted" title="Edit"><SettingsIcon style={{ fontSize: 12 }} /></button>
                            <button type="button" onClick={() => removeQuickSearchButton(b.id)} className="p-0.5 rounded hover:bg-destructive/20 text-destructive" title="Remove"><DeleteOutlineIcon style={{ fontSize: 12 }} /></button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <button type="button" onClick={closeQuickSearchForm} title="Close" className="absolute top-1 right-1 p-0.5 rounded hover:bg-muted"><CloseIcon style={{ fontSize: 14 }} /></button>
                </div>,
                document.body
              )}
          </div>
        </div>
        <div className="w-px h-5 bg-border mx-1" />
        {/* Dedup: simple collapsible dropdown list */}
        <div className="relative inline-block" ref={dedupConfigRef}>
          <label
            className={`flex items-center gap-1.5 text-[10px] cursor-pointer whitespace-nowrap ${dedupData === undefined ? "opacity-50 pointer-events-none" : ""}`}
            title="View/search a filtered copy: lines matching your patterns are omitted (invert match)."
          >
            <input
              type="checkbox"
              checked={dedupActive}
              disabled={!projectId || dedupData === undefined}
              onChange={(e) => {
                if (dedupData === undefined || !projectId) return;
                if (dedupPersistTimerRef.current) {
                  clearTimeout(dedupPersistTimerRef.current);
                  dedupPersistTimerRef.current = null;
                }
                void saveDedupFull({ dedup_active: e.target.checked, patterns: dedupPatterns });
              }}
              className="rounded border-border shrink-0"
            />
            <span className={dedupActive ? "font-medium text-teal-800 dark:text-teal-200" : "text-muted-foreground"}>
              Remove Duplicate
            </span>
            <button
              type="button"
              onClick={() => setDedupPanelOpen(!dedupPanelOpen)}
              className="ml-1 px-1.5 py-0.5 text-xs font-semibold text-foreground bg-primary/20 hover:bg-primary/30 rounded transition-colors shrink-0"
              title="Show/hide dedup pattern list"
            >
              {dedupPanelOpen ? "▼" : "▶"} Patterns
            </button>
          </label>
          {dedupPanelOpen &&
            dedupDropdownShownRef.current &&
            dedupPanelPosition &&
            createPortal(
              <div
                data-dedup-dropdown
                className="min-w-[300px] p-2 bg-card border border-border rounded-lg shadow-lg"
                style={{
                  position: "fixed",
                  left: dedupPanelPosition.left,
                  top: dedupPanelPosition.top,
                  zIndex: 9999,
                }}
              >
                {/* Add new pattern section */}
                <div className="mb-2 pb-2 border-b border-border">
                  <div className="text-[10px] font-medium text-muted-foreground mb-1">Add Pattern</div>
                  <div className="flex flex-col gap-1">
                    <input
                      type="text"
                      key={dedupEdit?.id || "new"}
                      defaultValue={dedupEdit?.name || ""}
                      onChange={(e) => {
                        dedupFormNameRef.current = e.target.value;
                        setDedupFormValidation(!!(e.target.value.trim() && dedupFormRegexRef.current.trim()));
                      }}
                      placeholder="Pattern name"
                      className="px-2 py-1 text-xs border border-input rounded bg-background"
                    />
                    <input
                      type="text"
                      key={dedupEdit?.id || "new"}
                      defaultValue={dedupEdit?.regex || ""}
                      onChange={(e) => {
                        dedupFormRegexRef.current = e.target.value;
                        setDedupFormValidation(!!(dedupFormNameRef.current.trim() && e.target.value.trim()));
                      }}
                      placeholder="Regex (lines matching this are omitted)"
                      className="px-2 py-1 text-xs border border-input rounded bg-background font-mono"
                    />
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => void saveDedupPattern()}
                        disabled={!dedupFormValidation}
                        className="px-2 py-0.5 text-[10px] bg-primary text-primary-foreground rounded font-medium disabled:opacity-50 flex-1"
                      >
                        {dedupEdit ? "Update" : "+ Add"}
                      </button>
                      {dedupEdit && (
                        <button
                          type="button"
                          onClick={closeDedupForm}
                          className="px-2 py-0.5 text-[10px] border border-border rounded hover:bg-muted"
                        >
                          Cancel
                        </button>
                      )}
                    </div>
                    {dedupSaveError && (
                      <p className="text-[10px] text-destructive" role="alert">
                        {dedupSaveError}
                      </p>
                    )}
                  </div>
                </div>

                {/* Patterns list */}
                {dedupPatterns.length > 0 ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted-foreground mb-1">Patterns ({dedupPatterns.filter((p) => p.enabled).length}/{dedupPatterns.length})</div>
                    <ul className="space-y-1 max-h-48 overflow-y-auto">
                      {dedupPatterns.map((p) => (
                        <li
                          key={p.id}
                          className="flex items-center gap-1 px-1.5 py-1 rounded border border-border bg-background text-[10px] group hover:bg-muted/50"
                        >
                          <input
                            type="checkbox"
                            checked={p.enabled}
                            onChange={(e) => toggleDedupPatternEnabled(p.id, e.target.checked)}
                            className="rounded border-border shrink-0"
                            aria-label={`Enable pattern ${p.name}`}
                          />
                          <span className="truncate flex-1 cursor-pointer" onClick={() => openDedupForm(p)} title={p.regex}>
                            {p.name}
                          </span>
                          <button
                            type="button"
                            onClick={() => void removeDedupPattern(p.id)}
                            className="p-0 text-destructive hover:text-destructive/80 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                            title="Remove pattern"
                          >
                            ×
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="text-[10px] text-muted-foreground text-center py-2">No patterns added</p>
                )}
              </div>,
              document.body,
            )}
        </div>
        <div className="w-px h-5 bg-border mx-1" />
        {/* Syntax highlight toggle */}
        <button onClick={() => setSyntaxHL(!syntaxHL)} title="Syntax highlighting"
          className={`flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded font-medium ${syntaxHL ? "bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-300" : "text-muted-foreground hover:bg-muted"}`}>
          <FormatColorTextIcon style={{ fontSize: 13 }} /> Syntax
        </button>
        <div className="flex items-center gap-0.5">
          <button onClick={() => setFontSize((s) => Math.max(8, s - 1))} title="Decrease font size" className="p-0.5 rounded hover:bg-muted"><TextDecreaseIcon style={{ fontSize: 14 }} /></button>
          <span className="text-[10px] text-muted-foreground w-4 text-center">{fontSize}</span>
          <button onClick={() => setFontSize((s) => Math.min(20, s + 1))} title="Increase font size" className="p-0.5 rounded hover:bg-muted"><TextIncreaseIcon style={{ fontSize: 14 }} /></button>
        </div>
        <select value={linesPerPage} onChange={(e) => { setLinesPerPage(Number(e.target.value)); setCurrentPage(1); }} title="Number of lines to display per page" className="text-[10px] border border-input rounded bg-background px-1 py-0.5">
          {LINES_OPTIONS.map((n) => <option key={n} value={n}>{n} lines</option>)}
        </select>
        <div className="w-px h-5 bg-border mx-1" />
        <div className="flex items-center gap-1">
          <LanguageIcon style={{ fontSize: 13 }} className="text-muted-foreground" />
          <select value={logTimezone} onChange={(e) => setLogTimezone(e.target.value)} className="text-[10px] border border-input rounded bg-background px-1 py-0.5" title="Convert log timestamps">
            {TZ_OPTIONS.map((tz) => <option key={tz.id} value={tz.id}>{tz.id === "Original" ? "TZ: Original" : `TZ: ${tz.label}`}</option>)}
          </select>
        </div>
        <div className="w-px h-5 bg-border mx-1" />
        <button
          onClick={() => setShowNotes(!showNotes)}
          title={hasNotes ? "Notes saved for this project — click to open" : "Notes — no saved notes yet"}
          className={`flex items-center gap-1.5 px-1.5 py-0.5 text-[10px] rounded font-medium ${showNotes ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}
        >
          <NoteAltIcon style={{ fontSize: 13 }} />
          <span>Notes</span>
          {hasNotes && <span className="rounded-full w-1.5 h-1.5 bg-green-500 shrink-0" title="Project has saved notes" aria-hidden />}
        </button>
        {hasFiles && (
          <button onClick={() => projectId && downloadMergedLogs(projectId, cpeId)} title="Download all log files shown in the viewer as a ZIP (merged_logs-cpe-mac.zip)" className="flex items-center gap-1 px-2 py-0.5 text-[10px] rounded font-medium bg-emerald-600 text-white hover:bg-emerald-700 dark:bg-emerald-700 dark:hover:bg-emerald-600 shadow-sm">
            <DownloadIcon style={{ fontSize: 13 }} /> Download merged logs
          </button>
        )}
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
            <div className="flex items-center gap-1">
              {isIndexing && (
                <span className="flex items-center gap-1 text-[9px] text-blue-600 dark:text-blue-400 font-medium" title="Background indexing in progress">
                  <CircularProgress size={10} thickness={5} /> Indexing
                </span>
              )}
              <button onClick={() => qc.invalidateQueries({ queryKey: ["files", projectId] })} title="Refresh file list" className="p-0.5 rounded hover:bg-muted"><RefreshIcon style={{ fontSize: 14 }} className="text-muted-foreground" /></button>
            </div>
          </div>
          {hasFiles && (
            <div className="px-1.5 py-1 border-b border-border">
              <div className="flex items-center gap-1 bg-muted/50 rounded px-2 py-1">
                <SearchIcon style={{ fontSize: 12 }} className="text-muted-foreground shrink-0" />
                <input
                  type="text"
                  value={fileSearchQuery}
                  onChange={(e) => setFileSearchQuery(e.target.value)}
                  placeholder="Search files..."
                  title="Filter files by name"
                  className="flex-1 min-w-0 bg-transparent text-[11px] outline-none placeholder:text-muted-foreground"
                />
              </div>
            </div>
          )}
          <div className="flex-1 overflow-y-auto custom-scrollbar p-1 space-y-0.5">
            {filesLoading && <p className="text-[10px] text-muted-foreground p-2">Loading...</p>}
            {!hasFiles && !filesLoading && (
              <div {...getRootProps()} className={cn("border border-dashed rounded-lg p-3 text-center cursor-pointer text-[10px] text-muted-foreground", isDragActive && "border-primary bg-accent")}>
                <input {...getInputProps()} /><CloudUploadIcon style={{ fontSize: 20 }} className="mx-auto mb-1 opacity-50" /><p>Drop files here</p>
              </div>
            )}
            {(fileSearchQuery.trim()
              ? files.filter((f: { filename: string }) => f.filename.toLowerCase().includes(fileSearchQuery.trim().toLowerCase()))
              : files
            ).map((f: { filename: string; file_path: string; file_size: number; is_viewable: boolean; file_size_mb: number }) => (
              <div key={f.file_path} className={cn("flex items-center gap-1 px-1.5 py-1 rounded text-[11px] cursor-pointer group", selectedFile === f.filename ? "bg-accent text-accent-foreground" : "hover:bg-muted")}
                onClick={() => { if (f.is_viewable) { setSelectedFile(f.filename); setCurrentPage(1); } }}>
                <DescriptionIcon style={{ fontSize: 13 }} className="text-muted-foreground shrink-0" />
                <span className="truncate flex-1" title={f.filename}>{f.filename}</span>
                <span className="text-[9px] text-muted-foreground shrink-0">{f.file_size_mb}M</span>
                <button onClick={(e) => { e.stopPropagation(); if (projectId) downloadFile(projectId, f.filename, cpeId); }} className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-muted shrink-0" title="Download"><DownloadIcon style={{ fontSize: 12 }} /></button>
              </div>
            ))}
          </div>
        </div>

        {/* CENTER: Log Content */}
        <div className="flex-1 flex flex-col min-w-0">
          {selectedFile && (
            <div className="flex items-center justify-between px-3 py-1 border-b border-border bg-muted/30 shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs font-medium truncate" title={selectedFile}>{selectedFile}</span>
                {fileContent && (
                  <span className="text-[10px] text-muted-foreground shrink-0">
                    L{fileContent.start_line}–{fileContent.end_line} of {fileContent.total_lines}
                    {fileContent.dedup_applied && fileContent.total_lines_raw != null && (
                      <span title="Raw line count before deduplication"> ({fileContent.total_lines_raw} raw)</span>
                    )}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button onClick={() => { if (projectId && selectedFile) downloadFile(projectId, selectedFile, cpeId); }} className="p-0.5 rounded hover:bg-muted" title="Download"><DownloadIcon style={{ fontSize: 16 }} className="text-muted-foreground" /></button>
                {fileContent && fileContent.total_pages > 1 && (<>
                  <div className="w-px h-4 bg-border mx-1" />
                  <button onClick={() => setCurrentPage(1)} disabled={currentPage <= 1} title="Go to first page" className="p-0.5 rounded hover:bg-muted disabled:opacity-30"><FirstPageIcon style={{ fontSize: 16 }} /></button>
                  <button onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} disabled={currentPage <= 1} title="Go to previous page" className="p-0.5 rounded hover:bg-muted disabled:opacity-30"><ChevronLeftIcon style={{ fontSize: 16 }} /></button>
                  <span className="text-[10px] px-1">{currentPage}/{fileContent.total_pages}</span>
                  <button onClick={() => setCurrentPage((p) => Math.min(fileContent.total_pages, p + 1))} disabled={currentPage >= fileContent.total_pages} title="Go to next page" className="p-0.5 rounded hover:bg-muted disabled:opacity-30"><ChevronRightIcon style={{ fontSize: 16 }} /></button>
                  <button onClick={() => setCurrentPage(fileContent.total_pages)} disabled={currentPage >= fileContent.total_pages} title="Go to last page" className="p-0.5 rounded hover:bg-muted disabled:opacity-30"><LastPageIcon style={{ fontSize: 16 }} /></button>
                </>)}
              </div>
            </div>
          )}

          <div
            ref={logContainerRef}
            className={cn(
              "flex-1 overflow-auto bg-slate-900 text-slate-200 log-viewer log-scroll transition-opacity",
              contentIsPlaceholder && "opacity-65",
            )}
            style={{ fontSize: `${fontSize}px` }}
          >
            {!selectedFile && <div className="flex items-center justify-center h-full text-slate-500 text-sm">Select a file from the sidebar to view its contents</div>}
            {contentLoading && <div className="p-4 text-slate-400 text-xs">Loading...</div>}
            {fileContent?.lines?.map((line: string, idx: number) => {
              const lineNum = fileContent.line_numbers?.[idx] ?? (fileContent.start_line || 1) + idx;
              return (
                <div key={`${lineNum}-${idx}`} data-line={lineNum} className="hover:bg-slate-800/50 whitespace-pre-wrap px-3 leading-relaxed transition-colors duration-500">
                  <span className="text-slate-600 select-none mr-3 inline-block w-12 text-right tabular-nums">{lineNum}</span>
                  {renderLine(line)}
                </div>
              );
            })}
          </div>

          {searchResults && (
            <div className="border-t border-border bg-card shrink-0">
              {/* Resize handle */}
              {showSearch && (
                <div
                  onMouseDown={onResizeStart}
                  className="h-1.5 cursor-row-resize bg-border/50 hover:bg-primary/40 active:bg-primary/60 transition-colors flex items-center justify-center"
                >
                  <div className="w-8 h-0.5 rounded-full bg-muted-foreground/40" />
                </div>
              )}
              <button onClick={() => setShowSearch(!showSearch)} className="w-full flex items-center justify-between px-3 py-1 text-xs font-medium hover:bg-muted">
                <span>
                  Search Results — {searchResults.total} match(es)
                  {searchAllResult?.truncated && " (first 500)"}
                </span>
                {showSearch ? <KeyboardArrowDownIcon style={{ fontSize: 16 }} /> : <KeyboardArrowUpIcon style={{ fontSize: 16 }} />}
              </button>
              {showSearch && (
                <div className="overflow-auto bg-slate-900 text-slate-200 log-viewer log-scroll" style={{ fontSize: `${fontSize}px`, height: `${searchPanelHeight}px` }}>
                  {isAllFilesSearch
                    ? (searchResults.matches as Array<{ filename: string; line_number: number; text: string; content_page?: number }>).map((m, idx) => (
                        <div
                          key={idx}
                          onDoubleClick={() => {
                            setSelectedFile(m.filename);
                            const targetPage = m.content_page ?? Math.ceil(m.line_number / linesPerPage);
                            setCurrentPage(targetPage);
                            setScrollToLine(m.line_number);
                          }}
                          title="Double-click to open file and jump to line"
                          className="hover:bg-slate-800/50 cursor-pointer whitespace-pre-wrap px-3 leading-relaxed select-none"
                        >
                          <span className="text-slate-500 select-none mr-2 text-[10px] truncate max-w-[120px] inline-block align-top" title={m.filename}>{m.filename}</span>
                          <span className="text-slate-600 select-none mr-2 inline-block w-10 text-right tabular-nums text-[10px]">{m.line_number}</span>
                          {renderLine(m.text)}
                        </div>
                      ))
                    : searchResults.matches.map((m: { line_number: number; text: string; content_page?: number }, idx: number) => (
                        <div
                          key={idx}
                          onDoubleClick={() => {
                            const targetPage = m.content_page ?? Math.ceil(m.line_number / linesPerPage);
                            setCurrentPage(targetPage);
                            setScrollToLine(m.line_number);
                          }}
                          title="Double-click to jump to this line"
                          className="hover:bg-slate-800/50 cursor-pointer whitespace-pre-wrap px-3 leading-relaxed select-none"
                        >
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
              <div className="flex items-center gap-1.5 min-w-0">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1 shrink-0"><NoteAltIcon style={{ fontSize: 14 }} /> Notes</h3>
                {hasNotes && <span className="text-[9px] text-green-600 dark:text-green-400 font-medium shrink-0" title="Notes saved for this project">Saved</span>}
              </div>
              <button onClick={() => setShowNotes(false)} title="Close notes panel" className="p-0.5 rounded hover:bg-muted shrink-0"><CloseIcon style={{ fontSize: 14 }} /></button>
            </div>
            {hasUnsavedChanges && (
              <div className="px-2 py-1 text-[10px] text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200 dark:border-amber-800">
                Unsaved changes — click Save to update project notes
              </div>
            )}
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="flex-1 p-2 text-xs bg-transparent resize-none outline-none" placeholder="Write analysis notes..." />
            <div className="flex items-center gap-2 px-2 py-1.5 border-t border-border">
              <button onClick={saveNotes} className="flex items-center gap-1 px-2 py-1 text-[10px] bg-primary text-primary-foreground rounded font-medium"><SaveIcon style={{ fontSize: 12 }} /> Save</button>
              {saveStatus && <span className="text-[10px] text-green-600 dark:text-green-400">{saveStatus}</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

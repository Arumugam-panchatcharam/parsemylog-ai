import { useState, useCallback, useMemo, useRef } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import { telemetryCsvApi } from "@/api/endpoints";
import { cn } from "@/lib/utils";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DescriptionIcon from "@mui/icons-material/Description";
import SearchIcon from "@mui/icons-material/Search";
import CloseIcon from "@mui/icons-material/Close";
import AddIcon from "@mui/icons-material/Add";
import LocalOfferIcon from "@mui/icons-material/LocalOffer";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import CircularProgress from "@mui/material/CircularProgress";
import Plot from "react-plotly.js";
import { usePlotlyLayoutMerge } from "@/lib/plotlyTheme";

const PLOT_CFG = { displayModeBar: false, responsive: true } as const;

const TYPE_COLORS = {
  numeric: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  string: "bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-300",
  datetime: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
};

export default function TelemetryCsvAnalyzerPage() {
  const queryClient = useQueryClient();
  const mergePlot = usePlotlyLayoutMerge();

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(224);
  const [fileSearch, setFileSearch] = useState("");
  const [columnSearch, setColumnSearch] = useState("");
  const [xColumn, setXColumn] = useState<string | null>(null);
  const [yColumns, setYColumns] = useState<string[]>([]);
  const [chartType, setChartType] = useState<"line" | "scatter" | "bar">("line");
  const [maxPoints, setMaxPoints] = useState<number>(5000);
  const [plotRequest, setPlotRequest] = useState<{ x: string; y: string[]; max: number } | null>(null);
  const [expandedColumns, setExpandedColumns] = useState<Set<string>>(new Set());
  const [editingTags, setEditingTags] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");

  const isResizing = useRef(false);

  // ── Fetch files list ──────────────────────────────────────────────────────
  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ["telemetryCsvFiles"],
    queryFn: async () => {
      const res = await telemetryCsvApi.listFiles();
      return res.data;
    },
  });

  // ── Upload mutation ───────────────────────────────────────────────────────
  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => telemetryCsvApi.upload(files),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["telemetryCsvFiles"] });
    },
  });

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      uploadMutation.mutate(acceptedFiles);
    }
  }, [uploadMutation]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
      "application/zip": [".zip"],
      "application/gzip": [".gz"],
      "application/x-gzip": [".gz"],
    },
    multiple: true,
  });

  // ── Delete mutation ───────────────────────────────────────────────────────
  const deleteMutation = useMutation({
    mutationFn: (filename: string) => telemetryCsvApi.deleteFile(filename),
    onSuccess: (_, filename) => {
      queryClient.invalidateQueries({ queryKey: ["telemetryCsvFiles"] });
      if (selectedFile === filename) {
        setSelectedFile(null);
        setXColumn(null);
        setYColumns([]);
        queryClient.removeQueries({ queryKey: ["telemetryCsvMetadata", filename] });
        queryClient.removeQueries({ queryKey: ["telemetryCsvSeries", filename] });
      }
    },
  });

  // ── Update tags mutation ──────────────────────────────────────────────────
  const updateTagsMutation = useMutation({
    mutationFn: ({ filename, tags }: { filename: string; tags: string[] }) => 
      telemetryCsvApi.updateTags(filename, tags),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["telemetryCsvFiles"] });
    },
  });

  // ── Fetch metadata ────────────────────────────────────────────────────────
  const { data: metadata, isLoading: metadataLoading } = useQuery({
    queryKey: ["telemetryCsvMetadata", selectedFile],
    queryFn: async () => {
      if (!selectedFile) return null;
      const res = await telemetryCsvApi.getMetadata(selectedFile);
      return res.data;
    },
    enabled: !!selectedFile,
  });

  // ── Fetch series data for plotting ────────────────────────────────────────
  const { data: seriesData, isLoading: seriesLoading } = useQuery({
    queryKey: ["telemetryCsvSeries", selectedFile, plotRequest],
    queryFn: async () => {
      if (!selectedFile || !plotRequest) return null;
      const res = await telemetryCsvApi.getSeries(selectedFile, plotRequest.x, plotRequest.y, plotRequest.max);
      return res.data;
    },
    enabled: !!selectedFile && !!plotRequest,
  });

  // ── Filter columns by search ──────────────────────────────────────────────
  const filteredColumns = useMemo(() => {
    if (!metadata) return [];
    const search = columnSearch.toLowerCase();
    return metadata.columns.filter((col) => col.toLowerCase().includes(search));
  }, [metadata, columnSearch]);

  // ── Filter files by search ────────────────────────────────────────────────
  const filteredFiles = useMemo(() => {
    if (!filesData?.files) return [];
    const search = fileSearch.toLowerCase().trim();
    if (!search) return filesData.files;
    
    return filesData.files.filter((file) => {
      const matchesFilename = file.filename.toLowerCase().includes(search);
      const matchesTags = file.tags.some((tag) => tag.toLowerCase().includes(search));
      return matchesFilename || matchesTags;
    });
  }, [filesData, fileSearch]);

  // ── Chart data preparation ────────────────────────────────────────────────
  const chartData = useMemo(() => {
    if (!seriesData) return null;

    return seriesData.series.map((s) => ({
      x: seriesData.x,
      y: s.values,
      type: chartType as any,
      mode: chartType === "scatter" ? "markers" : chartType === "line" ? "lines+markers" : undefined,
      name: s.name,
      marker: { size: chartType === "scatter" ? 6 : 4 },
    }));
  }, [seriesData, chartType]);

  // ── Toggle column selection ───────────────────────────────────────────────
  const toggleYColumn = (col: string) => {
    setYColumns((prev) =>
      prev.includes(col) ? prev.filter((c) => c !== col) : [...prev, col]
    );
  };

  // ── Toggle column expansion ────────────────────────────────────────────────
  const toggleColumnExpansion = (col: string) => {
    setExpandedColumns((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(col)) {
        newSet.delete(col);
      } else {
        newSet.add(col);
      }
      return newSet;
    });
  };

  // ── Tag management ─────────────────────────────────────────────────────────
  const handleAddTag = (filename: string, currentTags: string[]) => {
    const newTag = tagInput.trim();
    if (newTag && !currentTags.includes(newTag)) {
      updateTagsMutation.mutate({ filename, tags: [...currentTags, newTag] });
      setTagInput("");
    }
  };

  const handleRemoveTag = (filename: string, currentTags: string[], tagToRemove: string) => {
    updateTagsMutation.mutate({ 
      filename, 
      tags: currentTags.filter(t => t !== tagToRemove) 
    });
  };

  // ── Resize handler ─────────────────────────────────────────────────────────
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    isResizing.current = true;
    const startX = e.clientX;
    const startWidth = sidebarWidth;
    const onMouseMove = (e: MouseEvent) => {
      if (!isResizing.current) return;
      const newWidth = Math.min(400, Math.max(160, startWidth + e.clientX - startX));
      setSidebarWidth(newWidth);
    };
    const onMouseUp = () => {
      isResizing.current = false;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }, [sidebarWidth]);

  // ── Render ────────────────────────────────────────────────────────────────

  const files = filteredFiles;

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Left panel: File list */}
      <div 
        className={cn("border-r border-border flex flex-col transition-all relative", sidebarCollapsed && "transition-none")}
        style={{ width: sidebarCollapsed ? 40 : sidebarWidth }}
      >
        <div className="flex items-center justify-between px-2 py-1.5 border-b border-border">
          {!sidebarCollapsed && (
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <DescriptionIcon style={{ fontSize: 14 }} />
              CSV Files
            </h3>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="p-0.5 rounded hover:bg-muted"
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {sidebarCollapsed ? (
              <ChevronRightIcon style={{ fontSize: 14 }} className="text-muted-foreground" />
            ) : (
              <ChevronLeftIcon style={{ fontSize: 14 }} className="text-muted-foreground" />
            )}
          </button>
        </div>

        {!sidebarCollapsed && (
          <>
            {/* Upload area */}
            <div className="p-4 border-b border-border">
              <div
                {...getRootProps()}
                className={cn(
                  "border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors",
                  isDragActive
                    ? "border-primary bg-primary/5"
                    : "border-muted-foreground/30 hover:border-primary/50 hover:bg-muted/30"
                )}
              >
                <input {...getInputProps()} />
                <CloudUploadIcon className="mx-auto mb-2 text-muted-foreground" style={{ fontSize: 32 }} />
                <p className="text-sm text-muted-foreground">
                  {isDragActive ? "Drop files here" : "Drop CSV files or click to browse"}
                </p>
                <p className="text-xs text-muted-foreground mt-1">Supports .csv, .zip, .gz</p>
              </div>
              {uploadMutation.isPending && (
                <p className="text-xs text-primary mt-2 flex items-center gap-2">
                  <CircularProgress size={12} /> Uploading...
                </p>
              )}
              {uploadMutation.isError && (
                <p className="text-xs text-destructive mt-2">Upload failed</p>
              )}
            </div>

            {/* File search */}
            <div className="p-4 border-b border-border">
              <div className="relative">
                <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" style={{ fontSize: 18 }} />
                <input
                  type="text"
                  value={fileSearch}
                  onChange={(e) => setFileSearch(e.target.value)}
                  placeholder="Search files by name or tag..."
                  className="w-full pl-10 pr-10 py-2 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                />
                {fileSearch && (
                  <button
                    onClick={() => setFileSearch("")}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <CloseIcon style={{ fontSize: 18 }} />
                  </button>
                )}
              </div>
            </div>

            {/* Files list */}
            <div className="flex-1 overflow-y-auto p-2">
              {filesLoading && (
                <div className="flex items-center justify-center p-8">
                  <CircularProgress size={24} />
                </div>
              )}
              {!filesLoading && files.length === 0 && (
                <p className="text-sm text-muted-foreground text-center p-4">No files uploaded yet</p>
              )}
          <div className="space-y-1">
            {files.map((file) => (
              <div
                key={file.filename}
                className={cn(
                  "p-3 rounded-lg transition-colors group",
                  selectedFile === file.filename
                    ? "bg-primary/10 border border-primary"
                    : "hover:bg-muted/50 border border-transparent"
                )}
              >
                <div 
                  className="cursor-pointer"
                  onClick={() => {
                    setSelectedFile(file.filename);
                    setXColumn(null);
                    setYColumns([]);
                    setColumnSearch("");
                    setPlotRequest(null);
                    setExpandedColumns(new Set());
                    setEditingTags(null);
                    setTagInput("");
                  }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate" title={file.filename}>
                        {file.filename}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {file.size_mb} MB
                      </p>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`Delete ${file.filename}?`)) {
                          deleteMutation.mutate(file.filename);
                        }
                      }}
                      className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-destructive/10 text-destructive transition-opacity"
                      title="Delete file"
                    >
                      <DeleteOutlineIcon style={{ fontSize: 16 }} />
                    </button>
                  </div>
                </div>

                {/* Tags section */}
                <div className="mt-2 pt-2 border-t border-border/50" onClick={(e) => e.stopPropagation()}>
                  <div className="flex items-center gap-1 flex-wrap mb-1">
                    <LocalOfferIcon className="text-muted-foreground" style={{ fontSize: 14 }} />
                    {file.tags.length === 0 && editingTags !== file.filename && (
                      <span className="text-xs text-muted-foreground">No tags</span>
                    )}
                    {file.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-primary/20 text-primary"
                      >
                        {tag}
                        <button
                          onClick={() => handleRemoveTag(file.filename, file.tags, tag)}
                          className="hover:text-destructive"
                          title="Remove tag"
                        >
                          <CloseIcon style={{ fontSize: 12 }} />
                        </button>
                      </span>
                    ))}
                    {editingTags !== file.filename && (
                      <button
                        onClick={() => setEditingTags(file.filename)}
                        className="p-0.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
                        title="Add tag"
                      >
                        <AddIcon style={{ fontSize: 14 }} />
                      </button>
                    )}
                  </div>

                  {/* Tag input */}
                  {editingTags === file.filename && (
                    <div className="flex items-center gap-1 mt-1">
                      <input
                        type="text"
                        value={tagInput}
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            handleAddTag(file.filename, file.tags);
                          } else if (e.key === "Escape") {
                            setEditingTags(null);
                            setTagInput("");
                          }
                        }}
                        onBlur={() => {
                          setEditingTags(null);
                          setTagInput("");
                        }}
                        placeholder="Add tag..."
                        className="flex-1 px-2 py-1 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                        autoFocus
                      />
                      <button
                        onMouseDown={(e) => {
                          e.preventDefault();
                          handleAddTag(file.filename, file.tags);
                        }}
                        className="p-1 rounded bg-primary text-primary-foreground hover:bg-primary/90"
                        title="Add"
                      >
                        <AddIcon style={{ fontSize: 14 }} />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
            </div>
          </>
        )}
        
        {/* Resize handle */}
        {!sidebarCollapsed && (
          <div
            onMouseDown={handleMouseDown}
            className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/30 transition-colors"
          />
        )}
      </div>

      {/* Center panel: Column picker and chart */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {!selectedFile && (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <DescriptionIcon className="mx-auto mb-4 text-muted-foreground" style={{ fontSize: 64 }} />
              <p className="text-lg text-muted-foreground">Select a CSV file to begin</p>
            </div>
          </div>
        )}

        {selectedFile && metadataLoading && (
          <div className="flex-1 flex items-center justify-center">
            <CircularProgress size={48} />
          </div>
        )}

        {selectedFile && !metadataLoading && metadata && (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* File info bar */}
            <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border bg-muted/30 shrink-0">
              <span className="text-xs font-medium font-mono truncate" title={selectedFile}>
                {selectedFile}
              </span>
              <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                {metadata.row_count.toLocaleString()} rows × {metadata.column_count.toLocaleString()} columns
              </span>
              {filesData?.files.find(f => f.filename === selectedFile)?.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-1.5 py-0 rounded text-[9px] font-medium bg-primary/10 text-primary"
                >
                  {tag}
                </span>
              ))}
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {/* Row 1: Column Search */}
              <div>
                <div className="relative">
                  <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" style={{ fontSize: 18 }} />
                  <input
                    type="text"
                    value={columnSearch}
                    onChange={(e) => setColumnSearch(e.target.value)}
                    placeholder="Search columns..."
                    className="w-full pl-10 pr-10 py-2.5 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  {columnSearch && (
                    <button
                      onClick={() => setColumnSearch("")}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      <CloseIcon style={{ fontSize: 18 }} />
                    </button>
                  )}
                </div>
              </div>

              {/* Row 2: Two columns - Column List + Chart Settings & Selection */}
              <div className="grid grid-cols-2 gap-4">
                {/* Column 1: Column List Table */}
                <div>
                  <h3 className="text-sm font-semibold mb-3">Available Columns</h3>
                  <div className="border rounded-lg overflow-hidden">
                    <div className="max-h-96 overflow-y-auto">
                      {filteredColumns.length === 0 && (
                        <p className="text-sm text-muted-foreground text-center p-4">No columns match your search</p>
                      )}
                      {filteredColumns.map((col, index) => {
                        const dtype = metadata.dtypes[col];
                        const isX = xColumn === col;
                        const isY = yColumns.includes(col);
                        const isNumeric = dtype === "numeric";
                        const isString = dtype === "string";
                        const uniqueValues = metadata.unique_values?.[col] || [];
                        const isExpanded = expandedColumns.has(col);

                        return (
                          <div key={col}>
                            <div
                              className={cn(
                                "flex items-center justify-between px-3 py-2 border-b border-border/50 hover:bg-muted/30 transition-colors",
                                (isX || isY) && "bg-muted/50"
                              )}
                            >
                              <div className="flex-1 min-w-0 flex items-center gap-2">
                                <span className="text-xs text-muted-foreground font-mono w-10 flex-shrink-0">
                                  {(index + 1).toString().padStart(3, ' ')}
                                </span>
                                <span className="text-sm truncate" title={col}>
                                  {col}
                                </span>
                                <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium", TYPE_COLORS[dtype as keyof typeof TYPE_COLORS])}>
                                  {dtype}
                                </span>
                                {isString && uniqueValues.length > 0 && (
                                  <button
                                    onClick={() => toggleColumnExpansion(col)}
                                    className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/50"
                                    title="Click to view unique values"
                                  >
                                    {uniqueValues.length} unique
                                  </button>
                                )}
                              </div>
                              <div className="flex gap-1">
                                <button
                                  onClick={() => setXColumn(col)}
                                  disabled={isX}
                                  className={cn(
                                    "px-2 py-1 text-xs rounded transition-colors",
                                    isX
                                      ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300 cursor-default"
                                      : "bg-muted hover:bg-green-100 hover:text-green-700 dark:hover:bg-green-900/30 dark:hover:text-green-300"
                                  )}
                                >
                                  X
                                </button>
                                <button
                                  onClick={() => toggleYColumn(col)}
                                  disabled={!isNumeric}
                                  className={cn(
                                    "px-2 py-1 text-xs rounded transition-colors",
                                    !isNumeric
                                      ? "opacity-30 cursor-not-allowed"
                                      : isY
                                      ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                                      : "bg-muted hover:bg-blue-100 hover:text-blue-700 dark:hover:bg-blue-900/30 dark:hover:text-blue-300"
                                  )}
                                  title={!isNumeric ? "Only numeric columns can be Y-axis" : undefined}
                                >
                                  Y
                                </button>
                              </div>
                            </div>
                            {isString && isExpanded && uniqueValues.length > 0 && (
                              <div className="px-3 py-2 bg-muted/20 border-b border-border/50">
                                <p className="text-xs text-muted-foreground mb-1">Unique values:</p>
                                <div className="flex flex-wrap gap-1">
                                  {uniqueValues.map((val, idx) => (
                                    <span
                                      key={idx}
                                      className="px-1.5 py-0.5 rounded text-[10px] bg-background border border-border text-foreground"
                                      title={val}
                                    >
                                      {val.length > 20 ? val.substring(0, 20) + '...' : val}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* Column 2: Chart Settings & Selected Axes */}
                <div className="space-y-4">
                  {/* Row 1: Chart Settings */}
                  <div>
                    <h3 className="text-sm font-semibold mb-3">Chart Settings</h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs text-muted-foreground block mb-1">Chart Type</label>
                        <select
                          value={chartType}
                          onChange={(e) => setChartType(e.target.value as any)}
                          className="w-full px-3 py-2 text-sm rounded-lg border border-input bg-background"
                        >
                          <option value="line">Line</option>
                          <option value="scatter">Scatter</option>
                          <option value="bar">Bar</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground block mb-1">Max Points</label>
                        <input
                          type="number"
                          value={maxPoints}
                          onChange={(e) => setMaxPoints(Number(e.target.value))}
                          min="100"
                          max="50000"
                          step="500"
                          className="w-full px-3 py-2 text-sm rounded-lg border border-input bg-background"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Row 2: Selected X & Y Axes */}
                  <div className="border rounded-lg p-4 bg-muted/30 space-y-3">
                    {/* Selected X column */}
                    <div>
                      <p className="text-xs font-semibold text-muted-foreground mb-2">X-Axis:</p>
                      {xColumn ? (
                        <div className="flex flex-wrap gap-1">
                          <span className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300">
                            {xColumn}
                            <button
                              onClick={() => setXColumn(null)}
                              className="hover:text-destructive"
                            >
                              <CloseIcon style={{ fontSize: 12 }} />
                            </button>
                          </span>
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground italic">No X-axis selected</p>
                      )}
                    </div>

                    {/* Selected Y columns */}
                    <div>
                      <p className="text-xs font-semibold text-muted-foreground mb-2">
                        Y-Axes {yColumns.length > 0 && `(${yColumns.length})`}:
                      </p>
                      {yColumns.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {yColumns.map((col) => (
                            <span
                              key={col}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
                            >
                              {col}
                              <button
                                onClick={() => toggleYColumn(col)}
                                className="hover:text-destructive"
                              >
                                <CloseIcon style={{ fontSize: 12 }} />
                              </button>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground italic">No Y-axes selected</p>
                      )}
                    </div>

                    {/* Plot Graph Button */}
                    <div className="pt-2">
                      <button
                        onClick={() => setPlotRequest({ x: xColumn!, y: yColumns, max: maxPoints })}
                        disabled={!xColumn || yColumns.length === 0}
                        className="w-full px-4 py-2.5 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        Plot Graph
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Row 3: Chart Plot */}
              <div>
                {!xColumn || yColumns.length === 0 ? (
                  <div className="border rounded-lg p-12 text-center bg-muted/30">
                    <p className="text-sm text-muted-foreground">
                      Select one X column and at least one numeric Y column to plot
                    </p>
                  </div>
                ) : seriesLoading ? (
                  <div className="border rounded-lg p-12 flex items-center justify-center bg-muted/30">
                    <CircularProgress size={40} />
                  </div>
                ) : chartData ? (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-semibold">Chart</h3>
                      {seriesData?.downsampled && (
                        <span className="text-xs text-orange-600 dark:text-orange-400">
                          Downsampled to {seriesData.row_count.toLocaleString()} points
                        </span>
                      )}
                    </div>
                    <div className="border rounded-lg p-4 bg-background">
                      <Plot
                        data={chartData}
                        layout={mergePlot({
                          autosize: true,
                          height: 450,
                          margin: { l: 50, r: 20, t: 30, b: 40 },
                          xaxis: { title: { text: xColumn ?? "" } },
                          yaxis: {},
                          showlegend: true,
                          legend: { x: 1, xanchor: "right", y: 1 },
                        })}
                        config={PLOT_CFG}
                        className="w-full"
                      />
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

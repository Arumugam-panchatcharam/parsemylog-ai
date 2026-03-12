import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useProject } from "@/hooks/useProject";
import { useCPE } from "@/hooks/useCPE";
import { mlAnomalyApi, cpesApi, type LogAnomalyReport, type TelemetryAnomalyReport, type FleetAnalysisReport } from "@/api/endpoints";
import CircularProgress from "@mui/material/CircularProgress";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import TimelineIcon from "@mui/icons-material/Timeline";
import BugReportIcon from "@mui/icons-material/BugReport";
import SpeedIcon from "@mui/icons-material/Speed";
import GroupsIcon from "@mui/icons-material/Groups";
import ThumbUpIcon from "@mui/icons-material/ThumbUp";
import ThumbDownIcon from "@mui/icons-material/ThumbDown";

export default function MLPipelinePage() {
  const { projectId } = useProject();
  const { cpeId } = useCPE();

  const [selectedMode, setSelectedMode] = useState<"single-cpe" | "fleet">("single-cpe");
  const [selectedDomain] = useState<string>("all");
  
  // NEW: Vector-based method toggles
  const [enableVectorSimilarity, setEnableVectorSimilarity] = useState(true);
  const [enableGRU, setEnableGRU] = useState(true);
  const [enableIsolationForest, setEnableIsolationForest] = useState(true);
  
  const [expandedSections, setExpandedSections] = useState<{ [key: string]: boolean }>({
    logAnomalies: true,
    telemetryAnomalies: true,
    fleetAnalysis: true,
  });

  // Pagination and filtering state
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [expandedAnomalies, setExpandedAnomalies] = useState<Set<string>>(new Set());

  // Batch feedback state - stores pending feedback before submission
  const [pendingFeedback, setPendingFeedback] = useState<Map<string, { is_true_positive: boolean; domain: string }>>(new Map());
  const [isBatchMode, setIsBatchMode] = useState(false);

  const [logReport, setLogReport] = useState<LogAnomalyReport | null>(null);
  const [telemetryReport, setTelemetryReport] = useState<TelemetryAnomalyReport | null>(null);
  const [fleetReport, setFleetReport] = useState<FleetAnalysisReport | null>(null);
  const [feedbackSubmitted, setFeedbackSubmitted] = useState<Set<string>>(new Set());

  // Fetch CPE list for fleet mode
  const { data: cpeData } = useQuery({
    queryKey: ["cpes", projectId],
    queryFn: async () => (await cpesApi.list(projectId!)).data,
    enabled: !!projectId,
  });
  const cpeList = cpeData?.cpes ?? [];

  // Mutations for running ML analysis
  const logMutation = useMutation({
    mutationFn: () =>
      mlAnomalyApi.detectLogAnomalies(projectId!, {
        cpe_id: cpeId || undefined,
        domain: selectedDomain === "all" ? undefined : selectedDomain,
        top_n: 500,
        // NEW: Vector-based methods
        enable_vector_similarity: enableVectorSimilarity,
        enable_gru: enableGRU,
        enable_isolation_forest: enableIsolationForest,
      }),
    onSuccess: (res) => setLogReport(res.data),
  });

  const telemetryMutation = useMutation({
    mutationFn: () =>
      mlAnomalyApi.detectTelemetryAnomalies(projectId!, cpeId || undefined),
    onSuccess: (res) => setTelemetryReport(res.data),
  });

  const fleetMutation = useMutation({
    mutationFn: () =>
      mlAnomalyApi.runFleetAnalysis(
        projectId!,
        undefined,
        {
          max_workers: 8,
          // NEW: Vector-based methods
          enable_vector_similarity: enableVectorSimilarity,
          enable_gru: enableGRU,
          enable_isolation_forest: enableIsolationForest,
          enable_log: true,
          enable_telemetry: true,
        }
      ),
    onSuccess: (res) => setFleetReport(res.data),
  });

  // Feedback mutation (for immediate submission)
  const feedbackMutation = useMutation({
    mutationFn: (data: {
      template: string;
      anomaly_type: string;
      is_true_positive: boolean;
      domain: string;
    }) =>
      mlAnomalyApi.submitFeedback(projectId!, {
        cpe_id: cpeId || "",
        domain: data.domain,
        template: data.template,
        anomaly_type: data.anomaly_type,
        is_true_positive: data.is_true_positive,
        confidence: 1.0,
      }),
    onSuccess: (_, variables) => {
      const feedbackKey = `${variables.template}-${variables.anomaly_type}`;
      setFeedbackSubmitted(prev => new Set(prev).add(feedbackKey));
    },
  });

  // Batch feedback submission mutation
  const batchFeedbackMutation = useMutation({
    mutationFn: async (feedbackList: Array<{
      template: string;
      anomaly_type: string;
      is_true_positive: boolean;
      domain: string;
    }>) => {
      // Submit all feedback sequentially
      const results = [];
      for (const feedback of feedbackList) {
        const result = await mlAnomalyApi.submitFeedback(projectId!, {
          cpe_id: cpeId || "",
          domain: feedback.domain,
          template: feedback.template,
          anomaly_type: feedback.anomaly_type,
          is_true_positive: feedback.is_true_positive,
          confidence: 1.0,
        });
        results.push(result);
      }
      return results;
    },
    onSuccess: (_, variables) => {
      // Mark all as submitted
      const newSubmitted = new Set(feedbackSubmitted);
      variables.forEach(v => {
        const feedbackKey = `${v.template}-${v.anomaly_type}`;
        newSubmitted.add(feedbackKey);
      });
      setFeedbackSubmitted(newSubmitted);
      // Clear pending feedback
      setPendingFeedback(new Map());
    },
  });

  // Handle batch mode toggle
  const toggleBatchMode = () => {
    if (isBatchMode && pendingFeedback.size > 0) {
      // Confirm before switching off with unsaved changes
      if (window.confirm(`You have ${pendingFeedback.size} unsaved feedback items. Discard them?`)) {
        setPendingFeedback(new Map());
        setIsBatchMode(false);
      }
    } else {
      setIsBatchMode(!isBatchMode);
      if (!isBatchMode) {
        setPendingFeedback(new Map()); // Clear when enabling
      }
    }
  };

  // Handle individual feedback (immediate or batch)
  const handleFeedback = (template: string, anomalyType: string, domain: string, isTruePositive: boolean) => {
    const feedbackKey = `${template}-${anomalyType}`;
    
    if (isBatchMode) {
      // Store in pending feedback
      setPendingFeedback(prev => {
        const newMap = new Map(prev);
        newMap.set(feedbackKey, { is_true_positive: isTruePositive, domain });
        return newMap;
      });
    } else {
      // Submit immediately
      feedbackMutation.mutate({
        template,
        anomaly_type: anomalyType,
        is_true_positive: isTruePositive,
        domain,
      });
    }
  };

  // Remove pending feedback
  const removePendingFeedback = (template: string, anomalyType: string) => {
    const feedbackKey = `${template}-${anomalyType}`;
    setPendingFeedback(prev => {
      const newMap = new Map(prev);
      newMap.delete(feedbackKey);
      return newMap;
    });
  };

  // Submit all pending feedback
  const submitAllFeedback = () => {
    if (pendingFeedback.size === 0) return;
    
    const feedbackList = Array.from(pendingFeedback.entries()).map(([key, value]) => {
      const [template] = key.split('-ensemble');
      return {
        template: template,
        anomaly_type: "ensemble",
        is_true_positive: value.is_true_positive,
        domain: value.domain,
      };
    });
    
    batchFeedbackMutation.mutate(feedbackList);
  };

  // Get pending feedback for a template
  const getPendingFeedback = (template: string, anomalyType: string) => {
    const feedbackKey = `${template}-${anomalyType}`;
    return pendingFeedback.get(feedbackKey);
  };

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
  };

  const toggleAnomalyExpand = (template: string) => {
    setExpandedAnomalies((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(template)) {
        newSet.delete(template);
      } else {
        newSet.add(template);
      }
      return newSet;
    });
  };

  // Filter and paginate anomalies
  const getFilteredAnomalies = () => {
    if (!logReport?.anomalies) return [];
    
    let filtered = logReport.anomalies;
    
    // Filter by domain
    if (domainFilter !== "all") {
      filtered = filtered.filter(a => a.category === domainFilter);
    }
    
    return filtered;
  };

  const getPaginatedAnomalies = () => {
    const filtered = getFilteredAnomalies();
    const startIdx = (currentPage - 1) * pageSize;
    const endIdx = startIdx + pageSize;
    return filtered.slice(startIdx, endIdx);
  };

  const totalPages = Math.ceil((getFilteredAnomalies().length || 0) / pageSize);
  const filteredCount = getFilteredAnomalies().length;

  // Get unique domains from anomalies for filter dropdown
  const availableDomains = logReport?.anomalies
    ? Array.from(new Set(logReport.anomalies.map(a => a.category).filter(Boolean)))
    : [];

  // Reset to page 1 when filter changes
  const handleDomainFilterChange = (newDomain: string) => {
    setDomainFilter(newDomain);
    setCurrentPage(1);
  };

  const getHealthColor = (score: number) => {
    if (score >= 80) return "text-green-600";
    if (score >= 60) return "text-yellow-600";
    return "text-red-600";
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <TimelineIcon />
            ML Anomaly Detection Pipeline
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Advanced ML-based anomaly detection for log patterns and telemetry data
          </p>
        </div>
      </div>

      {/* Mode Selection */}
      <div className="bg-card border border-border rounded-lg p-4">
        <div className="flex items-center gap-4 mb-4">
          <h2 className="text-lg font-semibold">Analysis Mode</h2>
          <div className="flex gap-2">
            <button
              onClick={() => setSelectedMode("single-cpe")}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                selectedMode === "single-cpe"
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
              }`}
            >
              Single CPE Analysis
            </button>
            <button
              onClick={() => setSelectedMode("fleet")}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                selectedMode === "fleet"
                  ? "bg-primary text-primary-foreground"
                  : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
              }`}
            >
              <GroupsIcon style={{ fontSize: 16, marginRight: 4 }} />
              Fleet Analysis
            </button>
          </div>
        </div>

        {/* ML Method Configuration */}
        <div className="border-t border-border pt-4">
          <h3 className="text-sm font-semibold mb-3 text-muted-foreground">ML Methods</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {/* NEW: Vector-based methods */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enableVectorSimilarity}
                onChange={(e) => setEnableVectorSimilarity(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm font-medium text-primary">Vector Similarity (KNN+Cluster+Temporal)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enableGRU}
                onChange={(e) => setEnableGRU(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm font-medium text-primary">GRU on Embeddings</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enableIsolationForest}
                onChange={(e) => setEnableIsolationForest(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm font-medium text-primary">IsolationForest on Embeddings</span>
            </label>
          </div>
        </div>

        {/* Run Analysis Buttons */}
        <div className="border-t border-border pt-4 mt-4 flex gap-3">
          {selectedMode === "single-cpe" ? (
            <>
              <button
                onClick={() => logMutation.mutate()}
                disabled={logMutation.isPending || !cpeId}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {logMutation.isPending ? (
                  <CircularProgress size={16} className="text-current" />
                ) : (
                  <PlayArrowIcon style={{ fontSize: 16 }} />
                )}
                Run Log Analysis
              </button>
              <button
                onClick={() => telemetryMutation.mutate()}
                disabled={telemetryMutation.isPending || !cpeId}
                className="px-4 py-2 bg-secondary text-secondary-foreground rounded-lg text-sm font-medium hover:bg-secondary/80 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {telemetryMutation.isPending ? (
                  <CircularProgress size={16} className="text-current" />
                ) : (
                  <PlayArrowIcon style={{ fontSize: 16 }} />
                )}
                Run Telemetry Analysis
              </button>
            </>
          ) : (
            <button
              onClick={() => fleetMutation.mutate()}
              disabled={fleetMutation.isPending}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {fleetMutation.isPending ? (
                <>
                  <CircularProgress size={16} className="text-current" />
                  Analyzing {cpeList.length} CPEs...
                </>
              ) : (
                <>
                  <PlayArrowIcon style={{ fontSize: 16 }} />
                  Run Fleet Analysis ({cpeList.length} CPEs)
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Single CPE Results */}
      {selectedMode === "single-cpe" && (
        <>
          {/* Log Anomalies */}
          {logReport && (
            <div className="bg-card border border-border rounded-lg">
              <div
                className="p-4 flex items-center justify-between cursor-pointer hover:bg-accent/50"
                onClick={() => toggleSection("logAnomalies")}
              >
                <h2 className="text-lg font-semibold flex items-center gap-2">
                  <BugReportIcon className="text-primary" />
                  Log Anomalies ({logReport.anomalies.length})
                </h2>
                {expandedSections.logAnomalies ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              </div>

              {expandedSections.logAnomalies && (
                <div className="p-4 border-t border-border space-y-4">
                  {/* Summary */}
                  <div className="bg-muted/30 p-3 rounded-lg">
                    <p className="text-sm text-muted-foreground">{logReport.summary}</p>
                  </div>

                  {/* Method Stats */}
                  {logReport.method_stats && (
                  <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                    {Object.entries(logReport.method_stats).map(([method, stats]) => (
                      <div key={method} className="bg-secondary/30 p-3 rounded-lg">
                        <p className="text-xs text-muted-foreground uppercase">{method}</p>
                        <p className="text-xl font-bold text-foreground">
                          {stats.detected}
                        </p>
                      </div>
                    ))}
                  </div>
                  )}

                  {/* Batch Feedback Controls */}
                  <div className="bg-accent/20 border border-primary/20 p-4 rounded-lg space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={isBatchMode}
                            onChange={toggleBatchMode}
                            className="w-4 h-4"
                          />
                          <span className="text-sm font-medium">
                            Batch Mode: Review & Submit All at Once
                          </span>
                        </label>
                        {isBatchMode && pendingFeedback.size > 0 && (
                          <span className="px-2 py-1 bg-primary/10 text-primary text-xs rounded font-medium">
                            {pendingFeedback.size} pending
                          </span>
                        )}
                      </div>
                      {isBatchMode && pendingFeedback.size > 0 && (
                        <div className="flex gap-2">
                          <button
                            onClick={() => {
                              if (window.confirm(`Clear all ${pendingFeedback.size} pending feedback items?`)) {
                                setPendingFeedback(new Map());
                              }
                            }}
                            className="px-3 py-1 bg-secondary text-secondary-foreground rounded text-sm hover:bg-secondary/80"
                          >
                            Clear All
                          </button>
                          <button
                            onClick={submitAllFeedback}
                            disabled={batchFeedbackMutation.isPending}
                            className="px-4 py-1 bg-primary text-primary-foreground rounded text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
                          >
                            {batchFeedbackMutation.isPending ? "Submitting..." : `Submit All (${pendingFeedback.size})`}
                          </button>
                        </div>
                      )}
                    </div>
                    {isBatchMode && (
                      <p className="text-xs text-muted-foreground">
                        ℹ️ In batch mode, your feedback is saved locally. Review and change your selections, then click "Submit All" when ready.
                      </p>
                    )}
                  </div>

                  {/* Anomalies Table with Filters and Pagination */}
                  <div className="space-y-4">
                    {/* Filters and Controls */}
                    <div className="flex items-center justify-between gap-4 p-3 bg-secondary/30 rounded-lg">
                      <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2">
                          <label className="text-sm font-medium text-muted-foreground">Filter by Domain:</label>
                          <select
                            value={domainFilter}
                            onChange={(e) => handleDomainFilterChange(e.target.value)}
                            className="px-3 py-1 border border-border rounded-lg bg-background text-sm"
                          >
                            <option value="all">All Domains ({filteredCount})</option>
                            {availableDomains.map((domain) => (
                              <option key={domain} value={domain}>
                                {domain} ({logReport.anomalies.filter(a => a.category === domain).length})
                              </option>
                            ))}
                          </select>
                        </div>
                        
                        <div className="flex items-center gap-2">
                          <label className="text-sm font-medium text-muted-foreground">Per Page:</label>
                          <select
                            value={pageSize}
                            onChange={(e) => {
                              setPageSize(Number(e.target.value));
                              setCurrentPage(1);
                            }}
                            className="px-3 py-1 border border-border rounded-lg bg-background text-sm"
                          >
                            <option value={10}>10</option>
                            <option value={20}>20</option>
                            <option value={50}>50</option>
                            <option value={100}>100</option>
                          </select>
                        </div>
                      </div>
                      
                      <div className="text-sm text-muted-foreground">
                        Showing {Math.min((currentPage - 1) * pageSize + 1, filteredCount)} - {Math.min(currentPage * pageSize, filteredCount)} of {filteredCount}
                      </div>
                    </div>

                    {/* Anomalies Table */}
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="bg-muted">
                          <tr>
                            <th className="p-2 text-left w-8"></th>
                            <th className="p-2 text-left w-16">S.No</th>
                            <th className="p-2 text-left">Score</th>
                            <th className="p-2 text-left">Template</th>
                            <th className="p-2 text-left">Category</th>
                            <th className="p-2 text-left">Feedback</th>
                          </tr>
                        </thead>
                        <tbody>
                          {getPaginatedAnomalies().map((anomaly, idx) => {
                            const feedbackKey = `${anomaly.template}-ensemble`;
                            const hasGivenFeedback = feedbackSubmitted.has(feedbackKey);
                            const isExpanded = expandedAnomalies.has(anomaly.template);
                            const serialNumber = (currentPage - 1) * pageSize + idx + 1;
                            const pendingFeedbackItem = getPendingFeedback(anomaly.template, "ensemble");
                            
                            return (
                              <>
                                <tr key={idx} className="border-t border-border hover:bg-accent/30">
                                  <td className="p-2">
                                    <button
                                      onClick={() => toggleAnomalyExpand(anomaly.template)}
                                      className="p-1 hover:bg-accent rounded"
                                      title={isExpanded ? "Hide sample logs" : "Show sample logs"}
                                    >
                                      {isExpanded ? (
                                        <ExpandLessIcon style={{ fontSize: 18 }} />
                                      ) : (
                                        <ExpandMoreIcon style={{ fontSize: 18 }} />
                                      )}
                                    </button>
                                  </td>
                                  <td className="p-2 text-muted-foreground">
                                    {serialNumber}
                                  </td>
                                  <td className="p-2">
                                    <span
                                      className={`font-mono font-semibold ${
                                        (anomaly.score ?? anomaly.anomaly_score) > 0.8
                                          ? "text-red-600"
                                          : (anomaly.score ?? anomaly.anomaly_score) > 0.6
                                          ? "text-yellow-600"
                                          : "text-blue-600"
                                      }`}
                                    >
                                      {(anomaly.score ?? anomaly.anomaly_score).toFixed(2)}
                                    </span>
                                  </td>
                                  <td className="p-2 font-mono text-xs max-w-md truncate" title={anomaly.template}>
                                    {anomaly.template}
                                  </td>
                                  <td className="p-2">
                                    {anomaly.category && (
                                      <span className="px-2 py-1 bg-primary/10 text-primary text-xs rounded">
                                        {anomaly.category}
                                      </span>
                                    )}
                                  </td>
                                  <td className="p-2">
                                    {hasGivenFeedback ? (
                                      <span className="text-xs text-muted-foreground">✓ Submitted</span>
                                    ) : pendingFeedbackItem ? (
                                      // Show pending feedback with ability to change
                                      <div className="flex gap-1 items-center">
                                        <button
                                          onClick={() => handleFeedback(
                                            anomaly.template,
                                            "ensemble",
                                            anomaly.category || logReport.domain || "Unknown",
                                            true
                                          )}
                                          className={`p-1 rounded ${
                                            pendingFeedbackItem.is_true_positive
                                              ? "bg-green-100 ring-2 ring-green-500"
                                              : "hover:bg-green-50"
                                          }`}
                                          title="True Positive - This is a real anomaly"
                                        >
                                          <ThumbUpIcon style={{ fontSize: 16 }} className="text-green-600" />
                                        </button>
                                        <button
                                          onClick={() => handleFeedback(
                                            anomaly.template,
                                            "ensemble",
                                            anomaly.category || logReport.domain || "Unknown",
                                            false
                                          )}
                                          className={`p-1 rounded ${
                                            !pendingFeedbackItem.is_true_positive
                                              ? "bg-red-100 ring-2 ring-red-500"
                                              : "hover:bg-red-50"
                                          }`}
                                          title="False Positive - This is NOT an anomaly"
                                        >
                                          <ThumbDownIcon style={{ fontSize: 16 }} className="text-red-600" />
                                        </button>
                                        <button
                                          onClick={() => removePendingFeedback(anomaly.template, "ensemble")}
                                          className="text-xs text-muted-foreground hover:text-foreground ml-1"
                                          title="Remove feedback"
                                        >
                                          ✕
                                        </button>
                                      </div>
                                    ) : (
                                      // No feedback yet
                                      <div className="flex gap-1">
                                        <button
                                          onClick={() => handleFeedback(
                                            anomaly.template,
                                            "ensemble",
                                            anomaly.category || logReport.domain || "Unknown",
                                            true
                                          )}
                                          disabled={!isBatchMode && feedbackMutation.isPending}
                                          className="p-1 hover:bg-green-100 rounded disabled:opacity-50"
                                          title="True Positive - This is a real anomaly"
                                        >
                                          <ThumbUpIcon style={{ fontSize: 16 }} className="text-green-600" />
                                        </button>
                                        <button
                                          onClick={() => handleFeedback(
                                            anomaly.template,
                                            "ensemble",
                                            anomaly.category || logReport.domain || "Unknown",
                                            false
                                          )}
                                          disabled={!isBatchMode && feedbackMutation.isPending}
                                          className="p-1 hover:bg-red-100 rounded disabled:opacity-50"
                                          title="False Positive - This is NOT an anomaly"
                                        >
                                          <ThumbDownIcon style={{ fontSize: 16 }} className="text-red-600" />
                                        </button>
                                      </div>
                                    )}
                                  </td>
                                </tr>
                                
                                {/* Expanded Sample Logs */}
                                {isExpanded && anomaly.sample_loglines && anomaly.sample_loglines.length > 0 && (
                                  <tr key={`${idx}-expanded`} className="border-t border-border bg-accent/20">
                                    <td colSpan={6} className="p-4">
                                      <div className="space-y-2">
                                        <div className="flex items-center justify-between">
                                          <h4 className="text-sm font-semibold text-foreground">Sample Log Lines ({anomaly.count || 0} occurrences)</h4>
                                          <div className="text-xs text-muted-foreground">
                                            Method scores: {Object.entries(anomaly.methods || {})
                                              .filter(([_, score]) => score > 0.1)
                                              .map(([method, score]) => `${method}: ${score.toFixed(2)}`)
                                              .join(", ")}
                                          </div>
                                        </div>
                                        <div className="bg-card border border-border rounded-lg p-3 space-y-2">
                                          {anomaly.sample_loglines.slice(0, 5).map((logline, logIdx) => (
                                            <div key={logIdx} className="font-mono text-xs bg-muted/50 p-2 rounded overflow-x-auto">
                                              {logline}
                                            </div>
                                          ))}
                                          {anomaly.sample_loglines.length > 5 && (
                                            <p className="text-xs text-muted-foreground text-center pt-2">
                                              ... and {anomaly.sample_loglines.length - 5} more samples
                                            </p>
                                          )}
                                        </div>
                                      </div>
                                    </td>
                                  </tr>
                                )}
                              </>
                            );
                          })}
                        </tbody>
                      </table>
                      
                      {getPaginatedAnomalies().length === 0 && (
                        <div className="text-center py-8 text-muted-foreground">
                          No anomalies found matching the selected filters.
                        </div>
                      )}
                    </div>

                    {/* Pagination Controls */}
                    {totalPages > 1 && (
                      <div className="flex items-center justify-between p-3 bg-secondary/30 rounded-lg">
                        <button
                          onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                          disabled={currentPage === 1}
                          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Previous
                        </button>
                        
                        <div className="flex items-center gap-2">
                          {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                            let pageNum;
                            if (totalPages <= 7) {
                              pageNum = i + 1;
                            } else if (currentPage <= 4) {
                              pageNum = i + 1;
                            } else if (currentPage >= totalPages - 3) {
                              pageNum = totalPages - 6 + i;
                            } else {
                              pageNum = currentPage - 3 + i;
                            }
                            
                            return (
                              <button
                                key={i}
                                onClick={() => setCurrentPage(pageNum)}
                                className={`px-3 py-1 rounded text-sm font-medium ${
                                  currentPage === pageNum
                                    ? "bg-primary text-primary-foreground"
                                    : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
                                }`}
                              >
                                {pageNum}
                              </button>
                            );
                          })}
                        </div>
                        
                        <button
                          onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                          disabled={currentPage === totalPages}
                          className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Next
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Telemetry Anomalies */}
          {telemetryReport && (
            <div className="bg-card border border-border rounded-lg">
              <div
                className="p-4 flex items-center justify-between cursor-pointer hover:bg-accent/50"
                onClick={() => toggleSection("telemetryAnomalies")}
              >
                <h2 className="text-lg font-semibold flex items-center gap-2">
                  <SpeedIcon className="text-primary" />
                  Telemetry Health
                  {telemetryReport.health && telemetryReport.health.overall_score != null && (
                    <>
                      {" - Score: "}
                      <span className={getHealthColor(telemetryReport.health.overall_score)}>
                        {telemetryReport.health.overall_score.toFixed(0)}
                      </span>
                    </>
                  )}
                </h2>
                {expandedSections.telemetryAnomalies ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              </div>

              {expandedSections.telemetryAnomalies && (
                <div className="p-4 border-t border-border space-y-4">
                  {telemetryReport.summary && typeof telemetryReport.summary === 'object' && telemetryReport.summary.narrative && (
                    <div className="bg-muted/30 p-3 rounded-lg">
                      <p className="text-sm text-muted-foreground">{telemetryReport.summary.narrative}</p>
                    </div>
                  )}

                  {/* Time-Series Plots */}
                  {telemetryReport.plot_data && telemetryReport.plot_data.metrics && telemetryReport.plot_data.metrics.length > 0 ? (
                    <div className="space-y-4">
                      <h3 className="text-sm font-semibold text-foreground">Metric Trends (Last 24 Hours)</h3>
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        {telemetryReport.plot_data.metrics.map((metric, idx) => {
                          // Count anomalies by severity
                          const severityCounts = { high: 0, medium: 0, low: 0, critical: 0 };
                          metric.anomaly_points?.severities?.forEach((sev: string) => {
                            if (sev === 'high' || sev === 'critical') severityCounts.high++;
                            else if (sev === 'medium') severityCounts.medium++;
                            else severityCounts.low++;
                          });
                          
                          const severityBadge = metric.has_anomalies ? 
                            [
                              severityCounts.high > 0 ? `${severityCounts.high} High` : null,
                              severityCounts.medium > 0 ? `${severityCounts.medium} Medium` : null,
                              severityCounts.low > 0 ? `${severityCounts.low} Low` : null,
                            ].filter(Boolean).join(', ') : '';
                          
                          return (
                            <div key={idx} className="bg-background border border-border rounded-lg p-4">
                              <h4 className="text-sm font-semibold mb-2 flex items-center justify-between">
                                <span>{metric.metric_label}</span>
                                {metric.has_anomalies && (
                                  <span className="text-xs bg-red-100 text-red-700 px-2 py-1 rounded">
                                    {severityBadge}
                                  </span>
                                )}
                              </h4>
                              <div className="relative" style={{ height: "240px" }}>
                                <svg width="100%" height="100%" viewBox="0 0 500 240" preserveAspectRatio="none">
                                  {/* Background grid */}
                                  <line x1="50" y1="10" x2="500" y2="10" stroke="currentColor" strokeWidth="0.5" opacity="0.1" />
                                  <line x1="50" y1="60" x2="500" y2="60" stroke="currentColor" strokeWidth="0.5" opacity="0.1" />
                                  <line x1="50" y1="110" x2="500" y2="110" stroke="currentColor" strokeWidth="0.5" opacity="0.1" />
                                  <line x1="50" y1="160" x2="500" y2="160" stroke="currentColor" strokeWidth="0.5" opacity="0.1" />
                                  
                                  {/* Threshold bands and lines */}
                                  {(() => {
                                    const values = metric.values;
                                    const minVal = Math.min(...values, metric.lower_threshold ?? Infinity);
                                    const maxVal = Math.max(...values, metric.upper_threshold ?? -Infinity);
                                    const range = maxVal - minVal || 1;
                                    const yScale = (val: number) => 200 - ((val - minVal) / range) * 180;
                                    
                                    const upperY = metric.upper_threshold != null ? yScale(metric.upper_threshold) : null;
                                    const lowerY = metric.lower_threshold != null ? yScale(metric.lower_threshold) : null;
                                    const meanY = metric.mean != null ? yScale(metric.mean) : null;
                                    
                                    // Format timestamp helper
                                    const formatTime = (ts: string | number) => {
                                      if (typeof ts === 'string' && ts.includes('T')) {
                                        const date = new Date(ts);
                                        return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
                                      }
                                      return '';
                                    };
                                    
                                    // Get time labels (show 5 timestamps evenly spaced)
                                    const timeLabels = [];
                                    for (let i = 0; i < 5; i++) {
                                      const idx = Math.floor((i / 4) * (metric.timestamps.length - 1));
                                      const ts = metric.timestamps[idx];
                                      const x = 50 + ((i / 4) * 450);
                                      timeLabels.push({ x, label: formatTime(ts) });
                                    }
                                    
                                    return (
                                      <>
                                        {/* Threshold zone */}
                                        {upperY != null && lowerY != null && (
                                        <rect
                                          x="50"
                                          y={upperY}
                                          width="450"
                                          height={lowerY - upperY}
                                          fill="green"
                                          opacity="0.05"
                                        />
                                        )}
                                        
                                        {/* Mean line */}
                                        {meanY != null && (
                                        <line
                                          x1="50"
                                          y1={meanY}
                                          x2="500"
                                          y2={meanY}
                                          stroke="blue"
                                          strokeWidth="1"
                                          strokeDasharray="4,4"
                                          opacity="0.5"
                                        />
                                        )}
                                        
                                        {/* Upper threshold */}
                                        {upperY != null && (
                                        <line
                                          x1="50"
                                          y1={upperY}
                                          x2="500"
                                          y2={upperY}
                                          stroke="orange"
                                          strokeWidth="1"
                                          strokeDasharray="2,2"
                                          opacity="0.6"
                                        />
                                        )}
                                        
                                        {/* Lower threshold */}
                                        {lowerY != null && (
                                        <line
                                          x1="50"
                                          y1={lowerY}
                                          x2="500"
                                          y2={lowerY}
                                          stroke="orange"
                                          strokeWidth="1"
                                          strokeDasharray="2,2"
                                          opacity="0.6"
                                        />
                                        )}
                                        
                                        {/* Value line */}
                                        <polyline
                                          points={values.map((val, i) => {
                                            const x = 50 + ((i / (values.length - 1 || 1)) * 450);
                                            const y = yScale(val);
                                            return `${x},${y}`;
                                          }).join(' ')}
                                          fill="none"
                                          stroke="currentColor"
                                          strokeWidth="2"
                                        />
                                        
                                        {/* Anomaly markers with vertical lines pointing to x-axis */}
                                        {metric.anomaly_points?.values.map((val, i) => {
                                          const timestamp = metric.anomaly_points?.timestamps[i];
                                          
                                          if (!timestamp) return null;
                                          
                                          // Find closest timestamp index (more robust matching)
                                          let timestampIdx = metric.timestamps.indexOf(timestamp);
                                          
                                          // If exact match fails, try to find by parsing timestamps
                                          if (timestampIdx === -1 && typeof timestamp === 'string') {
                                            const anomalyTime = new Date(timestamp).getTime();
                                            let closestIdx = 0;
                                            let closestDiff = Infinity;
                                            
                                            metric.timestamps.forEach((ts: any, idx: number) => {
                                              const tsTime = typeof ts === 'string' ? new Date(ts).getTime() : ts;
                                              const diff = Math.abs(tsTime - anomalyTime);
                                              if (diff < closestDiff) {
                                                closestDiff = diff;
                                                closestIdx = idx;
                                              }
                                            });
                                            
                                            // Use closest if within 5 minutes (300000ms)
                                            if (closestDiff < 300000) {
                                              timestampIdx = closestIdx;
                                            }
                                          }
                                          
                                          // If still not found, skip this anomaly marker
                                          if (timestampIdx === -1) {
                                            console.warn('Anomaly timestamp not found:', timestamp, 'in', metric.metric_label);
                                            return null;
                                          }
                                          
                                          const x = 50 + ((timestampIdx / (values.length - 1 || 1)) * 450);
                                          const y = yScale(val);
                                          const severity = metric.anomaly_points?.severities?.[i];
                                          const color = severity === 'high' || severity === 'critical' ? 'red' : 
                                                        severity === 'medium' ? 'orange' : '#16A34A'; // Green-600 for clear differentiation
                                          
                                          return (
                                            <g key={i}>
                                              {/* Vertical dotted line from value point to x-axis */}
                                              <line
                                                x1={x}
                                                y1={y}
                                                x2={x}
                                                y2="210"
                                                stroke={color}
                                                strokeWidth="2"
                                                strokeDasharray="3,3"
                                                opacity="0.8"
                                              />
                                            </g>
                                          );
                                        })}
                                        
                                        {/* X-axis time labels */}
                                        {timeLabels.map((tl, i) => (
                                          <text
                                            key={i}
                                            x={tl.x}
                                            y="230"
                                            fontSize="10"
                                            fill="currentColor"
                                            textAnchor="middle"
                                            opacity="0.6"
                                          >
                                            {tl.label}
                                          </text>
                                        ))}
                                        
                                        {/* Y-axis */}
                                        <line x1="50" y1="10" x2="50" y2="210" stroke="currentColor" strokeWidth="1" opacity="0.3" />
                                        {/* X-axis */}
                                        <line x1="50" y1="210" x2="500" y2="210" stroke="currentColor" strokeWidth="1" opacity="0.3" />
                                      </>
                                    );
                                  })()}
                                </svg>
                              </div>
                              <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
                                <div className="flex items-center gap-1">
                                  <div className="w-3 h-0.5 bg-blue-500 opacity-50"></div>
                                  <span>Mean</span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <div className="w-3 h-0.5 border-t-2 border-dashed border-orange-500"></div>
                                  <span>Threshold</span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <div className="w-2 h-2 rounded-full bg-red-500"></div>
                                  <span>High</span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <div className="w-2 h-2 rounded-full bg-orange-500"></div>
                                  <span>Med</span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: '#16A34A' }}></div>
                                  <span>Low</span>
                                </div>
                              </div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                Range: {metric.values.length > 0 ? Math.min(...metric.values).toFixed(1) : 0} - {metric.values.length > 0 ? Math.max(...metric.values).toFixed(1) : 0} {metric.unit}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground text-center py-4">
                      No telemetry data available for visualization
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Fleet Analysis Results */}
      {selectedMode === "fleet" && fleetReport && (
        <div className="bg-card border border-border rounded-lg">
          <div
            className="p-4 flex items-center justify-between cursor-pointer hover:bg-accent/50"
            onClick={() => toggleSection("fleetAnalysis")}
          >
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <GroupsIcon className="text-primary" />
              Fleet Analysis Results ({fleetReport.analyzed_cpes} / {fleetReport.total_cpes} CPEs)
            </h2>
            {expandedSections.fleetAnalysis ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </div>

          {expandedSections.fleetAnalysis && (
            <div className="p-4 border-t border-border space-y-4">
              {/* Summary */}
              <div className="bg-muted/30 p-3 rounded-lg">
                <p className="text-sm text-muted-foreground">{fleetReport.summary}</p>
              </div>

              {/* Health Distribution */}
              {fleetReport.health_distribution && (
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-green-50 border border-green-200 p-4 rounded-lg">
                  <p className="text-sm text-green-700">Healthy</p>
                  <p className="text-2xl font-bold text-green-700">
                    {fleetReport.health_distribution.healthy}
                  </p>
                </div>
                <div className="bg-yellow-50 border border-yellow-200 p-4 rounded-lg">
                  <p className="text-sm text-yellow-700">Warning</p>
                  <p className="text-2xl font-bold text-yellow-700">
                    {fleetReport.health_distribution.warning}
                  </p>
                </div>
                <div className="bg-red-50 border border-red-200 p-4 rounded-lg">
                  <p className="text-sm text-red-700">Critical</p>
                  <p className="text-2xl font-bold text-red-700">
                    {fleetReport.health_distribution.critical}
                  </p>
                </div>
              </div>
              )}

              {/* Fleet Anomaly Patterns */}
              {fleetReport.fleet_anomaly_patterns && fleetReport.fleet_anomaly_patterns.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-2">Fleet-Wide Anomaly Patterns</h3>
                  <div className="space-y-2">
                    {fleetReport.fleet_anomaly_patterns.map((pattern, idx) => (
                      <div key={idx} className="bg-secondary/30 p-3 rounded-lg flex justify-between">
                        <span className="text-sm font-mono">{pattern.pattern || pattern.template}</span>
                        <span className="text-sm text-muted-foreground">
                          {pattern.affected_cpes || pattern.cpe_count} CPEs affected
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Outlier CPEs */}
              {fleetReport.outlier_cpes && fleetReport.outlier_cpes.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-2">Outlier CPEs</h3>
                  <div className="flex flex-wrap gap-2">
                    {fleetReport.outlier_cpes.map((cpe) => (
                      <span
                        key={cpe.cpe_id}
                        className="px-3 py-1 bg-red-100 text-red-700 rounded-full text-xs font-mono"
                      >
                        {cpe.cpe_id}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Per-CPE Results Table */}
              <div>
                <h3 className="text-sm font-semibold mb-2">Per-CPE Results</h3>
                <div className="overflow-x-auto max-h-96 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-muted sticky top-0">
                      <tr>
                        <th className="p-2 text-left">CPE ID</th>
                        <th className="p-2 text-left">Health Score</th>
                        <th className="p-2 text-left">Log Anomalies</th>
                        <th className="p-2 text-left">Telemetry Anomalies</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fleetReport.per_cpe_summary && Object.entries(fleetReport.per_cpe_summary).map(([cpeId, result], idx) => (
                        <tr key={idx} className="border-t border-border hover:bg-accent/30">
                          <td className="p-2 font-mono text-xs">{cpeId}</td>
                          <td className="p-2">
                            <span className={`font-bold ${getHealthColor(result.overall_score)}`}>
                              {result.overall_score.toFixed(0)}
                            </span>
                          </td>
                          <td className="p-2">{result.log_anomaly_count}</td>
                          <td className="p-2">{result.telemetry_anomaly_count}</td>
                        </tr>
                      ))}
                      {fleetReport.per_cpe_results && fleetReport.per_cpe_results.map((result, idx) => (
                        <tr key={idx} className="border-t border-border hover:bg-accent/30">
                          <td className="p-2 font-mono text-xs">{result.cpe_id}</td>
                          <td className="p-2">
                            <span className={`font-bold ${getHealthColor(result.health_score ?? result.overall_score)}`}>
                              {(result.health_score ?? result.overall_score).toFixed(0)}
                            </span>
                          </td>
                          <td className="p-2">{result.log_anomalies ?? result.log_anomaly_count}</td>
                          <td className="p-2">{result.telemetry_anomalies ?? result.telemetry_anomaly_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Error Messages */}
      {logMutation.isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-700">
            Log analysis error: {(logMutation.error as Error).message}
          </p>
        </div>
      )}
      {telemetryMutation.isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-700">
            Telemetry analysis error: {(telemetryMutation.error as Error).message}
          </p>
        </div>
      )}
      {fleetMutation.isError && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-700">
            Fleet analysis error: {(fleetMutation.error as Error).message}
          </p>
        </div>
      )}

      {/* Empty State */}
      {selectedMode === "single-cpe" && !logReport && !telemetryReport && !logMutation.isPending && !telemetryMutation.isPending && (
        <div className="bg-muted/30 border border-border rounded-lg p-8 text-center">
          <TimelineIcon className="text-muted-foreground mb-2" style={{ fontSize: 48 }} />
          <p className="text-muted-foreground">
            {cpeId
              ? "Click 'Run Log Analysis' or 'Run Telemetry Analysis' to start"
              : "Please select a CPE from the dropdown above"}
          </p>
        </div>
      )}
      {selectedMode === "fleet" && !fleetReport && !fleetMutation.isPending && (
        <div className="bg-muted/30 border border-border rounded-lg p-8 text-center">
          <GroupsIcon className="text-muted-foreground mb-2" style={{ fontSize: 48 }} />
          <p className="text-muted-foreground">
            Click 'Run Fleet Analysis' to analyze all {cpeList.length} CPEs
          </p>
        </div>
      )}
    </div>
  );
}

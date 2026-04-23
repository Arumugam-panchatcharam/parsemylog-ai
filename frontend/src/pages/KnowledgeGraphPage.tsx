import { useState, useCallback, useRef, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
  type Node,
  type Edge,
  type OnConnect,
  type NodeTypes,
  type NodeProps,
  Handle,
  Position,
  Panel,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {
  knowledgeGraphApi,
  type KnowledgeGraphSummary,
  type KnowledgeNodeData,
  type KnowledgeEdgeData,
} from "../api/endpoints";

import { ArchitectureGraphView } from "@/components/knowledge-graph/ArchitectureGraphView";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useTheme";

import CircularProgress from "@mui/material/CircularProgress";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import SaveIcon from "@mui/icons-material/Save";
import DownloadIcon from "@mui/icons-material/Download";
import AutoFixHighIcon from "@mui/icons-material/AutoFixHigh";
import CloseIcon from "@mui/icons-material/Close";
import HubIcon from "@mui/icons-material/Hub";
import FileUploadIcon from "@mui/icons-material/FileUpload";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";

// ---------------------------------------------------------------------------
// Node type colors & styles
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  EVENT:      { bg: "bg-blue-50 dark:bg-blue-950/40",   border: "border-blue-400 dark:border-blue-600",   text: "text-blue-700 dark:text-blue-300" },
  CONDITION:  { bg: "bg-yellow-50 dark:bg-yellow-950/40", border: "border-yellow-400 dark:border-yellow-600", text: "text-yellow-700 dark:text-yellow-300" },
  ISSUE:      { bg: "bg-orange-50 dark:bg-orange-950/40", border: "border-orange-400 dark:border-orange-600", text: "text-orange-700 dark:text-orange-300" },
  ROOT_CAUSE: { bg: "bg-red-50 dark:bg-red-950/40",     border: "border-red-400 dark:border-red-600",     text: "text-red-700 dark:text-red-300" },
  SUBGRAPH:   { bg: "bg-purple-50 dark:bg-purple-950/40", border: "border-purple-400 dark:border-purple-600", text: "text-purple-700 dark:text-purple-300" },
};

const NODE_TYPE_LABELS: Record<string, string> = {
  EVENT: "Event",
  CONDITION: "Condition",
  ISSUE: "Issue",
  ROOT_CAUSE: "Root Cause",
  SUBGRAPH: "Subgraph",
};

// ---------------------------------------------------------------------------
// Custom ReactFlow node
// ---------------------------------------------------------------------------

function KGNode({ data, selected }: NodeProps) {
  const d = data as KnowledgeNodeData & { onEdit?: (id: string) => void; _refGraphName?: string };
  const colors = NODE_COLORS[d.node_type] ?? NODE_COLORS.EVENT;

  return (
    <div
      className={`rounded-lg border-2 px-3 py-2 min-w-[160px] max-w-[240px] shadow-sm transition-shadow
        ${colors.bg} ${colors.border} ${selected ? "ring-2 ring-blue-500" : ""}`}
    >
      <Handle type="target" position={Position.Top} className="!w-2.5 !h-2.5 !bg-gray-400" />
      <div className="flex items-center gap-1.5 mb-1">
        <span className={`text-[10px] font-bold uppercase tracking-wider ${colors.text}`}>
          {NODE_TYPE_LABELS[d.node_type] ?? d.node_type}
        </span>
        {d.domain && (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
            {d.domain}
          </span>
        )}
      </div>
      <div className="text-sm font-semibold truncate">{d.label || d.name}</div>
      {d.node_type === "SUBGRAPH" && d._refGraphName && (
        <div className="text-[10px] mt-0.5 flex items-center gap-1 text-purple-600 dark:text-purple-400">
          <HubIcon sx={{ fontSize: 10 }} />
          <span className="truncate">{d._refGraphName}</span>
        </div>
      )}
      {d.description && (
        <div className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">{d.description}</div>
      )}
      <Handle type="source" position={Position.Bottom} className="!w-2.5 !h-2.5 !bg-gray-400" />
    </div>
  );
}

function ColumnHeaderNode({ data }: NodeProps) {
  const c = NODE_COLORS[data.columnType as string] ?? NODE_COLORS.EVENT;
  return (
    <div
      className={`text-[11px] font-bold uppercase tracking-wider px-4 py-1.5 rounded-md border ${c.bg} ${c.border} ${c.text} text-center pointer-events-none select-none`}
      style={{ minWidth: 140 }}
    >
      {data.label as string}
    </div>
  );
}

const nodeTypes: NodeTypes = { kgNode: KGNode, columnHeader: ColumnHeaderNode };

// ---------------------------------------------------------------------------
// Edge styling by type
// ---------------------------------------------------------------------------

const EDGE_STYLES: Record<string, Partial<Edge>> = {
  COULD_CAUSE:     { style: { stroke: "#f97316", strokeDasharray: "6 3" }, animated: true },
  LEADS_TO:        { style: { stroke: "#3b82f6" } },
  INDICATES:       { style: { stroke: "#22c55e", strokeDasharray: "3 3" } },
  CORRELATES_WITH: { style: { stroke: "#a855f7", strokeDasharray: "2 4" } },
};

function toFlowEdge(e: KnowledgeEdgeData): Edge {
  const extra = EDGE_STYLES[e.relationship_type] ?? {};
  return {
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    label: e.label ?? e.relationship_type,
    markerEnd: { type: MarkerType.ArrowClosed },
    data: e,
    ...extra,
  };
}

const TYPE_COLUMN_ORDER = ["EVENT", "CONDITION", "ISSUE", "ROOT_CAUSE"];
const COLUMN_LABELS: Record<string, string> = {
  EVENT: "Event",
  CONDITION: "Condition",
  ISSUE: "Issue",
  ROOT_CAUSE: "Root Cause",
};
const COLUMN_X_SPACING = 300;
const ROW_Y_SPACING = 140;
const COLUMN_X_START = 50;
const ROW_Y_START = 80;

function layoutColumn(t: string): string {
  return t === "SUBGRAPH" ? "EVENT" : t;
}

function autoLayoutNodes(nodes: KnowledgeNodeData[]): Node[] {
  const allAtOrigin = nodes.every((n) => n.position_x === 0 && n.position_y === 0);
  if (!allAtOrigin) {
    return nodes.map((n) => ({
      id: n.id,
      type: "kgNode",
      position: { x: n.position_x, y: n.position_y },
      data: n,
    }));
  }
  const byType: Record<string, KnowledgeNodeData[]> = {};
  for (const n of nodes) {
    const t = layoutColumn(n.node_type || "EVENT");
    (byType[t] ??= []).push(n);
  }
  const result: Node[] = [];
  for (let col = 0; col < TYPE_COLUMN_ORDER.length; col++) {
    const type = TYPE_COLUMN_ORDER[col];
    const group = byType[type] ?? [];
    for (let row = 0; row < group.length; row++) {
      const n = group[row];
      result.push({
        id: n.id,
        type: "kgNode",
        position: {
          x: COLUMN_X_START + col * COLUMN_X_SPACING,
          y: ROW_Y_START + row * ROW_Y_SPACING,
        },
        data: n,
      });
    }
  }
  return result;
}

function forceColumnLayout(nodes: KnowledgeNodeData[]): Node[] {
  const byType: Record<string, KnowledgeNodeData[]> = {};
  for (const n of nodes) {
    const t = layoutColumn(n.node_type || "EVENT");
    (byType[t] ??= []).push(n);
  }
  const result: Node[] = [];
  for (let col = 0; col < TYPE_COLUMN_ORDER.length; col++) {
    const type = TYPE_COLUMN_ORDER[col];
    const group = byType[type] ?? [];
    for (let row = 0; row < group.length; row++) {
      const n = group[row];
      result.push({
        id: n.id,
        type: "kgNode",
        position: {
          x: COLUMN_X_START + col * COLUMN_X_SPACING,
          y: ROW_Y_START + row * ROW_Y_SPACING,
        },
        data: n,
      });
    }
  }
  return result;
}

function columnHeaderNodes(): Node[] {
  return TYPE_COLUMN_ORDER.map((type, col) => ({
    id: `__header_${type}`,
    type: "columnHeader",
    position: {
      x: COLUMN_X_START + col * COLUMN_X_SPACING - 10,
      y: 10,
    },
    data: { label: COLUMN_LABELS[type], columnType: type },
    draggable: false,
    selectable: false,
    connectable: false,
  }));
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function KnowledgeGraphPage() {
  const qc = useQueryClient();
  const { resolvedTheme } = useTheme();
  const flowDotColor =
    resolvedTheme === "dark" ? "rgba(154, 160, 166, 0.35)" : "rgba(95, 99, 104, 0.35)";

  // Graph list
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(224);

  const { data: graphs, isLoading: graphsLoading } = useQuery({
    queryKey: ["knowledgeGraphs"],
    queryFn: async () => (await knowledgeGraphApi.list()).data,
  });
  const { data: templates } = useQuery({
    queryKey: ["kgTemplates"],
    queryFn: async () => (await knowledgeGraphApi.listTemplates()).data,
  });

  const [selectedGraphId, setSelectedGraphId] = useState<string | null>(null);
  const [editingNode, setEditingNode] = useState<KnowledgeNodeData | null>(null);
  const [editingEdge, setEditingEdge] = useState<KnowledgeEdgeData | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newGraphName, setNewGraphName] = useState("");
  const [newGraphDesc, setNewGraphDesc] = useState("");
  const [activeView, setActiveView] = useState<"editor" | "architecture">("editor");

  // Load selected graph
  const { data: graphData, isLoading: graphLoading } = useQuery({
    queryKey: ["knowledgeGraph", selectedGraphId],
    queryFn: async () => (await knowledgeGraphApi.get(selectedGraphId!)).data,
    enabled: !!selectedGraphId,
  });

  // ReactFlow state
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const loadedGraphRef = useRef<string | null>(null);
  const isResizing = useRef(false);
  const [pendingLayout, setPendingLayout] = useState<Node[] | null>(null);

  const enrichedNodes = useMemo(() => {
    if (!graphData) return [];
    return graphData.nodes.map((n) => {
      if (n.node_type === "SUBGRAPH" && n.detection_config?.referenced_graph_id) {
        const refGraph = graphs?.find((g) => g.id === n.detection_config?.referenced_graph_id);
        return { ...n, _refGraphName: refGraph?.name ?? "(unknown)" } as KnowledgeNodeData & { _refGraphName?: string };
      }
      return n;
    });
  }, [graphData, graphs]);

  // Clear canvas immediately when switching graphs (before new data loads)
  useEffect(() => {
    loadedGraphRef.current = null;
    setNodes([]);
    setEdges([]);
  }, [selectedGraphId, setNodes, setEdges]);

  // Populate canvas once graph data arrives
  useEffect(() => {
    if (!graphData) return;

    const isFirstLoad = loadedGraphRef.current !== selectedGraphId;

    if (isFirstLoad) {
      const headers = columnHeaderNodes();
      let laid: Node[] = [];
      if (enrichedNodes.length > 0) {
        const allAtOrigin = enrichedNodes.every((n) => n.position_x === 0 && n.position_y === 0);
        laid = autoLayoutNodes(enrichedNodes as KnowledgeNodeData[]);
        if (allAtOrigin && laid.length > 0) {
          setPendingLayout(laid);
        }
      }
      setNodes([...headers, ...laid]);
      setEdges(graphData.edges.map(toFlowEdge));
      loadedGraphRef.current = selectedGraphId;
    } else {
      // Same graph refetched (after add/delete) -- preserve canvas positions
      setNodes((prev) => {
        const headers = columnHeaderNodes();
        const posMap = new Map(
          prev.filter((n) => !n.id.startsWith("__header_")).map((n) => [n.id, n.position]),
        );
        const updated = (enrichedNodes as KnowledgeNodeData[]).map((n) => ({
          id: n.id,
          type: "kgNode",
          position: posMap.get(n.id) ?? { x: Math.random() * 400 + 100, y: Math.random() * 300 + 100 },
          data: n,
        }));
        return [...headers, ...updated];
      });
      setEdges(graphData.edges.map(toFlowEdge));
    }
  }, [enrichedNodes, graphData, selectedGraphId, setNodes, setEdges]);

  // Mutations
  const createGraphMut = useMutation({
    mutationFn: (data: { name: string; description?: string }) =>
      knowledgeGraphApi.create(data),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["knowledgeGraphs"] });
      setSelectedGraphId(res.data.id);
      setShowCreateDialog(false);
      setNewGraphName("");
      setNewGraphDesc("");
    },
  });

  const importMut = useMutation({
    mutationFn: (template: string) =>
      knowledgeGraphApi.importGraph({ template }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["knowledgeGraphs"] });
      setSelectedGraphId(res.data.id);
    },
  });

  const importJsonMut = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      knowledgeGraphApi.importGraph(payload as { template?: string } & Record<string, unknown>),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["knowledgeGraphs"] });
      setSelectedGraphId(res.data.id);
    },
  });

  const fileInputRef = useRef<HTMLInputElement>(null);
  const handleImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const json = JSON.parse(reader.result as string);
        importJsonMut.mutate(json);
      } catch {
        alert("Invalid JSON file");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const deleteGraphMut = useMutation({
    mutationFn: (id: string) => knowledgeGraphApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["knowledgeGraphs"] });
      setSelectedGraphId(null);
    },
  });

  const addNodeMut = useMutation({
    mutationFn: (data: Partial<KnowledgeNodeData>) =>
      knowledgeGraphApi.createNode(selectedGraphId!, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledgeGraph", selectedGraphId] }),
  });

  const updateNodeMut = useMutation({
    mutationFn: ({ nodeId, data }: { nodeId: string; data: Partial<KnowledgeNodeData> }) =>
      knowledgeGraphApi.updateNode(selectedGraphId!, nodeId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledgeGraph", selectedGraphId] }),
  });

  // Persist auto-layout positions to the server so they survive refetches
  useEffect(() => {
    if (!pendingLayout || !selectedGraphId) return;
    const toSave = pendingLayout;
    setPendingLayout(null);
    for (const n of toSave) {
      knowledgeGraphApi.updateNode(selectedGraphId, n.id, {
        position_x: n.position.x,
        position_y: n.position.y,
      });
    }
  }, [pendingLayout, selectedGraphId]);

  const deleteNodeMut = useMutation({
    mutationFn: (nodeId: string) => knowledgeGraphApi.deleteNode(selectedGraphId!, nodeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["knowledgeGraph", selectedGraphId] });
      setEditingNode(null);
    },
  });

  const addEdgeMut = useMutation({
    mutationFn: (data: Partial<KnowledgeEdgeData>) =>
      knowledgeGraphApi.createEdge(selectedGraphId!, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledgeGraph", selectedGraphId] }),
  });

  const updateEdgeMut = useMutation({
    mutationFn: ({ edgeId, data }: { edgeId: string; data: Partial<KnowledgeEdgeData> }) =>
      knowledgeGraphApi.updateEdge(selectedGraphId!, edgeId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledgeGraph", selectedGraphId] }),
  });

  const deleteEdgeMut = useMutation({
    mutationFn: (edgeId: string) => knowledgeGraphApi.deleteEdge(selectedGraphId!, edgeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["knowledgeGraph", selectedGraphId] });
      setEditingEdge(null);
    },
  });

  // Handlers
  const onConnect: OnConnect = useCallback(
    (connection) => {
      if (!selectedGraphId) return;
      addEdgeMut.mutate({
        source_node_id: connection.source!,
        target_node_id: connection.target!,
        relationship_type: "COULD_CAUSE",
        conditions: { source_min_count: 1, confidence: 0.5 },
        label: "COULD_CAUSE",
      });
    },
    [selectedGraphId, addEdgeMut],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.id.startsWith("__header_")) return;
      setEditingNode(node.data as KnowledgeNodeData);
      setEditingEdge(null);
    },
    [],
  );

  const onEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      setEditingEdge(edge.data as KnowledgeEdgeData);
      setEditingNode(null);
    },
    [],
  );

  const onNodeDragStop = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (!selectedGraphId || node.id.startsWith("__header_")) return;
      updateNodeMut.mutate({
        nodeId: node.id,
        data: { position_x: node.position.x, position_y: node.position.y },
      });
    },
    [selectedGraphId, updateNodeMut],
  );

  const handleAddNode = (nodeType: string) => {
    if (!selectedGraphId) return;
    const x = Math.random() * 400 + 100;
    const y = Math.random() * 300 + 100;
    addNodeMut.mutate({
      node_type: nodeType as KnowledgeNodeData["node_type"],
      name: `new_${nodeType.toLowerCase()}`,
      label: `New ${NODE_TYPE_LABELS[nodeType] ?? nodeType}`,
      position_x: x,
      position_y: y,
    });
  };

  const handleExport = async () => {
    if (!selectedGraphId) return;
    const res = await knowledgeGraphApi.exportGraph(selectedGraphId);
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `knowledge_graph_${selectedGraphId.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

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

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="h-[calc(100vh-4rem)] flex">
      {/* Left sidebar - graph list */}
      <div 
        className={cn("border-r border-border bg-card flex flex-col overflow-hidden transition-all relative", sidebarCollapsed && "transition-none")}
        style={{ width: sidebarCollapsed ? 40 : sidebarWidth }}
      >
        <div className="flex items-center justify-between px-2 py-1.5 border-b border-border">
          {!sidebarCollapsed && (
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <HubIcon fontSize="small" className="text-blue-500" />
              Knowledge Graphs
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
            <div className="p-3 border-b border-border">
              <div className="flex gap-1.5">
                <button
                  onClick={() => setShowCreateDialog(true)}
                  className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  <AddIcon fontSize="small" /> New Graph
                </button>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={importJsonMut.isPending}
                  className="flex items-center justify-center gap-1 px-2.5 py-1.5 text-xs border border-border rounded-lg hover:bg-muted"
                  title="Import graph from JSON file"
                >
                  <FileUploadIcon sx={{ fontSize: 16 }} />
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json"
                  onChange={handleImportFile}
                  className="hidden"
                />
              </div>
            </div>

            {/* Architecture */}
            <div className="px-3 py-2 border-b border-border">
              <button
                onClick={() => setActiveView("architecture")}
                className={`w-full text-left text-xs px-2 py-1.5 rounded flex items-center gap-1.5 ${
                  activeView === "architecture"
                    ? "bg-blue-100 dark:bg-blue-900/40 border border-blue-300 dark:border-blue-700 font-medium text-blue-900 dark:text-blue-100"
                    : "hover:bg-muted text-muted-foreground"
                }`}
              >
                <HubIcon sx={{ fontSize: 16 }} className={activeView === "architecture" ? "text-blue-600 dark:text-blue-400" : ""} />
                <span>RDK-B Architecture</span>
              </button>
            </div>

            {/* Templates */}
            {templates && templates.length > 0 && (
              <div className="px-3 py-2 border-b border-border">
                <div className="text-[10px] uppercase text-muted-foreground font-semibold mb-1.5">Templates</div>
                {templates.map((t) => (
                  <button
                    key={t.filename}
                    onClick={() => importMut.mutate(t.filename)}
                    disabled={importMut.isPending}
                    className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-muted mb-1 flex items-center gap-1"
                  >
                    <AddIcon sx={{ fontSize: 14 }} className="text-muted-foreground" />
                    <span className="truncate">{t.name}</span>
                    <span className="ml-auto text-[10px] text-muted-foreground">{t.node_count}n</span>
                  </button>
                ))}
              </div>
            )}

            {/* Graph list */}
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {graphsLoading && (
                <div className="flex justify-center py-4"><CircularProgress size={20} /></div>
              )}
              {graphs?.map((g) => (
                <div
                  key={g.id}
                  className={`group flex items-center gap-1 px-2.5 py-2 rounded-lg text-xs transition-colors cursor-pointer ${
                    selectedGraphId === g.id && activeView === "editor"
                      ? "bg-blue-100 dark:bg-blue-900/40 border border-blue-300 dark:border-blue-700"
                      : "hover:bg-muted"
                  }`}
                  onClick={() => {
                    setSelectedGraphId(g.id);
                    setActiveView("editor");
                    setEditingNode(null);
                    setEditingEdge(null);
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{g.name}</div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Delete "${g.name}"?`)) {
                        deleteGraphMut.mutate(g.id);
                      }
                    }}
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-red-500 transition-opacity"
                title="Delete graph"
              >
                <DeleteIcon sx={{ fontSize: 14 }} />
              </button>
            </div>
          ))}
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

      {/* Main canvas area */}
      <div className="flex-1 relative flex flex-col">
        <div className="flex-1 relative overflow-hidden">
          {activeView === "architecture" ? (
            <div className="h-full min-h-0 p-2 md:p-4">
              <ArchitectureGraphView />
            </div>
          ) : !selectedGraphId ? (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <div className="text-center">
                <HubIcon sx={{ fontSize: 48 }} className="text-muted-foreground/30 mb-3" />
                <p>Select or create a knowledge graph to get started</p>
              </div>
            </div>
          ) : graphLoading ? (
            <div className="flex items-center justify-center h-full">
              <CircularProgress size={32} />
            </div>
          ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onNodeDragStop={onNodeDragStop}
            nodeTypes={nodeTypes}
            fitView
            className="bg-background"
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color={flowDotColor} />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                if (n.id.startsWith("__header_")) return "transparent";
                const nt = (n.data as KnowledgeNodeData)?.node_type;
                if (nt === "EVENT") return "#3b82f6";
                if (nt === "CONDITION") return "#eab308";
                if (nt === "ISSUE") return "#f97316";
                if (nt === "ROOT_CAUSE") return "#ef4444";
                if (nt === "SUBGRAPH") return "#a855f7";
                return "#888";
              }}
            />

            {/* Toolbar panel */}
            <Panel position="top-left" className="flex gap-1.5 flex-wrap">
              {Object.entries(NODE_TYPE_LABELS).map(([type, label]) => {
                const c = NODE_COLORS[type];
                return (
                  <button
                    key={type}
                    onClick={() => handleAddNode(type)}
                    className={`px-2.5 py-1 text-xs rounded-md border ${c.bg} ${c.border} ${c.text} hover:opacity-80`}
                  >
                    + {label}
                  </button>
                );
              })}
              <span className="w-px bg-border" />
              <button
                onClick={() => {
                  if (!enrichedNodes.length) return;
                  const forced = forceColumnLayout(enrichedNodes as KnowledgeNodeData[]);
                  setNodes([...columnHeaderNodes(), ...forced]);
                  for (const n of forced) {
                    updateNodeMut.mutate({
                      nodeId: n.id,
                      data: { position_x: n.position.x, position_y: n.position.y },
                    });
                  }
                }}
                className="px-2.5 py-1 text-xs rounded-md border border-border bg-card hover:bg-muted flex items-center gap-1"
                title="Auto-arrange nodes in columns by type"
              >
                <AutoFixHighIcon sx={{ fontSize: 14 }} /> Layout
              </button>
              <button
                onClick={handleExport}
                className="px-2.5 py-1 text-xs rounded-md border border-border bg-card hover:bg-muted flex items-center gap-1"
              >
                <DownloadIcon sx={{ fontSize: 14 }} /> Export
              </button>
            </Panel>


          </ReactFlow>
          )}
        </div>
      </div>

      {/* Right panel - property editor */}
      {(editingNode || editingEdge) && activeView === "editor" && (
        <div className="w-80 border-l border-border bg-card overflow-y-auto">
          {editingNode && (
            <NodeEditor
              node={editingNode}
              graphs={graphs ?? []}
              currentGraphId={selectedGraphId}
              onUpdate={(data) =>
                updateNodeMut.mutate({ nodeId: editingNode.id, data })
              }
              onDelete={() => deleteNodeMut.mutate(editingNode.id)}
              onClose={() => setEditingNode(null)}
            />
          )}
          {editingEdge && (
            <EdgeEditor
              edge={editingEdge}
              nodes={graphData?.nodes ?? []}
              onUpdate={(data) =>
                updateEdgeMut.mutate({ edgeId: editingEdge.id, data })
              }
              onDelete={() => deleteEdgeMut.mutate(editingEdge.id)}
              onClose={() => setEditingEdge(null)}
            />
          )}
        </div>
      )}

      {/* Create dialog */}
      {showCreateDialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl border border-border p-6 w-96 shadow-xl">
            <h3 className="text-lg font-semibold mb-4">Create Knowledge Graph</h3>
            <div className="space-y-3">
              <input
                value={newGraphName}
                onChange={(e) => setNewGraphName(e.target.value)}
                placeholder="Graph name"
                className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background"
              />
              <textarea
                value={newGraphDesc}
                onChange={(e) => setNewGraphDesc(e.target.value)}
                placeholder="Description (optional)"
                rows={3}
                className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background resize-none"
              />
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => { setShowCreateDialog(false); }}
                className="px-3 py-1.5 text-sm rounded-lg border border-border hover:bg-muted"
              >
                Cancel
              </button>
              <button
                onClick={() =>
                  createGraphMut.mutate({
                    name: newGraphName,
                    description: newGraphDesc,
                  })
                }
                disabled={!newGraphName.trim() || createGraphMut.isPending}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Node property editor
// ---------------------------------------------------------------------------

function NodeEditor({
  node,
  graphs,
  currentGraphId,
  onUpdate,
  onDelete,
  onClose,
}: {
  node: KnowledgeNodeData;
  graphs: KnowledgeGraphSummary[];
  currentGraphId: string | null;
  onUpdate: (data: Partial<KnowledgeNodeData>) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(node.name);
  const [label, setLabel] = useState(node.label);
  const [domain, setDomain] = useState(node.domain ?? "");
  const [desc, setDesc] = useState(node.description ?? "");
  const [nodeType, setNodeType] = useState(node.node_type);
  const [keywords, setKeywords] = useState(
    node.detection_config?.keywords?.join("\n") ?? ""
  );
  const [sourceDomains, setSourceDomains] = useState(
    node.detection_config?.source_domains?.join(", ") ?? ""
  );
  const [exclusions, setExclusions] = useState(
    node.detection_config?.exclusions?.join("\n") ?? ""
  );
  const [patterns, setPatterns] = useState(
    node.detection_config?.patterns?.join("\n") ?? ""
  );
  const [templatePatterns, setTemplatePatterns] = useState(
    node.detection_config?.template_patterns?.join("\n") ?? ""
  );
  const [templateKeywords, setTemplateKeywords] = useState(
    node.detection_config?.template_keywords?.join("\n") ?? ""
  );
  const [refGraphId, setRefGraphId] = useState(
    node.detection_config?.referenced_graph_id ?? ""
  );
  const [activationMode, setActivationMode] = useState<"any_issue" | "all_issues">(
    node.detection_config?.activation_mode ?? "any_issue"
  );

  useEffect(() => {
    setName(node.name);
    setLabel(node.label);
    setDomain(node.domain ?? "");
    setDesc(node.description ?? "");
    setNodeType(node.node_type);
    setKeywords(node.detection_config?.keywords?.join("\n") ?? "");
    setSourceDomains(node.detection_config?.source_domains?.join(", ") ?? "");
    setExclusions(node.detection_config?.exclusions?.join("\n") ?? "");
    setPatterns(node.detection_config?.patterns?.join("\n") ?? "");
    setTemplatePatterns(node.detection_config?.template_patterns?.join("\n") ?? "");
    setTemplateKeywords(node.detection_config?.template_keywords?.join("\n") ?? "");
    setRefGraphId(node.detection_config?.referenced_graph_id ?? "");
    setActivationMode(node.detection_config?.activation_mode ?? "any_issue");
  }, [node]);

  const availableGraphs = graphs.filter((g) => g.id !== currentGraphId);

  const handleSave = () => {
    let dc: KnowledgeNodeData["detection_config"] = null;
    if (nodeType === "EVENT") {
      const patLines = patterns
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      const tmplPatLines = templatePatterns
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      const tmplKwLines = templateKeywords
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      dc = {
        method: "keyword",
        keywords: keywords
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        patterns: patLines.length ? patLines : undefined,
        source_domains: sourceDomains
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        template_patterns: tmplPatLines.length ? tmplPatLines : undefined,
        template_keywords: tmplKwLines.length ? tmplKwLines : undefined,
        exclusions: exclusions
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      };
    } else if (nodeType === "SUBGRAPH") {
      dc = {
        method: "subgraph",
        referenced_graph_id: refGraphId || undefined,
        activation_mode: activationMode,
      };
    }

    onUpdate({
      name,
      label,
      domain: domain || null,
      description: desc || null,
      node_type: nodeType,
      detection_config: dc,
    });
  };

  const colors = NODE_COLORS[nodeType] ?? NODE_COLORS.EVENT;

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className={`font-semibold text-sm ${colors.text}`}>
          {NODE_TYPE_LABELS[nodeType]} Node
        </h3>
        <button onClick={onClose} className="p-1 rounded hover:bg-muted">
          <CloseIcon fontSize="small" />
        </button>
      </div>

      <div className="space-y-3 text-sm">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Type</label>
          <select
            value={nodeType}
            onChange={(e) => setNodeType(e.target.value as KnowledgeNodeData["node_type"])}
            className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background"
          >
            {Object.entries(NODE_TYPE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-muted-foreground mb-1">Name (ID)</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background font-mono"
          />
        </div>

        <div>
          <label className="block text-xs text-muted-foreground mb-1">Label</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background"
          />
        </div>

        <div>
          <label className="block text-xs text-muted-foreground mb-1">Domain</label>
          <input
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="e.g. wireless, core_router"
            className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background"
          />
        </div>

        <div>
          <label className="block text-xs text-muted-foreground mb-1">Description</label>
          <textarea
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            rows={2}
            className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background resize-none"
          />
        </div>

        {nodeType === "EVENT" && (
          <>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Keywords / Regex (one per line)
              </label>
              <textarea
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                rows={5}
                placeholder={"\\bdisassoc\n\\bdeauth\ndisconnected\\s+event"}
                className="w-full px-2 py-1.5 text-xs border border-border rounded-md bg-background resize-none font-mono"
              />
            </div>

            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Log line regex — patterns (one per line, optional)
              </label>
              <textarea
                value={patterns}
                onChange={(e) => setPatterns(e.target.value)}
                rows={3}
                placeholder={"Separate from keywords when using explicit patterns[] API"}
                className="w-full px-2 py-1.5 text-xs border border-border rounded-md bg-background resize-none font-mono"
              />
            </div>

            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Drain3 template regex (one per line, optional)
              </label>
              <textarea
                value={templatePatterns}
                onChange={(e) => setTemplatePatterns(e.target.value)}
                rows={3}
                placeholder={"WIFI.*disassoc\n<*>\\s+timeout"}
                className="w-full px-2 py-1.5 text-xs border border-border rounded-md bg-background resize-none font-mono"
              />
            </div>

            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Drain3 template substrings (one per line, optional)
              </label>
              <textarea
                value={templateKeywords}
                onChange={(e) => setTemplateKeywords(e.target.value)}
                rows={2}
                placeholder={"disassoc\ntimeout"}
                className="w-full px-2 py-1.5 text-xs border border-border rounded-md bg-background resize-none font-mono"
              />
            </div>

            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Source Domains (comma-separated)
              </label>
              <input
                value={sourceDomains}
                onChange={(e) => setSourceDomains(e.target.value)}
                placeholder="wireless, platform"
                className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background font-mono"
              />
            </div>

            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Exclusions (one per line)
              </label>
              <textarea
                value={exclusions}
                onChange={(e) => setExclusions(e.target.value)}
                rows={2}
                className="w-full px-2 py-1.5 text-xs border border-border rounded-md bg-background resize-none font-mono"
              />
            </div>
          </>
        )}

        {nodeType === "SUBGRAPH" && (
          <>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Referenced Graph
              </label>
              <select
                value={refGraphId}
                onChange={(e) => setRefGraphId(e.target.value)}
                className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background"
              >
                <option value="">-- Select a graph --</option>
                {availableGraphs.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Activation Mode
              </label>
              <div className="space-y-1.5">
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="radio"
                    name="activation_mode"
                    checked={activationMode === "any_issue"}
                    onChange={() => setActivationMode("any_issue")}
                    className="accent-purple-600"
                  />
                  Any issue activates
                </label>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="radio"
                    name="activation_mode"
                    checked={activationMode === "all_issues"}
                    onChange={() => setActivationMode("all_issues")}
                    className="accent-purple-600"
                  />
                  All issues must activate
                </label>
              </div>
            </div>
          </>
        )}
      </div>

      <div className="flex gap-2 mt-4">
        <button
          onClick={handleSave}
          className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          <SaveIcon sx={{ fontSize: 14 }} /> Save
        </button>
        <button
          onClick={() => { if (confirm("Delete this node?")) onDelete(); }}
          className="px-3 py-1.5 text-xs border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/30"
        >
          <DeleteIcon sx={{ fontSize: 14 }} />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Edge property editor
// ---------------------------------------------------------------------------

function EdgeEditor({
  edge,
  nodes,
  onUpdate,
  onDelete,
  onClose,
}: {
  edge: KnowledgeEdgeData;
  nodes: KnowledgeNodeData[];
  onUpdate: (data: Partial<KnowledgeEdgeData>) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [relType, setRelType] = useState(edge.relationship_type);
  const [label, setLabel] = useState(edge.label ?? "");
  const [desc, setDesc] = useState(edge.description ?? "");
  const [minCount, setMinCount] = useState(edge.conditions?.source_min_count ?? 1);
  const [timeWindow, setTimeWindow] = useState(edge.conditions?.time_window_minutes ?? 60);
  const [confidence, setConfidence] = useState(edge.conditions?.confidence ?? 0.5);

  useEffect(() => {
    setRelType(edge.relationship_type);
    setLabel(edge.label ?? "");
    setDesc(edge.description ?? "");
    setMinCount(edge.conditions?.source_min_count ?? 1);
    setTimeWindow(edge.conditions?.time_window_minutes ?? 60);
    setConfidence(edge.conditions?.confidence ?? 0.5);
  }, [edge]);

  const srcNode = nodes.find((n) => n.id === edge.source_node_id);
  const tgtNode = nodes.find((n) => n.id === edge.target_node_id);

  const handleSave = () => {
    onUpdate({
      relationship_type: relType,
      label: label || relType,
      description: desc || null,
      conditions: {
        source_min_count: minCount,
        time_window_minutes: timeWindow,
        confidence,
      },
    });
  };

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-sm">Edge Properties</h3>
        <button onClick={onClose} className="p-1 rounded hover:bg-muted">
          <CloseIcon fontSize="small" />
        </button>
      </div>

      <div className="text-xs mb-3 p-2 rounded-md bg-muted">
        <span className="font-medium">{srcNode?.label ?? edge.source_node_id}</span>
        <span className="mx-2 text-muted-foreground">&rarr;</span>
        <span className="font-medium">{tgtNode?.label ?? edge.target_node_id}</span>
      </div>

      <div className="space-y-3 text-sm">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Relationship</label>
          <select
            value={relType}
            onChange={(e) => setRelType(e.target.value as KnowledgeEdgeData["relationship_type"])}
            className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background"
          >
            <option value="COULD_CAUSE">COULD_CAUSE</option>
            <option value="LEADS_TO">LEADS_TO</option>
            <option value="INDICATES">INDICATES</option>
            <option value="CORRELATES_WITH">CORRELATES_WITH</option>
          </select>
        </div>

        <div>
          <label className="block text-xs text-muted-foreground mb-1">Label</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background"
          />
        </div>

        <div>
          <label className="block text-xs text-muted-foreground mb-1">Description</label>
          <textarea
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            rows={2}
            className="w-full px-2 py-1.5 text-sm border border-border rounded-md bg-background resize-none"
          />
        </div>

        <div className="border-t border-border pt-3">
          <div className="text-xs font-medium text-muted-foreground mb-2 uppercase">Conditions</div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] text-muted-foreground mb-0.5">Min Count</label>
              <input
                type="number"
                value={minCount}
                onChange={(e) => setMinCount(Number(e.target.value))}
                min={0}
                className="w-full px-2 py-1 text-sm border border-border rounded-md bg-background"
              />
            </div>
            <div>
              <label className="block text-[10px] text-muted-foreground mb-0.5">Time Window (min)</label>
              <input
                type="number"
                value={timeWindow}
                onChange={(e) => setTimeWindow(Number(e.target.value))}
                min={0}
                className="w-full px-2 py-1 text-sm border border-border rounded-md bg-background"
              />
            </div>
          </div>

          <div className="mt-2">
            <label className="block text-[10px] text-muted-foreground mb-0.5">
              Confidence ({confidence.toFixed(2)})
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={confidence}
              onChange={(e) => setConfidence(Number(e.target.value))}
              className="w-full"
            />
          </div>
        </div>
      </div>

      <div className="flex gap-2 mt-4">
        <button
          onClick={handleSave}
          className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          <SaveIcon sx={{ fontSize: 14 }} /> Save
        </button>
        <button
          onClick={() => { if (confirm("Delete this edge?")) onDelete(); }}
          className="px-3 py-1.5 text-xs border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/30"
        >
          <DeleteIcon sx={{ fontSize: 14 }} />
        </button>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlowProvider,
  useNodesState,
  useEdgesState,
  useReactFlow,
  MarkerType,
  Handle,
  Position,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { knowledgeGraphApi, type RdkbArchitectureEdge, type RdkbArchitectureNode } from "@/api/endpoints";
import Autocomplete from "@mui/material/Autocomplete";
import CircularProgress from "@mui/material/CircularProgress";
import TextField from "@mui/material/TextField";
import HubIcon from "@mui/icons-material/Hub";

const COL_GAP = 280;
const ROW_GAP = 96;
const ORIGIN_X = 40;
const ORIGIN_Y = 40;

function normalizeDomainToken(s: string): string {
  return s.trim().toLowerCase().replace(/\s+/g, "_");
}

/** True if node lists this domain in any primary_domains slot (not only the first). */
function nodeHasDomain(n: RdkbArchitectureNode, domainKey: string): boolean {
  if (!domainKey) return true;
  const want = normalizeDomainToken(domainKey);
  return (n.domains ?? []).some((d) => normalizeDomainToken(d) === want);
}

/** Empty selection = show all. Otherwise include node if it matches any selected domain (union). */
function nodeMatchesDomainSelection(n: RdkbArchitectureNode, selectedDomains: readonly string[]): boolean {
  if (selectedDomains.length === 0) return true;
  return selectedDomains.some((d) => nodeHasDomain(n, d));
}

function primaryDomain(n: RdkbArchitectureNode): string {
  const d = n.domains?.[0];
  return d && d.length > 0 ? d : "unknown";
}

function collectUniqueDomains(nodes: RdkbArchitectureNode[]): string[] {
  const s = new Set<string>();
  for (const n of nodes) {
    for (const d of n.domains ?? []) {
      if (d?.trim()) s.add(d.trim());
    }
  }
  return [...s].sort((a, b) => a.localeCompare(b));
}

function layoutArchitectureNodes(apiNodes: RdkbArchitectureNode[]): Node[] {
  const domains = [...new Set(apiNodes.map(primaryDomain))].sort((a, b) => a.localeCompare(b));
  const byDomain = new Map<string, RdkbArchitectureNode[]>();
  for (const n of apiNodes) {
    const d = primaryDomain(n);
    const list = byDomain.get(d);
    if (list) list.push(n);
    else byDomain.set(d, [n]);
  }

  const out: Node[] = [];
  domains.forEach((domain, col) => {
    const group = byDomain.get(domain) ?? [];
    group.forEach((n, row) => {
      out.push({
        id: n.id,
        type: "archModule",
        position: {
          x: ORIGIN_X + col * COL_GAP,
          y: ORIGIN_Y + row * ROW_GAP,
        },
        data: {
          label: n.label,
          domains: n.domains ?? [],
          description: n.description ?? "",
        },
      });
    });
  });
  return out;
}

function toFlowEdges(apiEdges: RdkbArchitectureEdge[], nodeIds: Set<string>): Edge[] {
  return apiEdges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.relationship || undefined,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      style: { strokeWidth: 1.2 },
      labelStyle: { fontSize: 10, fill: "var(--muted-foreground, #64748b)" },
      labelBgStyle: { fill: "var(--card, #fff)" },
    }));
}

function ArchModuleNode({ data }: NodeProps) {
  const d = data as { label: string; domains: string[]; description: string };
  const domainChip = d.domains?.[0] ?? "";
  return (
    <div
      className="rounded-lg border-2 border-emerald-500/60 bg-emerald-50/90 dark:bg-emerald-950/50 px-3 py-2 min-w-[140px] max-w-[220px] shadow-sm"
      title={d.description || undefined}
    >
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-slate-400" />
      <div className="flex items-center gap-1 mb-0.5 flex-wrap">
        {domainChip ? (
          <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300 uppercase">
            {domainChip}
          </span>
        ) : null}
      </div>
      <div className="text-xs font-semibold text-slate-800 dark:text-slate-100 leading-tight">{d.label}</div>
      {d.description ? (
        <div className="text-[10px] text-muted-foreground mt-1 line-clamp-2">{d.description}</div>
      ) : null}
      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-slate-400" />
    </div>
  );
}

const nodeTypes: NodeTypes = { archModule: ArchModuleNode };

function ArchitectureGraphInner() {
  /** Empty = all domains. Non-empty = union (module shown if any selected domain appears in primary_domains). */
  const [selectedDomains, setSelectedDomains] = useState<string[]>([]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["rdkbArchitectureGraph"],
    queryFn: async () => (await knowledgeGraphApi.getRdkbArchitectureGraph()).data,
    staleTime: 5 * 60 * 1000,
  });

  const domainOptions = useMemo(
    () => (data?.nodes?.length ? collectUniqueDomains(data.nodes) : []),
    [data?.nodes],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { fitView } = useReactFlow();

  useEffect(() => {
    if (!data?.nodes?.length) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const filtered = data.nodes.filter((n) => nodeMatchesDomainSelection(n, selectedDomains));
    if (filtered.length === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const nodeIds = new Set(filtered.map((n) => n.id));
    setNodes(layoutArchitectureNodes(filtered));
    setEdges(toFlowEdges(data.edges ?? [], nodeIds));
  }, [data, selectedDomains, setNodes, setEdges]);

  useEffect(() => {
    if (nodes.length === 0) return;
    const id = requestAnimationFrame(() => {
      fitView({ padding: 0.15, duration: 200 });
    });
    return () => cancelAnimationFrame(id);
  }, [nodes, edges, fitView]);

  const miniMapColor = useCallback((n: Node) => {
    if (n.type === "archModule") return "#10b981";
    return "#888";
  }, []);

  const onDomainsChange = useCallback((_event: React.SyntheticEvent, newValue: string[]) => {
    setSelectedDomains(newValue);
  }, []);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[400px] gap-3 text-muted-foreground">
        <CircularProgress size={36} />
        <span className="text-sm">Loading RDK-B architecture graph…</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-6 text-center text-destructive text-sm">
        Failed to load architecture graph
        {error instanceof Error ? `: ${error.message}` : "."}
      </div>
    );
  }

  if (!data?.nodes?.length) {
    return (
      <div className="p-6 text-center text-muted-foreground space-y-2">
        <HubIcon className="mx-auto text-muted-foreground/40" sx={{ fontSize: 40 }} />
        <p className="text-sm font-medium">No architecture nodes</p>
        <p className="text-xs max-w-md mx-auto">
          {data?.warning ??
            "Ensure configs/rdkb_module_graph.yaml is present on the server and contains nodes."}
        </p>
      </div>
    );
  }

  const filterNoResults =
    selectedDomains.length > 0 && nodes.length === 0 && data.nodes.length > 0;

  return (
    <div className="flex flex-col h-full min-h-[520px]">
      <div className="flex-1 min-h-0 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          className="bg-background"
          nodesDraggable
          nodesConnectable={false}
          elementsSelectable
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
          <Controls />
          <MiniMap nodeColor={miniMapColor} zoomable pannable />
          <Panel position="top-left" className="m-3 w-[min(100%-24px,24rem)]">
            <Autocomplete
              multiple
              id="arch-domain-filter"
              size="small"
              options={domainOptions}
              value={selectedDomains}
              onChange={onDomainsChange}
              className="bg-card/90 backdrop-blur-sm shadow-sm rounded-lg"
              sx={{
                "& .MuiOutlinedInput-root": {
                  fieldset: {
                    borderColor: "var(--border)",
                  },
                  "&:hover fieldset": {
                    borderColor: "var(--border)",
                  },
                },
              }}
              renderInput={(params) => (
                <TextField
                  {...params}
                  variant="outlined"
                  placeholder={selectedDomains.length === 0 ? "Filter by domains..." : ""}
                />
              )}
              fullWidth
            />
          </Panel>
        </ReactFlow>
        {filterNoResults ? (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="pointer-events-auto rounded-lg border border-border bg-background/95 px-4 py-3 text-sm text-muted-foreground shadow-md max-w-sm text-center">
              No modules match the selected domain(s). <strong>Clear selection</strong> to show the full graph or pick
              different domains.
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Static RDK-B architecture (YAML) for the Knowledge Graph page Architecture tab.
 */
export function ArchitectureGraphView() {
  return (
    <div className="h-full w-full bg-background rounded-lg border border-border overflow-hidden">
      <ReactFlowProvider>
        <ArchitectureGraphInner />
      </ReactFlowProvider>
    </div>
  );
}
